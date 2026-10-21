"""Colour tokens, fonts and the application stylesheet (TRD section 8)."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

BG = "#0E1116"
PANEL = "#161B22"
BORDER = "#262C36"
TEXT = "#E6EDF3"
MUTED = "#8B949E"
ACCENT = "#FF4D6D"          # pulse colour: the only accent
GOOD = "#3FB950"
FAIR = "#D29922"
POOR = "#F85149"
LIGHT_FRAME = "#FFFFFF"

QUALITY_COLOR = {"good": GOOD, "fair": FAIR, "poor": POOR, "n/a": MUTED}
QUALITY_TEXT = {"good": "Good signal", "fair": "Fair signal", "poor": "Poor signal", "n/a": "No signal"}
HINT_COLOR = {"info": MUTED, "ok": TEXT, "warn": FAIR, "error": POOR}

SPACING = 16                # outer gutter and gap between cards
RADIUS = 10
BPM_FONT_PX = 96
STATE_FONT_PX = 20
STAT_FONT_PX = 14
SMALL_FONT_PX = 12


def apply(app: QApplication) -> None:
    font = QFont(app.font())                # the system sans-serif: native look, no missing-font fallback cost
    font.setPixelSize(STAT_FONT_PX)
    app.setFont(font)
    app.setStyleSheet(stylesheet())


def stylesheet() -> str:
    return f"""
    QWidget {{ color: {TEXT}; }}
    #dashboard {{ background: {BG}; }}
    #card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; }}
    #cardTitle {{ color: {MUTED}; font-size: {SMALL_FONT_PX}px; letter-spacing: 1px; }}
    #bpmNumber {{ font-size: {BPM_FONT_PX}px; font-weight: 600; }}
    #bpmUnit {{ color: {MUTED}; font-size: {STATE_FONT_PX}px; }}
    #stateLine {{ font-size: {STATE_FONT_PX}px; }}
    #qualityText {{ color: {MUTED}; font-size: {STAT_FONT_PX}px; }}
    #stat {{ color: {MUTED}; font-size: {STAT_FONT_PX}px; }}
    #methodCell {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 8px; }}
    #methodCell[active="true"] {{ border: 1px solid {ACCENT}; }}
    #methodName {{ color: {MUTED}; font-size: {SMALL_FONT_PX}px; letter-spacing: 1px; }}
    #methodValue {{ font-size: {STATE_FONT_PX + 4}px; font-weight: 600; }}
    #video {{ background: {BG}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; }}
    QPushButton {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
        padding: 8px 16px; font-size: {STAT_FONT_PX}px;
    }}
    QPushButton:hover {{ border: 1px solid {MUTED}; }}
    QPushButton:checked {{ border: 1px solid {ACCENT}; color: {ACCENT}; }}
    QPushButton:disabled {{ color: {BORDER}; }}
    QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: {BG}; font-weight: 600; }}
    QPushButton#primary:hover {{ border: 1px solid {TEXT}; }}
    QComboBox {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
        padding: 8px 12px; font-size: {STAT_FONT_PX}px;
    }}
    QComboBox:hover {{ border: 1px solid {MUTED}; }}
    QComboBox QAbstractItemView {{
        background: {PANEL}; border: 1px solid {BORDER}; selection-background-color: {BORDER}; color: {TEXT};
    }}
    QLineEdit {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
        padding: 8px 12px; font-size: {STAT_FONT_PX}px; color: {TEXT}; placeholder-text-color: {MUTED};
    }}
    QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
    QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; }}
    """
