"""Main window: video, BPM panel, plots, controls, recording, reference logger, light frame, fullscreen (TRD section 8).

Samples reach the window through `_on_sample(FrameSample)`, from the CaptureWorker's signal (webcam, file) or
from a 30 Hz timer driving MockSource.
"""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDoubleValidator, QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
                               QVBoxLayout, QWidget)

import config
import recorder
import signal_proc
from capture import MockSource
from estimator import Estimator
from models import FrameSample
from ui import theme
from ui.widgets import BpmPanel, Card, PulsePlot, SpectrumPlot, VideoView, brightness, build_display
from worker import CaptureWorker

SOURCES = ("mock", "webcam", "file")
STATUS_CLEAR_MS = 8000
VIDEO_FILTER = "Video (*.mkv *.avi *.mp4 *.mov *.m4v);;All files (*)"


class LightFrame(QWidget):
    """Outer frame: white (on) or the app background (off). On adds LIGHT_FRAME_PX of white around the dashboard."""

    def __init__(self, inner: QWidget):
        super().__init__()
        self.setObjectName("lightFrame")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.addWidget(inner)
        self.on = False
        self.set_on(config.LIGHT_FRAME_DEFAULT)

    def set_on(self, on: bool) -> None:
        self.on = on
        margin = config.LIGHT_FRAME_PX if on else 0
        self.layout().setContentsMargins(margin, margin, margin, margin)
        self.setStyleSheet(f"#lightFrame {{ background: {theme.LIGHT_FRAME if on else theme.BG}; }}")


class MainWindow(QMainWindow):
    def __init__(self, source: str = "webcam", steady: bool = False):
        super().__init__()
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        self.setWindowTitle("PulseCam")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
        self.steady = steady
        self.estimator = Estimator(config.DEFAULT_METHOD)

        self._running = False
        self._mock: MockSource | None = None
        self._worker: CaptureWorker | None = None
        self._t0 = 0.0
        self._result = None
        self._analyses: dict = {}
        self._plots_dirty = False
        self._latest_t = 0.0
        self._warm_start = 0.0
        self._face_prev = False
        self._bright: deque[tuple[float, float]] = deque()
        self._file_path: str | None = None
        self._stopped_hint = "Press Start"
        self._recorder: recorder.Recorder | None = None
        self._rec_started = 0.0
        self._last_meta_path: Path | None = None

        self._build_ui(source)
        self._build_timers()
        self._build_shortcuts()
        self._update_controls()
        self._refresh()

    # ------------------------------------------------------------ construction

    def _build_ui(self, source: str) -> None:
        self.video = VideoView()
        self.panel = BpmPanel()
        self.pulse_plot = PulsePlot()
        self.spectrum_plot = SpectrumPlot()

        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.toggle_running)
        self.method_combo = QComboBox()
        self.method_combo.addItems(list(signal_proc.METHODS))
        self.method_combo.setCurrentText(self.estimator.method)
        self.method_combo.currentTextChanged.connect(self._on_method)
        self.source_combo = QComboBox()
        self.source_combo.addItems(["Mock", "Webcam", "File..."])
        self.source_combo.setCurrentIndex(SOURCES.index(source))
        self._source_index = self.source_combo.currentIndex()
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        self.light_button = QPushButton("Light frame")
        self.light_button.setCheckable(True)
        self.light_button.setChecked(config.LIGHT_FRAME_DEFAULT)
        self.light_button.toggled.connect(lambda on: self.light.set_on(on))
        self.full_button = QPushButton("Fullscreen")
        self.full_button.setCheckable(True)
        self.full_button.toggled.connect(self._set_fullscreen)

        self.record_button = QPushButton("Record")
        self.record_button.setCheckable(True)
        self.record_button.toggled.connect(self._on_record_toggled)
        self.ref_edit = QLineEdit()
        self.ref_edit.setPlaceholderText("Ref BPM")
        self.ref_edit.setFixedWidth(90)
        self.ref_edit.setValidator(QDoubleValidator(20.0, 250.0, 1))
        self.ref_edit.editingFinished.connect(self._on_ref_changed)
        self.device_combo = QComboBox()
        self.device_combo.addItems(list(config.REF_DEVICES))
        self.device_combo.currentTextChanged.connect(lambda _: self._on_ref_changed())
        self.log_button = QPushButton("Log")
        self.log_button.setToolTip("Append the current reading and the reference BPM to results/readings.csv")
        self.log_button.clicked.connect(self._log_reading)
        self.status = QLabel("")
        self.status.setObjectName("stat")

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self.start_button)
        for text, combo in (("Method", self.method_combo), ("Source", self.source_combo)):
            label = QLabel(text)
            label.setObjectName("stat")
            controls.addWidget(label)
            controls.addWidget(combo)
        controls.addStretch(1)
        controls.addWidget(self.light_button)
        controls.addWidget(self.full_button)

        second = QHBoxLayout()
        second.setSpacing(8)
        second.addWidget(self.record_button)
        second.addWidget(self.ref_edit)
        second.addWidget(self.device_combo)
        second.addWidget(self.log_button)
        second.addWidget(self.status, 1)

        left = QVBoxLayout()
        left.setSpacing(theme.SPACING)
        left.addWidget(self.video, 1)
        left.addLayout(controls)
        left.addLayout(second)

        right = QVBoxLayout()
        right.setSpacing(theme.SPACING)
        right.addWidget(self.panel)
        right.addWidget(Card(f"Filtered pulse, last {config.WINDOW_SEC:.0f} s (seconds)", self.pulse_plot), 1)
        right.addWidget(Card("Spectrum: Hz (bottom), BPM (top), peak marked", self.spectrum_plot), 1)

        dashboard = QWidget()
        dashboard.setObjectName("dashboard")
        dashboard.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(dashboard)
        row.setContentsMargins(theme.SPACING, theme.SPACING, theme.SPACING, theme.SPACING)
        row.setSpacing(theme.SPACING)
        row.addLayout(left, 5)
        row.addLayout(right, 4)

        self.light = LightFrame(dashboard)
        self.setCentralWidget(self.light)

    def _build_timers(self) -> None:
        self._frame_timer = QTimer(self)                    # drives MockSource only
        self._frame_timer.setInterval(round(1000 / config.MOCK_HZ))
        self._frame_timer.timeout.connect(self._tick_mock)
        self._estimate_timer = QTimer(self)
        self._estimate_timer.setInterval(round(config.UPDATE_SEC * 1000))
        self._estimate_timer.timeout.connect(self._estimate)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(config.PLOT_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._refresh)

    def _build_shortcuts(self) -> None:
        for key, slot in (("L", self.light_button.toggle), ("F", self.full_button.toggle),
                          ("Esc", lambda: self.full_button.setChecked(False))):
            QShortcut(QKeySequence(key), self, activated=slot)

    # ------------------------------------------------------------ status line and control states

    @property
    def source_kind(self) -> str:
        return SOURCES[self.source_combo.currentIndex()]

    def _say(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.POOR if error else theme.MUTED};")
        QTimer.singleShot(STATUS_CLEAR_MS, lambda: self.status.text() == text and self.status.setText(""))

    def _update_controls(self) -> None:
        recording_possible = self._running and self._worker is not None and self.source_kind == "webcam"
        self.record_button.setEnabled(recording_possible or self._recorder is not None)
        self.record_button.setToolTip("" if recording_possible else "Recording needs the live webcam running")
        self.source_combo.setEnabled(not self._running)

    # ------------------------------------------------------------ run control

    def toggle_running(self) -> None:
        self.stop() if self._running else self.start()

    def _make_worker(self, kind: str, path: str | None) -> CaptureWorker:
        return CaptureWorker(kind, path)

    def start(self) -> None:
        kind = self.source_kind
        if kind == "file" and not self._file_path and not self._choose_file():
            return
        self.estimator.reset()
        self._result, self._analyses = None, {}
        self._bright.clear()
        self._face_prev = False
        self._stopped_hint = "Press Start"
        self._running = True
        if kind == "mock":
            self._mock = MockSource(scenario=not self.steady)
            self._t0 = time.perf_counter()
            self._frame_timer.start()
        else:
            self._worker = self._make_worker(kind, self._file_path)
            self._worker.sample.connect(self._on_sample)
            self._worker.failed.connect(self._on_failed)
            self._worker.ended.connect(self._on_ended)
            self._worker.start()
        self.start_button.setText("Stop")
        self._estimate_timer.start()
        self._refresh_timer.start()
        self._plots_dirty = True
        self._update_controls()
        self._refresh()

    def _halt(self) -> None:
        """Stop recording, the capture thread and all timers."""
        if self._recorder is not None:
            self.record_button.setChecked(False)
        for timer in (self._frame_timer, self._estimate_timer, self._refresh_timer):
            timer.stop()
        if self._worker is not None:
            for signal, slot in ((self._worker.sample, self._on_sample), (self._worker.failed, self._on_failed),
                                 (self._worker.ended, self._on_ended)):
                try:
                    signal.disconnect(slot)         # late frames must not repaint a stopped window
                except (RuntimeError, TypeError):
                    pass
            self._worker.stop()
            self._worker.wait(3000)
            self._worker = None
        self._running = False
        self.start_button.setText("Start")

    def stop(self) -> None:
        self._halt()
        self._result, self._analyses = None, {}
        self.video.clear_frame()
        self._plots_dirty = True
        self._update_controls()
        self._refresh()

    def _on_failed(self, message: str) -> None:
        self.stop()
        self._say(message, error=True)

    def _on_ended(self) -> None:
        """A file finished: keep the last result and plots on screen."""
        self._estimate()
        self._halt()
        self._stopped_hint = "End of file: press Start to replay"
        self._update_controls()
        self._refresh()

    def _set_fullscreen(self, on: bool) -> None:
        self.showFullScreen() if on else self.showNormal()

    def _on_method(self, name: str) -> None:
        self.estimator.set_method(name)
        if self._running:
            self._estimate()
        self._refresh()

    def _choose_file(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(self, "Open a recorded clip",
                                              str(recorder.project_dir(config.RECORDINGS_DIR)), VIDEO_FILTER)
        if not path:
            return False
        self._file_path = path
        self.source_combo.setItemText(2, f"File: {Path(path).name}")
        self.source_combo.setToolTip(path)
        return True

    def _on_source_changed(self, index: int) -> None:
        if SOURCES[index] == "file" and not self._choose_file():
            self.source_combo.blockSignals(True)            # cancelled: go back to where we were
            self.source_combo.setCurrentIndex(self._source_index)
            self.source_combo.blockSignals(False)
            return
        self._source_index = index
        self._update_controls()

    # ------------------------------------------------------------ recording and reference

    def _ref_value(self) -> float | None:
        try:
            return float(self.ref_edit.text().replace(",", "."))
        except ValueError:
            return None

    def _ref_fields(self) -> dict:
        return {"ref_bpm": self._ref_value(), "device": self.device_combo.currentText()}

    def _on_record_toggled(self, on: bool) -> None:
        if on:
            if self._worker is None or self._recorder is not None:
                self.record_button.blockSignals(True)
                self.record_button.setChecked(False)
                self.record_button.blockSignals(False)
                return
            self._recorder = recorder.Recorder(self.estimator.method, self.source_kind, self.light.on, self._ref_fields())
            self._worker.set_recorder(self._recorder)
            self._rec_started = time.perf_counter()
            self._last_meta_path = self._recorder.meta_path
            self._say(f"Recording {self._recorder.stamp}")
            return
        rec, self._recorder = self._recorder, None
        if rec is None:
            return
        if self._worker is not None:
            self._worker.set_recorder(None)                 # returns once the worker has stopped writing
        meta = rec.close(method=self.estimator.method, ref=self._ref_fields())
        note = f"; {meta['warnings'][0]}" if meta["warnings"] else ""
        self._say(f"Saved {rec.stamp}: {meta['frames']} frames, {meta['duration_sec']:.0f} s, {meta['video']['codec']}{note}",
                  error=bool(meta["warnings"]))
        self._update_controls()

    def _on_ref_changed(self) -> None:
        """The reference can be typed during or after a recording: it goes into that clip's meta file."""
        if self._last_meta_path is None or not self._last_meta_path.exists():
            return
        recorder.update_meta(self._last_meta_path, **self._ref_fields())
        self._say(f"Reference saved to {self._last_meta_path.name}")

    def _log_reading(self) -> None:
        ref = self._ref_value()
        r = self._result
        if ref is None:
            self._say("Type the reference BPM first", error=True)
        elif r is None or r.bpm_smooth is None:
            self._say("No reading to log yet", error=True)
        else:
            row = recorder.log_reading(r.method, r.bpm_smooth, ref, r.snr_db, self.light.on)
            self._say(f"Logged {row['bpm_smooth']} vs ref {row['ref_bpm']} (error {row['abs_error']})")

    # ------------------------------------------------------------ data flow

    def _tick_mock(self) -> None:
        self._on_sample(self._mock.sample_at(time.perf_counter() - self._t0))

    def _on_sample(self, s: FrameSample) -> None:
        """Every frame: show the preview and append to the estimator (cheap)."""
        self.video.set_frame(s.preview)
        self.estimator.push(s.t, s.rgb, s.face_found, s.relock)
        self._latest_t = s.t
        # Warm-up clock: starts when the face appears (a re-lock keeps the buffer, so it does not restart it).
        if s.face_found and not self._face_prev:
            self._warm_start = s.t
        self._face_prev = s.face_found
        b = brightness(s.rgb)
        if b is not None:
            self._bright.append((s.t, b))
        while self._bright and s.t - self._bright[0][0] > config.LOW_LIGHT_WINDOW_SEC:
            self._bright.popleft()

    def _estimate(self) -> None:
        """Every UPDATE_SEC: one estimate, plus every method on the same buffer for the side-by-side row."""
        self._result = self.estimator.estimate()
        self._analyses = self.estimator.analyze_all()
        self._plots_dirty = True

    def _brightness_level(self) -> float | None:
        if not self._bright:
            return None
        return sum(b for _, b in self._bright) / len(self._bright)

    def _refresh(self) -> None:
        """At most every PLOT_REFRESH_MS: text always, plots only when a new result has arrived."""
        level = self._brightness_level()
        warm_x = max(0, int(self._latest_t - self._warm_start))
        self.panel.update_display(build_display(
            self._running, self._result, self._analyses, self.estimator.method, warm_x,
            low_light=level is not None and level < config.LOW_LIGHT_LEVEL, brightness_level=level,
            stopped_hint=self._stopped_hint))
        if self._recorder is not None:
            self._say(f"Recording {self._recorder.stamp}: {time.perf_counter() - self._rec_started:.0f} s")
        if self._plots_dirty:
            self.pulse_plot.set_result(self._result)
            self.spectrum_plot.set_result(self._result)
            self._plots_dirty = False

    def closeEvent(self, event) -> None:
        self._halt()
        super().closeEvent(event)
