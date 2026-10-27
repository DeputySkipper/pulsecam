"""Dashboard widgets: video view, BPM panel, pulse and spectrum plots (TRD section 8).

The text shown in the BPM panel is decided by `build_display`, a pure function of the estimator output,
so the state and hint logic is testable without a window.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGraphicsView, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

import config
import signal_proc
from models import HRResult
from ui import theme
from ui.animated import Scaled, mix_color
from ui.panels import Lbl, Panel, StatusDot, light_bar, paint_glass, scrim_for

HAS_READING = ("measuring", "poor_signal")


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
    bpm_live: float | None = None           # the displayed rate while it is a live reading (not held, not "--")
    snr_db: float | None = None             # numeric values behind the texts, for the scale and bars
    brightness: float | None = None


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
                       blank_methods, brightness=brightness_level)

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
            methods.append((m, f"{analyses[m].bpm:.1f}", analyses[m].quality))
    dim = not show_bpm or result.state == "poor_signal"            # a held value is greyed out
    return Display(
        bpm_text=f"{result.bpm_smooth:.0f}" if show_bpm else "--",
        bpm_dim=dim, bpm_live=None if dim else result.bpm_smooth,
        hint=hint, hint_kind=kind,
        quality=result.quality if has_reading else "n/a",
        snr_text=f"{result.snr_db:+.1f} dB" if result.snr_db is not None else "--",
        fps_text=f"{result.fps:.0f}" if result.fps > 0 else "--", brightness_text=bright,
        method=method, methods=methods, snr_db=result.snr_db, brightness=brightness_level)


# ---------------------------------------------------------------- widgets

class VideoTag(QLabel):
    """Small mono tag on top of the video (a child widget: never drawn into the frame data)."""

    def __init__(self, parent: QWidget):
        super().__init__("", parent)
        self.setFont(theme.font("mono", theme.SMALL_FONT_PX, 500))
        r, g, b, a = theme.TAG_FILL
        self.setStyleSheet(f"background: rgba({r}, {g}, {b}, {a}); color: {theme.TAG_TEXT}; padding: 7px 9px; "
                           f"border: 1px solid {theme.TAG_BORDER}; border-radius: {theme.TAG_RADIUS}px;")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()


class VideoView(QLabel):
    """Shows the preview frame scaled to fit, keeping the aspect ratio, with two tags in its corners: the face-lock
    state at the top left and "LIGHT n / FPS n" at the bottom right."""
    TAG_INSET = 14

    def __init__(self):
        super().__init__("No video")
        self.setObjectName("video")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 160)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)   # the frame must not drive the layout size
        self._pixmap: QPixmap | None = None
        self.lock_tag = VideoTag(self)
        self.light_tag = VideoTag(self)

    def set_tags(self, lock_text: str, light_text: str) -> None:
        self.lock_tag.setText(lock_text)
        self.light_tag.setText(light_text)
        self._place_tags()

    def _place_tags(self) -> None:
        visible = self._pixmap is not None
        for tag in (self.lock_tag, self.light_tag):
            tag.adjustSize()
            tag.setVisible(visible and bool(tag.text()))
        self.lock_tag.move(self.TAG_INSET, self.TAG_INSET)
        self.light_tag.move(self.width() - self.light_tag.width() - self.TAG_INSET,
                            self.height() - self.light_tag.height() - self.TAG_INSET)

    def set_frame(self, bgr: np.ndarray) -> None:
        h, w = bgr.shape[:2]
        bgr = np.ascontiguousarray(bgr)
        self._pixmap = QPixmap.fromImage(QImage(bgr.data, w, h, bgr.strides[0], QImage.Format_BGR888))
        self._render()
        self._place_tags()

    def clear_frame(self) -> None:
        self._pixmap = None
        self.clear()
        self.setText("No video")
        self._place_tags()

    def _render(self) -> None:
        if self._pixmap is not None:
            self.setPixmap(self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def paintEvent(self, event) -> None:
        """Rounded corners, a dark base, then the picture centred (QLabel's own painting cannot clip to a radius)."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, theme.VIDEO_RADIUS, theme.VIDEO_RADIUS)
        p.setClipPath(clip)
        p.fillRect(rect, theme.color(theme.VIDEO_BG))
        pm = self.pixmap()
        if pm is not None and not pm.isNull():
            w, h = pm.width() / pm.devicePixelRatio(), pm.height() / pm.devicePixelRatio()
            p.drawPixmap(QRectF((rect.width() - w) / 2, (rect.height() - h) / 2, w, h), pm, QRectF(pm.rect()))
        else:
            p.setPen(theme.color(theme.MUTED))
            p.setFont(self.font())
            p.drawText(rect, Qt.AlignCenter, self.text())
        p.setClipping(False)
        p.setPen(QPen(theme.color(theme.WHITE, 0.14), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), theme.VIDEO_RADIUS, theme.VIDEO_RADIUS)
        p.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render()
        self._place_tags()


# ---------------------------------------------------------------- hero, cards, plots: pure helpers

def beat_period_ms(bpm: float | None) -> float | None:
    """Milliseconds between heartbeats of the dot for a displayed rate; None for no rate."""
    return 60000.0 / bpm if bpm is not None and bpm > 0 else None


NUMBER_WIDTH_EM = 1.65               # a three-digit light-weight number with tight tracking, in ems


def fit_number_px(width: float, height: float) -> int:
    """Font size of the big BPM number for the room it has: at most HERO_NUMBER_PX, at least HERO_NUMBER_MIN_PX, and
    small enough that three digits fit the width and the line fits the height."""
    px = min(float(theme.HERO_NUMBER_PX), width / NUMBER_WIDTH_EM, float(height))
    return int(max(theme.HERO_NUMBER_MIN_PX, px))


def pulse_tail(t_sig: np.ndarray, pulse: np.ndarray, tail_sec: float = theme.PULSE_TAIL_SEC):
    """The newest `tail_sec` seconds of the real filtered pulse as (x in 0-1, y in -1..1), or None with no pulse.

    x is time within the tail, so the newest sample is always at x = 1. y is the pulse divided by the largest
    absolute value of the whole window (the amplitude the 15 s plot shows). Nothing is interpolated or smoothed."""
    t_sig, pulse = np.asarray(t_sig, dtype=float), np.asarray(pulse, dtype=float)
    if pulse.size == 0 or t_sig.size != pulse.size:
        return None
    span = max(float(np.max(np.abs(pulse))), 1e-12)
    keep = t_sig >= t_sig[-1] - tail_sec
    return (t_sig[keep] - (t_sig[-1] - tail_sec)) / tail_sec, pulse[keep] / span


def spectrum_range_hz() -> tuple[float, float]:
    return config.BAND_LO, config.BAND_HI                      # the view is the heart-rate band: 54 to 180 BPM


def tick_labels() -> list[tuple[float, str, str]]:
    """(position 0-1 across the spectrum, text, anchor) for the BPM ticks under the plot."""
    lo, hi = (v * 60 for v in spectrum_range_hz())
    out = []
    for i, bpm in enumerate(theme.SPECTRUM_TICKS_BPM):
        last = i == len(theme.SPECTRUM_TICKS_BPM) - 1
        out.append(((bpm - lo) / (hi - lo), f"{bpm} BPM" if last else str(bpm),
                    "left" if i == 0 else "right" if last else "center"))
    return out


def hover_readout(hz: float) -> str:
    """Header text while hovering the spectrum: "NN BPM / N.NN Hz" (the cursor is kept inside the view)."""
    lo, hi = spectrum_range_hz()
    hz = min(hi, max(lo, hz))
    return f"{round(hz * 60):d} BPM / {hz:.2f} Hz"


def peak_text(r: HRResult | None) -> str:
    """Header text when not hovering. No peak is claimed on a poor window (as before)."""
    if r is None or r.freqs.size == 0:
        return "--"
    if r.peak_hz is not None and r.quality != "poor":
        return f"Peak {r.peak_hz * 60:.0f} BPM"
    return "No clear peak"


def card_label(name: str, active: bool) -> str:
    return f"{name}, active" if active else name


# ---------------------------------------------------------------- hero

class HeroNumber(QLabel):
    """The big BPM number: light weight, tight tracking; `set_px` resizes the font and the (stable) width."""

    def __init__(self):
        super().__init__("--")
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Ignored)      # the room decides the size, not the text
        self.px = 0
        self.set_px(theme.HERO_NUMBER_PX)
        self.set_dim(True)

    def set_px(self, px: int) -> None:
        if px != self.px:
            self.px = px
            self.setFont(theme.font("sans", px, 300, -0.04))
            self._fit_width()

    def setText(self, text: str) -> None:
        super().setText(text)
        self._fit_width()

    def _fit_width(self) -> None:
        self.setFixedWidth(QFontMetrics(self.font()).horizontalAdvance(self.text()) + 4)

    def set_dim(self, dim: bool) -> None:
        self.setStyleSheet(f"color: {theme.MUTED if dim else theme.WHITE};")


class HeartbeatDot(QWidget):
    """A 12 px dot with a ring that grows and fades once per beat, at the displayed rate. Static with no number."""
    SIZE = 40

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.SIZE, self.SIZE)
        self._phase = 0.0
        self._period: int | None = None
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self._anim.valueChanged.connect(self._set_phase)

    @property
    def period_ms(self) -> int | None:
        return self._period

    def set_bpm(self, bpm: float | None) -> None:
        period = beat_period_ms(bpm) if theme.ANIMATIONS else None
        if period is None:
            self._anim.stop()
            self._period, self._phase = None, 0.0
            self.update()
            return
        period = max(1, round(period))
        if period != self._period:
            self._anim.setDuration(period)
            self._period = period
        if self._anim.state() != QAbstractAnimation.State.Running:
            self._anim.start()

    def _set_phase(self, v) -> None:
        self._phase = float(v)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        if self._period is not None:
            grow = 1.0 + (theme.BEAT_RING_SCALE - 1.0) * self._phase
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(theme.color(theme.PRIMARY_FILL, theme.BEAT_RING_ALPHA * (1.0 - self._phase)), 1.5))
            p.drawEllipse(c, 6.0 * grow, 6.0 * grow)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color(theme.PRIMARY_FILL, 1.0 if self._period is not None else 0.35))
        p.drawEllipse(c, 6.0, 6.0)
        p.end()


class LivePulseStrip(QWidget):
    """The newest 5 s of the real filtered pulse, with a bright dot on the newest sample. Redrawn when a new result
    arrives (HRResult.pulse only changes once per estimate); no interpolation or synthetic scrolling."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(theme.PULSE_STRIP_MIN_H)
        self.setMaximumHeight(theme.PULSE_STRIP_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.trace = None

    def set_result(self, r: HRResult | None) -> None:
        self.trace = None if r is None else pulse_tail(r.t_sig, r.pulse)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        if self.trace is None:
            p.setFont(theme.font("mono", theme.SMALL_FONT_PX, 400))
            p.setPen(theme.color(theme.MUTED))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "Waiting for signal")
            p.end()
            return
        xs, ys = self.trace
        inset = 5.0
        px = inset + xs * (w - 2 * inset)
        py = h / 2 - ys * (h / 2 - inset)
        path = QPainterPath(QPointF(px[0], py[0]))
        for x, y in zip(px[1:], py[1:]):
            path.lineTo(x, y)
        pen = QPen(theme.color(theme.PRIMARY_FILL), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color(theme.WHITE))
        p.drawEllipse(QPointF(px[-1], py[-1]), 3.5, 3.5)
        p.end()


class LightBar(QWidget):
    """Thin bar filled to the live ROI brightness (n / 255) with a tick at the low-light threshold."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(10)
        self._level: float | None = None

    def set_level(self, level: float | None) -> None:
        if level != self._level:
            self._level = level
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fill, tick = light_bar(self._level)
        w, h = float(self.width()), float(self.height())
        track = QRectF(0, (h - 4) / 2, w, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color(theme.LIGHT_TRACK))
        p.drawRoundedRect(track, 2, 2)
        if fill > 0:
            p.setBrush(theme.color(theme.LIGHT_FILL))
            p.drawRoundedRect(QRectF(0, track.top(), w * fill, 4), 2, 2)
        p.fillRect(QRectF(round(w * tick), 0, 1, h), theme.color(theme.LIGHT_TICK))      # snapped to a pixel: crisp
        p.end()


class NumberRow(QWidget):
    """The row holding the number, the unit and the dot; tells the hero when its size really changes (a child's size
    is only known after the layout has run, so the hero cannot fit the number from its own resize event)."""
    resized = Signal()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()


class BpmPanel(Panel):
    """Hero: state, the big BPM number with the heartbeat dot, the live pulse strip, and the stats list."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(theme.HERO_MIN_H)
        self.setMaximumHeight(theme.HERO_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(30, 22, 0, 22)
        left.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(Lbl("Heart rate"))
        state = QHBoxLayout()
        state.setSpacing(8)
        self.state_dot = StatusDot(7)
        self.state_line = QLabel("")
        self.state_line.setFont(theme.font("sans", 13, 400))
        state.addWidget(self.state_dot)
        state.addWidget(self.state_line)
        head.addLayout(state)
        head.addStretch(1)
        left.addLayout(head)

        self.number = HeroNumber()
        self.unit = Lbl("BPM", px=13)
        self.beat = HeartbeatDot()
        self.number_row = NumberRow()
        self.number_row.resized.connect(self._fit_number)
        self.number_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        row = QHBoxLayout(self.number_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.number)
        unit_col = QVBoxLayout()
        unit_col.setContentsMargins(0, 0, 0, 0)
        unit_col.addStretch(1)
        unit_col.addWidget(self.unit)
        unit_col.addSpacing(24)
        row.addLayout(unit_col)
        row.addWidget(self.beat)
        row.addStretch(1)
        left.addWidget(self.number_row, 1)

        strip_box = QVBoxLayout()
        strip_box.setContentsMargins(0, 0, 22, 0)
        strip_box.setSpacing(6)
        strip_head = QHBoxLayout()
        strip_head.addWidget(Lbl("Live pulse"))
        strip_head.addStretch(1)
        self.rate_label = QLabel("--")
        self.rate_label.setFont(theme.font("mono", theme.SMALL_FONT_PX, 400))
        self.rate_label.setStyleSheet(f"color: {theme.MUTED};")
        strip_head.addWidget(self.rate_label)
        self.strip = LivePulseStrip()
        strip_box.addLayout(strip_head)
        strip_box.addWidget(self.strip)
        left.addLayout(strip_box)
        outer.addLayout(left, 1)

        stats = QFrame()
        stats.setObjectName("statsColumn")
        stats.setStyleSheet(f"#statsColumn {{ border-left: 1px solid {theme.BORDER}; }}")
        stats.setMinimumWidth(theme.STATS_MIN_W)
        stats.setMaximumWidth(theme.STATS_W + 56)
        col = QVBoxLayout(stats)
        col.setContentsMargins(24, 0, 24, 0)
        col.setSpacing(14)
        col.addStretch(1)
        self.stat_values: dict[str, QLabel] = {}
        for key, name in (("method", "Method"), ("snr", "SNR"), ("light", "Light"), ("window", "Window"), ("range", "Range")):
            line = QHBoxLayout()
            line.addWidget(Lbl(name))
            line.addStretch(1)
            value = QLabel("--")
            value.setFont(theme.font("mono", 14, 500))
            value.setStyleSheet(f"color: {theme.WHITE};")
            self.stat_values[key] = value
            line.addWidget(value)
            if key == "light":
                box = QVBoxLayout()
                box.setSpacing(8)
                box.addLayout(line)
                self.light_bar = LightBar()
                box.addWidget(self.light_bar)
                col.addLayout(box)
            else:
                col.addLayout(line)
        col.addStretch(1)
        self.light_value = self.stat_values["light"]
        self.stat_values["window"].setText(f"{config.WINDOW_SEC:.0f} s")
        self.stat_values["range"].setText(f"{config.BAND_LO * 60:.0f}-{config.BAND_HI * 60:.0f}")
        outer.addWidget(stats)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_number()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_number()

    def _fit_number(self) -> None:
        """Give the number the room the row has: width after the unit label, the dot and the stats column."""
        free_w = self.number_row.width() - self.unit.sizeHint().width() - self.beat.width() - 2 * 14
        self.number.set_px(fit_number_px(free_w, self.number_row.height()))

    def update_display(self, d: Display) -> None:
        self.number.setText(d.bpm_text)
        self.number.set_dim(d.bpm_dim)
        self.state_line.setText(d.hint)
        self.state_line.setStyleSheet(f"color: {theme.HINT_COLOR[d.hint_kind]};")
        self.state_dot.set_color(theme.STATE_DOT_COLOR[d.hint_kind])
        self.beat.set_bpm(d.bpm_live)
        self.rate_label.setText(f"{d.bpm_live / 60:.1f} Hz" if d.bpm_live else "--")
        self.stat_values["method"].setText(d.method)
        self.stat_values["snr"].setText(d.snr_text)
        self.light_value.setText(f"{d.brightness_text} / {theme.LIGHT_MAX:.0f}")
        self.light_bar.set_level(d.brightness)

    def set_result(self, r: HRResult | None) -> None:
        self.strip.set_result(r)


# ---------------------------------------------------------------- method cards

class MethodCard(Scaled, QWidget):
    """One method's estimate for this window: label, quality dot and number, painted as a glass panel that scales up
    slightly on hover (2.5%) and down when pressed. The active method has a white outline."""
    hover_scale = theme.HOVER_SCALE_CARD

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.value_text = "--"
        self.quality = "n/a"
        self.active = False
        m = 2 * theme.ANIM_MARGIN
        self.setMinimumHeight(theme.CARDS_MIN_H + m)
        self.setMaximumHeight(theme.CARDS_H + m)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setProperty("active", "false")
        self.init_scale()

    def set_active(self, active: bool) -> None:
        self.active = active
        self.setProperty("active", "true" if active else "false")
        self.update()

    def set_value(self, text: str, quality: str) -> None:
        self.value_text, self.quality = text, quality
        self.update()

    def border_color(self) -> QColor:
        rest, hover = ((theme.CARD_BORDER_ACTIVE, theme.WHITE) if self.active else (theme.BORDER, theme.BTN_BORDER_HOVER))
        return mix_color(rest, hover, self._mix)

    def paintEvent(self, event) -> None:
        p, rect = self.begin_paint()
        emphasised = self.active or self._mix > 0.01             # idle cards keep the plain glass rim
        paint_glass(p, rect, self.border_color().name() if emphasised else None, radius=theme.CARD_RADIUS, scrim=scrim_for(self))
        pad_x, pad_y = 20.0, 14.0
        label_font = theme.font("mono", theme.SMALL_FONT_PX, 500, 0.12)
        p.setFont(label_font)
        p.setPen(theme.color(theme.WHITE if self.active else theme.MUTED))
        room = rect.width() - 2 * pad_x - 16
        label = card_label(self.name, self.active).upper()
        if QFontMetrics(label_font).horizontalAdvance(label) > room:        # narrow card: the outline says "active"
            label = self.name.upper()
        p.drawText(QRectF(rect.left() + pad_x, rect.top() + pad_y, room, 14), Qt.AlignVCenter | Qt.AlignLeft, label)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color(theme.QUALITY_COLOR[self.quality]))
        p.drawEllipse(QPointF(rect.right() - pad_x - 3.5, rect.top() + pad_y + 7), 3.5, 3.5)
        px = int(min(32, max(18, rect.height() * 0.33)))
        p.setFont(theme.font("sans", px, 300, -0.02))
        p.setPen(theme.color(theme.TEXT if self.quality in ("good", "fair") else theme.MUTED))
        p.drawText(QRectF(rect.left() + pad_x, rect.top() + pad_y, rect.width() - 2 * pad_x, rect.height() - 2 * pad_y),
                   Qt.AlignBottom | Qt.AlignLeft, self.value_text)
        p.end()


class MethodCards(QWidget):
    """The three method cards in a row. The cards carry their own hover margin, so the row spacing makes up the gap."""

    def __init__(self):
        super().__init__()
        m = 2 * theme.ANIM_MARGIN
        self.setMinimumHeight(theme.CARDS_MIN_H + m)
        self.setMaximumHeight(theme.CARDS_H + m)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACING - m)
        self.cells = {m: MethodCard(m) for m in signal_proc.METHODS}
        for cell in self.cells.values():
            row.addWidget(cell, 1)

    def update_display(self, d: Display) -> None:
        for name, text, quality in d.methods:
            self.cells[name].set_active(name == d.method)
            self.cells[name].set_value(text, quality)


# ---------------------------------------------------------------- plots

def _make_transparent(plot: pg.PlotWidget) -> None:
    """Plots sit inside a glass panel: no background of their own, no axes, no margins, no frame."""
    plot.setFrameShape(QFrame.NoFrame)
    plot.viewport().setAutoFillBackground(False)
    plot.setCacheMode(QGraphicsView.CacheNone)       # pyqtgraph's default background cache is an opaque pixmap
    plot.setMenuEnabled(False)
    plot.setMouseEnabled(x=False, y=False)
    plot.hideButtons()
    item = plot.getPlotItem()
    for axis in ("left", "bottom", "top", "right"):
        item.hideAxis(axis)
    item.layout.setContentsMargins(0, 0, 0, 0)
    item.setContentsMargins(0, 0, 0, 0)


class _Placeholder:
    """Muted 'waiting' text centred on a plot, shown while there is no signal."""

    def __init__(self, plot: pg.PlotWidget, text: str):
        self.item = pg.TextItem(text, color=theme.MUTED, anchor=(0.5, 0.5))
        self.item.setFont(theme.font("mono", theme.SMALL_FONT_PX, 400))
        plot.addItem(self.item, ignoreBounds=True)

    def show(self, x: float, y: float) -> None:
        self.item.setPos(x, y)
        self.item.setVisible(True)

    def hide(self) -> None:
        self.item.setVisible(False)


def _add_grid(plot: pg.PlotWidget, xs=(), ys=()) -> list:
    """Faint grid lines behind a plot's data, like ECG paper. Returned so tests can find them."""
    lines = []
    for angle, positions in ((90, xs), (0, ys)):
        for pos in positions:
            line = pg.InfiniteLine(pos=pos, angle=angle, pen=pg.mkPen(theme.color(theme.GRID_COLOR, theme.PLOT_GRID_ALPHA), width=1),
                                   movable=False)
            line.setZValue(-20)
            plot.addItem(line, ignoreBounds=True)
            lines.append(line)
    return lines


class PulsePlot(pg.PlotWidget):
    """The filtered pulse of the whole window: #EDEDED, 1.7 px, over a dashed zero line. No axes."""

    def __init__(self):
        super().__init__(background=None)
        _make_transparent(self)
        self.setMinimumHeight(60)
        self.setXRange(0, config.WINDOW_SEC, padding=0)
        self.setYRange(-1, 1, padding=0)
        zero_pen = pg.mkPen(theme.color(theme.WHITE, 0.08), width=1)
        zero_pen.setDashPattern([3, 6])
        self.zero_line = pg.InfiniteLine(pos=0, angle=0, pen=zero_pen)
        self.addItem(self.zero_line, ignoreBounds=True)
        self.grid_lines = _add_grid(self, xs=range(0, int(config.WINDOW_SEC) + 1, 3))        # a line every 3 s
        self.curve = self.plot(pen=pg.mkPen(theme.PRIMARY_FILL, width=1.7))
        self.placeholder = _Placeholder(self, "Waiting for signal")
        self.set_result(None)

    def set_result(self, r: HRResult | None) -> None:
        if r is None or r.pulse.size == 0:
            self.curve.setData([], [])
            self.zero_line.setVisible(False)                          # the waiting text would sit on the dashed line
            self.placeholder.show(config.WINDOW_SEC / 2, 0)
            return
        self.placeholder.hide()
        self.zero_line.setVisible(True)
        self.curve.setData(r.t_sig, r.pulse)
        span = max(float(np.max(np.abs(r.pulse))), 1e-12) * 1.3       # symmetric, so the baseline stays centred
        self.setYRange(-span, span, padding=0)


class TickRow(QWidget):
    """BPM tick labels under the spectrum, placed in proportion to the view (54 to 180 BPM)."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(16)
        self._font = theme.font("mono", theme.SMALL_FONT_PX, 400)

    def visible_ticks(self, width: float) -> list[tuple[float, str]]:
        """(x, text) of the labels that fit: when two would touch, the unit on the last label goes first, then the
        middle labels; the first and the last stay."""
        fm = QFontMetrics(self._font)
        placed = []
        labels = tick_labels()
        for i, (frac, text, anchor) in enumerate(labels):
            def x_of(t):
                tw = fm.horizontalAdvance(t)
                return {"left": 0.0, "right": width - tw}.get(anchor, frac * width - tw / 2), tw
            x, tw = x_of(text)
            if placed and x < placed[-1][0] + placed[-1][2] + 6:
                if anchor == "right":
                    x, tw = x_of(text.replace(" BPM", ""))
                    placed = [q for q in placed if q[0] + q[2] + 6 <= x] if x < placed[-1][0] + placed[-1][2] + 6 else placed
                    text = text.replace(" BPM", "")
                else:
                    continue
            placed.append((x, text, tw))
        return [(x, t) for x, t, _ in placed]

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setFont(self._font)
        p.setPen(theme.color(theme.MUTED))
        fm = QFontMetrics(self._font)
        for x, text in self.visible_ticks(float(self.width())):
            p.drawText(QRectF(x, 0, fm.horizontalAdvance(text) + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


class SpectrumPlot(pg.PlotWidget):
    """Spectrum over the heart-rate band (54 to 180 BPM): a faint grey area under a #DADADA line, a dashed peak line,
    and a hover crosshair whose reading is sent to the card header through `readout`."""
    readout = Signal(str)

    def __init__(self):
        super().__init__(background=None)
        _make_transparent(self)
        lo, hi = spectrum_range_hz()
        self.setMinimumHeight(60)
        self.setXRange(lo, hi, padding=0)
        self.setYRange(0, 1.15, padding=0)
        self.grid_lines = _add_grid(self, xs=[b / 60.0 for b in theme.SPECTRUM_TICKS_BPM], ys=(0.29, 0.58, 0.86))
        self.curve = self.plot(pen=pg.mkPen(theme.SPECTRUM_LINE, width=1.5), fillLevel=0, brush=pg.mkBrush(255, 255, 255, 30))
        peak_pen = pg.mkPen(theme.MUTED, width=1)
        peak_pen.setDashPattern([3, 4])
        self.peak_line = pg.InfiniteLine(angle=90, pen=peak_pen)
        self.cursor = pg.InfiniteLine(angle=90, pen=pg.mkPen(theme.WHITE, width=1))
        self.addItem(self.peak_line, ignoreBounds=True)
        self.addItem(self.cursor, ignoreBounds=True)
        self.cursor.setVisible(False)
        self.placeholder = _Placeholder(self, "Waiting for signal")
        self.default_readout = "--"
        self._has_data = False
        self._hovering = False
        self.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.set_result(None)

    # -- hover
    def _on_mouse_moved(self, scene_pos) -> None:
        vb = self.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(scene_pos):
            self.clear_hover()
            return
        self.hover_at(vb.mapSceneToView(scene_pos).x())

    def hover_at(self, hz: float) -> None:
        if not self._has_data:
            return
        lo, hi = spectrum_range_hz()
        self._hovering = True
        self.cursor.setValue(min(hi, max(lo, hz)))
        self.cursor.setVisible(True)
        self.readout.emit(hover_readout(hz))

    def clear_hover(self) -> None:
        was = self._hovering
        self._hovering = False
        self.cursor.setVisible(False)
        if was:
            self.readout.emit(self.default_readout)

    def leaveEvent(self, event) -> None:
        self.clear_hover()
        super().leaveEvent(event)

    # -- data
    def set_result(self, r: HRResult | None) -> None:
        lo, hi = spectrum_range_hz()
        self.default_readout = peak_text(r)
        if r is None or r.freqs.size == 0:
            self._has_data = False
            self.curve.setData([], [])
            self.peak_line.setVisible(False)
            self.placeholder.show((lo + hi) / 2, 0.5)
            self.clear_hover()
            if not self._hovering:
                self.readout.emit(self.default_readout)
            return
        self._has_data = True
        self.placeholder.hide()
        keep = (r.freqs >= lo) & (r.freqs <= hi)
        power = r.power[keep]
        peak = float(power.max())
        self.curve.setData(r.freqs[keep], power / peak if peak > 0 else power)
        if r.peak_hz is not None and r.quality != "poor":        # no peak marker on a poor window: it would imply a detection
            self.peak_line.setValue(r.peak_hz)
            self.peak_line.setVisible(True)
        else:
            self.peak_line.setVisible(False)
        if not self._hovering:
            self.readout.emit(self.default_readout)


class PlotCard(Panel):
    """A plot in a glass panel with a header: the title on the left and a small mono text on the right."""

    def __init__(self, title: str, right_text: str, body: QWidget, right_color: str = theme.MUTED, footer: QWidget | None = None):
        super().__init__()
        self.setMinimumHeight(theme.PLOTS_MIN_H)
        if theme.PLOTS_MAX_H:
            self.setMaximumHeight(theme.PLOTS_MAX_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)
        head = QHBoxLayout()
        self.title = Lbl(title)
        self.right = QLabel(right_text)
        self.right.setFont(theme.font("mono", theme.SMALL_FONT_PX, 400))
        self.right.setStyleSheet(f"color: {right_color};")
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.right)
        box.addLayout(head)
        box.addWidget(body, 1)
        if footer is not None:
            box.addWidget(footer)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # the small right-hand text gives way when the card is too narrow for both texts
        room = self.width() - 36 - 16
        self.right.setVisible(self.title.sizeHint().width() + self.right.sizeHint().width() <= room)
