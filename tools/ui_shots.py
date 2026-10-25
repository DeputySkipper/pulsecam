"""Headless UI screenshots: drives the dashboard through every mock state and saves PNGs to debug/shots/.

    python tools/ui_shots.py              # every mock state at 1280x800, plus light-frame-on (1440x1000) and 1100x720 / 1366x768 / 1440x900 size shots
    python tools/ui_shots.py --dashboard  # one slide-ready shot: steady 72 BPM reading -> debug/shots/dashboard.png
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":        # the offscreen platform finds no fonts on Windows unless told where they are
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pyqtgraph as pg  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import config  # noqa: E402
from capture import MockSource  # noqa: E402
from ui import theme  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

# seconds into the mock cycle -> file name (cycle: measuring 0-30, dim 30-38, poor 38-52, no face 52-56)
STATES = {6: "1_warming_up", 25: "2_measuring", 34: "3_low_light", 41: "4_poor_held", 48: "5_poor_dashes", 54: "6_no_face"}


DASHBOARD_SIZE = (1440, 900)
SIZES = ((1100, 720), (1366, 768), (1440, 900))
DASHBOARD_SETTLE_SEC = 30.0       # long enough for the warm-up and the first confirmed number


def dashboard(out: Path) -> int:
    """A single measuring frame from the steady 72 BPM mock, for slides."""
    app = QApplication([])
    pg.setConfigOptions(antialias=True)
    theme.apply(app)
    w = MainWindow(source="mock", steady=True)
    w.resize(*DASHBOARD_SIZE)
    w.show()
    w._running = True
    w._mock = MockSource(scenario=False)
    w.start_button.setText("Stop")
    step = 1.0 / config.MOCK_HZ
    for i in range(int(DASHBOARD_SETTLE_SEC * config.MOCK_HZ)):
        t = i * step
        w._on_sample(w._mock.sample_at(t))
        if i % int(config.MOCK_HZ) == 0 and t > 0:
            w._estimate()
    w._refresh()
    app.processEvents()
    path = out / "dashboard.png"
    w.grab().save(str(path))
    print(f"saved {path}: '{w.panel.state_line.text()}', {w.panel.number.text()} BPM, {w.quality_panel.state_text.text()}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", action="store_true", help="save one steady 72 BPM dashboard shot for slides")
    args = ap.parse_args()
    out = ROOT / "debug" / "shots"
    out.mkdir(parents=True, exist_ok=True)
    if args.dashboard:
        return dashboard(out)
    app = QApplication([])
    pg.setConfigOptions(antialias=True)
    theme.apply(app)
    w = MainWindow(source="mock")
    w.resize(1280, 800)
    w.show()
    w._running = True
    w._mock = MockSource()
    w.start_button.setText("Stop")
    step = 1.0 / config.MOCK_HZ
    last = max(STATES)
    for i in range(int((last + 1) * config.MOCK_HZ)):
        t = i * step
        w._on_sample(w._mock.sample_at(t))
        if i % int(config.MOCK_HZ) == 0 and t > 0:
            w._estimate()
        if i % 3 == 0:
            w._refresh()
        if i % int(config.MOCK_HZ) == 0 and int(t) in STATES:
            w._refresh()
            app.processEvents()
            w.grab().save(str(out / f"{STATES[int(t)]}.png"))
            print(f"saved {STATES[int(t)]}.png  (t={int(t)} s: '{w.panel.state_line.text()}', {w.panel.number.text()} BPM)")
    # back to a measuring frame for the layout variants
    t = 56.0
    while t < 56.0 + 28.0:
        w._on_sample(w._mock.sample_at(t))
        if abs(t - round(t)) < step / 2:
            w._estimate()
        t += step
    w._refresh()
    w.light_button.setChecked(True)        # the window grows to keep the dashboard at its minimum size (screen permitting)
    w.resize(1440, 1000)
    app.processEvents()
    w._refresh()
    w.grab().save(str(out / "7_light_frame_on_1440x1000.png"))
    w.light_button.setChecked(False)
    for size in SIZES:                     # the layout is flexible in height: compare the three common sizes
        w.resize(*size)
        app.processEvents()
        w._refresh()
        app.processEvents()
        name = f"size_{size[0]}x{size[1]}.png"
        w.grab().save(str(out / name))
        print(f"saved {name}: window {w.width()}x{w.height()}, hero {w.panel.height()} px, cards {w.cards.height() - 12} px, "
              f"plots {w.pulse_card.height()} px, video {w.video.height()} px")
    print(f"saved light-frame and size variants; all in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
