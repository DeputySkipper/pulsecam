"""Dashboard widgets: video view, BPM panel, pulse and spectrum plots (TRD section 8).

The text shown in the BPM panel is decided by `build_display`, a pure function of the estimator output,
so the state and hint logic is testable without a window.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget)

import config
import signal_proc
from models import HRResult
from ui import theme

SPECTRUM_VIEW_HZ = (0.5, 4.0)      # PRD: spectrum shown from 0.5 to 4 Hz
HAS_READING = ("measuring", "poor_signal")
PLOT_MIN_HEIGHT = 110              # px; keeps both plots readable when the light frame shrinks the dashboard


# ---------------------------------------------------------------- view model (pure logic)

@dataclass
class Display:
    bpm_text: str
    bpm_dim: bool
    hint: str
    hint_kind: str                          # "info" | "ok" | "warn" | "error"
    quality: str                            # "good" | "fair" | "poor" | "n/a"
    snr_text: str
    fps_text: str
    brightness_text: str
    method: str
    methods: list[tuple[str, str, str]]     # (name, bpm text, quality) for every method


def warmup_total_sec() -> float:
    """Seconds from the face appearing to the first estimate: MIN_SEC of buffer. The ROI lock phase is part of that
    buffer (a re-lock level-matches instead of restarting it), so it adds nothing."""
    return config.MIN_SEC


def brightness(rgb: np.ndarray | None) -> float | None:
    """Mean of the ROI R, G, B means (0-255)."""
    return None if rgb is None else float(np.mean(rgb))


def state_hint(state: str, warm_x: int, low_light: bool, running: bool = True) -> tuple[str, str]:
    """Plain-words state line and its kind. Priority: stopped, no face, low light, then the estimator state."""
    if not running:
        return "Press Start", "info"
    if state == "no_face":
        return "No face detected", "error"
    if low_light:
        return "More light needed", "warn"
    if state == "warming_up":
        return f"Warming up {min(warm_x, int(warmup_total_sec()))}/{warmup_total_sec():.0f} s", "info"
    if state == "poor_signal":
        return "Hold still", "warn"
    return "Measuring", "ok"


def build_display(running: bool, result: HRResult | None, analyses: dict, method: str,
                  warm_x: int = 0, low_light: bool = False, brightness_level: float | None = None,
                  stopped_hint: str = "Press Start") -> Display:
    """When not running, a kept result (a finished file) is still shown, with `stopped_hint` as the state line."""
    blank_methods = [(m, "--", "n/a") for m in signal_proc.METHODS]
    bright = f"{brightness_level:.0f}" if brightness_level is not None else "--"
    if result is None:
        return Display("--", True, stopped_hint if not running else "Starting...", "info", "n/a", "--", "--", bright, method,
                       blank_methods)

    hint, kind = state_hint(result.state, warm_x, low_light)
    if not running:
        hint, kind = stopped_hint, "info"
    has_reading = result.state in HAS_READING
    show_bpm = has_reading and result.bpm_smooth is not None
    methods = []
    for m in signal_proc.METHODS:
        if not analyses:
            methods.append((m, "--", "n/a"))
        elif analyses.get(m) is None:
            methods.append((m, "--", "poor"))
        else:
            methods.append((m, f"{analyses[m].bpm:.0f}", analyses[m].quality))
    return Display(
        bpm_text=f"{result.bpm_smooth:.0f}" if show_bpm else "--",
        bpm_dim=not show_bpm or result.state == "poor_signal",      # held value is greyed out
        hint=hint, hint_kind=kind,
        quality=result.quality if has_reading else "n/a",
        snr_text=f"{result.snr_db:.1f} dB" if result.snr_db is not None else "--",
        fps_text=f"{result.fps:.0f}" if result.fps > 0 else "--", brightness_text=bright,
        method=method, methods=methods)


# ---------------------------------------------------------------- widgets

class Dot(QLabel):
    def __init__(self, size: int = 12):
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)
        self.set_color(theme.MUTED)

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"background: {color}; border-radius: {self._size // 2}px;")


class VideoView(QLabel):
    """Shows the preview frame scaled to fit, keeping the aspect ratio."""

    def __init__(self):
        super().__init__("No video")
        self.setObjectName("video")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)   # the frame must not drive the layout size
        self._pixmap: QPixmap | None = None

    def set_frame(self, bgr: np.ndarray) -> None:
        h, w = bgr.shape[:2]
        bgr = np.ascontiguousarray(bgr)
        self._pixmap = QPixmap.fromImage(QImage(bgr.data, w, h, bgr.strides[0], QImage.Format_BGR888))
        self._render()

    def clear_frame(self) -> None:
        self._pixmap = None
        self.clear()
        self.setText("No video")

    def _render(self) -> None:
        if self._pixmap is not None:
            self.setPixmap(self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render()


class Card(QFrame):
    def __init__(self, title: str, content: QWidget):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACING, 12, theme.SPACING, theme.SPACING)
        layout.setSpacing(8)
        label = QLabel(title.upper())
        label.setObjectName("cardTitle")
        layout.addWidget(label)
        layout.addWidget(content, 1)


class MethodCell(QFrame):
    def __init__(self, name: str):
        super().__init__()
        self.setObjectName("methodCell")
        self.name = name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        top = QHBoxLayout()
        title = QLabel(name)
        title.setObjectName("methodName")
        self.dot = Dot(8)
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.dot)
        self.value = QLabel("--")
        self.value.setObjectName("methodValue")
        layout.addLayout(top)
        layout.addWidget(self.value)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_value(self, text: str, quality: str) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"color: {theme.TEXT if quality in ('good', 'fair') else theme.MUTED};")
        self.dot.set_color(theme.QUALITY_COLOR[quality])


class BpmPanel(QFrame):
    """Big BPM number, state line, quality dot, stats row, and the three methods side by side."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACING, 12, theme.SPACING, theme.SPACING)
        outer.setSpacing(8)

        top = QHBoxLayout()
        self.number = QLabel("--")
        self.number.setObjectName("bpmNumber")
        self.number.setFixedWidth(int(theme.BPM_FONT_PX * 1.9))        # stable width: digits do not shift the layout
        self.number.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        unit = QLabel("BPM")
        unit.setObjectName("bpmUnit")
        unit.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.quality_dot = Dot(14)
        self.quality_text = QLabel(theme.QUALITY_TEXT["n/a"])
        self.quality_text.setObjectName("qualityText")
        top.addWidget(self.number)
        top.addWidget(unit, 0, Qt.AlignBottom)
        top.addStretch(1)
        top.addWidget(self.quality_dot, 0, Qt.AlignTop)
        top.addWidget(self.quality_text, 0, Qt.AlignTop)
        outer.addLayout(top)

        self.state_line = QLabel("")
        self.state_line.setObjectName("stateLine")
        outer.addWidget(self.state_line)

        stats = QHBoxLayout()
        self.stat_method, self.stat_snr, self.stat_fps, self.stat_light = (QLabel() for _ in range(4))
        for label in (self.stat_method, self.stat_snr, self.stat_fps, self.stat_light):
            label.setObjectName("stat")
            stats.addWidget(label)
        stats.addStretch(1)
        outer.addLayout(stats)

        cells = QHBoxLayout()
        cells.setSpacing(8)
        self.cells = {m: MethodCell(m) for m in signal_proc.METHODS}
        for cell in self.cells.values():
            cells.addWidget(cell, 1)
        outer.addLayout(cells)

    def update_display(self, d: Display) -> None:
        self.number.setText(d.bpm_text)
        self.number.setStyleSheet(f"color: {theme.MUTED if d.bpm_dim else theme.TEXT};")
        self.state_line.setText(d.hint)
        self.state_line.setStyleSheet(f"color: {theme.HINT_COLOR[d.hint_kind]};")
        self.quality_dot.set_color(theme.QUALITY_COLOR[d.quality])
        self.quality_text.setText(theme.QUALITY_TEXT[d.quality])
        self.stat_method.setText(f"Method {d.method}")
        self.stat_snr.setText(f"SNR {d.snr_text}")
        self.stat_fps.setText(f"FPS {d.fps_text}")
        self.stat_light.setText(f"Light {d.brightness_text}")
        for name, text, quality in d.methods:
            self.cells[name].set_active(name == d.method)
            self.cells[name].set_value(text, quality)


# ---------------------------------------------------------------- plots

def _style_axis(axis: pg.AxisItem) -> None:
    axis.setPen(pg.mkPen(theme.BORDER))
    axis.setTextPen(pg.mkPen(theme.MUTED))


class BpmAxis(pg.AxisItem):
    """Axis whose ticks are the Hz values of the view, labelled in BPM."""

    def tickStrings(self, values, scale, spacing):
        return [f"{v * 60:.0f}" for v in values]


class _Placeholder:
    """Muted 'waiting' text centred on a plot, shown while there is no signal."""

    def __init__(self, plot: pg.PlotWidget, text: str):
        self.item = pg.TextItem(text, color=theme.MUTED, anchor=(0.5, 0.5))
        plot.addItem(self.item, ignoreBounds=True)

    def show(self, x: float, y: float) -> None:
        self.item.setPos(x, y)
        self.item.setVisible(True)

    def hide(self) -> None:
        self.item.setVisible(False)


class PulsePlot(pg.PlotWidget):
    def __init__(self):
        super().__init__(background=theme.PANEL)
        self.setFrameShape(QFrame.NoFrame)
        self.setMenuEnabled(False)
        self.setMouseEnabled(x=False, y=False)
        self.hideButtons()
        self.getPlotItem().hideAxis("left")
        _style_axis(self.getAxis("bottom"))
        self.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.setXRange(0, config.WINDOW_SEC, padding=0)
        self.setYRange(-1, 1, padding=0)
        self.curve = self.plot(pen=pg.mkPen(theme.ACCENT, width=2))
        self.placeholder = _Placeholder(self, "Waiting for signal")
        self.set_result(None)

    def set_result(self, r: HRResult | None) -> None:
        if r is None or r.pulse.size == 0:
            self.curve.setData([], [])
            self.placeholder.show(config.WINDOW_SEC / 2, 0)
            return
        self.placeholder.hide()
        self.curve.setData(r.t_sig, r.pulse)
        span = max(float(np.max(np.abs(r.pulse))), 1e-12) * 1.3       # symmetric, so the baseline stays centred
        self.setYRange(-span, span, padding=0)


class SpectrumPlot(pg.PlotWidget):
    def __init__(self):
        axes = {"top": BpmAxis("top")}
        super().__init__(background=theme.PANEL, axisItems=axes)
        self.setFrameShape(QFrame.NoFrame)
        self.setMenuEnabled(False)
        self.setMouseEnabled(x=False, y=False)
        self.hideButtons()
        item = self.getPlotItem()
        item.hideAxis("left")
        item.showAxis("top")
        for name in ("bottom", "top"):
            _style_axis(self.getAxis(name))
        lo, hi = SPECTRUM_VIEW_HZ
        self.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.setXRange(lo, hi, padding=0)
        self.setYRange(0, 1.3, padding=0)
        self.band = pg.LinearRegionItem(values=(config.BAND_LO, config.BAND_HI), movable=False,
                                        brush=pg.mkBrush(255, 255, 255, 14), pen=pg.mkPen(None))
        self.addItem(self.band, ignoreBounds=True)
        self.curve = self.plot(pen=pg.mkPen(theme.TEXT, width=2))
        self.peak_line = pg.InfiniteLine(angle=90, pen=pg.mkPen(theme.ACCENT, width=2))
        self.peak_label = pg.TextItem(color=theme.ACCENT, anchor=(0.0, 0.0))   # right of the line, inside the view
        self.addItem(self.peak_line, ignoreBounds=True)
        self.addItem(self.peak_label, ignoreBounds=True)
        self.placeholder = _Placeholder(self, "Waiting for signal")
        self.set_result(None)

    def set_result(self, r: HRResult | None) -> None:
        lo, hi = SPECTRUM_VIEW_HZ
        if r is None or r.freqs.size == 0:
            self.curve.setData([], [])
            self.peak_line.setVisible(False)
            self.peak_label.setVisible(False)
            self.placeholder.show((lo + hi) / 2, 0.5)
            return
        self.placeholder.hide()
        keep = (r.freqs >= lo) & (r.freqs <= hi)
        power = r.power[keep]
        peak = float(power.max())
        self.curve.setData(r.freqs[keep], power / peak if peak > 0 else power)
        if r.peak_hz is not None and r.quality != "poor":        # no peak marker on a poor window: it would imply a detection
            self.peak_line.setValue(r.peak_hz)
            self.peak_line.setVisible(True)
            self.peak_label.setText(f"{r.peak_hz * 60:.0f} BPM")
            self.peak_label.setAnchor((1.0, 0.0) if r.peak_hz > (lo + hi) / 2 + 0.5 else (0.0, 0.0))   # keep it inside the view
            self.peak_label.setPos(r.peak_hz, 1.28)
            self.peak_label.setVisible(True)
        else:
            self.peak_line.setVisible(False)
            self.peak_label.setVisible(False)
