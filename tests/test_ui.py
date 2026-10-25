"""UI logic and a deterministic drive of MainWindow against MockSource (offscreen, no real time)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":        # the offscreen platform finds no fonts on Windows unless told where they are; text metrics need them
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"))

import re

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
    assert live.bpm_text == "72" and not live.bpm_dim and live.snr_text == "+6.0 dB" and live.fps_text == "30"


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
    assert window.quality_panel.state_text.text() == "Good"                          # was p.quality_text == "Good signal" (now in the quality panel)
    values = [c.value_text for c in window.cards.cells.values()]                     # was {"72"} (integers); cards show one decimal now
    assert all(re.fullmatch(r"\d+\.\d", v) and abs(float(v) - 72) <= 0.5 for v in values)   # all three methods agree
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
    assert window.cards.cells["CHROM"].property("active") == "true"                  # cards moved from the hero panel to window.cards
    window.method_combo.setCurrentText("GREEN")
    assert window.estimator.method == "GREEN" and window.panel.stat_values["method"].text() == "GREEN"   # was "Method GREEN"
    assert window.cards.cells["GREEN"].property("active") == "true"
    assert window.cards.cells["CHROM"].property("active") == "false"


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
    level = int(p.light_value.text().split()[0])                       # live ROI brightness ("164 / 255"); mock base is about 161
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


# ---- U1: shell, theme tokens, hover animation

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFocusEvent, QFontMetrics, QImage, QRegion
from PySide6.QtWidgets import QWidget

from ui.animated import AnimButton, ComboButton, mix_color, scale_target
from ui.panels import Dashboard, Panel, camera_text


def render_to_image(widget, scale=None):
    """The widget's own painting on a transparent image (no ancestor background), optionally at a forced scale."""
    if scale is not None:
        widget._scale_anim.stop()
        widget._scale = scale
    img = QImage(widget.size(), QImage.Format_ARGB32)
    img.fill(0)
    widget.render(img, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    return img


def edge_alphas(img):
    w, h = img.width(), img.height()
    pts = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    return [img.pixelColor(x, y).alpha() for x, y in pts]


def test_theme_tokens_follow_the_brief():
    assert (theme.BG, theme.BG_HIGHLIGHT, theme.BORDER, theme.TEXT, theme.MUTED) == ("#0A0A0A", "#1B1B1D", "#26262A", "#E8E8E8", "#9A9A9A")
    assert (theme.BTN_FILL, theme.BTN_BORDER, theme.BTN_FILL_HOVER, theme.BTN_BORDER_HOVER) == ("#151516", "#333336", "#1F1F21", "#4A4A4E")
    assert (theme.PRIMARY_FILL, theme.PRIMARY_TEXT, theme.FIELD_FILL) == ("#EDEDED", "#0A0A0A", "#0E0E0F")
    assert (theme.GOOD, theme.FAIR, theme.POOR) == ("#7FBF9E", "#C9A85F", "#B26A78")
    assert (theme.ZONE_GOOD, theme.ZONE_FAIR, theme.ZONE_POOR) == ("#477A60", "#8A7447", "#7A4450")
    assert (theme.CONTROL_H, theme.CONTROL_RADIUS, theme.RADIUS, theme.TOPBAR_H, theme.LEFT_MAX_W) == (40, 8, 12, 56, 600)
    assert theme.MIN_WINDOW == (1100, 720) and theme.DESIGN_WINDOW == (1440, 900)
    assert theme.PANEL_ALPHA == 0.035 and theme.CHECKED_BORDER == "#BDBDBD"


def test_font_helper_sets_pixel_size_and_letter_spacing(app):
    f = theme.font("mono", 11, 500, 0.12)
    assert f.pixelSize() == 11 and f.letterSpacing() == pytest.approx(0.12 * 11, abs=0.02)      # Qt stores spacing in 1/64 px
    assert theme.family("sans") and theme.family("mono")


def test_scale_target_values_and_the_animation_switch(monkeypatch):
    assert scale_target(False, False, theme.HOVER_SCALE_BUTTON) == 1.0
    assert scale_target(True, False, theme.HOVER_SCALE_BUTTON) == pytest.approx(1.045)
    assert scale_target(True, False, theme.HOVER_SCALE_CARD) == pytest.approx(1.025)
    assert scale_target(True, True, theme.HOVER_SCALE_BUTTON) == pytest.approx(0.97)     # pressed wins over hover
    monkeypatch.setattr(theme, "ANIMATIONS", False)
    assert scale_target(True, False, theme.HOVER_SCALE_BUTTON) == 1.0 and scale_target(True, True, 1.045) == 1.0


def test_mix_color_endpoints_and_middle():
    assert mix_color("#000000", "#FFFFFF", 0).name() == "#000000" and mix_color("#000000", "#FFFFFF", 1).name() == "#ffffff"
    assert mix_color("#000000", "#FFFFFF", 0.5).red() in (127, 128)
    assert mix_color("#000000", "#FFFFFF", 7).name() == "#ffffff"                          # clamped


def test_button_eases_to_the_hover_and_press_scales(app):
    b = AnimButton("Log", glyph="log")
    b.show()
    assert b.scale == 1.0
    b.set_hover(True)
    assert b._scale_anim.duration() == theme.ANIM_MS == 180 and b._scale_anim.endValue() == pytest.approx(1.045)
    b._scale_anim.setCurrentTime(theme.ANIM_MS)
    assert b.scale == pytest.approx(1.045)
    b.set_pressed(True)
    b._scale_anim.setCurrentTime(theme.ANIM_MS)
    assert b.scale == pytest.approx(0.97)
    b.set_pressed(False)
    b._scale_anim.setCurrentTime(theme.ANIM_MS)
    assert b.scale == pytest.approx(1.045)                                                 # still hovered
    b.set_hover(False)
    b._scale_anim.setCurrentTime(theme.ANIM_MS)
    assert b.scale == pytest.approx(1.0)
    b.close()


def test_with_animations_off_the_scale_never_changes_but_colours_still_react(app, monkeypatch):
    monkeypatch.setattr(theme, "ANIMATIONS", False)
    b = AnimButton("Log")
    b.set_hover(True)
    assert b.scale == 1.0 and b._mix == 1.0
    b.set_pressed(True)
    assert b.scale == 1.0
    b.set_hover(False)
    b.set_pressed(False)
    assert b._mix == 0.0


def test_hover_scale_is_a_paint_transform_so_geometry_and_hit_area_do_not_change(app):
    b = AnimButton("Record", glyph="record")
    b.show()
    before = (b.geometry(), b.size(), b.rect())
    b.set_hover(True)
    b._scale_anim.setCurrentTime(theme.ANIM_MS)
    assert (b.geometry(), b.size(), b.rect()) == before
    assert b.sizeHint().height() == theme.CONTROL_H + 2 * theme.ANIM_MARGIN
    b.close()


def test_every_animated_control_stays_inside_its_widget_at_full_hover_scale(window):
    controls = [window.start_button, window.method_combo, window.source_combo, window.record_button,
                window.device_combo, window.log_button, window.light_button, window.full_button]
    window.source_combo.setItemText(2, "File: a_rather_long_recording_name_for_testing.mkv")   # widest case
    for c in controls:
        assert c.sizeHint().width() - 2 * theme.ANIM_MARGIN <= theme.MAX_CONTROL_W + 1
        c.resize(c.sizeHint())
        img = render_to_image(c, scale=theme.HOVER_SCALE_BUTTON)
        assert max(edge_alphas(img)) == 0, c                                                # nothing painted on the edge
        assert max(edge_alphas(render_to_image(c, scale=1.0))) == 0
        assert any(img.pixelColor(x, img.height() // 2).alpha() for x in range(img.width()))   # and it did draw


def test_combo_button_draws_the_prefix_but_is_a_normal_combo(app):
    c = ComboButton("Method")
    c.addItems(["GREEN", "CHROM", "POS"])
    c.setCurrentText("CHROM")
    assert c.display_text() == "Method: CHROM" and c.currentText() == "CHROM" and c.count() == 3
    assert ComboButton("").display_text() == ""
    c.set_pressed(True)
    c.hidePopup()                                                                          # a closed popup resets the press
    assert c._pressed is False


def test_keyboard_focus_ring_only_for_keyboard_focus(app):
    b = AnimButton("Log")
    b.focusInEvent(QFocusEvent(QEvent.FocusIn, Qt.MouseFocusReason))
    assert b._kb_focus is False
    b.focusInEvent(QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
    assert b._kb_focus is True
    b.focusOutEvent(QFocusEvent(QEvent.FocusOut, Qt.TabFocusReason))
    assert b._kb_focus is False


def test_start_button_glyph_follows_its_text(app):
    b = AnimButton("Start", glyph="run", primary=True)
    assert b.current_glyph() == "play"
    b.setText("Stop")
    assert b.current_glyph() == "stop"


def test_panel_paints_translucent_fill_and_a_border(app):
    p = Panel()
    p.resize(200, 100)
    img = render_to_image(p)
    c = img.pixelColor(100, 50)
    assert (c.red(), c.green(), c.blue()) == (255, 255, 255) and 8 <= c.alpha() <= 10           # white at 3.5%
    edge = img.pixelColor(0, 50)
    assert edge.alpha() > 240 and abs(edge.red() - 0x26) <= 3                                   # the 1 px #26262A border
    assert img.pixelColor(0, 0).alpha() == 0                                                    # rounded corner is clear


def test_dashboard_background_is_black_with_a_highlight_at_the_top_right(app):
    d = Dashboard()
    d.resize(1000, 600)
    img = render_to_image(d)
    bottom_left = img.pixelColor(20, 580)
    assert (bottom_left.red(), bottom_left.green(), bottom_left.blue()) == (10, 10, 10)
    top_right = img.pixelColor(700, 3)
    assert top_right.red() > bottom_left.red() + 8                                              # the #1B1B1D highlight


def test_camera_text_names_the_actual_source():
    assert camera_text("webcam", 29.6) == "Camera 30 fps"
    assert camera_text("mock", 30.0) == "Mock 30 fps"
    assert camera_text("file", None) == "File -- fps" and camera_text("webcam", 0.0) == "Camera -- fps"


def test_top_bar_shows_real_source_and_fps(window):
    window._refresh()
    assert window.topbar.camera.text() == "Mock -- fps"                                         # nothing measured yet
    drive(window, window._mock, 0.0, 14.0)
    assert window.topbar.camera.text() == "Mock 30 fps" and window.topbar.dot._color == theme.GOOD
    window.stop()
    assert window.topbar.camera.text() == "Mock -- fps" and window.topbar.dot._color != theme.GOOD


def test_window_sizes(app):
    w = MainWindow(source="mock")
    assert (w.minimumSize().width(), w.minimumSize().height()) == (1100, 720)
    assert w.width() >= 1100 and w.height() >= 720
    ws, hs = MainWindow._initial_size()
    assert 1100 <= ws <= 1440 and 720 <= hs <= 900
    w.close()


def test_left_column_is_capped_at_600_px(window):
    window.resize(1800, 1000)
    window.repaint()
    left = window.video.parentWidget().parentWidget()
    assert left.maximumWidth() == 600 and left.width() <= 600


def test_controls_keep_their_attribute_names_and_behaviour(window):
    window.light_button.toggle()
    assert window.light.on
    window.light_button.toggle()
    assert window.record_button.isCheckable() and window.start_button.text() == "Start"
    assert window.ref_edit.height() == theme.CONTROL_H and window.ref_edit.placeholderText() == "Ref BPM"


def test_light_frame_raises_the_window_minimum_by_its_margins_and_restores_it(window):
    screen = window.screen().availableGeometry()
    window.light_button.setChecked(True)
    want_w = min(1100 + 2 * config.LIGHT_FRAME_PX, max(screen.width(), 1100))
    want_h = min(720 + 2 * config.LIGHT_FRAME_PX, max(screen.height(), 720))
    assert (window.minimumWidth(), window.minimumHeight()) == (want_w, want_h)
    assert window.width() >= want_w and window.height() >= want_h
    window.light_button.setChecked(False)
    assert (window.minimumWidth(), window.minimumHeight()) == (1100, 720)


# ---- U2: video tags, signal quality panel

from ui.panels import (FaceLock, QualityPanel, QualityShare, ShareBar, SnrScale, light_bar, snr_fraction, tick_marks,
                       zone_fractions)


def pixel(img, x, y):
    c = img.pixelColor(x, y)
    return c.red(), c.green(), c.blue(), c.alpha()


def rgb_of(hex_color):
    from PySide6.QtGui import QColor
    c = QColor(hex_color)
    return c.red(), c.green(), c.blue()


# -- SNR marker position

@pytest.mark.parametrize("snr,expected", [(-4.0, 0.0), (8.0, 1.0), (0.0, 1 / 3), (2.0, 0.5), (4.1, 0.675), (-4.0 + 12 * 0.25, 0.25)])
def test_snr_fraction_is_linear_over_minus4_to_plus8_db(snr, expected):
    assert snr_fraction(snr) == pytest.approx(expected)          # +4.1 dB sits at 67.5%, as in the reference


def test_snr_fraction_clamps_outside_the_scale_and_has_no_marker_without_a_value():
    assert snr_fraction(-30.0) == 0.0 and snr_fraction(40.0) == 1.0 and snr_fraction(None) is None


# -- zone boundaries come from config

def test_zone_widths_for_the_configured_thresholds():
    poor, fair, good = zone_fractions()
    assert (poor, fair, good) == pytest.approx((1 / 3, 1 / 6, 1 / 2))
    assert poor + fair + good == pytest.approx(1.0)
    assert poor == pytest.approx(snr_fraction(config.SNR_FAIR_DB))                       # the poor/fair edge is the fair threshold
    assert poor + fair == pytest.approx(snr_fraction(config.SNR_GOOD_DB))                # the fair/good edge is the good threshold


def test_zone_widths_follow_config_when_the_thresholds_change(monkeypatch):
    monkeypatch.setattr(config, "SNR_FAIR_DB", -1.0)
    monkeypatch.setattr(config, "SNR_GOOD_DB", 3.0)
    assert zone_fractions() == pytest.approx((3 / 12, 4 / 12, 5 / 12))
    assert [t for _, t, _ in tick_marks()] == ["-4", "-1 fair", "+3 good", "+8 dB"]
    assert [round(f, 4) for f, _, _ in tick_marks()] == [0.0, 0.25, round(7 / 12, 4), 1.0]


def test_zone_widths_cope_with_a_good_threshold_below_the_fair_one():
    poor, fair, good = zone_fractions(fair_db=2.0, good_db=0.0)
    assert fair == 0.0 and poor + good == pytest.approx(1.0)


def test_tick_labels_and_positions_from_config():
    assert tick_marks() == [(0.0, "-4", "left"), (pytest.approx(1 / 3), "0 fair", "center"),
                            (0.5, "+2 good", "center"), (1.0, "+8 dB", "right")]


def test_scale_widget_paints_zones_and_the_white_marker(app):
    s = SnrScale()
    s.resize(600, s.height())
    s.set_snr(4.1)
    img = render_to_image(s)
    row = s.MARK_H // 2
    assert pixel(img, 60, row)[:3] == rgb_of(theme.ZONE_POOR) and pixel(img, 250, row)[:3] == rgb_of(theme.ZONE_FAIR)
    assert pixel(img, 480, row)[:3] == rgb_of(theme.ZONE_GOOD)
    mx = round(0.675 * 600)
    assert pixel(img, mx, 0)[:3] == (255, 255, 255) and pixel(img, mx, s.MARK_H - 1)[:3] == (255, 255, 255)   # marker is taller than the bar
    assert pixel(img, mx + 6, 0)[3] == 0                                                                    # and only 2 px wide
    s.set_snr(None)
    assert max(pixel(render_to_image(s), x, 0)[3] for x in range(600)) == 0                                # no marker without an SNR
    s.set_snr(30.0)
    assert pixel(render_to_image(s), 598, 0)[:3] == (255, 255, 255)                                         # clamped to the right end


# -- the 60 s share

def test_share_percentages_match_the_reference_example():
    q = QualityShare(window_sec=1000)
    for i, k in enumerate(["good"] * 46 + ["fair"] * 38 + ["poor"] * 16):
        q.add(float(i), k)
    assert q.shares() == {"good": 46, "fair": 38, "poor": 16}


def test_share_percentages_always_sum_to_100_by_largest_remainder():
    q = QualityShare(window_sec=1000)
    for i, k in enumerate(["good", "fair", "poor"]):
        q.add(float(i), k)
    s = q.shares()
    assert sum(s.values()) == 100 and sorted(s.values()) == [33, 33, 34]
    rng = np.random.default_rng(6)
    for n in (1, 2, 7, 33, 101):
        q = QualityShare(window_sec=1e6)
        for i in range(n):
            q.add(float(i), rng.choice(["good", "fair", "poor"]))
        s = q.shares()
        exact = {k: 100.0 * sum(1 for _, x in q._items if x == k) / n for k in s}
        assert sum(s.values()) == 100 and all(abs(s[k] - exact[k]) < 1.0 for k in s)


def test_share_keeps_only_the_last_60_seconds():
    q = QualityShare()
    assert q.window == 60.0
    q.add(0.0, "good")
    q.add(60.0, "poor")
    assert q.shares() == {"good": 50, "fair": 0, "poor": 50}              # an update exactly 60 s old still counts
    q.add(61.0, "poor")
    assert q.shares() == {"good": 0, "fair": 0, "poor": 100}              # one second later it has left the window
    for t in range(62, 200):
        q.add(float(t), "fair")
    assert q.shares() == {"good": 0, "fair": 100, "poor": 0} and len(q) == 61


def test_share_ignores_updates_without_a_quality_and_repeated_timestamps():
    q = QualityShare()
    assert q.shares() is None
    q.add(0.0, "n/a")
    assert q.shares() is None and len(q) == 0
    q.add(1.0, "good")
    q.add(1.0, "poor")                                                   # same stream time: the same result again
    assert q.shares() == {"good": 100, "fair": 0, "poor": 0}
    q.add(100.0, "n/a")                                                  # time still ages out old updates
    assert q.shares() is None
    q.add(101.0, "fair")
    q.clear()
    assert q.shares() is None


def test_share_bar_draws_segments_with_gaps_and_an_empty_track(app):
    b = ShareBar()
    b.resize(1000, 8)
    b.set_shares({"good": 50, "fair": 30, "poor": 20})
    img = render_to_image(b)
    assert pixel(img, 250, 4)[:3] == rgb_of(theme.ZONE_GOOD) and pixel(img, 600, 4)[:3] == rgb_of(theme.ZONE_FAIR)
    assert pixel(img, 900, 4)[:3] == rgb_of(theme.ZONE_POOR)
    assert any(pixel(img, x, 4)[3] == 0 for x in range(490, 510))        # a 2 px gap between good and fair
    b.set_shares(None)
    assert pixel(render_to_image(b), 500, 4)[:3] == rgb_of(theme.BORDER)


# -- light bar fill and threshold tick

def test_light_bar_matches_the_reference_numbers():
    fill, tick = light_bar(164.0)
    assert fill == pytest.approx(0.643, abs=0.001) and tick == pytest.approx(0.471, abs=0.001)   # 64.3% fill, tick at 47.1%


def test_light_bar_edges_and_threshold_follow_config(monkeypatch):
    assert light_bar(None)[0] == 0.0 and light_bar(0.0)[0] == 0.0 and light_bar(-5.0)[0] == 0.0
    assert light_bar(255.0)[0] == 1.0 and light_bar(400.0)[0] == 1.0
    assert light_bar(127.5)[0] == pytest.approx(0.5)
    monkeypatch.setattr(config, "LOW_LIGHT_LEVEL", 51.0)
    assert light_bar(100.0)[1] == pytest.approx(0.2)


# -- face-lock state machine (the video tag claims only what the flags show)

def test_face_lock_follows_the_start_and_freeze_flags():
    f = FaceLock()
    assert f.state == "no_face" and f.text == "NO FACE"
    assert f.update(True, True) == "locking" and f.text == "LOCKING"
    assert f.update(True, False) == "locking"
    assert f.update(True, True) == "locked" and f.text == "FACE LOCKED"          # the freeze flag
    assert f.update(True, False) == "locked"
    assert f.update(True, True) == "locking"                                     # a re-lock starts again
    assert f.update(True, True) == "locked"
    assert f.update(False, False) == "no_face"
    assert f.update(True, True) == "locking"                                     # a new face starts a new lock


def test_face_without_any_lock_flag_is_only_found_never_locked():
    f = FaceLock()
    assert f.update(True, False) == "found" and f.text == "FACE FOUND"
    assert f.update(True, False) == "found"
    assert f.update(True, True) == "locking"
    f.reset()
    assert f.state == "no_face"


# -- the window: tags, quality panel, share

def feed_to(window, t_to):
    return drive(window, window._mock, 0.0, t_to)


def test_video_tags_are_child_widgets_and_never_drawn_into_the_frame(app):
    v = VideoView_for_test()
    frame = np.full((48, 64, 3), (10, 200, 30), np.uint8)
    v.set_frame(frame)
    before = v._pixmap.toImage()
    v.set_tags("FACE LOCKED", "LIGHT 164 / FPS 30")
    assert v._pixmap.toImage() == before                                         # the frame data is untouched
    assert v.lock_tag.parent() is v and v.light_tag.parent() is v
    assert v.lock_tag.text() == "FACE LOCKED" and v.light_tag.text() == "LIGHT 164 / FPS 30"
    img = v._pixmap.toImage()
    assert (img.pixelColor(5, 5).blue(), img.pixelColor(5, 5).green(), img.pixelColor(5, 5).red()) == (10, 200, 30)


def VideoView_for_test():
    from ui.widgets import VideoView
    v = VideoView()
    v.resize(600, 400)
    v.show()
    return v


def test_video_tags_sit_14_px_from_the_corners_and_hide_without_video(app):
    v = VideoView_for_test()
    v.set_tags("NO FACE", "LIGHT -- / FPS --")
    assert not v.lock_tag.isVisible() and not v.light_tag.isVisible()            # no frame yet: nothing to tag
    v.set_frame(np.zeros((48, 64, 3), np.uint8))
    assert v.lock_tag.isVisible() and v.light_tag.isVisible()
    assert (v.lock_tag.x(), v.lock_tag.y()) == (14, 14)
    assert v.width() - (v.light_tag.x() + v.light_tag.width()) == 14 and v.height() - (v.light_tag.y() + v.light_tag.height()) == 14
    v.resize(800, 500)
    assert v.width() - (v.light_tag.x() + v.light_tag.width()) == 14             # follows a resize
    v.clear_frame()
    assert not v.lock_tag.isVisible()


def test_window_tags_follow_the_real_lock_flags_and_numbers(window):
    t = drive(window, window._mock, 0.0, 1.0)
    assert window.video.lock_tag.text() == "LOCKING"                              # face appeared, freeze comes ROI_LOCK_SEC later
    t = drive(window, window._mock, t, 3.0)
    assert window.video.lock_tag.text() == "FACE LOCKED"
    t = drive(window, window._mock, t, 25.0)
    assert window.video.light_tag.text().startswith("LIGHT 16") and window.video.light_tag.text().endswith(" / FPS 30")
    t = drive(window, window._mock, t, 54.0)                                      # the mock's no-face phase
    assert window.video.lock_tag.text() == "NO FACE"
    t = drive(window, window._mock, t, 57.0)                                      # the next cycle: a new face, a new lock
    assert window.video.lock_tag.text() == "LOCKING"
    drive(window, window._mock, t, 60.0)
    assert window.video.lock_tag.text() == "FACE LOCKED"


def test_quality_panel_shows_the_real_quality_snr_marker_and_share(window):
    drive(window, window._mock, 0.0, 25.0)
    q = window.quality_panel
    r = window._result
    assert q.state_text.text() == "Good" and q.state_dot._color == theme.GOOD
    assert q.snr_value.text() == f"{r.snr_db:+.1f} dB" and q.snr_value.text().startswith("+")
    assert q.scale.marker_fraction == pytest.approx(snr_fraction(r.snr_db))
    assert window.share.shares() == {"good": 100, "fair": 0, "poor": 0}          # every counted update so far was good
    assert q.legend["good"].text() == "Good 100%" and q.legend["poor"].text() == "Poor 0%"
    assert q.share_bar._shares == {"good": 100, "fair": 0, "poor": 0}


def test_share_is_not_double_counted_and_resets_on_stop_start_and_method_change(window):
    drive(window, window._mock, 0.0, 16.0)
    n = len(window.share)
    assert n >= 5
    window._estimate()                                                            # the same result again (no new samples)
    assert len(window.share) == n
    window.method_combo.setCurrentText("GREEN")                                   # a different method: start over
    assert window.share.shares() is None or len(window.share) <= 1
    drive(window, window._mock, 16.0, 30.0)
    assert len(window.share) > 3
    window.stop()
    assert window.share.shares() is None and window.quality_panel.legend["good"].text() == "Good --"
    assert window.quality_panel.state_text.text() == "No signal" and window.quality_panel.snr_value.text() == "--"
    assert window.quality_panel.scale.marker_fraction is None


def test_quality_panel_dot_follows_the_quality(app):
    q = QualityPanel()
    for quality, name in (("good", "Good"), ("fair", "Fair"), ("poor", "Poor"), ("n/a", "No signal")):
        q.update_display(quality, "--", None, None)
        assert q.state_text.text() == name and q.state_dot._color == theme.QUALITY_COLOR[quality]


def test_display_carries_the_numbers_behind_its_texts():
    d = build_display(True, result("measuring", 72, "good", 6.04), {}, "CHROM", brightness_level=131.6)
    assert d.snr_db == 6.04 and d.brightness == 131.6 and d.snr_text == "+6.0 dB"
    assert build_display(True, result("measuring", 72, "poor", -3.26), {}, "CHROM").snr_text == "-3.3 dB"
    assert build_display(False, None, {}, "CHROM").snr_db is None


# ---- U3: hero, method cards, plots, flexible heights

from types import SimpleNamespace

from PySide6.QtCore import QAbstractAnimation, QPointF

from ui.widgets import (HeartbeatDot, LightBar, LivePulseStrip, MethodCard, PlotCard, SpectrumPlot, TickRow,
                        beat_period_ms, card_label, fit_number_px, hover_readout, peak_text, pulse_tail,
                        spectrum_range_hz, tick_labels)


def spectrum_result(quality="good", peak_hz=1.2):
    freqs = np.linspace(0, 5, 400)
    power = np.exp(-((freqs - 1.2) / 0.05) ** 2)
    t = np.arange(450) / 30.0
    return HRResult(t=1.0, state="measuring", method="CHROM", bpm=72.0, bpm_smooth=72.0, snr_db=5.0, quality=quality,
                    fps=30.0, buffer_sec=15.0, t_sig=t, pulse=np.sin(2 * np.pi * 1.2 * t), freqs=freqs, power=power,
                    peak_hz=peak_hz)


# -- number size

def test_number_size_is_112_with_room_and_shrinks_with_less_but_never_below_the_minimum():
    assert fit_number_px(1000, 1000) == 112 == theme.HERO_NUMBER_PX
    assert fit_number_px(165, 1000) == 100                       # three digits need about 1.65 em of width
    assert fit_number_px(1000, 80) == 80                          # and one em of height
    assert fit_number_px(10, 10) == theme.HERO_NUMBER_MIN_PX == 56


def test_number_is_light_weight_with_tight_tracking(window):
    f = window.panel.number.font()
    assert f.weight() == 300 or f.weight() == 25 or f.weight() <= 300                          # light
    assert f.letterSpacing() < 0                                                              # -0.04 em
    assert window.panel.number.text() == "--"


# -- heartbeat dot

def test_beat_period_follows_the_rate():
    assert beat_period_ms(72) == pytest.approx(833.33, abs=0.01)
    assert beat_period_ms(60) == 1000.0 and beat_period_ms(120) == 500.0
    assert beat_period_ms(None) is None and beat_period_ms(0) is None and beat_period_ms(-5) is None


def test_heartbeat_dot_pulses_at_the_rate_and_is_static_without_a_number(app):
    d = HeartbeatDot()
    assert d.period_ms is None and d._anim.state() != QAbstractAnimation.State.Running
    d.set_bpm(72.0)
    assert d.period_ms == 833 and d._anim.duration() == 833 and d._anim.state() == QAbstractAnimation.State.Running
    d.set_bpm(90.0)                                                       # a new rate re-times the same animation
    assert d.period_ms == 667 and d._anim.duration() == 667
    d._anim.setCurrentTime(300)
    assert 0.0 < d._phase < 1.0
    d.set_bpm(None)
    assert d.period_ms is None and d._phase == 0.0 and d._anim.state() != QAbstractAnimation.State.Running


def test_heartbeat_dot_is_static_with_animations_off(app, monkeypatch):
    monkeypatch.setattr(theme, "ANIMATIONS", False)
    d = HeartbeatDot()
    d.set_bpm(72.0)
    assert d.period_ms is None and d._anim.state() != QAbstractAnimation.State.Running


def test_dot_follows_the_displayed_bpm_and_stops_for_held_or_missing_values(window):
    drive(window, window._mock, 0.0, 6.0)
    assert window.panel.number.text() == "--" and window.panel.beat.period_ms is None            # warming up: no number
    t = drive(window, window._mock, 6.0, 25.0)
    shown = float(window.panel.number.text())
    assert window.panel.beat.period_ms == pytest.approx(60000 / window._result.bpm_smooth, abs=1)
    assert abs(60000 / window.panel.beat.period_ms - shown) < 1.0                                # the displayed rate
    assert window.panel.rate_label.text() == f"{window._result.bpm_smooth / 60:.1f} Hz"
    t = drive(window, window._mock, t, 41.0)
    assert window.panel.state_line.text() == "Hold still" and window.panel.beat.period_ms is None   # a held, greyed value does not pulse
    drive(window, window._mock, t, 50.0)
    assert window.panel.number.text() == "--" and window.panel.beat.period_ms is None
    assert window.panel.rate_label.text() == "--"


def test_display_bpm_live_only_for_a_live_reading():
    assert build_display(True, result("measuring", 72.4, "good", 6.0), {}, "CHROM").bpm_live == 72.4
    assert build_display(True, result("poor_signal", 72.4, "poor", -3.0), {}, "CHROM").bpm_live is None
    assert build_display(True, result("poor_signal", None, "poor", -3.0), {}, "CHROM").bpm_live is None
    assert build_display(True, result("warming_up"), {}, "CHROM").bpm_live is None


# -- live pulse strip

def test_pulse_tail_is_the_newest_5_seconds_of_the_real_samples():
    t = np.arange(450) / 30.0
    pulse = np.sin(2 * np.pi * 1.2 * t) * 3.0
    xs, ys = pulse_tail(t, pulse)
    assert len(xs) == 151 and xs[-1] == pytest.approx(1.0) and xs[0] == pytest.approx(0.0, abs=1e-9)
    assert np.allclose(ys * np.max(np.abs(pulse)), pulse[-151:])                 # the real samples, scaled only: no interpolation
    assert np.max(np.abs(ys)) <= 1.0 + 1e-12 and np.max(np.abs(ys)) == pytest.approx(1.0, abs=0.01)
    assert np.all(np.diff(xs) > 0)


def test_pulse_tail_edge_cases():
    assert pulse_tail(np.array([]), np.array([])) is None
    assert pulse_tail(np.arange(5.0), np.arange(4.0)) is None                    # mismatched arrays are not drawn
    t = np.arange(60) / 30.0                                                     # only 2 s of signal: it starts partway in
    xs, ys = pulse_tail(t, np.sin(t))
    assert xs[-1] == pytest.approx(1.0) and xs[0] == pytest.approx(1 - 2 / 5, abs=0.02)
    xs, ys = pulse_tail(t, np.zeros(60))                                         # a flat signal does not divide by zero
    assert np.all(np.isfinite(ys)) and np.all(ys == 0)


def test_strip_draws_a_bright_dot_on_the_newest_sample_and_waits_without_signal(app):
    s = LivePulseStrip()
    s.resize(400, 54)
    s.set_result(None)
    assert s.trace is None
    s.set_result(spectrum_result())
    xs, ys = s.trace
    img = render_to_image(s)
    px, py = 5.0 + xs[-1] * (400 - 10), 54 / 2 - ys[-1] * (54 / 2 - 5.0)
    c = img.pixelColor(round(px), round(py))
    assert (c.red(), c.green(), c.blue()) == (255, 255, 255) and c.alpha() == 255      # the dot sits on the newest sample
    assert img.pixelColor(2, 2).alpha() == 0                                           # and nothing else fills the strip
    s.set_result(None)
    assert s.trace is None


def test_strip_redraws_only_when_a_new_result_arrives(window):
    drive(window, window._mock, 0.0, 14.0)
    calls = []
    original = window.panel.strip.set_result
    window.panel.strip.set_result = lambda r: (calls.append(1), original(r))
    for _ in range(10):
        window._refresh()
    assert calls == []
    window._estimate()
    window._refresh()
    assert calls == [1]


def test_window_strip_shows_the_real_pulse(window):
    drive(window, window._mock, 0.0, 16.0)
    xs, ys = window.panel.strip.trace
    r = window._result
    assert np.allclose(ys * np.max(np.abs(r.pulse)), r.pulse[-len(ys):])


# -- stats, light

def test_stats_list_shows_method_snr_light_window_and_range(window):
    drive(window, window._mock, 0.0, 25.0)
    v = window.panel.stat_values
    assert v["method"].text() == "CHROM" and v["snr"].text().startswith("+") and v["snr"].text().endswith(" dB")
    assert v["window"].text() == f"{config.WINDOW_SEC:.0f} s" == "15 s" and v["range"].text() == "54-180"
    n, total = v["light"].text().split(" / ")
    assert total == "255" and 150 <= int(n) <= 170
    assert window.panel.light_bar._level == pytest.approx(window._brightness_level())


def test_light_bar_paints_fill_and_threshold_tick(app):
    b = LightBar()
    b.resize(200, 10)
    b.set_level(164.0)
    img = render_to_image(b)
    fill_x, tick_x = round(200 * 164 / 255), round(200 * config.LOW_LIGHT_LEVEL / 255)
    assert pixel(img, fill_x - 10, 5)[:3] == rgb_of(theme.LIGHT_FILL)              # inside the fill
    assert pixel(img, fill_x + 10, 5)[:3] == rgb_of(theme.LIGHT_TRACK)              # past it: the track
    assert pixel(img, tick_x, 0)[:3] == rgb_of(theme.LIGHT_TICK) and pixel(img, tick_x, 9)[:3] == rgb_of(theme.LIGHT_TICK)   # a crisp 1 px tick
    assert pixel(img, tick_x - 5, 0)[3] == 0                                        # the tick is taller than the 4 px track
    b.set_level(None)
    assert pixel(render_to_image(b), 20, 5)[:3] == rgb_of(theme.LIGHT_TRACK)       # no reading: an empty bar


def test_hero_state_dot_follows_the_state_kind(window):
    drive(window, window._mock, 0.0, 25.0)
    assert window.panel.state_dot._color == theme.GOOD and window.panel.state_line.text() == "Measuring"
    drive(window, window._mock, 25.0, 35.0)
    assert window.panel.state_line.text() == "More light needed" and window.panel.state_dot._color == theme.FAIR
    drive(window, window._mock, 35.0, 54.0)
    assert window.panel.state_line.text() == "No face detected" and window.panel.state_dot._color == theme.POOR


# -- method cards

def test_card_hover_scale_is_2_5_percent_and_press_97(app):
    c = MethodCard("GREEN")
    c.show()
    assert c.hover_scale == theme.HOVER_SCALE_CARD == 1.025
    c.set_hover(True)
    c._scale_anim.setCurrentTime(theme.ANIM_MS)
    assert c.scale == pytest.approx(1.025)
    c.set_pressed(True)
    c._scale_anim.setCurrentTime(theme.ANIM_MS)
    assert c.scale == pytest.approx(0.97)
    before = c.geometry()
    assert c.geometry() == before
    c.close()


def test_card_stays_inside_its_widget_at_hover_scale_and_draws_its_text(app):
    c = MethodCard("CHROM")
    c.resize(320, 108)
    c.set_active(True)
    c.set_value("72.1", "good")
    img = render_to_image(c, scale=theme.HOVER_SCALE_CARD)
    assert max(edge_alphas(img)) == 0
    assert any(pixel(img, x, 54)[3] for x in range(c.width()))


def test_card_labels_and_values():
    assert card_label("CHROM", True) == "CHROM, active" and card_label("GREEN", False) == "GREEN"


def test_cards_show_one_decimal_quality_dots_and_the_active_outline(window):
    drive(window, window._mock, 0.0, 25.0)
    cells = window.cards.cells
    assert set(cells) == {"GREEN", "CHROM", "POS"}
    assert [c.active for c in cells.values()] == [False, True, False]
    assert all(re.fullmatch(r"\d+\.\d", c.value_text) for c in cells.values())
    assert all(c.quality == "good" for c in cells.values())
    assert cells["CHROM"].border_color().name() == theme.CARD_BORDER_ACTIVE.lower()
    assert cells["GREEN"].border_color().name() == theme.BORDER.lower()
    window.stop()
    assert [c.value_text for c in cells.values()] == ["--", "--", "--"] and all(c.quality == "n/a" for c in cells.values())


def test_display_method_numbers_have_one_decimal():
    d = build_display(True, result("measuring", 72, "good", 5.0),
                      {"CHROM": SimpleNamespace(bpm=71.94, quality="good"), "GREEN": None, "POS": SimpleNamespace(bpm=72.0, quality="fair")}, "CHROM")
    assert d.methods == [("GREEN", "--", "poor"), ("CHROM", "71.9", "good"), ("POS", "72.0", "fair")]


# -- plots

def test_plots_are_transparent_and_have_no_axes(window):
    for plot in (window.pulse_plot, window.spectrum_plot):
        img = QImage(plot.viewport().size(), QImage.Format_ARGB32)
        img.fill(0)
        QWidget.render(plot.viewport(), img, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
        assert img.pixelColor(2, img.height() - 3).alpha() == 0                      # the glass panel shows through
        item = plot.getPlotItem()
        assert not any(item.getAxis(a).isVisible() for a in ("left", "bottom", "top", "right"))


def test_pulse_plot_line_is_1_7_px_light_grey_and_spectrum_is_a_grey_area_with_a_light_line(window):
    pen = window.pulse_plot.curve.opts["pen"]
    assert pen.widthF() == pytest.approx(1.7) and pen.color().name() == theme.PRIMARY_FILL.lower()
    line = window.spectrum_plot.curve.opts["pen"]
    assert line.widthF() == pytest.approx(1.5) and line.color().name() == theme.SPECTRUM_LINE.lower()
    assert window.spectrum_plot.curve.opts["fillLevel"] == 0 and window.spectrum_plot.curve.opts["fillBrush"] is not None
    assert window.spectrum_plot.peak_line.pen.style() == Qt.CustomDashLine


def test_spectrum_view_is_the_heart_rate_band(window):
    lo, hi = spectrum_range_hz()
    assert (lo, hi) == (config.BAND_LO, config.BAND_HI) == (0.9, 3.0)
    x0, x1 = window.spectrum_plot.viewRange()[0]
    assert x0 == pytest.approx(0.9) and x1 == pytest.approx(3.0)


def test_spectrum_tick_labels_are_54_90_120_150_180_in_proportion():
    ticks = tick_labels()
    assert [t for _, t, _ in ticks] == ["54", "90", "120", "150", "180 BPM"]
    assert [round(f, 4) for f, _, _ in ticks] == [0.0, round(36 / 126, 4), round(66 / 126, 4), round(96 / 126, 4), 1.0]
    assert [a for _, _, a in ticks] == ["left", "center", "center", "center", "right"]


def test_tick_row_drops_labels_that_would_touch_but_keeps_the_ends(app):
    row = TickRow()
    wide = row.visible_ticks(3000.0)
    assert [t for _, t in wide] == ["54", "90", "120", "150", "180 BPM"]
    narrow = row.visible_ticks(120.0)
    texts = [t for _, t in narrow]
    assert texts[0] == "54" and texts[-1].startswith("180") and len(texts) < 5
    fm = row.fontMetrics()
    xs = [(x, QFontMetrics(row._font).horizontalAdvance(t)) for x, t in narrow]
    assert all(a[0] + a[1] + 6 <= b[0] for a, b in zip(xs, xs[1:]))                  # nothing overlaps


def test_hover_readout_text_and_clamping():
    assert hover_readout(1.2) == "72 BPM / 1.20 Hz" and hover_readout(1.0) == "60 BPM / 1.00 Hz"
    assert hover_readout(1.2345) == "74 BPM / 1.23 Hz"                               # BPM rounded, Hz to two decimals
    assert hover_readout(0.1) == "54 BPM / 0.90 Hz" and hover_readout(9.0) == "180 BPM / 3.00 Hz"


def test_peak_text_never_claims_a_peak_on_a_poor_window():
    assert peak_text(None) == "--"
    assert peak_text(spectrum_result("good")) == "Peak 72 BPM"
    assert peak_text(spectrum_result("fair")) == "Peak 72 BPM"
    assert peak_text(spectrum_result("poor")) == "No clear peak"
    assert peak_text(result("warming_up")) == "--"                                   # no spectrum yet


def test_spectrum_hover_shows_a_crosshair_and_the_reading_then_restores_the_peak_text(app):
    plot = SpectrumPlot()
    plot.resize(400, 150)
    seen = []
    plot.readout.connect(seen.append)
    plot.hover_at(1.5)
    assert seen == [] and not plot.cursor.isVisible()                               # no data yet: nothing to read
    plot.set_result(spectrum_result())
    assert seen[-1] == "Peak 72 BPM" and plot.default_readout == "Peak 72 BPM"
    plot.hover_at(1.5)
    assert plot.cursor.isVisible() and plot.cursor.value() == pytest.approx(1.5) and seen[-1] == "90 BPM / 1.50 Hz"
    plot.set_result(spectrum_result())                                              # a new result while hovering keeps the reading
    assert seen[-1] == "90 BPM / 1.50 Hz"
    plot.clear_hover()                                                              # mouse leaves
    assert not plot.cursor.isVisible() and seen[-1] == "Peak 72 BPM"
    plot.hover_at(2.0)
    plot.leaveEvent(QEvent(QEvent.Leave))
    assert not plot.cursor.isVisible() and seen[-1] == "Peak 72 BPM"


def test_spectrum_hover_from_scene_coordinates(app):
    plot = SpectrumPlot()
    plot.resize(400, 150)
    plot.show()
    plot.set_result(spectrum_result())
    seen = []
    plot.readout.connect(seen.append)
    vb = plot.getPlotItem().vb
    plot._on_mouse_moved(vb.mapViewToScene(QPointF(1.8, 0.5)))
    assert seen[-1] == "108 BPM / 1.80 Hz" and plot.cursor.isVisible()
    plot._on_mouse_moved(QPointF(-50, -50))                                         # outside the plot area
    assert not plot.cursor.isVisible() and seen[-1] == "Peak 72 BPM"
    plot.close()


def test_window_header_shows_the_peak_and_follows_the_hover(window):
    drive(window, window._mock, 0.0, 25.0)
    assert window.spectrum_card.right.text() == "Peak 72 BPM"
    window.spectrum_plot.hover_at(2.0)
    assert window.spectrum_card.right.text() == "120 BPM / 2.00 Hz"
    window.spectrum_plot.clear_hover()
    assert window.spectrum_card.right.text() == "Peak 72 BPM"
    drive(window, window._mock, 25.0, 41.0)                                         # a poor stretch: no peak is claimed
    assert window.spectrum_card.right.text() in ("No clear peak", "--")


def test_plot_card_header_text_gives_way_when_narrow(app):
    card = PlotCard("Filtered pulse, last 15 s", "0.9-3.0 Hz", QWidget())
    card.show()
    card.resize(600, 200)
    assert not card.right.isHidden()
    card.resize(150, 200)
    assert card.right.isHidden()
    card.close()


# -- flexible heights

@pytest.mark.parametrize("size", [(1100, 720), (1366, 768), (1440, 900), (1600, 1000)])
def test_right_column_is_flexible_in_height_and_never_overlaps(window, size):
    drive(window, window._mock, 0.0, 16.0)
    window.resize(*size)
    QApplication.processEvents()
    hero, cards, p1, p2 = window.panel, window.cards, window.pulse_card, window.spectrum_card
    m = 2 * theme.ANIM_MARGIN
    assert theme.HERO_MIN_H <= hero.height() <= theme.HERO_H
    assert theme.CARDS_MIN_H + m <= cards.height() <= theme.CARDS_H + m
    assert theme.PLOTS_MIN_H <= p1.height() <= theme.PLOTS_H and p1.height() == p2.height()
    top = lambda w: w.mapTo(window, w.rect().topLeft()).y()
    assert top(hero) + hero.height() <= top(cards) + m // 2 and top(cards) + cards.height() - m // 2 <= top(p1)
    assert top(p1) + p1.height() <= window.height()
    q = window.quality_panel
    assert top(q) + q.height() <= window.height() and window.video.height() >= 160
    if size[1] >= 900:                                                              # the reference sizes
        assert (hero.height(), cards.height() - m, p1.height()) == (300, 96, 290)
        assert window.panel.number.px == 112
    if size == (1100, 720):
        assert hero.height() < 300 and p1.height() < 290 and window.panel.number.px < 112


def test_layout_minimum_fits_the_minimum_window_so_nothing_is_squeezed(window):
    need = window.light.minimumSizeHint()
    assert need.width() <= 1100 and need.height() <= 720


def test_three_digit_number_still_fits_at_the_minimum_window(window):
    window.resize(1100, 720)
    QApplication.processEvents()
    window.panel.number.setText("188")
    QApplication.processEvents()
    row_w = window.panel.number_row.width()
    assert window.panel.beat.geometry().right() <= row_w and window.panel.unit.geometry().right() <= row_w
    assert window.panel.number.geometry().right() <= window.panel.unit.geometry().left()


def test_right_column_edges_line_up_with_the_cards(window):
    window.resize(1440, 900)
    QApplication.processEvents()
    m = theme.ANIM_MARGIN
    left = lambda w: w.mapTo(window, w.rect().topLeft()).x()
    right = lambda w: left(w) + w.width()
    c = window.cards.cells
    assert left(window.panel) == left(window.cards.cells["GREEN"]) + m == left(window.pulse_card)
    assert right(window.panel) == right(c["POS"]) - m == right(window.spectrum_card)


def test_animations_off_leaves_cards_static(app, monkeypatch):
    monkeypatch.setattr(theme, "ANIMATIONS", False)
    c = MethodCard("POS")
    c.set_hover(True)
    c.set_pressed(True)
    assert c.scale == 1.0


def test_zero_line_hides_while_the_plot_waits_for_signal(window):
    assert not window.pulse_plot.zero_line.isVisible() and window.pulse_plot.placeholder.item.isVisible()
    drive(window, window._mock, 0.0, 14.0)
    assert window.pulse_plot.zero_line.isVisible() and not window.pulse_plot.placeholder.item.isVisible()
    window.stop()
    assert not window.pulse_plot.zero_line.isVisible()


# ---- U4: shortcuts, accessibility, fallbacks



def test_keyboard_shortcuts_still_work(window):
    """The offscreen platform has no active window, so key events do not reach QShortcut; the shortcuts' keys and what
    they do when activated are checked instead (the same three as before the restyle: L, F, Esc)."""
    from PySide6.QtGui import QShortcut
    by_key = {sc.key().toString(): sc for sc in window.findChildren(QShortcut)}
    assert set(by_key) == {"L", "F", "Esc"}
    assert not window.light.on and not window.isFullScreen()
    by_key["L"].activated.emit()
    assert window.light.on and window.light_button.isChecked()
    by_key["L"].activated.emit()
    assert not window.light.on
    by_key["F"].activated.emit()
    assert window.isFullScreen() and window.full_button.isChecked()
    by_key["Esc"].activated.emit()
    assert not window.isFullScreen() and not window.full_button.isChecked()


def test_controls_have_accessible_names(window):
    names = {c.accessibleName() for c in (window.light_button, window.full_button, window.method_combo, window.source_combo,
                                          window.device_combo, window.ref_edit)}
    assert names == {"Light frame", "Fullscreen", "Method", "Source", "Reference device", "Reference BPM"}


def test_low_light_and_no_face_messages_survive_the_restyle(window):
    drive(window, window._mock, 0.0, 35.0)
    assert window.panel.state_line.text() == "More light needed"
    assert window.panel.state_dot._color == theme.FAIR
    drive(window, window._mock, 35.0, 54.0)
    assert window.panel.state_line.text() == "No face detected" and window.video.lock_tag.text() == "NO FACE"


def test_font_family_falls_back_to_the_system_fonts_when_plex_is_missing(app, monkeypatch):
    from PySide6.QtGui import QFontDatabase
    theme.family.cache_clear()
    monkeypatch.setattr(QFontDatabase, "families", staticmethod(lambda *a, **k: ["Some Sans", "Some Mono"]))
    assert theme.family("sans") != theme.PLEX_SANS and theme.family("mono") != theme.PLEX_MONO
    monkeypatch.setattr(QFontDatabase, "families", staticmethod(lambda *a, **k: [theme.PLEX_SANS, theme.PLEX_MONO, "X"]))
    theme.family.cache_clear()
    assert theme.family("sans") == theme.PLEX_SANS and theme.family("mono") == theme.PLEX_MONO      # Plex when installed
    theme.family.cache_clear()
