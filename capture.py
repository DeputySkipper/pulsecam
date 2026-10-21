"""Frame sources (TRD section 6).

WebcamSource and FileSource return `(t, frame_bgr)` from `read()` (None at end/failure);
FaceROI turns that into a FrameSample. MockSource returns a FrameSample directly.
"""
from __future__ import annotations

import logging
import sys
import time

import cv2
import numpy as np

import config
from models import FrameSample

log = logging.getLogger(__name__)


class WebcamSource:
    """cv2.VideoCapture with perf_counter() timestamps taken right after each read."""

    def __init__(self, index: int = config.CAM_INDEX):
        # AVFoundation on macOS, DirectShow on Windows (faster open), default elsewhere.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera {index}. Check camera permission and that no other app uses it.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_H)
        self.cap.set(cv2.CAP_PROP_FPS, config.FPS_REQUEST)
        self._t_open = time.perf_counter()
        self._lock_done = not config.TRY_LOCK_CAMERA
        self.lock_result = "not attempted"
        self._times: list[float] = []

    def _try_lock_camera(self) -> None:
        """Best effort exposure / white-balance lock. Logs what the driver reports back."""
        before = (self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE), self.cap.get(cv2.CAP_PROP_AUTO_WB))
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)   # 0.25 = manual on DirectShow / V4L2
        self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        after = (self.cap.get(cv2.CAP_PROP_AUTO_EXPOSURE), self.cap.get(cv2.CAP_PROP_AUTO_WB))
        changed = before != after
        self.lock_result = f"auto_exposure/auto_wb before={before} after={after} ({'changed' if changed else 'no change: driver ignores it'})"
        log.info("Camera lock: %s", self.lock_result)

    def read(self) -> tuple[float, np.ndarray] | None:
        ok, frame = self.cap.read()
        t = time.perf_counter()
        if not ok or frame is None:
            return None
        if not self._lock_done and t - self._t_open >= config.CAM_WARMUP_SEC:
            self._lock_done = True
            self._try_lock_camera()
        self._times.append(t)
        del self._times[:-120]
        return t, frame

    @property
    def measured_fps(self) -> float:
        if len(self._times) < 2:
            return 0.0
        return (len(self._times) - 1) / (self._times[-1] - self._times[0])

    def release(self) -> None:
        self.cap.release()


class FileSource:
    """Video file; timestamps come from the file (POS_MSEC), falling back to index / fps."""

    def __init__(self, path: str):
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open video file: {path}")
        self.file_fps = self.cap.get(cv2.CAP_PROP_FPS) or float(config.FPS_REQUEST)
        self._index = 0

    def read(self) -> tuple[float, np.ndarray] | None:
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None
        pos_ms = self.cap.get(cv2.CAP_PROP_POS_MSEC)
        # Some backends report POS_MSEC = 0 for every frame; then fall back to index / fps.
        t = pos_ms / 1000.0 if (pos_ms > 0 or self._index == 0) else self._index / self.file_fps
        self._index += 1
        return t, frame

    def release(self) -> None:
        self.cap.release()


class MockSource:
    """Emits FrameSamples at MOCK_HZ with a synthetic pulse, bypassing face detection.

    With `scenario=True` it cycles through config.MOCK_SCENARIO so every UI state gets exercised; with
    `scenario=False` it is a steady, clean 72 BPM signal. `sample_at(t)` must be called with increasing t.
    `relock` flags mimic FaceROI: one when the face appears and one ROI_LOCK_SEC later (the freeze).
    """

    def __init__(self, bpm: float = config.MOCK_BPM, seed: int | None = 0, scenario: bool = True):
        self.bpm = bpm
        self.scenario = scenario
        self.rng = np.random.default_rng(seed)
        self._t0 = time.perf_counter()
        self._n = 0
        self._period = 1.0 / config.MOCK_HZ
        self._base = np.array(config.MOCK_BASE_RGB)
        self._dir = np.array(config.MOCK_PULSE_DIR)
        self._cycle = sum(d for _, d in config.MOCK_SCENARIO)
        self._tones = np.linspace(*config.MOCK_POOR_TONES)
        self._tone_phase = self.rng.uniform(0, 2 * np.pi, len(self._tones))
        self._tone_dir = self.rng.choice([-1.0, 1.0], (len(self._tones), 3)) * self.rng.uniform(0.5, 1.0, (len(self._tones), 3))
        self._face_since: float | None = None
        self._froze = False
        self._previews: dict[str, np.ndarray] = {}

    def phase_at(self, t: float) -> str:
        if not self.scenario:
            return "measuring"
        t %= self._cycle
        for name, dur in config.MOCK_SCENARIO:
            if t < dur:
                return name
            t -= dur
        return config.MOCK_SCENARIO[-1][0]

    def _gain(self, t: float) -> float:
        """Brightness gain: 1 normally, MOCK_DIM_GAIN in the dim phase, ramped over MOCK_RAMP_SEC at the edges."""
        if not self.scenario:
            return 1.0
        ago = np.linspace(0.0, config.MOCK_RAMP_SEC, 8)     # moving average of the target = a linear ramp
        return float(np.mean([config.MOCK_DIM_GAIN if self.phase_at(t - u) == "dim" else 1.0 for u in ago]))

    def _preview(self, phase: str) -> np.ndarray:
        if phase not in self._previews:
            w = config.PREVIEW_W
            h = w * config.FRAME_H // config.FRAME_W
            img = np.full((h, w, 3), 24, np.uint8)
            cv2.putText(img, "MOCK", (w // 2 - 60, h // 2 + 12), cv2.FONT_HERSHEY_SIMPLEX,
                        1.5, (160, 160, 160), 2, cv2.LINE_AA)
            if self.scenario:
                cv2.putText(img, phase, (12, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (120, 120, 120), 1, cv2.LINE_AA)
            self._previews[phase] = img
        return self._previews[phase].copy()

    def sample_at(self, t: float) -> FrameSample:
        phase = self.phase_at(t)
        preview = self._preview(phase)
        if phase == "no_face":
            self._face_since, self._froze = None, False
            return FrameSample(t=t, rgb=None, face_found=False, face_box=None, rois=[], preview=preview)

        relock = False
        if self._face_since is None:                    # face just appeared: lock starts
            self._face_since, self._froze, relock = t, False, True
        elif not self._froze and t - self._face_since >= config.ROI_LOCK_SEC:
            self._froze, relock = True, True            # lock phase over: box frozen

        f = self.bpm / 60.0
        pulse = config.MOCK_AMPLITUDE * np.sin(2 * np.pi * f * t) * self._dir
        drift = config.MOCK_DRIFT_AMP * np.sin(2 * np.pi * config.MOCK_DRIFT_HZ * t)
        noise = self.rng.normal(0.0, config.MOCK_NOISE_SIGMA, 3)
        if phase == "poor":     # per-channel directions differ, so CHROM / POS cannot cancel it as common-mode
            noise = noise + config.MOCK_POOR_TONE_AMP * (np.sin(2 * np.pi * self._tones * t + self._tone_phase)[:, None] * self._tone_dir).sum(axis=0)
        rgb = config.RGB_MAX * self._gain(t) * (self._base + pulse + drift + noise)
        h, w = preview.shape[:2]
        box = (w // 4, h // 6, w // 2, h * 2 // 3)
        return FrameSample(t=t, rgb=rgb, face_found=True, face_box=box, rois=[], preview=preview, relock=relock)

    def read(self) -> FrameSample:
        """Block until the next 30 Hz tick, then return its sample (t is seconds since start)."""
        due = self._t0 + self._n * self._period
        delay = due - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        sample = self.sample_at(time.perf_counter() - self._t0)
        self._n += 1
        return sample

    def release(self) -> None:
        pass
