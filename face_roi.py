"""Haar face detection, box smoothing, ROI geometry and per-frame mean RGB (TRD section 5.1).

Means are computed on the clean frame. Overlays are drawn on the downscaled preview copy only.
"""
from __future__ import annotations

import cv2
import numpy as np

import config
from models import FrameSample

BOX_COLOR = (150, 150, 150)   # BGR, thin grey face box
ROI_COLOR = (109, 77, 255)    # BGR of the accent #FF4D6D


class FaceROI:
    def __init__(self):
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(path)
        if self._cascade.empty():
            raise RuntimeError(f"Could not load Haar cascade: {path}")
        if config.ROI_SET not in config.ROI_SETS:
            raise ValueError(f"ROI_SET must be one of {list(config.ROI_SETS)}, got {config.ROI_SET!r}")
        self._box: np.ndarray | None = None    # smoothed x, y, w, h (float, full-res px)
        self._last_seen_t: float | None = None
        self._frame_idx = 0
        self._frozen = False
        self._lock_start_t: float | None = None
        self._last_check_t = 0.0
        self._move_checks: list[np.ndarray] = []   # face centres from consecutive checks that saw a move

    def reset(self) -> None:
        self._box = None
        self._last_seen_t = None
        self._frame_idx = 0
        self._frozen = False
        self._lock_start_t = None

    def _detect(self, frame: np.ndarray) -> tuple[int, int, int, int] | None:
        """Largest face in full-res coordinates, or None."""
        d = config.DETECT_DOWNSCALE
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, None, fx=1.0 / d, fy=1.0 / d, interpolation=cv2.INTER_AREA)
        m = config.HAAR_MIN_SIZE // d
        faces = self._cascade.detectMultiScale(
            small, scaleFactor=config.HAAR_SCALE_FACTOR,
            minNeighbors=config.HAAR_MIN_NEIGHBORS, minSize=(m, m))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        return int(x * d), int(y * d), int(w * d), int(h * d)

    def _start_lock(self, new: np.ndarray, t: float) -> None:
        self._box = new
        self._frozen = False
        self._lock_start_t = t
        self._move_checks.clear()

    def _update_box(self, frame: np.ndarray, t: float) -> bool:
        """Update the face box. Returns True when the ROI was (re)locked or frozen this frame.

        FREEZE_ROI: detect and EMA-smooth for ROI_LOCK_SEC, then hold the box fixed. While frozen, a fresh
        detection is compared with the box every RELOCK_CHECK_SEC; a centre move above RELOCK_MOVE_FRAC of
        the box width confirmed by RELOCK_CONFIRM_CHECKS consecutive agreeing checks, or a lost face, starts a new lock. Callers restart their buffer on a True return.
        """
        relock = False
        if self._frame_idx % config.DETECT_EVERY_N == 0:
            new = self._detect(frame)
            if new is not None:
                new = np.array(new, dtype=np.float64)
                lost = self._last_seen_t is not None and t - self._last_seen_t > config.FACE_LOST_SEC
                if self._box is None or (config.FREEZE_ROI and lost):
                    self._start_lock(new, t)
                    relock = config.FREEZE_ROI
                elif self._frozen:
                    if t - self._last_check_t >= config.RELOCK_CHECK_SEC:
                        self._last_check_t = t
                        limit = config.RELOCK_MOVE_FRAC * self._box[2]
                        centre = new[:2] + new[2:] / 2
                        if np.hypot(*(centre - (self._box[:2] + self._box[2:] / 2))) <= limit:
                            self._move_checks.clear()            # face is where the box is: any earlier "move" was an outlier
                        else:
                            if self._move_checks and np.hypot(*(centre - self._move_checks[-1])) > limit:
                                self._move_checks.clear()        # the checks disagree about where the face went
                            self._move_checks.append(centre)
                            if len(self._move_checks) >= config.RELOCK_CONFIRM_CHECKS:
                                self._start_lock(new, t)
                                relock = True
                else:
                    a = config.BOX_EMA_ALPHA
                    self._box = a * new + (1 - a) * self._box
                self._last_seen_t = t
        self._frame_idx += 1
        if (config.FREEZE_ROI and self._box is not None and not self._frozen
                and self._lock_start_t is not None and t - self._lock_start_t >= config.ROI_LOCK_SEC):
            self._frozen = True
            self._last_check_t = t
            relock = True
        return relock

    def _rois(self, frame_shape: tuple[int, ...]) -> list[tuple[int, int, int, int]]:
        fh, fw = frame_shape[:2]
        bx, by, bw, bh = self._box
        rois = []
        for name in config.ROI_SETS[config.ROI_SET]:
            x0, y0, x1, y1 = config.ROI_FRACTIONS[name]
            rx0 = int(round(max(0, bx + x0 * bw)))
            ry0 = int(round(max(0, by + y0 * bh)))
            rx1 = int(round(min(fw, bx + x1 * bw)))
            ry1 = int(round(min(fh, by + y1 * bh)))
            if rx1 > rx0 and ry1 > ry0:
                rois.append((rx0, ry0, rx1 - rx0, ry1 - ry0))
        return rois

    @staticmethod
    def _mean_rgb(frame: np.ndarray, rois: list[tuple[int, int, int, int]]) -> np.ndarray | None:
        """Pixel-count-weighted mean over all ROIs, returned in R, G, B order."""
        total = np.zeros(3)
        count = 0
        for x, y, w, h in rois:
            patch = frame[y:y + h, x:x + w]
            total += patch.reshape(-1, 3).sum(axis=0, dtype=np.float64)
            count += patch.shape[0] * patch.shape[1]
        if count == 0:
            return None
        return total[::-1] / count          # OpenCV is BGR; reverse to R, G, B

    def _make_preview(self, frame: np.ndarray, face_box, rois) -> np.ndarray:
        scale = config.PREVIEW_W / frame.shape[1]
        preview = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if face_box is not None:
            for box, color in [(face_box, BOX_COLOR)] + [(r, ROI_COLOR) for r in rois]:
                x, y, w, h = (int(round(v * scale)) for v in box)
                cv2.rectangle(preview, (x, y), (x + w, y + h), color, 1, cv2.LINE_AA)
        return preview

    def process(self, frame: np.ndarray, t: float) -> FrameSample:
        """frame: full-res BGR uint8. Returns a FrameSample (box and ROIs in full-res coordinates)."""
        relock = self._update_box(frame, t)
        found = (self._box is not None and self._last_seen_t is not None
                 and t - self._last_seen_t <= config.FACE_LOST_SEC)
        if not found:
            return FrameSample(t=t, rgb=None, face_found=False, face_box=None, rois=[],
                               preview=self._make_preview(frame, None, []))
        rois = self._rois(frame.shape)
        rgb = self._mean_rgb(frame, rois)          # clean frame, before any drawing
        face_box = tuple(int(round(v)) for v in self._box)
        return FrameSample(t=t, rgb=rgb, face_found=rgb is not None, face_box=face_box, rois=rois,
                           preview=self._make_preview(frame, face_box, rois), relock=relock)
