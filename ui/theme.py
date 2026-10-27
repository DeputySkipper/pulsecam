"""Colour tokens, fonts, animation constants and the application stylesheet.

The look is an instrument display in black mode: a near-black base with a fine measurement grid that fades towards the
edges, frosted rounded panels with a fine rim, one accent colour (clinical cyan: the pulse trace, the heartbeat dot, the
primary action), and colour otherwise only where it carries meaning (good, fair, poor). Qt has no backdrop blur, so the
frosting is painted (see ui/panels.py: paint_glass and Dashboard).
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# ---- surfaces
BG = "#030406"                      # window background (near black)
BG_TOP = "#070B10"                  # the background lifts to this at the top: a quiet change in the same hue
# ambient light: one soft field in the same family, so the panels have something faint to frost against.
# (centre x, centre y) as fractions of the window, radius as a fraction of its longer side, colour, peak alpha
AURORA = (
    (0.50, -0.15, 0.80, "#14343D", 0.22),
)
# the measurement grid behind everything: fine lines every GRID_MINOR_PX, a stronger line every GRID_MAJOR_EVERY-th,
# small registration crosses where two strong lines meet, all fading towards the window edges
GRID_COLOR = "#8FD3DE"
GRID_MINOR_PX = 24
GRID_MAJOR_EVERY = 5
GRID_MINOR_ALPHA, GRID_MAJOR_ALPHA, GRID_CROSS_ALPHA = 0.06, 0.13, 0.30
GRID_CROSS_ARM = 4                  # px
GRID_FADE_MIN = 0.12                # grid strength at the far edge, relative to the centre
PANEL_SCRIM_ALPHA = 0.72            # black laid under a panel's glass: dims the grid behind it (text sits on a calm surface; MUTED reaches 4.5:1 even at the brightest grid crossing)
NOTCH_LEN = 30                      # px: the short accent segment on the top edge of a panel
PANEL_GRID_MINOR_ALPHA, PANEL_GRID_MAJOR_ALPHA = 0.03, 0.06      # the same grid drawn inside the panels (no crosses)
# the Light frame's edge light: white at the rim of the dashboard, falling off smoothly into the dark UI, whose corners
# are rounded (like the macOS edge light). A solid band, then a smoothstep fade, around a rounded rectangle.
LIGHT_GLOW_EDGE_PX = 10             # solid white inside the dashboard's edge, so it joins the white frame seamlessly
LIGHT_GLOW_FADE_PX = 140            # width of the fade into the dark
LIGHT_GLOW_FALLOFF = 0.85           # alpha = (1 - distance/width) ** this: bright near the rim, then falling away
PANEL_SCRIM_ALPHA_LIGHT = 0.88      # panels get a darker scrim while the Light frame is on: dark glass cards on bright light
LIGHT_GLOW_RADIUS = 52              # corner radius of the dark area
PLOT_GRID_ALPHA = 0.09              # grid lines inside the two plots (like ECG paper)
GLASS_TOP_ALPHA = 0.085             # panel fill: white, a little brighter at the top...
GLASS_BOTTOM_ALPHA = 0.035          # ...fading to this at the bottom
GLASS_RIM_TOP = 0.24                # rim: white at the top left...
GLASS_RIM_BOTTOM = 0.06             # ...to this at the bottom right
GLASS_SPECULAR = 0.20               # peak alpha of the thin highlight along the top edge
PANEL = "#111A21"                   # a panel flattened over the background, for widgets that cannot be translucent
BORDER = "#25313B"                  # dividers and empty tracks
VIDEO_BG = "#05080B"

# ---- text
TEXT = "#EAF0F4"
TEXT_SOFT = "#C4CFD8"
MUTED = "#AEBBC7"
WHITE = "#FFFFFF"

# ---- controls
BTN_FILL = "#16202A"                # solid versions, for popups and the tooltip (which cannot be translucent)
BTN_BORDER = "#33414D"
BTN_FILL_HOVER = "#1E2B37"
BTN_BORDER_HOVER = "#4C5E6D"
BTN_ALPHA, BTN_ALPHA_HOVER, BTN_ALPHA_CHECKED = 0.06, 0.12, 0.16      # a glass control: white at this alpha
BTN_RIM, BTN_RIM_HOVER = 0.16, 0.36                                    # its 1 px rim: white at this alpha
ACCENT = "#4CC9D8"                  # clinical cyan: the pulse trace, the heartbeat dot, the primary action
PRIMARY_FILL = ACCENT
PRIMARY_FILL_HOVER = "#7EDCE8"
PRIMARY_FILL_LOW = "#34AEBF"        # the primary button fades to this at the bottom
PRIMARY_TEXT = "#04212A"
FIELD_FILL = "#0A1218"
FIELD_ALPHA, FIELD_RIM = 0.05, 0.16
PLACEHOLDER = "#9AA8B4"
FOCUS = "#7EDCE8"
CHECKED_BORDER = ACCENT
DISABLED_TEXT = "#5A6874"

# ---- status colours (dots and text) and signal-quality zones
GOOD = "#3DDC97"
FAIR = "#F2B84B"
POOR = "#FF6B6B"
ZONE_GOOD = "#2E9E72"
ZONE_FAIR = "#C79A3C"
ZONE_POOR = "#C25454"
LIGHT_FRAME = "#FFFFFF"

QUALITY_COLOR = {"good": GOOD, "fair": FAIR, "poor": POOR, "n/a": MUTED}
QUALITY_NAME = {"good": "Good", "fair": "Fair", "poor": "Poor", "n/a": "No signal"}
HINT_COLOR = {"info": MUTED, "ok": TEXT_SOFT, "warn": FAIR, "error": POOR}
STATE_DOT_COLOR = {"info": DISABLED_TEXT, "ok": GOOD, "warn": FAIR, "error": POOR}

# ---- video tags, signal-quality scale
TAG_FILL = (6, 12, 16, 160)         # a dark frosted tag on top of the video
TAG_BORDER = "#33414D"
TAG_TEXT = "#D5DEE6"
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
CARD_BORDER_ACTIVE = ACCENT
LIGHT_TRACK = "#25313B"
LIGHT_FILL = "#8FB8C2"
LIGHT_TICK = "#8896A3"
SPECTRUM_TICKS_BPM = (54, 90, 120, 150, 180)
SPECTRUM_LINE = "#CFEFF4"

# ---- sizes (px)
SPACING = 16                        # gap between panels
MARGIN = 24                         # outer margin of the dashboard
RADIUS = 20                         # panels
CARD_RADIUS = 16                    # the method cards
VIDEO_RADIUS = 16
TAG_RADIUS = 8
CONTROL_RADIUS = 14                 # rounded rectangles, not pills (an icon-only button is a rounded square)
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
    #video {{ background: transparent; border: none; color: {MUTED}; }}
    QComboBox QAbstractItemView {{
        background: {BTN_FILL}; border: 1px solid {BTN_BORDER}; border-radius: 14px;
        selection-background-color: {BTN_FILL_HOVER}; selection-color: {WHITE}; color: {TEXT}; outline: 0; padding: 6px;
    }}
    QLineEdit {{
        background: rgba(255, 255, 255, {int(FIELD_ALPHA * 255)}); border: 1px solid rgba(255, 255, 255, {int(FIELD_RIM * 255)});
        border-radius: {CONTROL_RADIUS}px; padding: 0 16px; font-size: {STAT_FONT_PX}px; color: {TEXT};
        placeholder-text-color: {PLACEHOLDER}; selection-background-color: {BTN_BORDER_HOVER};
    }}
    QLineEdit:hover {{ border: 1px solid rgba(255, 255, 255, {int(BTN_RIM_HOVER * 255)}); }}
    QLineEdit:focus {{ border: 1px solid {FOCUS}; background: rgba(255, 255, 255, {int(BTN_ALPHA_HOVER * 255)}); }}
    QToolTip {{ background: {BTN_FILL}; color: {TEXT}; border: 1px solid {BTN_BORDER}; border-radius: 8px; padding: 5px 8px; }}
    """
