"""Haar face detection, box smoothing, ROI geometry and per-frame mean RGB (TRD section 5.1).

Means are computed on the clean frame. Overlays are drawn on the downscaled preview copy only.
"""
from __future__ import annotations

import cv2
import numpy as np

import config
from models import FrameSample

BOX_COLOR = (150, 150, 150)   # BGR, thin grey box: the tracked face (follows it continuously)
ROI_COLOR = (109, 77, 255)    # BGR of the accent #FF4D6D: the regions being measured (held still between re-locks)


class FaceROI:
    """Finds the face, tracks it, and decides which region of the frame is measured.

    Two boxes: the *live* face box follows every detection (median of the last few detections, smoothed), and the
    *measurement* box, which defines the cheek regions, holds perfectly still while the face stays within a small dead
    band of it (so detector jitter never reaches the signal) and glides to the face when it moves beyond it.
    """

    def __init__(self):
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(path)
        if self._cascade.empty():
            raise RuntimeError(f"Could not load Haar cascade: {path}")
        if config.ROI_SET not in config.ROI_SETS:
            raise ValueError(f"ROI_SET must be one of {list(config.ROI_SETS)}, got {config.ROI_SET!r}")
        self._frame_idx = 0
        self._last_seen_t: float | None = None
        self._detections: list[np.ndarray] = []                # the last TRACK_MEDIAN_N detections
        self._live: np.ndarray | None = None                   # the tracked face (x, y, w, h)
        self._box: np.ndarray | None = None                    # the measurement box
        self._moving = False                                   # the measurement box is gliding to the face
        self._move_flagged = False                             # ...and that glide began with a flag (a real move, not a re-centre)
        self._settle_at: float | None = None                   # when the box settled; its flag is raised ROI_SETTLE_HOLD_SEC later
        self._move_until = 0.0                                 # the first lock follows for at least ROI_LOCK_SEC
        self._trail: list[tuple[float, np.ndarray]] = []       # (time, live centre) over the last ROI_STILL_SEC

    @property
    def live_box(self) -> tuple[int, int, int, int] | None:
        """The continuously tracked face box. The measurement ROIs can sit slightly off it (inside the dead band)."""
        return None if self._live is None else tuple(int(round(v)) for v in self._live)

    def reset(self) -> None:
        self._frame_idx = 0
        self._last_seen_t = None
        self._detections.clear()
        self._live = self._box = None
        self._moving = self._move_flagged = False
        self._settle_at = None
        self._trail.clear()

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

    @staticmethod
    def _centre(box: np.ndarray) -> np.ndarray:
        return box[:2] + box[2:] / 2

    def _track(self, new: np.ndarray, t: float, lost: bool) -> None:
        """Update the live face box from a detection: a median over the last few (one wild detection cannot move it),
        smoothed. After a lost face the history starts again."""
        if lost:
            self._detections.clear()
            self._live = None
        self._detections.append(new)
        del self._detections[:-config.TRACK_MEDIAN_N]
        median = np.median(np.array(self._detections), axis=0)
        a = config.TRACK_EMA
        self._live = median if self._live is None else a * median + (1 - a) * self._live
        self._trail.append((t, self._centre(self._live)))
        while self._trail and t - self._trail[0][0] > config.ROI_STILL_SEC:
            self._trail.pop(0)

    def _live_is_still(self, t: float) -> bool:
        """The tracked face has barely moved for ROI_STILL_SEC."""
        if not self._trail or t - self._trail[0][0] < config.ROI_STILL_SEC * 0.9:
            return False
        c = np.array([p for _, p in self._trail])
        return float(np.hypot(*np.ptp(c, axis=0))) <= 1.5 * config.ROI_STILL_FRAC * self._live[2]   # a step in the window is not still

    def _update_box(self, frame: np.ndarray, t: float) -> bool:
        """Track the face and move the measurement box. Returns True when the box starts gliding (a lock start) or
        settles (a freeze): the estimator level-matches across both.

        FREEZE_ROI off: the box is simply smoothed along with the face (no flags), as in the first version.
        FREEZE_ROI on: the box holds still while the live face is within RELOCK_MOVE_FRAC of the box width of it, and
        glides to the face (a fraction ROI_GLIDE_GAIN of the gap per detection) once it is further than that, until it is
        within ROI_SETTLE_FRAC. A real move raises a flag when it starts and another once the box has stayed settled for
        ROI_SETTLE_HOLD_SEC (continuous motion is one long follow: a new move cancels the pending settle). A smaller leftover
        offset (above ROI_RECENTRE_FRAC) is corrected gently, without flags, once the face has been still for ROI_STILL_SEC.
        """
        relock = False
        if self._frame_idx % config.DETECT_EVERY_N == 0:
            new = self._detect(frame)
            if new is not None:
                new = np.array(new, dtype=np.float64)
                lost = self._last_seen_t is not None and t - self._last_seen_t > config.FACE_LOST_SEC
                self._track(new, t, lost)
                if not config.FREEZE_ROI:
                    a = config.BOX_EMA_ALPHA
                    self._box = new.copy() if self._box is None else a * new + (1 - a) * self._box
                elif self._box is None or lost:
                    self._box, self._moving, self._move_flagged = self._live.copy(), True, True   # a (re)acquired face: lock on
                    self._move_until = t + max(0.0, config.ROI_LOCK_SEC - config.ROI_SETTLE_HOLD_SEC)
                    self._settle_at = None
                    relock = True
                else:
                    gap = float(np.hypot(*(self._centre(self._live) - self._centre(self._box))))
                    width = self._box[2]
                    if not self._moving:
                        real_move = gap > config.RELOCK_MOVE_FRAC * width
                        if real_move or (gap > config.ROI_RECENTRE_FRAC * width and self._live_is_still(t)):
                            self._moving, self._move_until = True, 0.0
                            if real_move:
                                relock = self._settle_at is None                       # a pending settle is cancelled: still one follow
                                self._move_flagged, self._settle_at = True, None
                    if not self._moving and self._settle_at is not None and t >= self._settle_at:
                        self._settle_at, self._move_flagged, relock = None, False, True   # settled for long enough: the freeze flag
                    if self._moving:
                        self._box = self._box + config.ROI_GLIDE_GAIN * (self._live - self._box)
                        gap = float(np.hypot(*(self._centre(self._live) - self._centre(self._box))))
                        if gap <= config.ROI_SETTLE_FRAC * self._box[2] and t >= self._move_until:
                            self._moving = False
                            if self._move_flagged:
                                self._settle_at = t + config.ROI_SETTLE_HOLD_SEC        # its flag comes after the hold
                self._last_seen_t = t
        self._frame_idx += 1
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
                           preview=self._make_preview(frame, self.live_box or face_box, rois), relock=relock)
