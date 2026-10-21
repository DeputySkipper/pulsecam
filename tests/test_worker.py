"""CaptureWorker without a camera: file playback, pacing, failure paths, recording hook."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import cv2
import numpy as np
import pytest

import worker as worker_module
from recorder import Recorder
from worker import CaptureWorker


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "clip.mp4"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (160, 120))
    for i in range(30):                                   # 1 s at 30 fps
        w.write(np.full((120, 160, 3), 40 + i, np.uint8))
    w.release()
    return str(path)


def run_worker(w):
    got, ended, failed = [], [], []
    w.sample.connect(got.append)
    w.ended.connect(lambda: ended.append(1))
    w.failed.connect(failed.append)
    t0 = time.perf_counter()
    w.run()                                               # synchronously: signals are delivered directly
    return got, ended, failed, time.perf_counter() - t0


def test_file_mode_plays_every_frame_in_real_time_and_signals_the_end(clip):
    got, ended, failed, elapsed = run_worker(CaptureWorker("file", clip))
    assert len(got) == 30 and ended == [1] and failed == []
    t = [s.t for s in got]
    assert t[0] == 0.0 and all(b > a for a, b in zip(t, t[1:]))       # timestamps come from the file
    assert abs((t[-1] - t[0]) - 29 / 30) < 0.02
    assert 0.85 <= elapsed <= 1.6                                     # paced to real time, not instant
    assert all(s.preview.shape[1] == 480 for s in got)                # preview downscaled, overlays on the copy only


def test_stop_ends_playback_early_without_an_end_signal(clip):
    w = CaptureWorker("file", clip)
    got = []
    w.sample.connect(lambda s: (got.append(s), w.stop() if len(got) == 5 else None))
    ended = []
    w.ended.connect(lambda: ended.append(1))
    w.run()
    assert len(got) == 5 and ended == []


def test_missing_file_reports_failure(tmp_path):
    got, ended, failed, _ = run_worker(CaptureWorker("file", str(tmp_path / "nope.mp4")))
    assert got == [] and ended == [] and failed and "nope.mp4" in failed[0]


def test_camera_that_cannot_open_reports_failure(monkeypatch):
    def boom():
        raise RuntimeError("Could not open camera 0")
    monkeypatch.setattr(worker_module, "WebcamSource", boom)
    got, ended, failed, _ = run_worker(CaptureWorker("webcam"))
    assert failed == ["Could not open camera 0"] and got == []


def test_camera_that_stops_delivering_frames_reports_failure(monkeypatch):
    class Dead:
        def read(self): return None
        def release(self): pass
    monkeypatch.setattr(worker_module, "WebcamSource", Dead)
    _, ended, failed, _ = run_worker(CaptureWorker("webcam"))
    assert ended == [] and failed == ["The camera stopped delivering frames"]


def test_recording_hook_writes_clean_frames_and_stops_cleanly(clip, tmp_path):
    rec = Recorder("CHROM", "file", False, directory=tmp_path)
    w = CaptureWorker("file", clip)
    w.set_recorder(rec)
    run_worker(w)
    w.set_recorder(None)
    meta = rec.close()
    assert meta["frames"] == 30 and meta["files"]["video"]
    cap = cv2.VideoCapture(str(rec.video_path))
    ok, first = cap.read()
    cap.release()
    assert ok and first.shape == (120, 160, 3)                        # full resolution, not the 480-wide preview


def test_constructor_validates_arguments():
    with pytest.raises(ValueError):
        CaptureWorker("tape")
    with pytest.raises(ValueError):
        CaptureWorker("file")
