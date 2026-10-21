"""PulseCam entry point: QApplication + MainWindow. Webcam by default; --mock for the synthetic source."""
import argparse
import sys

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from ui import theme
from ui.main_window import MainWindow


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="start with the mock source (cycles through every state)")
    ap.add_argument("--steady", action="store_true", help="mock source, but a steady clean 72 BPM instead of the cycle")
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    pg.setConfigOptions(antialias=True)
    theme.apply(app)
    window = MainWindow(source="mock" if (args.mock or args.steady) else "webcam", steady=args.steady)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
