"""Data contracts shared by capture, estimator and UI (TRD section 4)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class FrameSample:
    t: float                                    # seconds; perf_counter() right after read (file: POS_MSEC / 1000)
    rgb: np.ndarray | None                      # shape (3,), mean R, G, B over ROI skin pixels; None if no face
    face_found: bool
    face_box: tuple[int, int, int, int] | None  # smoothed x, y, w, h
    rois: list[tuple[int, int, int, int]]       # x, y, w, h per ROI
    preview: np.ndarray                         # BGR uint8, downscaled, overlays drawn
    motion: bool = False
    relock: bool = False                        # ROI box was (re)locked or frozen this frame: the estimator level-matches across it


@dataclass
class HRResult:
    t: float
    state: str            # "no_face" | "warming_up" | "measuring" | "poor_signal"
    method: str           # "GREEN" | "CHROM" | "POS"
    bpm: float | None     # this window's estimate
    bpm_smooth: float | None
    snr_db: float | None
    quality: str          # "good" | "fair" | "poor" | "n/a"
    fps: float            # measured capture rate over the buffer
    buffer_sec: float     # seconds of data buffered (warm-up progress)
    t_sig: np.ndarray = field(default_factory=lambda: np.empty(0))   # uniform time axis for plots (s, relative)
    raw: np.ndarray = field(default_factory=lambda: np.empty((0, 3)))  # (N, 3) normalised RGB
    pulse: np.ndarray = field(default_factory=lambda: np.empty(0))   # filtered pulse signal
    freqs: np.ndarray = field(default_factory=lambda: np.empty(0))   # Hz
    power: np.ndarray = field(default_factory=lambda: np.empty(0))
    peak_hz: float | None = None
