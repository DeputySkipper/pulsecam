"""UI logic and a deterministic drive of MainWindow against MockSource (offscreen, no real time)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QFileDialog

import config
from capture import MockSource
from estimator import Estimator
from models import HRResult
from ui import theme
from ui.main_window import MainWindow
import csv
import json

import recorder
from ui.widgets import build_display, state_hint, warmup_total_sec


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    pg.setConfigOptions(antialias=True)
    theme.apply(a)
    return a


def result(state, bpm_smooth=None, quality="n/a", snr=None, fps=30.0):
    return HRResult(t=0.0, state=state, method="CHROM", bpm=bpm_smooth, bpm_smooth=bpm_smooth,
                    snr_db=snr, quality=quality, fps=fps, buffer_sec=0.0)


# ---- pure view-model logic

def test_warmup_total_is_min_sec_because_a_relock_keeps_the_buffer():
    assert warmup_total_sec() == config.MIN_SEC == 10.0


@pytest.mark.parametrize("state,warm_x,low,running,expected", [
    ("measuring", 0, False, False, ("Press Start", "info")),
    ("no_face", 0, True, True, ("No face detected", "error")),          # no face beats low light
    ("measuring", 0, True, True, ("More light needed", "warn")),
    ("warming_up", 5, True, True, ("More light needed", "warn")),       # low light beats the warm-up counter
    ("warming_up", 5, False, True, ("Warming up 5/10 s", "info")),
    ("warming_up", 99, False, True, ("Warming up 10/10 s", "info")),    # counter never overshoots
    ("poor_signal", 0, False, True, ("Hold still", "warn")),
    ("measuring", 0, False, True, ("Measuring", "ok")),
])
def test_state_hint_priority(state, warm_x, low, running, expected):
    assert state_hint(state, warm_x, low, running) == expected


def test_display_shows_dashes_until_there_is_a_reading():
    for state in ("no_face", "warming_up"):
        d = build_display(True, result(state), {}, "CHROM")
        assert d.bpm_text == "--" and d.bpm_dim and d.quality == "n/a"


def test_display_dims_held_value_and_drops_it_when_none():
    held = build_display(True, result("poor_signal", 72.4, "poor", -3.0), {}, "CHROM")
    assert held.bpm_text == "72" and held.bpm_dim and held.hint == "Hold still" and held.quality == "poor"
    gone = build_display(True, result("poor_signal", None, "poor", -3.0), {}, "CHROM")
    assert gone.bpm_text == "--" and gone.hint == "Hold still"
    live = build_display(True, result("measuring", 72.4, "good", 6.0), {}, "CHROM")
    assert live.bpm_text == "72" and not live.bpm_dim and live.snr_text == "6.0 dB" and live.fps_text == "30"


def test_display_stopped():
    d = build_display(False, None, {}, "CHROM")
    assert d.hint == "Press Start" and d.bpm_text == "--" and [m[0] for m in d.methods] == ["GREEN", "CHROM", "POS"]


# ---- mock scenario

def test_mock_scenario_exercises_every_state():
    mock, est = MockSource(), Estimator("CHROM")
    seen, dash_while_poor, bright, shown_numbers = set(), 0, {}, 0
    relocks = []
    for i in range(int(sum(d for _, d in config.MOCK_SCENARIO) * config.MOCK_HZ)):
        t = i / config.MOCK_HZ
        s = mock.sample_at(t)
        est.push(s.t, s.rgb, s.face_found, s.relock)
        if s.relock:
            relocks.append(round(t, 1))
        if s.rgb is not None:
            bright.setdefault(mock.phase_at(t), []).append(float(np.mean(s.rgb)))
        if i % int(config.MOCK_HZ) == 0:
            r = est.estimate()
            seen.add(r.state)
            if r.state == "poor_signal" and r.bpm_smooth is None:
                dash_while_poor += 1
            if r.state == "measuring" and mock.phase_at(t) == "measuring" and r.bpm_smooth is not None:
                assert abs(r.bpm_smooth - config.MOCK_BPM) <= 1.0
                shown_numbers += 1
    assert seen == {"warming_up", "measuring", "poor_signal", "no_face"}
    assert dash_while_poor >= 4                                              # "--" is visible for a while
    assert shown_numbers >= 10                                               # and numbers do get shown once confirmed
    assert relocks == [0.0, config.ROI_LOCK_SEC]                             # face appears, then the freeze
    assert np.mean(bright["dim"]) < config.LOW_LIGHT_LEVEL < np.mean(bright["measuring"])


def test_mock_steady_mode_is_a_clean_signal():
    mock = MockSource(scenario=False)
    assert {mock.phase_at(t) for t in (0, 40, 100, 1000)} == {"measuring"}


# ---- window, driven without real time

def drive(w, mock, t_from, t_to):
    """Feed mock samples at 30 Hz, estimating once per second and refreshing every 3rd frame."""
    step = 1.0 / config.MOCK_HZ
    t = t_from
    while t < t_to:
        w._on_sample(mock.sample_at(t))
        if abs(t - round(t)) < step / 2:
            w._estimate()
        w._refresh()
        t += step
    return t


@pytest.fixture
def window(app):
    w = MainWindow(source="mock")
    w.show()
    w._running = True
    w._mock = MockSource()
    yield w
    w.close()


def test_window_walks_through_every_state(window):
    p = window.panel
    t = drive(window, window._mock, 0.0, 6.0)
    assert p.state_line.text() in ("Warming up 5/10 s", "Warming up 6/10 s")
    assert p.number.text() == "--"
    t = drive(window, window._mock, t, 25.0)
    assert p.state_line.text() == "Measuring" and p.number.text() == "72"
    assert p.quality_text.text() == "Good signal"
    assert {c.value.text() for c in p.cells.values()} == {"72"}                      # all three methods agree
    t = drive(window, window._mock, t, 35.0)
    assert p.state_line.text() == "More light needed"
    t = drive(window, window._mock, t, 41.0)
    assert p.state_line.text() == "Hold still"
    t = drive(window, window._mock, t, 50.0)
    assert p.state_line.text() == "Hold still" and p.number.text() == "--"           # held value dropped after the limit
    drive(window, window._mock, t, 54.0)
    assert p.state_line.text() == "No face detected" and p.number.text() == "--"


def test_active_method_cell_follows_the_dropdown(window):
    drive(window, window._mock, 0.0, 14.0)
    assert window.panel.cells["CHROM"].property("active") == "true"
    window.method_combo.setCurrentText("GREEN")
    assert window.estimator.method == "GREEN" and window.panel.stat_method.text() == "Method GREEN"
    assert window.panel.cells["GREEN"].property("active") == "true"
    assert window.panel.cells["CHROM"].property("active") == "false"


def test_light_frame_is_off_by_default_and_toggles(window):
    assert config.LIGHT_FRAME_DEFAULT is False and not window.light.on
    assert window.light.layout().contentsMargins().left() == 0
    window.light_button.setChecked(True)
    assert window.light.on and window.light.layout().contentsMargins().left() == config.LIGHT_FRAME_PX
    assert theme.LIGHT_FRAME in window.light.styleSheet()
    window.light_button.setChecked(False)
    assert not window.light.on and theme.LIGHT_FRAME not in window.light.styleSheet()


def test_fullscreen_toggle(window):
    window.full_button.setChecked(True)
    assert window.isFullScreen()
    window.full_button.setChecked(False)
    assert not window.isFullScreen()


def test_plots_redraw_only_when_a_new_result_arrives(window):
    drive(window, window._mock, 0.0, 14.0)
    calls = []
    original = window.pulse_plot.set_result
    window.pulse_plot.set_result = lambda r: (calls.append(1), original(r))
    for _ in range(10):                      # ten refreshes with no new estimate in between
        window._refresh()
    assert calls == []
    window._estimate()
    window._refresh()
    assert calls == [1]


def test_start_stop_resets_display(window):
    drive(window, window._mock, 0.0, 14.0)
    window.stop()
    assert window.panel.state_line.text() == "Press Start" and window.panel.number.text() == "--"
    assert window.start_button.text() == "Start"


# ---- build_display additions

def test_display_before_the_first_estimate_says_starting():
    d = build_display(True, None, {}, "CHROM")
    assert d.hint == "Starting..." and d.bpm_text == "--"


def test_display_keeps_a_finished_result_with_the_stopped_hint():
    d = build_display(False, result("measuring", 84.2, "good", 5.0), {}, "CHROM", stopped_hint="End of file: press Start to replay")
    assert d.bpm_text == "84" and d.hint == "End of file: press Start to replay" and d.quality == "good"


def test_display_shows_live_brightness():
    assert build_display(True, result("measuring", 72, "good", 5.0), {}, "CHROM", brightness_level=131.6).brightness_text == "132"
    assert build_display(True, result("measuring", 72, "good", 5.0), {}, "CHROM").brightness_text == "--"


def test_low_light_threshold_is_the_provisional_120():
    assert config.LOW_LIGHT_LEVEL == 120.0


# ---- P5: sources, worker, record, reference logger (a fake worker stands in for the camera thread)

class FakeWorker(QObject):
    sample = Signal(object)
    failed = Signal(str)
    ended = Signal()

    def __init__(self, kind, path):
        super().__init__()
        self.kind, self.path, self.recorder = kind, path, None
        self.started = self.stopped = False

    def start(self): self.started = True
    def stop(self): self.stopped = True
    def wait(self, ms=0): return True
    def set_recorder(self, rec): self.recorder = rec

    def deliver(self, mock_sample):
        """What the real worker does per frame: record the clean frame, then emit the sample."""
        frame = np.full((48, 64, 3), 90, np.uint8)
        if self.recorder is not None:
            self.recorder.write(frame, mock_sample)
        self.sample.emit(mock_sample)


@pytest.fixture
def live(app, tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "project_dir", lambda name: (tmp_path / name).mkdir(exist_ok=True) or tmp_path / name)
    w = MainWindow(source="webcam")
    w._make_worker = lambda kind, path: FakeWorker(kind, path)
    w.show()
    yield w
    w.close()


def feed_window(w, seconds, t0=0.0, mock=None):
    mock = mock or MockSource(scenario=False)
    t = t0
    while t < t0 + seconds:
        w._worker.deliver(mock.sample_at(t))
        if abs(t - round(t)) < 1 / 60:
            w._estimate()
        t += 1 / config.MOCK_HZ
    w._refresh()
    return mock, t


def test_window_defaults_to_the_webcam_and_offers_all_three_sources(app):
    w = MainWindow()
    assert w.source_kind == "webcam"
    assert [w.source_combo.itemText(i) for i in range(3)] == ["Mock", "Webcam", "File..."]
    assert all(w.source_combo.model().item(i).isEnabled() for i in range(3))
    w.close()


def test_start_launches_the_worker_and_samples_drive_the_display(live):
    live.start()
    assert live._worker.started and live._worker.kind == "webcam" and not live.source_combo.isEnabled()
    feed_window(live, 16.0)
    p = live.panel
    assert p.state_line.text() == "Measuring" and p.number.text() == "72"
    level = int(p.stat_light.text().split()[-1])                       # live ROI brightness; mock base is about 161
    assert 150 <= level <= 170 and level > config.LOW_LIGHT_LEVEL


def test_stop_halts_the_worker_and_ignores_late_frames(live):
    live.start()
    worker = live._worker
    feed_window(live, 3.0)
    live.stop()
    assert worker.stopped and live._worker is None and live.start_button.text() == "Start"
    worker.sample.emit(MockSource().sample_at(1.0))                    # a frame that was already in flight
    assert live.panel.state_line.text() == "Press Start"


def test_worker_failure_stops_and_shows_the_message(live):
    live.start()
    live._worker.failed.emit("Could not open camera 0. Check camera permission")
    assert not live._running and "Could not open camera 0" in live.status.text()
    assert live.panel.state_line.text() == "Press Start"


def test_end_of_file_keeps_the_last_reading_on_screen(live):
    live._file_path = "/some/clip.mkv"
    live.source_combo.blockSignals(True)
    live.source_combo.setCurrentIndex(2)
    live.source_combo.blockSignals(False)
    live.start()
    assert live._worker.kind == "file" and live._worker.path == "/some/clip.mkv"
    feed_window(live, 18.0)
    live._worker.ended.emit()
    assert not live._running
    assert live.panel.state_line.text() == "End of file: press Start to replay" and live.panel.number.text() == "72"
    live.start()                                                        # replay
    assert live.panel.number.text() == "--"


def test_file_source_asks_for_a_file_and_remembers_it(live, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("/data/clip one.mkv", ""))
    live.source_combo.setCurrentIndex(2)
    assert live._file_path == "/data/clip one.mkv" and live.source_combo.itemText(2) == "File: clip one.mkv"
    assert live.source_kind == "file"


def test_cancelling_the_file_dialog_goes_back_to_the_previous_source(live, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    live.source_combo.setCurrentIndex(2)
    assert live.source_kind == "webcam" and live._file_path is None


def test_record_is_only_available_for_the_running_webcam(live):
    assert not live.record_button.isEnabled()                           # not running
    live.start()
    assert live.record_button.isEnabled()
    live.stop()
    live.source_combo.setCurrentIndex(0)
    live.start()
    assert not live.record_button.isEnabled()                           # mock has no frames to record


def test_recording_writes_means_video_and_meta_with_the_active_settings(live, tmp_path):
    live.start()
    live.ref_edit.setText("90")
    live.device_combo.setCurrentText("smartwatch")
    live.method_combo.setCurrentText("POS")
    live.light_button.setChecked(True)
    live.record_button.setChecked(True)
    rec = live._recorder
    assert live._worker.recorder is rec
    feed_window(live, 3.0)
    live.record_button.setChecked(False)
    assert live._recorder is None and live._worker.recorder is None
    meta = json.loads(rec.meta_path.read_text())
    s = meta["settings"]
    assert s["ROI_SET"] == config.ROI_SET and s["FREEZE_ROI"] == config.FREEZE_ROI
    assert s["BAND_LO"] == config.BAND_LO and s["WINDOW_SEC"] == config.WINDOW_SEC and s["method"] == "POS"
    assert meta["ref_bpm"] == 90.0 and meta["device"] == "smartwatch" and meta["light_frame"] is True
    assert meta["source"] == "webcam" and meta["frames"] >= 85 and meta["files"]["video"]
    rows = list(csv.reader(open(rec.csv_path)))
    assert rows[0] == ["t", "R", "G", "B", "face_found", "relock"] and len(rows) - 1 == meta["frames"]
    assert "Saved" in live.status.text()


def test_reference_typed_after_recording_updates_that_clips_meta(live):
    live.start()
    live.record_button.setChecked(True)
    meta_path = live._recorder.meta_path
    feed_window(live, 2.0)
    live.record_button.setChecked(False)
    assert json.loads(meta_path.read_text())["ref_bpm"] is None
    live.ref_edit.setText("88.5")
    live.ref_edit.editingFinished.emit()
    assert json.loads(meta_path.read_text())["ref_bpm"] == 88.5
    live.device_combo.setCurrentText("pulse oximeter")
    assert json.loads(meta_path.read_text())["device"] == "pulse oximeter"


def test_stopping_the_app_run_finishes_an_active_recording(live):
    live.start()
    live.record_button.setChecked(True)
    meta_path = live._recorder.meta_path
    feed_window(live, 2.0)
    live.stop()
    assert live._recorder is None and "duration_sec" in json.loads(meta_path.read_text())


def test_log_button_appends_a_row_with_the_error(live, tmp_path):
    live.start()
    feed_window(live, 18.0)
    live.ref_edit.setText("70")
    live.log_button.click()
    rows = list(csv.DictReader(open(tmp_path / config.RESULTS_DIR / config.READINGS_CSV)))
    assert len(rows) == 1 and rows[0]["method"] == "CHROM" and rows[0]["ref_bpm"] == "70"
    assert float(rows[0]["abs_error"]) == pytest.approx(abs(float(rows[0]["bpm_smooth"]) - 70), abs=0.06)
    assert rows[0]["light_frame"] == "off" and "Logged" in live.status.text()


def test_log_button_explains_when_it_cannot_log(live, tmp_path):
    live.start()
    live.log_button.click()
    assert "reference" in live.status.text().lower()
    live.ref_edit.setText("80")
    live.log_button.click()
    assert "no reading" in live.status.text().lower()
    assert not (tmp_path / config.RESULTS_DIR / config.READINGS_CSV).exists()
