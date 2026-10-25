"""Colour tokens, fonts, animation constants and the application stylesheet.

The look is a black-and-grey, flat design taken from docs/ui_reference.html. Status colours are used sparingly;
the only accents are white and grey.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# ---- surfaces
BG = "#0A0A0A"                      # window background
BG_HIGHLIGHT = "#1B1B1D"            # soft radial highlight at the top right
PANEL_ALPHA = 0.035                 # panel fill: white at 3.5%
PANEL_TOP_ALPHA = 0.05              # faint highlight along a panel's top edge
PANEL = "#131313"                   # the panel fill flattened over BG, for widgets that cannot be translucent (plots)
BORDER = "#26262A"
VIDEO_BG = "#0D0D0E"

# ---- text
TEXT = "#E8E8E8"
TEXT_SOFT = "#C8C8C8"
MUTED = "#9A9A9A"
WHITE = "#FFFFFF"

# ---- controls
BTN_FILL = "#151516"
BTN_BORDER = "#333336"
BTN_FILL_HOVER = "#1F1F21"
BTN_BORDER_HOVER = "#4A4A4E"
PRIMARY_FILL = "#EDEDED"
PRIMARY_FILL_HOVER = "#FFFFFF"
PRIMARY_TEXT = "#0A0A0A"
FIELD_FILL = "#0E0E0F"
PLACEHOLDER = "#7E7E82"
FOCUS = "#BDBDBD"
CHECKED_BORDER = "#BDBDBD"
DISABLED_TEXT = "#5A5A5E"

# ---- status colours (dots and text) and signal-quality zones
GOOD = "#7FBF9E"
FAIR = "#C9A85F"
POOR = "#B26A78"
ZONE_GOOD = "#477A60"
ZONE_FAIR = "#8A7447"
ZONE_POOR = "#7A4450"
LIGHT_FRAME = "#FFFFFF"

QUALITY_COLOR = {"good": GOOD, "fair": FAIR, "poor": POOR, "n/a": MUTED}
QUALITY_NAME = {"good": "Good", "fair": "Fair", "poor": "Poor", "n/a": "No signal"}
HINT_COLOR = {"info": MUTED, "ok": TEXT_SOFT, "warn": FAIR, "error": POOR}
STATE_DOT_COLOR = {"info": DISABLED_TEXT, "ok": GOOD, "warn": FAIR, "error": POOR}

# ---- video tags, signal-quality scale
TAG_FILL = (0, 0, 0, 140)           # rgba(0, 0, 0, .55)
TAG_BORDER = "#2C2C2F"
TAG_TEXT = "#C8C8C8"
SNR_SCALE_LO, SNR_SCALE_HI = -4.0, 8.0     # dB range of the quality scale
SHARE_WINDOW_SEC = 60.0                    # "last 60 s of windows"
LIGHT_MAX = 255.0                          # the light bar's full scale (0-255 camera values)

# ---- hero, cards and plots: reference sizes and the smallest they may compress to (heights are flexible; 1100x720 must fit)
HERO_H, HERO_MIN_H = 300, 190
CARDS_H, CARDS_MIN_H = 96, 72
PLOTS_H, PLOTS_MIN_H = 290, 150
PLOTS_MAX_H = 290                   # reference size is the cap; set to None to let the plots fill any extra height
HERO_NUMBER_PX, HERO_NUMBER_MIN_PX = 112, 56
STATS_W, STATS_MIN_W = 220, 164
PULSE_TAIL_SEC = 5.0                # the live pulse strip shows the newest 5 s
PULSE_STRIP_H, PULSE_STRIP_MIN_H = 54, 28
BEAT_RING_SCALE = 2.4               # the heartbeat ring grows 1 to 2.4 times and fades from 0.7 to 0
BEAT_RING_ALPHA = 0.7
CARD_BORDER_ACTIVE = "#D6D6D6"
LIGHT_TRACK = "#2A2A2D"
LIGHT_FILL = "#BDBDBD"
LIGHT_TICK = "#8C8C8C"
SPECTRUM_TICKS_BPM = (54, 90, 120, 150, 180)
SPECTRUM_LINE = "#DADADA"

# ---- sizes (px)
SPACING = 16                        # gap between panels
MARGIN = 24                         # outer margin of the dashboard
RADIUS = 12                         # panels
CONTROL_RADIUS = 8
TOPBAR_H = 56
CONTROL_H = 40
LEFT_MAX_W = 600
LEFT_MIN_W = 600                    # the controls rows need this much, so the left column is 600 at every window size
STAT_FONT_PX = 13
SMALL_FONT_PX = 11
MIN_WINDOW = (1100, 720)
DESIGN_WINDOW = (1440, 900)

# ---- animation. Qt 6.12 exposes no reduced-motion setting, so this constant is the switch: False skips every
# hover and heartbeat animation (controls stay at scale 1).
ANIMATIONS = True
HOVER_SCALE_BUTTON = 1.045
HOVER_SCALE_CARD = 1.025
PRESS_SCALE = 0.97
ANIM_MS = 180
COLOR_MS = 150
ANIM_MARGIN = 6                     # px reserved around an animated control so the scaled drawing never clips
MAX_CONTROL_W = 200                 # widest animated control (visible px): 4.5% of it stays inside ANIM_MARGIN

PLEX_SANS = "IBM Plex Sans"
PLEX_MONO = "IBM Plex Mono"


SANS_FALLBACKS = ("Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans")
MONO_FALLBACKS = ("Consolas", "Menlo", "DejaVu Sans Mono", "Courier New")


@lru_cache(maxsize=None)
def family(kind: str) -> str:
    """IBM Plex if it is installed, otherwise the system sans-serif or monospace. No font files are bundled. When the
    platform reports a generic name that is not an installed family (a headless Qt platform), the first installed
    common family is used instead."""
    installed = set(QFontDatabase.families())
    plex, role, fallbacks = ((PLEX_MONO, QFontDatabase.FixedFont, MONO_FALLBACKS) if kind == "mono"
                             else (PLEX_SANS, QFontDatabase.GeneralFont, SANS_FALLBACKS))
    if plex in installed:
        return plex
    system = QFontDatabase.systemFont(role).family()
    if system in installed or not installed:
        return system
    return next((f for f in fallbacks if f in installed), system)


def font(kind: str = "sans", px: int = STAT_FONT_PX, weight: int = 400, spacing_em: float = 0.0) -> QFont:
    """A QFont with pixel size, weight (CSS numbers: 300, 400, 500, 600) and letter-spacing in em, set on the font
    itself because QSS letter-spacing is unreliable."""
    f = QFont(family(kind))
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(weight))
    if spacing_em:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing_em * px)
    return f


def color(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


def apply(app: QApplication) -> None:
    app.setFont(font("sans", STAT_FONT_PX))
    app.setStyleSheet(stylesheet())


def stylesheet() -> str:
    """Only what Qt cannot get from painting: text colour, tooltips, the combo popup and the line edit. Buttons,
    combo faces and panels are painted by ui/animated.py and ui/panels.py."""
    return f"""
    QWidget {{ color: {TEXT}; }}
    #stat {{ color: {MUTED}; font-size: {STAT_FONT_PX}px; }}
    #video {{ background: {VIDEO_BG}; border: none; border-radius: {CONTROL_RADIUS}px; color: {MUTED}; }}
    QComboBox QAbstractItemView {{
        background: {BTN_FILL}; border: 1px solid {BTN_BORDER}; selection-background-color: {BTN_FILL_HOVER};
        selection-color: {WHITE}; color: {TEXT}; outline: 0; padding: 4px;
    }}
    QLineEdit {{
        background: {FIELD_FILL}; border: 1px solid {BTN_BORDER}; border-radius: {CONTROL_RADIUS}px;
        padding: 0 14px; font-size: {STAT_FONT_PX}px; color: {TEXT}; placeholder-text-color: {PLACEHOLDER};
        selection-background-color: {BTN_BORDER_HOVER};
    }}
    QLineEdit:hover {{ border: 1px solid {BTN_BORDER_HOVER}; }}
    QLineEdit:focus {{ border: 1px solid {FOCUS}; }}
    QToolTip {{ background: {BTN_FILL}; color: {TEXT}; border: 1px solid {BTN_BORDER}; padding: 4px 6px; }}
    """
