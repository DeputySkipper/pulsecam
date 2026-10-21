"""Recorder, meta file and reading logger (no Qt, no camera)."""
import csv
import time
import json

import cv2
import numpy as np
import pytest

import config
import recorder
from models import FrameSample
from recorder import Recorder, log_reading, update_meta


def sample(t, rgb=(200.0, 100.0, 50.0), found=True):
    return FrameSample(t=t, rgb=None if rgb is None else np.array(rgb), face_found=found, face_box=None,
                       rois=[], preview=np.zeros((4, 4, 3), np.uint8))


def frames(n, seed=0):
    rng = np.random.default_rng(seed)
    return [rng.integers(0, 255, (48, 64, 3), dtype=np.uint8) for _ in range(n)]


def record(tmp_path, n=45, fps=25.0, **kw):
    rec = Recorder(method="CHROM", source="webcam", light_frame=False, directory=tmp_path, **kw)
    fs = frames(n)
    for i, f in enumerate(fs):
        rec.write(f, sample(100.0 + i / fps))
    return rec, fs


def test_means_csv_has_relative_time_rgb_order_and_blank_rows_without_a_face(tmp_path):
    rec = Recorder("CHROM", "webcam", False, directory=tmp_path)
    rec.write(frames(1)[0], sample(50.0))
    rec.write(frames(1)[0], sample(50.04, rgb=None, found=False))
    rec.close()
    rows = list(csv.reader(open(rec.csv_path)))
    assert rows[0] == ["t", "R", "G", "B", "face_found", "relock"]
    assert rows[1] == ["0.000000", "200.00000", "100.00000", "50.00000", "1", "0"]      # R, G, B order; t relative
    assert rows[2] == ["0.040000", "", "", "", "0", "0"]


def test_video_is_lossless_and_plays_at_the_measured_fps(tmp_path):
    rec, fs = record(tmp_path, n=45, fps=25.0)         # a camera that ran at 25 fps, not the nominal 30
    meta = rec.close()
    assert rec.video_path.suffix == ".mkv" and "lossless" in meta["video"]["codec"]
    cap = cv2.VideoCapture(str(rec.video_path))
    assert abs(cap.get(cv2.CAP_PROP_FPS) - 25.0) < 0.5
    back = [cap.read()[1] for _ in fs]
    cap.release()
    assert all(np.array_equal(a, b) for a, b in zip(fs, back))
    assert meta["frames"] == 45 and abs(meta["measured_fps"] - 25.0) < 0.1


def test_clip_shorter_than_the_fps_probe_is_still_saved(tmp_path):
    rec, fs = record(tmp_path, n=config.RECORD_FPS_PROBE_FRAMES - 10)
    meta = rec.close()
    cap = cv2.VideoCapture(str(rec.video_path))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == len(fs) and meta["files"]["video"]
    cap.release()


def test_falls_back_to_mjpg_with_a_warning_when_ffv1_is_unavailable(tmp_path, monkeypatch):
    ffv1 = cv2.VideoWriter_fourcc(*"FFV1")
    real = cv2.VideoWriter

    class Failing:
        def isOpened(self): return False
        def release(self): pass

    monkeypatch.setattr(recorder.cv2, "VideoWriter", lambda path, fourcc, *a: Failing() if fourcc == ffv1 else real(path, fourcc, *a))
    monkeypatch.setattr(recorder.cv2, "VideoWriter_fourcc", cv2.VideoWriter_fourcc, raising=False)
    rec, _ = record(tmp_path)
    meta = rec.close()
    assert rec.video_path.suffix == ".avi" and "lossy" in meta["video"]["codec"]
    assert any("lossy" in w for w in meta["warnings"])
    assert rec.csv_path.exists()                       # the means CSV is always written


def test_meta_has_settings_and_reference_fields(tmp_path):
    rec, _ = record(tmp_path, ref={"ref_bpm": 90, "device": "smartwatch", "notes": "torch on stand"})
    meta = rec.close(method="POS")
    s = meta["settings"]
    assert {"ROI_SET", "FREEZE_ROI", "BAND_LO", "WINDOW_SEC", "method"} <= set(s)
    assert s["ROI_SET"] == config.ROI_SET and s["BAND_LO"] == config.BAND_LO and s["method"] == "CHROM"
    assert meta["method_at_stop"] == "POS"
    assert meta["ref_bpm"] == 90 and meta["device"] == "smartwatch" and meta["notes"] == "torch on stand"
    assert meta["light_frame"] is False and meta["source"] == "webcam"
    assert meta["config"]["SNR_FAIR_DB"] == config.SNR_FAIR_DB and meta["config"]["ROI_SETS"]["cheeks"]
    assert json.loads(rec.meta_path.read_text()) == meta
    assert meta["duration_sec"] > 0 and meta["files"]["means"].endswith("_means.csv")


def test_meta_is_written_at_start_so_a_crash_still_leaves_it(tmp_path):
    rec = Recorder("CHROM", "webcam", True, directory=tmp_path)
    assert json.loads(rec.meta_path.read_text())["settings"]["method"] == "CHROM"
    rec.close()


def test_reference_can_be_added_after_the_clip_and_survives_close(tmp_path):
    rec, _ = record(tmp_path)
    update_meta(rec.meta_path, ref_bpm=88, device="pulse count")      # typed while recording
    meta = rec.close()
    assert meta["ref_bpm"] == 88 and meta["device"] == "pulse count"
    meta = update_meta(rec.meta_path, ref_bpm=90.5, notes="average of 3 readings")   # typed after stopping
    assert meta["ref_bpm"] == 90.5 and meta["settings"]["method"] == "CHROM"          # nothing else was lost
    assert json.loads(rec.meta_path.read_text())["notes"] == "average of 3 readings"


def test_config_snapshot_is_json_serialisable_and_complete():
    snap = recorder.config_snapshot()
    json.dumps(snap)
    assert snap["BAND_LO"] == config.BAND_LO and snap["DEFAULT_METHOD"] == config.DEFAULT_METHOD


def test_log_reading_creates_header_and_appends(tmp_path):
    path = tmp_path / "readings.csv"
    a = log_reading("CHROM", 84.13, 90, 4.2, False, path=path)
    log_reading("POS", 88.0, 90, None, True, path=path)
    rows = list(csv.DictReader(open(path)))
    assert list(rows[0]) == list(recorder.READING_COLUMNS)
    assert rows[0]["method"] == "CHROM" and rows[0]["bpm_smooth"] == "84.1" and rows[0]["abs_error"] == "5.9"
    assert rows[0]["snr_db"] == "4.2" and rows[0]["light_frame"] == "off" and a["ref_bpm"] == "90"
    assert rows[1]["snr_db"] == "" and rows[1]["light_frame"] == "on" and len(rows) == 2


# ---- encoding happens off the capture thread

class SlowWriter:
    """Stands in for cv2.VideoWriter: opens fine, but every frame takes a while to encode."""
    def __init__(self, delay=0.03, fail_after=None):
        self.delay, self.fail_after, self.frames = delay, fail_after, 0

    def isOpened(self): return True
    def set(self, *a): pass
    def release(self): pass

    def write(self, f):
        if self.fail_after is not None and self.frames >= self.fail_after:
            raise RuntimeError("disk full")
        time.sleep(self.delay)
        self.frames += 1


def test_write_never_waits_for_the_encoder_and_nothing_is_lost(tmp_path, monkeypatch):
    slow = SlowWriter(delay=0.01)
    monkeypatch.setattr(recorder.cv2, "VideoWriter", lambda *a, **k: slow)
    rec = Recorder("CHROM", "webcam", False, directory=tmp_path)
    fs = frames(120)                                 # more than the fps probe, so the flush and the live stream overlap
    t0 = time.perf_counter()
    for i, f in enumerate(fs):                       # the fps-probe flush used to block the 30th call for the whole batch
        rec.write(f, sample(10.0 + i / 30))
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.3, f"capture thread was blocked for {elapsed:.2f} s"
    meta = rec.close()
    assert slow.frames == 120 and meta["frames"] == 120              # every frame still reached the encoder
    assert meta["video_max_backlog_frames"] > 0                     # the backlog was real, and recorded
    assert len(list(csv.reader(open(rec.csv_path)))) == 121


def test_encoder_failure_is_reported_and_the_means_csv_survives(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder.cv2, "VideoWriter", lambda *a, **k: SlowWriter(delay=0, fail_after=95))
    rec = Recorder("CHROM", "webcam", False, directory=tmp_path)
    for i, f in enumerate(frames(130)):
        rec.write(f, sample(10.0 + i / 30))
    meta = rec.close()
    assert any("video encoding failed" in w and "disk full" in w for w in meta["warnings"])
    assert meta["frames"] == 130 and len(list(csv.reader(open(rec.csv_path)))) == 131


def test_relock_flag_is_written_so_evaluation_can_reproduce_the_live_estimator(tmp_path):
    rec = Recorder("CHROM", "webcam", False, directory=tmp_path)
    for i in range(4):
        smp = sample(5.0 + i / 30)
        smp.relock = i == 2
        rec.write(frames(1)[0], smp)
    rec.close()
    rows = list(csv.DictReader(open(rec.csv_path)))
    assert [r["relock"] for r in rows] == ["0", "0", "1", "0"]
