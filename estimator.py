"""Owns the sample buffer and the method; produces an HRResult on demand (TRD sections 3 and 5.2).

Live console demo:  python estimator.py [--seconds 60] [--method POS]
"""
from __future__ import annotations

from collections import deque
from statistics import median

import numpy as np

import config
import signal_proc
from models import HRResult


class Estimator:
    def __init__(self, method: str = config.DEFAULT_METHOD):
        if method not in signal_proc.METHODS:
            raise ValueError(f"Method {method!r} not available; implemented: {list(signal_proc.METHODS)}")
        self.method = method
        self._buf: deque[tuple[float, np.ndarray]] = deque()
        self._good: deque[float] = deque(maxlen=config.SMOOTH_K)   # recent accepted non-poor BPM estimates
        self._jump: list[float] = []                               # run of agreeing out-of-range estimates
        self._last_accept_t: float | None = None                   # sample time of the last estimate added to the history
        self._pending: list[float] = []                            # consecutive non-poor estimates awaiting confirmation
        self._gain = np.ones(3)                                    # raw -> buffer scale of the current ROI segment
        self._seam_pre: np.ndarray | None = None                   # mean of the last SEAM_MATCH_SEC before a re-lock
        self._post_raw: list[tuple[float, np.ndarray]] = []        # raw samples since the re-lock, until the match is final
        self._provisional_gain = np.ones(3)
        self._face_ok = False

    def set_method(self, method: str) -> None:
        """Switch method at runtime. The sample buffer is kept; the smoothing history is not."""
        if method not in signal_proc.METHODS:
            raise ValueError(f"Unknown method {method!r}; choose from {list(signal_proc.METHODS)}")
        self.method = method
        self._good.clear()
        self._jump.clear()
        self._pending.clear()
        self._last_accept_t = None

    def reset(self) -> None:
        self._buf.clear()
        self._good.clear()
        self._jump.clear()
        self._pending.clear()
        self._last_accept_t = None
        self._gain = np.ones(3)
        self._seam_pre, self._post_raw = None, []

    def push(self, t: float, rgb: np.ndarray | None, face_found: bool, relock: bool = False) -> None:
        """Cheap per-frame append. Resets the buffer on face loss or a gap; an ROI re-lock only level-matches."""
        if not face_found or rgb is None:
            self._face_ok = False
            self.reset()
            return
        self._face_ok = True
        if self._buf and t - self._buf[-1][0] > config.GAP_RESET_SEC:
            self.reset()
        rgb = np.asarray(rgb, dtype=np.float64)
        if relock:
            self._begin_seam(t)
        if self._seam_pre is not None:
            self._extend_seam(t, rgb)
        else:
            self._buf.append((t, rgb * self._gain))
        while t - self._buf[0][0] > config.WINDOW_SEC:
            self._buf.popleft()

    def _begin_seam(self, t: float) -> None:
        """The ROI box changed. Keep the buffer; scale the new segment so its per-channel means continue from the
        old segment's last SEAM_MATCH_SEC. (A level step at the seam would otherwise look like a pulse transient.)"""
        self._finish_seam()
        pre = [v for ts, v in self._buf if t - ts <= config.SEAM_MATCH_SEC]
        if pre and t - self._buf[0][0] >= config.SEAM_MIN_SEC:
            self._seam_pre = np.mean(pre, axis=0)
            self._post_raw = []

    def _extend_seam(self, t: float, rgb: np.ndarray) -> None:
        """While the new segment is shorter than SEAM_MATCH_SEC the gain is provisional: re-fit it and rewrite the
        segment's buffer entries on every sample, so estimates in the meantime already see a continuous signal."""
        self._post_raw.append((t, rgb))
        post_mean = np.mean([v for _, v in self._post_raw], axis=0)
        gain = self._seam_pre / post_mean if np.all(post_mean > config.MIN_CHANNEL_MEAN) else self._gain
        for _ in range(len(self._post_raw) - 1):
            self._buf.pop()
        for ts, v in self._post_raw:
            self._buf.append((ts, v * gain))
        self._provisional_gain = gain
        if t - self._post_raw[0][0] >= config.SEAM_MATCH_SEC:
            self._finish_seam()

    def _finish_seam(self) -> None:
        if self._seam_pre is not None and self._post_raw:
            self._gain = self._provisional_gain
        self._seam_pre, self._post_raw = None, []

    @property
    def buffer_sec(self) -> float:
        return self._buf[-1][0] - self._buf[0][0] if len(self._buf) >= 2 else 0.0

    @property
    def fps(self) -> float:
        """Measured capture rate over the buffer: (n - 1) / (t_last - t_first)."""
        return (len(self._buf) - 1) / self.buffer_sec if self.buffer_sec > 0 else 0.0

    def _accept(self, bpm: float, t: float) -> None:
        """Add a non-poor estimate to the smoothing history, with jump rejection (TRD 5.6).

        An estimate more than MAX_JUMP_BPM from the current smoothed value is held back. If
        JUMP_PERSIST consecutive held-back estimates agree with each other (each within MAX_JUMP_BPM
        of the previous one), the jump is real: the history is replaced by that run.
        """
        if not self._good:
            self._confirm(bpm, t)
            return
        if abs(bpm - median(self._good)) <= config.MAX_JUMP_BPM:
            self._good.append(bpm)
            self._jump.clear()
            self._last_accept_t = t
            return
        if self._jump and abs(bpm - self._jump[-1]) > config.MAX_JUMP_BPM:
            self._jump.clear()                       # candidates disagree: not a persistent new level
        self._jump.append(bpm)
        if len(self._jump) >= config.JUMP_PERSIST:
            self._good.clear()
            self._good.extend(self._jump[-config.SMOOTH_K:])
            self._jump.clear()
            self._last_accept_t = t

    def _confirm(self, bpm: float, t: float) -> None:
        """First number after a reset or a stale clear: needs CONFIRM_ESTIMATES consecutive non-poor
        estimates agreeing within CONFIRM_AGREE_BPM, so one lucky noise window cannot show a number."""
        self._pending.append(bpm)
        del self._pending[:-config.CONFIRM_ESTIMATES]
        if (len(self._pending) == config.CONFIRM_ESTIMATES
                and max(self._pending) - min(self._pending) <= config.CONFIRM_AGREE_BPM):
            self._good.extend(self._pending)
            self._pending.clear()
            self._last_accept_t = t

    def snapshot(self) -> tuple[np.ndarray, np.ndarray] | None:
        """Buffered (timestamps, RGB) once MIN_SEC of data exists, else None. Lets callers analyse the same data."""
        if not self._face_ok or self.buffer_sec < config.MIN_SEC:
            return None
        return (np.array([s[0] for s in self._buf]), np.stack([s[1] for s in self._buf]))

    def analyze_all(self) -> dict[str, signal_proc.Analysis | None]:
        """Every method on the current buffer (for side-by-side comparison). Empty before MIN_SEC of data."""
        snap = self.snapshot()
        if snap is None:
            return {}
        return {m: signal_proc.analyze(*snap, m) for m in signal_proc.METHODS}

    def estimate(self) -> HRResult:
        t_now = self._buf[-1][0] if self._buf else 0.0
        base = dict(t=t_now, method=self.method, bpm=None, bpm_smooth=None, snr_db=None,
                    quality="n/a", fps=self.fps, buffer_sec=self.buffer_sec)
        if not self._face_ok:
            return HRResult(state="no_face", **base)
        snap = self.snapshot()
        if snap is None:
            return HRResult(state="warming_up", **base)

        a = signal_proc.analyze(*snap, self.method)
        if a is not None and a.quality != "poor":
            self._accept(a.bpm, t_now)
        else:
            self._pending.clear()               # "consecutive" means no poor window in between
        if (self._last_accept_t is not None and t_now - self._last_accept_t > config.HOLD_MAX_SEC):
            self._good.clear()                  # nothing accepted for HOLD_MAX_SEC: the held value is stale
            self._jump.clear()                  # (also drops jump history, so a wrong value cannot stick)
            self._last_accept_t = None
        # On a poor window the last good value is held (up to HOLD_MAX_SEC); the UI greys it out.
        base["bpm_smooth"] = float(median(self._good)) if self._good else None
        if a is None:
            return HRResult(state="poor_signal", **{**base, "quality": "poor"})
        state = "poor_signal" if a.quality == "poor" else "measuring"
        return HRResult(state=state, **{**base, "bpm": a.bpm, "snr_db": a.snr_db, "quality": a.quality},
                        t_sig=a.t_sig, raw=a.raw, pulse=a.pulse, freqs=a.freqs, power=a.power,
                        peak_hz=a.peak_hz)


def _fmt(a) -> str:
    """One method's column: BPM, SNR, quality."""
    if a is None:
        return "  --   --dB poor"
    snr = f"{a.snr_db:5.1f}" if a.snr_db is not None else "  -- "
    return f"{a.bpm:5.1f} {snr}dB {a.quality:<4}"


def _print_summary(stats: dict[str, list[tuple[float | None, str]]]) -> None:
    print("\nSummary (windows after warm-up; a window with no usable signal counts as poor)")
    print(f"{'method':<7} {'windows':>7} {'median BPM (non-poor)':>22} {'good %':>7} {'fair %':>7} {'poor %':>7}")
    for m, rows in stats.items():
        n = len(rows)
        if n == 0:
            print(f"{m:<7} {0:>7}")
            continue
        non_poor = [bpm for bpm, q in rows if q != "poor" and bpm is not None]
        med = f"{median(non_poor):.1f}" if non_poor else "--"
        pct = {q: 100.0 * sum(1 for _, x in rows if x == q) / n for q in ("good", "fair", "poor")}
        print(f"{m:<7} {n:>7} {med:>22} {pct['good']:>7.1f} {pct['fair']:>7.1f} {pct['poor']:>7.1f}")


def _live_demo() -> int:
    import argparse
    import time
    from pathlib import Path

    from capture import WebcamSource
    from face_roi import FaceROI

    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--method", default=config.DEFAULT_METHOD, choices=list(signal_proc.METHODS),
                    help="method used for the smoothed BPM column")
    ap.add_argument("--save-means", action="store_true",
                    help="write t,R,G,B,face_found for every frame to recordings/<stamp>_means.csv")
    args = ap.parse_args()

    try:
        source = WebcamSource()
    except RuntimeError as e:
        print(f"FAILED: {e}")
        return 1
    face_roi, est = FaceROI(), Estimator(args.method)
    print(f"ROI set: {config.ROI_SET} {config.ROI_SETS[config.ROI_SET]} | smoothed method: {est.method} "
          f"| window {config.WINDOW_SEC:.0f} s, first reading after {config.MIN_SEC:.0f} s")

    stats: dict[str, list[tuple[float | None, str]]] = {m: [] for m in signal_proc.METHODS}
    t_start = next_print = None
    means_file = means_path = None
    if args.save_means:
        means_path = Path(__file__).resolve().parent / "recordings" / f"{time.strftime('%Y%m%d_%H%M%S')}_means.csv"
        means_path.parent.mkdir(exist_ok=True)
        means_file = open(means_path, "w")
        means_file.write("t,R,G,B,face_found\n")
        print(f"Saving means to {means_path}")
    try:
        while True:
            item = source.read()
            if item is None:
                print("Camera read failed")
                return 1
            t, frame = item
            t_start = t if t_start is None else t_start
            if t - t_start > args.seconds:
                break
            sample = face_roi.process(frame, t)
            if means_file is not None:                       # raw per-frame means, before any smoothing
                rgb = ",".join(f"{v:.5f}" for v in sample.rgb) if sample.rgb is not None else ",,"
                means_file.write(f"{t - t_start:.6f},{rgb},{int(sample.face_found)}\n")
            est.push(sample.t, sample.rgb, sample.face_found, sample.relock)
            if next_print is None or t >= next_print:
                next_print = t + config.UPDATE_SEC
                r = est.estimate()
                analyses = est.analyze_all()             # every method on the same buffer
                cols = []
                for m in signal_proc.METHODS:
                    a = analyses.get(m)
                    if analyses:
                        stats[m].append((a.bpm if a else None, a.quality if a else "poor"))
                    cols.append(f"{m} {_fmt(a)}" if analyses else f"{m} {'':<17}")
                smooth = f"{r.bpm_smooth:5.1f}" if r.bpm_smooth is not None else "  -- "
                print(f"t={t - t_start:5.1f}s {r.state:<11} buf={r.buffer_sec:4.1f}s fps={r.fps:4.1f} | "
                      + " | ".join(cols) + f" | smooth({est.method})={smooth}")
    except KeyboardInterrupt:
        pass
    finally:
        source.release()
        if means_file is not None:
            means_file.close()
    if means_path is not None:
        print(f"Means saved: {means_path}")
    _print_summary(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(_live_demo())
