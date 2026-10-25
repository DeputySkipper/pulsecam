"""Surfaces: the glass-like Panel, the dashboard background, the top bar, and the small label helper.

Qt has no backdrop blur, so a Panel approximates the reference's glass with a translucent fill, a 1 px border and a
faint highlight along its top edge, all painted in paintEvent.
"""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import config
from ui import theme

SOURCE_LABEL = {"mock": "Mock", "webcam": "Camera", "file": "File"}


def camera_text(source: str, fps: float | None) -> str:
    """Top-bar status text for the actual source, e.g. "Camera 30 fps"; "--" when there is no measured rate."""
    name = SOURCE_LABEL[source]
    return f"{name} {fps:.0f} fps" if fps and fps > 0 else f"{name} -- fps"


class Lbl(QLabel):
    """Small uppercase mono label (the reference's .lbl): 11 px, weight 500, letter-spacing .12 em, muted."""

    def __init__(self, text: str = "", color: str = theme.MUTED, px: int = theme.SMALL_FONT_PX, parent=None):
        super().__init__(text.upper(), parent)
        self.setFont(theme.font("mono", px, 500, 0.12))
        self.set_color(color)

    def setText(self, text: str) -> None:
        super().setText(text.upper())

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"color: {color}; background: transparent;")


def paint_glass(p: QPainter, rect: QRectF, border: str = theme.BORDER) -> None:
    """The glass look: translucent white fill, a faint highlight along the top edge, a 1 px border, radius 12."""
    r = theme.RADIUS
    body = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    p.setPen(Qt.NoPen)
    p.setBrush(theme.color(theme.WHITE, theme.PANEL_ALPHA))
    p.drawRoundedRect(body, r, r)
    # highlight: the rounded outline one pixel inside, kept to the top band so only the top edge and corners show
    p.save()
    clip = QPainterPath()
    clip.addRect(QRectF(rect.left(), rect.top(), rect.width(), r + 1))
    p.setClipPath(clip)
    p.setPen(QPen(theme.color(theme.WHITE, theme.PANEL_TOP_ALPHA), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(body.adjusted(0, 1, 0, 0), r - 1, r - 1)
    p.restore()
    p.setPen(QPen(theme.color(border), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(body, r, r)


class Panel(QFrame):
    """Translucent rounded panel: fill white at 3.5%, 1 px border, radius 12, a faint highlight along the top edge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_glass(p, QRectF(self.rect()))
        p.end()


class Dashboard(QWidget):
    """Window background: #0A0A0A with a soft elliptical highlight at the top right (the reference's stage)."""
    HIGHLIGHT_RADII = (900.0, 500.0)           # px, at 70% of the width and -10% of the height
    HIGHLIGHT_CENTER = (0.70, -0.10)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), theme.color(theme.BG))
        rx, ry = self.HIGHLIGHT_RADII
        cx, cy = self.width() * self.HIGHLIGHT_CENTER[0], self.height() * self.HIGHLIGHT_CENTER[1]
        grad = QRadialGradient(0, 0, ry)
        grad.setColorAt(0.0, theme.color(theme.BG_HIGHLIGHT))
        grad.setColorAt(0.7, theme.color(theme.BG))
        grad.setColorAt(1.0, theme.color(theme.BG))
        sx = rx / ry
        p.translate(cx, cy)
        p.scale(sx, 1.0)
        p.fillRect(QRectF(-cx / sx, -cy, self.width() / sx, self.height()), grad)
        p.end()


class PulseGlyph(QWidget):
    """The brand mark: a heartbeat line."""

    def __init__(self, size: int = 24):
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.width() / 28, self.height() / 28)
        path = QPainterPath(QPointF(2, 14))
        for x, y in ((8, 14), (11, 6), (16, 22), (19, 14), (26, 14)):
            path.lineTo(x, y)
        pen = QPen(theme.color(theme.PRIMARY_FILL), 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)
        p.end()


class StatusDot(QWidget):
    def __init__(self, size: int = 7):
        super().__init__()
        self.setFixedSize(size, size)
        self._color = theme.DISABLED_TEXT

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color(self._color))
        p.drawEllipse(QRectF(self.rect()))
        p.end()


class TopBar(Panel):
    """56 px bar: brand on the left; on the right the source's status dot and rate, and the disclaimer."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(theme.TOPBAR_H)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 22, 0)
        row.setSpacing(10)
        row.addWidget(PulseGlyph(24))
        self.brand = QLabel("PulseCam")
        self.brand.setFont(theme.font("sans", 15, 600))
        row.addWidget(self.brand)
        row.addStretch(1)
        self.dot = StatusDot(7)
        self.camera = QLabel(camera_text("webcam", None))
        self.camera.setFont(theme.font("sans", 12, 400))
        self.camera.setStyleSheet(f"color: {theme.MUTED};")
        self.disclaimer = QLabel("Not a medical device")
        self.disclaimer.setFont(theme.font("mono", 12, 400))
        self.disclaimer.setStyleSheet(f"color: {theme.MUTED};")
        row.addWidget(self.dot)
        row.addSpacing(-2)
        row.addWidget(self.camera)
        row.addSpacing(18)
        row.addWidget(self.disclaimer)

    def set_camera(self, source: str, fps: float | None, running: bool) -> None:
        self.camera.setText(camera_text(source, fps))
        self.dot.set_color(theme.GOOD if running and fps and fps > 0 else theme.DISABLED_TEXT)

    def sizeHint(self) -> QSize:
        return QSize(600, theme.TOPBAR_H)


# ---------------------------------------------------------------- signal quality: pure helpers

def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def snr_fraction(snr_db: float | None) -> float | None:
    """Position of an SNR on the quality scale, 0 at SNR_SCALE_LO and 1 at SNR_SCALE_HI; values outside are clamped to
    the ends. None (no SNR) gives None, so no marker is drawn."""
    if snr_db is None:
        return None
    lo, hi = theme.SNR_SCALE_LO, theme.SNR_SCALE_HI
    return _clamp01((snr_db - lo) / (hi - lo))


def zone_fractions(fair_db: float | None = None, good_db: float | None = None) -> tuple[float, float, float]:
    """Widths (as fractions of the scale) of the poor, fair and good zones. The boundaries are config.SNR_FAIR_DB and
    config.SNR_GOOD_DB (0 and +2 dB: 1/3, 1/6 and 1/2 of the -4 to +8 dB scale)."""
    fair = config.SNR_FAIR_DB if fair_db is None else fair_db
    good = config.SNR_GOOD_DB if good_db is None else good_db
    f, g = snr_fraction(fair), snr_fraction(max(good, fair))
    return f, g - f, 1.0 - g


def _db_text(v: float) -> str:
    return "0" if v == 0 else f"{v:+g}"


def tick_marks(fair_db: float | None = None, good_db: float | None = None) -> list[tuple[float, str, str]]:
    """(position 0-1, label, anchor) for the scale: the two ends and the two zone boundaries, from config."""
    fair = config.SNR_FAIR_DB if fair_db is None else fair_db
    good = config.SNR_GOOD_DB if good_db is None else good_db
    return [(0.0, _db_text(theme.SNR_SCALE_LO), "left"),
            (snr_fraction(fair), f"{_db_text(fair)} fair", "center"),
            (snr_fraction(good), f"{_db_text(good)} good", "center"),
            (1.0, f"{_db_text(theme.SNR_SCALE_HI)} dB", "right")]


def light_bar(level: float | None) -> tuple[float, float]:
    """(fill, threshold tick) of the light bar as fractions of 0-255: the live ROI brightness and
    config.LOW_LIGHT_LEVEL. No reading gives an empty bar."""
    tick = _clamp01(config.LOW_LIGHT_LEVEL / theme.LIGHT_MAX)
    return (0.0 if level is None else _clamp01(level / theme.LIGHT_MAX)), tick


SHARE_KEYS = ("good", "fair", "poor")


class QualityShare:
    """Rolling record of the quality of each estimate update over the last SHARE_WINDOW_SEC seconds (UI layer only; the
    estimator is not involved). Updates without a quality (warm-up, no face: "n/a") are not counted."""

    def __init__(self, window_sec: float | None = None):
        self.window = theme.SHARE_WINDOW_SEC if window_sec is None else window_sec
        self._items: deque[tuple[float, str]] = deque()

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def add(self, t: float, quality: str) -> None:
        """Record one update at stream time t. A second call with the same t (an extra refresh of the same result) is
        ignored, and so is a quality that is not good, fair or poor."""
        if self._items and t == self._items[-1][0]:
            return
        if quality in SHARE_KEYS:
            self._items.append((t, quality))
        while self._items and t - self._items[0][0] > self.window:
            self._items.popleft()

    def shares(self) -> dict[str, int] | None:
        """Whole percentages of good, fair and poor that sum to 100 (largest remainder), or None with no data."""
        n = len(self._items)
        if n == 0:
            return None
        counts = {k: sum(1 for _, q in self._items if q == k) for k in SHARE_KEYS}
        exact = {k: 100.0 * c / n for k, c in counts.items()}
        out = {k: int(v) for k, v in exact.items()}
        for k in sorted(SHARE_KEYS, key=lambda k: exact[k] - out[k], reverse=True)[:100 - sum(out.values())]:
            out[k] += 1
        return out


class FaceLock:
    """What the video tag may claim about the face, from the real per-frame `face_found` and `relock` flags only.

    FaceROI flags the start of a lock and again the freeze that ends it, so while a face is present the flags alternate:
    "locking" after a start flag, "locked" after the freeze flag, back to "locking" on a re-lock. A face with no flag
    seen yet is only "found". No face is "no_face".
    """
    TEXT = {"no_face": "NO FACE", "found": "FACE FOUND", "locking": "LOCKING", "locked": "FACE LOCKED"}

    def __init__(self):
        self.state = "no_face"

    def reset(self) -> None:
        self.state = "no_face"

    def update(self, face_found: bool, relock: bool) -> str:
        if not face_found:
            self.state = "no_face"
        elif relock:
            self.state = "locked" if self.state == "locking" else "locking"
        elif self.state == "no_face":
            self.state = "found"
        return self.state

    @property
    def text(self) -> str:
        return self.TEXT[self.state]


# ---------------------------------------------------------------- signal quality: widgets

class SnrScale(QWidget):
    """Horizontal -4 to +8 dB scale: poor, fair and good zones, a white marker at the current SNR, tick labels."""
    BAR_H = 10
    MARK_H = 20
    TICK_GAP = 8
    TICK_H = 14

    def __init__(self):
        super().__init__()
        self._snr: float | None = None
        self.setFixedHeight(self.MARK_H + self.TICK_GAP + self.TICK_H - 5)
        self.setMinimumWidth(160)
        self._font = theme.font("mono", 11, 400)

    def set_snr(self, snr_db: float | None) -> None:
        if snr_db != self._snr:
            self._snr = snr_db
            self.update()

    @property
    def marker_fraction(self) -> float | None:
        return snr_fraction(self._snr)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = float(self.width())
        top = (self.MARK_H - self.BAR_H) / 2
        bar = QRectF(0, top, w, self.BAR_H)
        clip = QPainterPath()
        clip.addRoundedRect(bar, self.BAR_H / 2, self.BAR_H / 2)
        p.save()
        p.setClipPath(clip)
        x = 0.0
        for frac, colour in zip(zone_fractions(), (theme.ZONE_POOR, theme.ZONE_FAIR, theme.ZONE_GOOD)):
            p.fillRect(QRectF(x, top, frac * w, self.BAR_H), theme.color(colour))
            x += frac * w
        p.restore()
        m = self.marker_fraction
        if m is not None:
            mx = min(max(m * w, 1.0), w - 1.0)                       # keep the 2 px marker inside the widget
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color(theme.WHITE))
            p.drawRoundedRect(QRectF(mx - 1, 0, 2, self.MARK_H), 1, 1)
        p.setFont(self._font)
        p.setPen(theme.color(theme.MUTED))
        fm = QFontMetrics(self._font)
        y = self.MARK_H + self.TICK_GAP - 5
        for frac, text, anchor in tick_marks():
            tw = fm.horizontalAdvance(text)
            x0 = {"left": 0.0, "right": w - tw}.get(anchor, frac * w - tw / 2)
            p.drawText(QRectF(x0, y, tw + 2, self.TICK_H), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


class ShareBar(QWidget):
    """Proportion bar: good, fair and poor shares as coloured segments with 2 px gaps; an empty track with no data."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(8)
        self._shares: dict[str, int] | None = None

    def set_shares(self, shares: dict[str, int] | None) -> None:
        if shares != self._shares:
            self._shares = shares
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h, w = float(self.height()), float(self.width())
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        p.setClipPath(clip)
        if not self._shares:
            p.fillRect(QRectF(0, 0, w, h), theme.color(theme.BORDER))
            p.end()
            return
        parts = [(k, v) for k, v in self._shares.items() if v > 0]
        gap = 2.0
        usable = w - gap * (len(parts) - 1)
        colours = {"good": theme.ZONE_GOOD, "fair": theme.ZONE_FAIR, "poor": theme.ZONE_POOR}
        x = 0.0
        for k, v in parts:
            seg = usable * v / 100.0
            p.fillRect(QRectF(x, 0, seg, h), theme.color(colours[k]))
            x += seg + gap
        p.end()


class Swatch(QWidget):
    def __init__(self, colour: str, size: int = 9):
        super().__init__()
        self.setFixedSize(size, size)
        self._colour = colour

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color(self._colour))
        p.drawRoundedRect(QRectF(self.rect()), 2, 2)
        p.end()


class QualityPanel(Panel):
    """Signal quality: the current label, the SNR on its scale, and the share of good, fair and poor windows."""
    LEGEND_COLOURS = {"good": theme.ZONE_GOOD, "fair": theme.ZONE_FAIR, "poor": theme.ZONE_POOR}

    def __init__(self):
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 18)
        box.setSpacing(theme.SPACING)

        head = QHBoxLayout()
        head.addWidget(Lbl("Signal quality"))
        head.addStretch(1)
        self.state_dot = StatusDot(8)
        self.state_text = QLabel(theme.QUALITY_NAME["n/a"])
        self.state_text.setFont(theme.font("sans", 13, 400))
        self.state_text.setStyleSheet(f"color: {theme.TEXT_SOFT};")
        head.addWidget(self.state_dot)
        head.addSpacing(2)
        head.addWidget(self.state_text)
        box.addLayout(head)

        snr_row = QHBoxLayout()
        label = QLabel("SNR now")
        label.setFont(theme.font("sans", 12, 400))
        label.setStyleSheet(f"color: {theme.MUTED};")
        self.snr_value = QLabel("--")
        self.snr_value.setFont(theme.font("mono", 15, 500))
        self.snr_value.setStyleSheet(f"color: {theme.WHITE};")
        snr_row.addWidget(label)
        snr_row.addStretch(1)
        snr_row.addWidget(self.snr_value)
        self.scale = SnrScale()
        snr_col = QVBoxLayout()
        snr_col.setSpacing(10)
        snr_col.addLayout(snr_row)
        snr_col.addWidget(self.scale)
        box.addLayout(snr_col)

        share_col = QVBoxLayout()
        share_col.setSpacing(8)
        caption = QLabel(f"Last {theme.SHARE_WINDOW_SEC:.0f} s of windows")
        caption.setFont(theme.font("sans", 12, 400))
        caption.setStyleSheet(f"color: {theme.MUTED};")
        self.share_bar = ShareBar()
        legend = QHBoxLayout()
        legend.setSpacing(22)
        self.legend: dict[str, QLabel] = {}
        for key in SHARE_KEYS:
            item = QHBoxLayout()
            item.setSpacing(7)
            item.addWidget(Swatch(self.LEGEND_COLOURS[key]))
            text = QLabel(f"{key.capitalize()} --")
            text.setFont(theme.font("sans", 12, 400))
            text.setStyleSheet(f"color: {theme.TEXT_SOFT};")
            self.legend[key] = text
            item.addWidget(text)
            legend.addLayout(item)
        legend.addStretch(1)
        share_col.addWidget(caption)
        share_col.addWidget(self.share_bar)
        share_col.addSpacing(2)
        share_col.addLayout(legend)
        box.addLayout(share_col)

    def update_display(self, quality: str, snr_text: str, snr_db: float | None, shares: dict[str, int] | None) -> None:
        self.state_text.setText(theme.QUALITY_NAME[quality])
        self.state_dot.set_color(theme.QUALITY_COLOR[quality])
        self.snr_value.setText(snr_text)
        self.scale.set_snr(snr_db)
        self.share_bar.set_shares(shares)
        for key, label in self.legend.items():
            label.setText(f"{key.capitalize()} {shares[key]}%" if shares else f"{key.capitalize()} --")
