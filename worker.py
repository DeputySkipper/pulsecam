"""CaptureWorker: source -> FaceROI -> FrameSample, off the UI thread (TRD section 3).

Qt widgets are never touched here; the worker only emits signals. Recording is also done here, from the
clean full-resolution frame, so the saved means and video never contain overlays.
"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal

from capture import FileSource, WebcamSource
from face_roi import FaceROI

SLEEP_SLICE_SEC = 0.05        # file pacing sleeps in slices so stop() is noticed quickly


class CaptureWorker(QThread):
    sample = Signal(object)       # FrameSample, one per frame
    failed = Signal(str)          # the source could not be opened, or stopped delivering frames
    ended = Signal()              # a file source reached its end

    def __init__(self, kind: str, path: str | None = None, parent=None):
        super().__init__(parent)
        if kind not in ("webcam", "file"):
            raise ValueError(f"kind must be 'webcam' or 'file', got {kind!r}")
        if kind == "file" and not path:
            raise ValueError("a file source needs a path")
        self.kind, self.path = kind, path
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._recorder = None

    def stop(self) -> None:
        self._stop_event.set()

    def set_recorder(self, recorder) -> None:
        """Start (or, with None, stop) writing frames to a Recorder. When this returns after set_recorder(None),
        the worker is no longer writing, so the caller can close the recorder safely."""
        with self._lock:
            self._recorder = recorder

    def run(self) -> None:
        try:
            source = FileSource(self.path) if self.kind == "file" else WebcamSource()
        except RuntimeError as e:
            self.failed.emit(str(e))
            return
        face_roi = FaceROI()
        wall0 = t_first = None
        try:
            while not self._stop_event.is_set():
                item = source.read()
                if item is None:
                    if self.kind == "file":
                        self.ended.emit()
                    else:
                        self.failed.emit("The camera stopped delivering frames")
                    return
                t, frame = item
                if self.kind == "file":
                    if wall0 is None:
                        wall0, t_first = time.perf_counter(), t
                    self._pace(wall0, t_first, t)
                    if self._stop_event.is_set():
                        return
                sample = face_roi.process(frame, t)
                with self._lock:
                    if self._recorder is not None:
                        self._recorder.write(frame, sample)
                self.sample.emit(sample)
        finally:
            source.release()

    def _pace(self, wall0: float, t_first: float, t: float) -> None:
        """Play a file back in real time: wait until the wall clock catches up with the frame's timestamp."""
        while not self._stop_event.is_set():
            delay = (t - t_first) - (time.perf_counter() - wall0)
            if delay <= 0:
                return
            time.sleep(min(delay, SLEEP_SLICE_SEC))
