"""Hover-animated controls: a scale mixin and the buttons built on it.

A control scales up slightly on hover and down when pressed. The scaling is a QPainter transform applied inside
paintEvent, so the widget's geometry and hit area never change. `theme.ANIM_MARGIN` px are reserved around the drawn
control so the enlarged drawing never clips. With `theme.ANIMATIONS = False` the scale stays at 1 (colours still react).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QPushButton, QSizePolicy

from ui import theme


def scale_target(hover: bool, pressed: bool, hover_scale: float) -> float:
    """Scale a control eases towards: PRESS_SCALE while pressed, hover_scale while hovered, else 1."""
    if not theme.ANIMATIONS:
        return 1.0
    if pressed:
        return theme.PRESS_SCALE
    return hover_scale if hover else 1.0


def mix_color(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    t = min(1.0, max(0.0, t))
    return QColor.fromRgbF(*(x + (y - x) * t for x, y in zip(ca.getRgbF(), cb.getRgbF())))


def ease_curve() -> QEasingCurve:
    """cubic-bezier(.2, .8, .2, 1), the reference's easing."""
    curve = QEasingCurve(QEasingCurve.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.2, 0.8), QPointF(0.2, 1.0), QPointF(1.0, 1.0))
    return curve


class Scaled:
    """Mixin for a QWidget: hover and press animation, and a painter already scaled about the control's centre.

    Put it before the Qt base class and call `init_scale()` after the Qt constructor.
    """
    hover_scale = theme.HOVER_SCALE_BUTTON

    def init_scale(self) -> None:
        self._hover = False
        self._pressed = False
        self._scale = 1.0
        self._mix = 0.0                                     # 0 = resting colours, 1 = hover colours
        self._scale_anim = QVariantAnimation(self)
        self._scale_anim.setDuration(theme.ANIM_MS)
        self._scale_anim.setEasingCurve(ease_curve())
        self._scale_anim.valueChanged.connect(self._set_scale)
        self._mix_anim = QVariantAnimation(self)
        self._mix_anim.setDuration(theme.COLOR_MS)
        self._mix_anim.valueChanged.connect(self._set_mix)

    # -- state
    @property
    def scale(self) -> float:
        return self._scale

    def set_hover(self, on: bool) -> None:
        self._hover = on
        self._retarget()

    def set_pressed(self, on: bool) -> None:
        self._pressed = on
        self._retarget()

    def _retarget(self) -> None:
        target = scale_target(self._hover, self._pressed, self.hover_scale)
        mix_target = 1.0 if (self._hover or self._pressed) else 0.0
        for anim, current, end in ((self._scale_anim, self._scale, target), (self._mix_anim, self._mix, mix_target)):
            anim.stop()
            if not theme.ANIMATIONS:
                continue
            anim.setStartValue(current)
            anim.setEndValue(end)
            anim.start()
        if not theme.ANIMATIONS:
            self._scale, self._mix = 1.0, mix_target       # colours still react, instantly; no scaling
            self.update()

    def _set_scale(self, v) -> None:
        self._scale = float(v)
        self.update()

    def _set_mix(self, v) -> None:
        self._mix = float(v)
        self.update()

    # -- events
    def enterEvent(self, event) -> None:
        self.set_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.set_hover(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.set_pressed(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.set_pressed(False)
        super().mouseReleaseEvent(event)

    # -- painting
    def begin_paint(self, scale: float | None = None) -> tuple[QPainter, QRectF]:
        """A painter scaled about the centre of the drawn control, and that control's unscaled rectangle."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        m = theme.ANIM_MARGIN
        rect = QRectF(self.rect()).adjusted(m, m, -m, -m)
        c = rect.center()
        p.translate(c)
        p.scale(self._scale if scale is None else scale, self._scale if scale is None else scale)
        p.translate(-c)
        return p, rect


# ---------------------------------------------------------------- glyphs (drawn, no image files)

def glyph_path(name: str) -> tuple[QPainterPath, bool]:
    """(path in a 24 x 24 box, filled?) for a glyph name."""
    p = QPainterPath()
    if name == "stop":
        p.addRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
        return p, True
    if name == "play":
        p.moveTo(8, 5.5)
        p.lineTo(18.5, 12)
        p.lineTo(8, 18.5)
        p.closeSubpath()
        return p, True
    if name == "record":
        p.addEllipse(QPointF(12, 12), 7, 7)
        p.addEllipse(QPointF(12, 12), 2.5, 2.5)
        return p, False
    if name == "log":
        for y, x1 in ((6, 19), (12, 19), (18, 14)):
            p.moveTo(5, y)
            p.lineTo(x1, y)
        return p, False
    if name == "light":
        p.addEllipse(QPointF(12, 12), 4, 4)
        for x0, y0, x1, y1 in ((12, 3, 12, 5), (12, 19, 12, 21), (3, 12, 5, 12), (19, 12, 21, 12), (5.6, 5.6, 7, 7),
                               (17, 17, 18.4, 18.4), (18.4, 5.6, 17, 7), (7, 17, 5.6, 18.4)):
            p.moveTo(x0, y0)
            p.lineTo(x1, y1)
        return p, False
    if name == "fullscreen":
        for pts in (((4, 9), (4, 4), (9, 4)), ((20, 9), (20, 4), (15, 4)), ((4, 15), (4, 20), (9, 20)),
                    ((20, 15), (20, 20), (15, 20))):
            p.moveTo(*pts[0])
            p.lineTo(*pts[1])
            p.lineTo(*pts[2])
        return p, False
    if name == "chevron":
        p.moveTo(6, 9)
        p.lineTo(12, 15)
        p.lineTo(18, 9)
        return p, False
    raise ValueError(f"unknown glyph {name!r}")


GLYPH_PX = 16


def draw_glyph(p: QPainter, name: str, x: float, y: float, color: QColor) -> None:
    """Draw a glyph with its top-left at (x, y), GLYPH_PX square: stroke 1.6 in the 24 box, like the reference."""
    path, filled = glyph_path(name)
    p.save()
    p.translate(x, y)
    p.scale(GLYPH_PX / 24, GLYPH_PX / 24)
    if filled:
        p.setPen(Qt.NoPen)
        p.setBrush(color)
    else:
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    if name == "record":                                    # the inner dot is filled
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(12, 12), 2.5, 2.5)
    p.restore()


# ---------------------------------------------------------------- shared look

PAD_X = 16                                                  # horizontal padding inside a button
GLYPH_GAP = 8


def _white(alpha: float) -> QColor:
    return theme.color(theme.WHITE, alpha)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _colors(primary: bool, enabled: bool, checked: bool, mix: float) -> tuple[QColor, QColor, QColor]:
    """(fill, border, text) for the control's current state. Glass controls are white at a low alpha; the primary
    control is a solid light pill."""
    if primary:
        fill = mix_color(theme.PRIMARY_FILL, theme.PRIMARY_FILL_HOVER, mix)
        return fill, QColor(fill), QColor(theme.PRIMARY_TEXT)
    if not enabled:
        return _white(0.04), _white(0.10), QColor(theme.DISABLED_TEXT)
    if checked:
        return _white(theme.BTN_ALPHA_CHECKED), theme.color(theme.CHECKED_BORDER, 0.85), QColor(theme.TEXT)
    return (_white(_lerp(theme.BTN_ALPHA, theme.BTN_ALPHA_HOVER, mix)),
            _white(_lerp(theme.BTN_RIM, theme.BTN_RIM_HOVER, mix)), QColor(theme.TEXT))


def _draw_body(p: QPainter, rect: QRectF, fill: QColor, border: QColor, focus: bool, primary: bool = False) -> None:
    """A rounded rectangle (radius CONTROL_RADIUS) with a soft sheen across its top half."""
    body = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    r = min(float(theme.CONTROL_RADIUS), body.height() / 2)
    path = QPainterPath()
    path.addRoundedRect(body, r, r)
    if primary:                                             # a faint glow in the margin reserved for the hover scale
        for grow, alpha in ((1.0, 0.16), (2.0, 0.08)):          # stays well inside ANIM_MARGIN even at full hover scale
            glow = QPainterPath()
            glow.addRoundedRect(body.adjusted(-grow, -grow, grow, grow), r + grow, r + grow)
            p.setPen(QPen(_white(alpha), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(glow)
    if focus:                                               # 2 px ring, 2 px outside the control
        p.setPen(QPen(QColor(theme.FOCUS), 2))
        p.setBrush(Qt.NoBrush)
        ring = QPainterPath()
        ring.addRoundedRect(rect.adjusted(-2, -2, 2, 2), r + 2, r + 2)
        p.drawPath(ring)
    if primary:
        grad = QLinearGradient(body.topLeft(), body.bottomLeft())
        grad.setColorAt(0.0, fill)
        grad.setColorAt(1.0, mix_color(fill.name(), theme.PRIMARY_FILL_LOW, 0.85))
        p.fillPath(path, QBrush(grad))
    else:
        p.fillPath(path, fill)
        sheen = QLinearGradient(body.topLeft(), body.bottomLeft())
        sheen.setColorAt(0.0, _white(0.16))
        sheen.setColorAt(0.55, _white(0.0))
        p.fillPath(path, QBrush(sheen))
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class AnimButton(Scaled, QPushButton):
    """A 40 px button: text, an optional glyph, optional `primary` look, checkable like any QPushButton.

    glyph "run" draws a play triangle while the text is "Start" and a stop square while it is "Stop".
    """

    def __init__(self, text: str = "", glyph: str | None = None, primary: bool = False, checkable: bool = False,
                 parent=None):
        super().__init__(text, parent)
        self.glyph, self.primary = glyph, primary
        self.setCheckable(checkable)
        self.setFont(theme.font("sans", theme.STAT_FONT_PX, 500))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(theme.CONTROL_H + 2 * theme.ANIM_MARGIN)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._kb_focus = False
        self.init_scale()

    def current_glyph(self) -> str | None:
        if self.glyph == "run":
            return "stop" if self.text() == "Stop" else "play"
        return self.glyph

    def sizeHint(self) -> QSize:
        m = 2 * theme.ANIM_MARGIN
        if not self.text():
            return QSize(theme.CONTROL_H + m, theme.CONTROL_H + m)
        w = 2 * PAD_X + QFontMetrics(self.font()).horizontalAdvance(self.text())
        if self.glyph:
            w += GLYPH_PX + GLYPH_GAP
        return QSize(w + m, theme.CONTROL_H + m)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def focusInEvent(self, event) -> None:
        self._kb_focus = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._kb_focus = False
        super().focusOutEvent(event)

    def paintEvent(self, event) -> None:
        p, rect = self.begin_paint()
        fill, border, text_color = _colors(self.primary, self.isEnabled(), self.isChecked(), self._mix)
        _draw_body(p, rect, fill, border, self._kb_focus and self.hasFocus(), primary=self.primary)
        glyph = self.current_glyph()
        fm = QFontMetrics(self.font())
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        content_w = text_w + (GLYPH_PX + (GLYPH_GAP if text_w else 0) if glyph else 0)
        x = rect.center().x() - content_w / 2
        if glyph:
            draw_glyph(p, glyph, x, rect.center().y() - GLYPH_PX / 2, text_color)
            x += GLYPH_PX + (GLYPH_GAP if text_w else 0)
        if text_w:
            p.setPen(text_color)
            p.setFont(self.font())
            p.drawText(QRectF(x, rect.top(), text_w + 2, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class ComboButton(Scaled, QComboBox):
    """A QComboBox drawn like the reference's "Method: CHROM v" button. The items, signals and popup are the
    standard QComboBox ones, so it is driven exactly like a combo box."""
    MAX_TEXT_W = theme.MAX_CONTROL_W - 2 * 16 - 8 - 16          # text area so that the whole control is at most MAX_CONTROL_W

    def __init__(self, prefix: str = "", parent=None):
        super().__init__(parent)
        self.prefix = prefix
        self._popup_open = False
        self._kb_focus = False
        self.setFont(theme.font("sans", theme.STAT_FONT_PX, 500))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(theme.CONTROL_H + 2 * theme.ANIM_MARGIN)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.init_scale()

    def display_text(self) -> str:
        return f"{self.prefix}: {self.currentText()}" if self.prefix else self.currentText()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        longest = max((fm.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        pre = fm.horizontalAdvance(f"{self.prefix}: ") if self.prefix else 0
        w = 2 * PAD_X + min(pre + longest, self.MAX_TEXT_W) + GLYPH_GAP + GLYPH_PX
        return QSize(w + 2 * theme.ANIM_MARGIN, theme.CONTROL_H + 2 * theme.ANIM_MARGIN)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def showPopup(self) -> None:
        self._popup_open = True
        self.set_pressed(False)
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self._popup_open = False
        self.set_pressed(False)
        self.set_hover(self.underMouse())

    def focusInEvent(self, event) -> None:
        self._kb_focus = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._kb_focus = False
        super().focusOutEvent(event)

    def paintEvent(self, event) -> None:
        p, rect = self.begin_paint()
        fill, border, text_color = _colors(False, self.isEnabled(), self._popup_open, self._mix)
        _draw_body(p, rect, fill, border, self._kb_focus and self.hasFocus())
        text_rect = QRectF(rect.left() + PAD_X, rect.top(), rect.width() - 2 * PAD_X - GLYPH_GAP - GLYPH_PX, rect.height())
        p.setPen(text_color)
        p.setFont(self.font())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(self.font()).elidedText(self.display_text(), Qt.ElideRight, int(text_rect.width())))
        draw_glyph(p, "chevron", rect.right() - PAD_X - GLYPH_PX, rect.center().y() - GLYPH_PX / 2, text_color)
        p.end()
