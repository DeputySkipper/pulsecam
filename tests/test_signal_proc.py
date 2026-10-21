"""Synthetic tests for signal_proc and Estimator (TRD section 10). Fixed seeds throughout."""
import numpy as np
import pytest

import config
import signal_proc
from estimator import Estimator

PULSE_DIR = np.array([0.33, 0.77, 0.53])


def synth(bpm=72.0, seconds=10.0, fs=30.0, noise=0.001, seed=0, drift=0.02):
    """Uniformly sampled RGB with a pulse, a linear drift and Gaussian noise (TRD test 1)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * fs)) / fs
    pulse = 0.005 * np.sin(2 * np.pi * (bpm / 60.0) * t)[:, None] * PULSE_DIR
    trend = drift * (t / seconds)[:, None]
    return t, 0.5 + pulse + trend + rng.normal(0, noise, (len(t), 3))


def test_1_green_recovers_72_bpm():
    t, rgb = synth()
    a = signal_proc.analyze(t, rgb, "GREEN")
    assert a is not None
    assert abs(a.bpm - 72.0) <= 1.0


def test_3_irregular_timestamps_and_dropped_frames():
    t, rgb = synth(seed=1)
    rng = np.random.default_rng(2)
    keep = rng.random(len(t)) > 0.10                       # drop 10% of frames
    t_j = t[keep] + rng.uniform(-0.005, 0.005, keep.sum())  # +-5 ms jitter
    order = np.argsort(t_j)
    a = signal_proc.analyze(t_j[order], rgb[keep][order], "GREEN")
    assert a is not None
    assert abs(a.bpm - 72.0) <= 2.0


@pytest.mark.parametrize("bpm", [60.0, 120.0])
def test_4_range(bpm):
    t, rgb = synth(bpm=bpm, seed=3)
    a = signal_proc.analyze(t, rgb, "GREEN")
    assert a is not None
    assert abs(a.bpm - bpm) <= 1.5


def test_4_below_band_floor_is_not_reported():
    """Range is 54-180 BPM (BAND_LO = 0.9 Hz). A 50 BPM pulse must not be reported as 50, nor as a good reading."""
    t, rgb = synth(bpm=50.0, seed=3)
    a = signal_proc.analyze(t, rgb, "GREEN")
    assert a is None or (abs(a.bpm - 50.0) > 1.5 and a.quality != "good")


def test_6_constant_input_returns_none():
    t = np.arange(300) / 30.0
    rgb = np.full((300, 3), 0.5)
    assert signal_proc.analyze(t, rgb, "GREEN") is None


def test_6_near_zero_means_return_none():
    t, rgb = synth()
    rgb[:, 1] = 0.0                                         # dead green channel
    assert signal_proc.analyze(t, rgb, "GREEN") is None
    assert signal_proc.analyze(t, np.zeros_like(rgb), "GREEN") is None


def test_6_too_few_samples_return_none():
    assert signal_proc.analyze(np.array([0.0]), np.array([[0.5, 0.5, 0.5]]), "GREEN") is None
    t, rgb = synth(seconds=0.5)
    assert signal_proc.analyze(t, rgb, "GREEN") is None


def test_estimator_warms_up_then_measures():
    est = Estimator("GREEN")
    t, rgb = synth(seconds=12.0)
    states = []
    for ti, ci in zip(t, rgb):
        est.push(ti, ci, True)
        states.append(est.estimate().state)
    assert states[0] == "warming_up"
    assert states[-1] == "measuring"
    r = est.estimate()
    assert abs(r.bpm - 72.0) <= 1.0
    assert r.buffer_sec <= config.WINDOW_SEC + 1e-9
    assert abs(r.fps - 30.0) < 0.5


def test_estimator_resets_on_face_loss_and_gap():
    est = Estimator("GREEN")
    t, rgb = synth(seconds=config.MIN_SEC + 1.0)
    for ti, ci in zip(t, rgb):
        est.push(ti, ci, True)
    assert est.estimate().state in ("measuring", "poor_signal")
    est.push(t[-1] + 0.03, None, False)
    r = est.estimate()
    assert r.state == "no_face" and r.bpm is None and r.buffer_sec == 0.0
    est.push(t[-1] + 0.06, rgb[-1], True)
    assert est.estimate().state == "warming_up"
    est.push(t[-1] + 0.06 + config.GAP_RESET_SEC + 0.5, rgb[-1], True)   # gap -> buffer restarts
    assert est.buffer_sec == 0.0


def common_mode(t, rgb, amp=0.02, hz=1.0):
    """Intensity change applied equally to all channels, inside the heart-rate band."""
    return rgb * (1.0 + amp * np.sin(2 * np.pi * hz * t))[:, None]


@pytest.mark.parametrize("method", ["POS", "CHROM"])
def test_2_chrominance_methods_reject_common_mode(method):
    t, rgb = synth(seed=4)
    clean = signal_proc.analyze(t, rgb, method)
    noisy = signal_proc.analyze(t, common_mode(t, rgb), method)
    assert clean is not None and abs(clean.bpm - 72.0) <= 1.0
    assert noisy is not None and abs(noisy.bpm - 72.0) <= 1.0


def test_2_green_is_not_immune_to_common_mode():
    """Sanity check that the common-mode test is adversarial: GREEN must be hurt by it."""
    t, rgb = synth(seed=4)
    a = signal_proc.analyze(t, common_mode(t, rgb), "GREEN")
    assert a is None or abs(a.bpm - 72.0) > 1.0


@pytest.mark.parametrize("method", ["GREEN", "CHROM", "POS"])
def test_5_pure_noise_is_not_good(method):
    t, clean = synth(seed=5)
    reference = signal_proc.analyze(t, clean, method)
    for seed in range(10):
        noise = 0.5 + np.random.default_rng(100 + seed).normal(0, 0.005, clean.shape)
        a = signal_proc.analyze(t, noise, method)
        assert a is not None
        assert a.quality != "good", f"seed {seed}: SNR {a.snr_db:.1f} dB classed good"
        assert a.snr_db < reference.snr_db - 3.0, f"seed {seed}: noise SNR {a.snr_db:.1f} vs {reference.snr_db:.1f}"


@pytest.mark.parametrize("method", ["POS", "CHROM"])
def test_6_degenerate_input_returns_none(method):
    t = np.arange(300) / 30.0
    assert signal_proc.analyze(t, np.full((300, 3), 0.5), method) is None
    t, rgb = synth()
    rgb[:, 1] = 0.0
    assert signal_proc.analyze(t, rgb, method) is None


def test_pos_needs_at_least_one_window():
    t, rgb = synth(seconds=1.0)          # shorter than POS_WIN_SEC plus filter padding
    assert signal_proc.analyze(t, rgb, "POS") is None


def feed(est, t, rgb):
    for ti, ci in zip(t, rgb):
        est.push(ti, ci, True)


def test_estimator_default_method_is_chrom_and_set_method_switches():
    est = Estimator()
    assert est.method == config.DEFAULT_METHOD == "CHROM"
    t, rgb = synth(seconds=12.0)
    feed(est, t, rgb)
    assert est.estimate().method == "CHROM"
    est.set_method("GREEN")
    r = est.estimate()
    assert r.method == "GREEN" and abs(r.bpm - 72.0) <= 1.0
    with pytest.raises(ValueError):
        est.set_method("BOGUS")


def test_smoothing_is_median_of_good_estimates_and_held_on_poor():
    est = Estimator("POS")
    t, rgb = synth(seconds=12.0)
    feed(est, t, rgb)
    for _ in range(3):
        good = est.estimate()
    assert good.state == "measuring"
    assert abs(good.bpm_smooth - 72.0) <= 1.0

    # Feed noise and estimate once per UPDATE_SEC. A poor window either holds the previous smoothed value or,
    # once nothing has been accepted for HOLD_MAX_SEC, drops it. It never invents a number.
    noise = 0.5 + np.random.default_rng(7).normal(0, 0.01, rgb.shape)
    t2 = t + t[-1] + 1.0 / config.FS
    step = int(config.UPDATE_SEC * config.FS)
    prev, poor = good, []
    for k, (ti, ci) in enumerate(zip(t2, noise)):
        est.push(ti, ci, True)
        if (k + 1) % step == 0:
            r = est.estimate()
            if r.state == "poor_signal":
                poor.append(r)
                assert r.bpm_smooth is None or r.bpm_smooth == prev.bpm_smooth
            prev = r
    assert poor, "noise never produced a poor_signal window"
    assert any(abs(r.bpm_smooth - 72.0) <= 1.0 for r in poor if r.bpm_smooth is not None), "value was never held"
    assert any(r.bpm_smooth is None for r in poor), "stale value was never dropped"


def run_scripted(monkeypatch, estimates, seconds_per_update=1.0):
    """Estimator driven by scripted (bpm, quality) estimates, advancing sample time between updates."""
    est = Estimator("POS")
    t, rgb = synth(seconds=config.MIN_SEC + 1.0)
    feed(est, t, rgb)
    script = iter(estimates)
    monkeypatch.setattr("estimator.signal_proc.analyze", lambda *a: FakeAnalysis(*next(script)))
    out, now = [], t[-1]
    for _ in estimates:
        for _ in range(int(seconds_per_update * config.FS)):
            now += 1.0 / config.FS
            est.push(now, rgb[-1], True)
        out.append(est.estimate())
    return out


def test_hold_expires_after_hold_max_sec_and_clears_history(monkeypatch):
    n_poor = int(config.HOLD_MAX_SEC) + 3
    seq = [(72, "good")] * 5 + [(60, "poor")] * n_poor + [(100, "fair")] * config.CONFIRM_ESTIMATES
    out = run_scripted(monkeypatch, seq)
    last_accept = out[4].t                                   # the HOLD_MAX_SEC clock runs from the last accepted estimate
    for r in out[5:5 + n_poor]:
        age = r.t - last_accept
        if age < config.HOLD_MAX_SEC - 0.5:
            assert r.bpm_smooth == 72.0, f"dropped too early at age {age:.1f} s"
        elif age > config.HOLD_MAX_SEC + 0.5:
            assert r.bpm_smooth is None, f"still held at age {age:.1f} s"
    assert out[5 + n_poor - 1].bpm_smooth is None
    # History was cleared: a far-away estimate is not jump-rejected, but it must be confirmed like a first number.
    assert out[-config.CONFIRM_ESTIMATES].bpm_smooth is None
    assert out[-1].bpm_smooth == 100.0


def test_stale_value_expires_even_if_rejected_estimates_keep_alternating_with_poor(monkeypatch):
    """Intermittent non-poor windows far from the held value must not keep it alive (jump-rejected, never accepted)."""
    seq = [(72, "good")] * 5 + [(100, "fair"), (60, "poor"), (130, "fair"), (60, "poor")] * 3
    out = run_scripted(monkeypatch, seq)
    assert out[5].bpm_smooth == 72.0                         # held at first
    expired = [r for r in out if r.t - out[4].t > config.HOLD_MAX_SEC + 0.5]
    assert expired and all(r.bpm_smooth != 72.0 for r in expired)    # the stale 72 does not survive
    assert any(r.bpm_smooth is None for r in out[5:])


def test_short_poor_run_is_held_then_recovers(monkeypatch):
    seq = [(72, "good")] * 5 + [(60, "poor")] * 3 + [(74, "fair")]
    smooth = [r.bpm_smooth for r in run_scripted(monkeypatch, seq)]
    assert smooth[5:8] == [72.0] * 3
    assert smooth[8] is not None and abs(smooth[8] - 72.0) <= config.MAX_JUMP_BPM


def test_smoothing_history_cleared_on_face_loss():
    est = Estimator("POS")
    t, rgb = synth(seconds=12.0)
    feed(est, t, rgb)
    for _ in range(config.CONFIRM_ESTIMATES):
        last = est.estimate()
    assert last.bpm_smooth is not None
    est.push(t[-1] + 0.03, None, False)
    assert est.estimate().bpm_smooth is None


def test_roi_means_continue_from_last_box_during_short_detection_miss(monkeypatch):
    """A detection miss shorter than FACE_LOST_SEC must keep producing means from the smoothed box."""
    from face_roi import FaceROI
    frame = np.full((480, 640, 3), (10, 100, 200), np.uint8)
    fr = FaceROI()
    boxes = iter([(200, 100, 200, 250)])
    monkeypatch.setattr(fr, "_detect", lambda f: next(boxes, None))   # one hit, then only misses
    first = fr.process(frame, 0.0)
    assert first.face_found and first.rgb is not None
    t = 0.0
    while t < config.FACE_LOST_SEC - 0.05:
        t += 1.0 / 30.0
        s = fr.process(frame, t)
        assert s.face_found and s.rois == first.rois
        assert np.allclose(s.rgb, (200, 100, 10))
    s = fr.process(frame, config.FACE_LOST_SEC + 0.1)               # beyond the limit: face is lost
    assert not s.face_found and s.rgb is None


class FakeAnalysis:
    """Stand-in for signal_proc.Analysis: only the fields Estimator reads."""
    def __init__(self, bpm, quality="fair"):
        self.bpm, self.quality, self.snr_db = bpm, quality, 0.0
        self.t_sig = self.pulse = self.freqs = self.power = np.zeros(1)
        self.raw = np.zeros((1, 3))
        self.peak_hz = bpm / 60.0


def smoothed_sequence(monkeypatch, estimates):
    """Run an Estimator over a scripted sequence of (bpm, quality) estimates; return bpm_smooth per update."""
    est = Estimator("POS")
    t, rgb = synth(seconds=config.MIN_SEC + 1.0)
    feed(est, t, rgb)
    script = iter(estimates)
    monkeypatch.setattr("estimator.signal_proc.analyze", lambda *a: FakeAnalysis(*next(script)))
    return [est.estimate().bpm_smooth for _ in estimates]


def test_jump_rejection_ignores_short_excursion(monkeypatch):
    seq = [(72, "good")] * 5 + [(50, "fair")] * (config.JUMP_PERSIST - 1) + [(72, "good")] * 3
    out = smoothed_sequence(monkeypatch, seq)
    assert out[:config.CONFIRM_ESTIMATES - 1] == [None] * (config.CONFIRM_ESTIMATES - 1)
    assert out[config.CONFIRM_ESTIMATES - 1:] == [72.0] * (len(seq) - config.CONFIRM_ESTIMATES + 1)


def test_jump_accepted_after_jump_persist_agreeing_updates(monkeypatch):
    seq = [(72, "good")] * 5 + [(110 + i, "fair") for i in range(config.JUMP_PERSIST)]
    out = smoothed_sequence(monkeypatch, seq)
    assert out[config.CONFIRM_ESTIMATES - 1:5] == [72.0] * (5 - config.CONFIRM_ESTIMATES + 1)
    assert out[5:-1] == [72.0] * (config.JUMP_PERSIST - 1)       # held while the jump is unconfirmed
    assert abs(out[-1] - 112.0) < 1e-9                             # median of 110..114


def test_jump_not_accepted_when_candidates_disagree(monkeypatch):
    seq = [(72, "good")] * 5 + [(50, "fair"), (110, "fair")] * config.JUMP_PERSIST
    out = smoothed_sequence(monkeypatch, seq)
    assert out[config.CONFIRM_ESTIMATES - 1:] == [72.0] * (len(seq) - config.CONFIRM_ESTIMATES + 1)


def test_poor_windows_do_not_count_toward_a_jump(monkeypatch):
    n = config.JUMP_PERSIST
    seq = [(72, "good")] * 5 + [(110, "fair")] * (n - 1) + [(110, "poor")] * 3
    out = smoothed_sequence(monkeypatch, seq)
    assert out[config.CONFIRM_ESTIMATES - 1:] == [72.0] * (len(seq) - config.CONFIRM_ESTIMATES + 1)


def test_small_moves_within_max_jump_pass_straight_through(monkeypatch):
    seq = [(72, "good")] * 5 + [(80, "fair")] * 5
    out = smoothed_sequence(monkeypatch, seq)
    assert out[-1] == 80.0


# ---- ROI freeze / re-lock (face_roi) ----

class ScriptedDetector:
    """Replaces FaceROI._detect: returns whatever box is set now (None = miss)."""
    def __init__(self):
        self.box = None

    def __call__(self, frame):
        return self.box


def make_roi(monkeypatch):
    from face_roi import FaceROI
    roi, det = FaceROI(), ScriptedDetector()
    monkeypatch.setattr(roi, "_detect", det)
    return roi, det, np.full((480, 640, 3), (10, 100, 200), np.uint8)


def run_frames(roi, frame, det, t0, seconds, box_fn=None):
    """Process frames at 30 fps; box_fn(t) sets the detection each frame. Returns the list of samples."""
    out, t = [], t0
    while t < t0 + seconds:
        if box_fn:
            det.box = box_fn(t)
        out.append(roi.process(frame, t))
        t += 1.0 / 30.0
    return out


def test_roi_freezes_after_lock_sec_despite_detector_jitter(monkeypatch):
    roi, det, frame = make_roi(monkeypatch)
    rng = np.random.default_rng(0)
    jitter = lambda t: (200 + int(rng.integers(-3, 4)), 100 + int(rng.integers(-3, 4)), 200, 250)
    samples = run_frames(roi, frame, det, 0.0, config.ROI_LOCK_SEC + 3.0, jitter)
    frozen = [s for s in samples if s.t > config.ROI_LOCK_SEC + 0.2]
    assert len({tuple(s.rois) for s in frozen}) == 1           # identical ROIs every frame once frozen
    assert len({tuple(s.rois) for s in samples if s.t < config.ROI_LOCK_SEC - 0.2}) > 1   # EMA moving before


def test_relock_flag_fires_at_lock_start_and_at_freeze(monkeypatch):
    roi, det, frame = make_roi(monkeypatch)
    samples = run_frames(roi, frame, det, 0.0, config.ROI_LOCK_SEC + 2.0, lambda t: (200, 100, 200, 250))
    flagged = [s.t for s in samples if s.relock]
    assert len(flagged) == 2
    assert flagged[0] == 0.0 and abs(flagged[1] - config.ROI_LOCK_SEC) < 0.1


def test_small_face_move_does_not_relock(monkeypatch):
    roi, det, frame = make_roi(monkeypatch)
    run_frames(roi, frame, det, 0.0, config.ROI_LOCK_SEC + 1.0, lambda t: (200, 100, 200, 250))
    small = int(0.5 * config.RELOCK_MOVE_FRAC * 200)
    after = run_frames(roi, frame, det, 3.1, 3.0, lambda t: (200 + small, 100, 200, 250))
    assert not any(s.relock for s in after)


def test_large_face_move_relocks_then_refreezes_at_new_position(monkeypatch):
    roi, det, frame = make_roi(monkeypatch)
    first = run_frames(roi, frame, det, 0.0, config.ROI_LOCK_SEC + 1.0, lambda t: (200, 100, 200, 250))
    big = int(2 * config.RELOCK_MOVE_FRAC * 200)
    after = run_frames(roi, frame, det, 3.1, config.ROI_LOCK_SEC + 3.0, lambda t: (200 + big, 100, 200, 250))
    flagged = [s for s in after if s.relock]
    assert len(flagged) == 2                                    # re-lock, then re-freeze
    assert after[-1].rois != first[-1].rois
    assert len({tuple(s.rois) for s in after if s.t > flagged[1].t + 0.1}) == 1


def test_face_lost_then_found_elsewhere_relocks_without_ema_blend(monkeypatch):
    roi, det, frame = make_roi(monkeypatch)
    run_frames(roi, frame, det, 0.0, config.ROI_LOCK_SEC + 1.0, lambda t: (200, 100, 200, 250))
    gone = run_frames(roi, frame, det, 3.1, config.FACE_LOST_SEC + 0.5, lambda t: None)
    assert not gone[-1].face_found
    back = run_frames(roi, frame, det, 4.8, 0.2, lambda t: (400, 100, 200, 250))
    first = next(x for x in back if x.relock)                    # detection runs every DETECT_EVERY_N frames
    assert first.face_box[0] == 400                              # hard set to the new box, no blend with the old one


def test_freeze_off_keeps_ema_tracking(monkeypatch):
    monkeypatch.setattr(config, "FREEZE_ROI", False)
    roi, det, frame = make_roi(monkeypatch)
    samples = run_frames(roi, frame, det, 0.0, 6.0, lambda t: (200 + int(10 * t), 100, 200, 250))
    assert not any(s.relock for s in samples)
    assert samples[-1].rois != samples[int(4 * 30)].rois


# ---- re-lock: the buffer is kept and the new segment is gain-matched across the seam

STEP = (1.08, 0.94, 1.03)               # per-channel level change when the ROI box jumps


def seam_run(step=None, flags=(8.0,), total=18.0, seed=0, method="CHROM", steps=None, step_at=8.0):
    """Synthetic clip where the ROI changes at each time in `flags`. `steps` maps a flag time to its own gain."""
    t, rgb = synth(seconds=total, seed=seed)
    rgb = rgb.copy()
    gains = steps or ({step_at: step} if step is not None else {})
    for at, g in gains.items():
        rgb[int(at * config.FS):] *= np.array(g)
    est = Estimator(method)
    flag_idx = {int(f * config.FS) for f in flags}
    results = []
    for i, (ti, ci) in enumerate(zip(t, rgb)):
        est.push(ti, ci, True, relock=i in flag_idx)
        if i % int(config.FS) == int(config.FS) - 1 and ti > config.MIN_SEC:
            results.append(est.estimate())
    return est, results


def level_ratio(est, seam_t, span=1.5):
    """Mean buffer level just after the seam over just before it, per channel."""
    buf = list(est._buf)
    pre = np.mean([v for ts, v in buf if seam_t - span <= ts < seam_t], axis=0)
    post = np.mean([v for ts, v in buf if seam_t + 0.2 <= ts < seam_t + 0.2 + span], axis=0)
    return post / pre


def test_relock_keeps_the_buffer_and_the_state():
    est = Estimator("CHROM")
    t, rgb = synth(seconds=config.MIN_SEC + 3.0)
    feed(est, t, rgb)
    before = est.buffer_sec
    est.push(t[-1] + 1 / config.FS, rgb[-1], True, relock=True)
    assert est.buffer_sec > before                          # grew, was not reset
    assert est.estimate().state in ("measuring", "poor_signal")


def test_level_step_is_removed_across_a_relock():
    est, _ = seam_run(step=STEP)
    assert np.allclose(level_ratio(est, 8.0), 1.0, atol=0.004), level_ratio(est, 8.0)


def test_without_matching_the_step_is_really_there():
    """Control: the same step with no re-lock flag stays in the buffer, so the test above is not vacuous."""
    est, _ = seam_run(step=STEP, flags=())
    assert np.allclose(level_ratio(est, 8.0), STEP, atol=0.01)


@pytest.mark.parametrize("method", ["GREEN", "CHROM", "POS"])
def test_matched_step_costs_nothing_but_an_unmatched_one_costs_snr(method):
    clean = seam_run(method=method)[1][-1]
    matched = seam_run(step=STEP, method=method)[1][-1]
    unmatched = seam_run(step=STEP, flags=(), method=method)[1][-1]
    assert abs(matched.bpm - 72.0) <= 1.0 and matched.state == "measuring"
    assert matched.snr_db >= clean.snr_db - 0.5
    assert unmatched.snr_db <= clean.snr_db - 2.0           # a 8% step is a real hit; matching removes it


def test_signal_is_already_continuous_while_the_new_segment_is_still_short():
    est, _ = seam_run(step=STEP, total=8.0 + 0.6)           # stop 0.6 s after the seam, well inside SEAM_MATCH_SEC
    ratio = level_ratio(est, 8.0, span=0.4)
    assert est._seam_pre is not None                        # the match is still provisional
    assert np.allclose(ratio, 1.0, atol=0.02), ratio


def test_lock_start_and_freeze_are_both_matched():
    steps = {8.0: STEP, 10.0: (0.97, 1.04, 0.99)}           # box jumps at the lock start, then settles at the freeze
    est, results = seam_run(flags=(8.0, 10.0), steps=steps, total=20.0)
    assert np.allclose(level_ratio(est, 8.0), 1.0, atol=0.006)
    assert np.allclose(level_ratio(est, 10.0), 1.0, atol=0.006)
    assert all(r.state != "warming_up" for r in results)
    assert abs(results[-1].bpm - 72.0) <= 1.0


def test_a_second_relock_while_the_first_is_still_settling_is_handled():
    est, results = seam_run(flags=(8.0, 8.8), steps={8.0: STEP, 8.8: (1.02, 0.98, 1.0)}, total=18.0)
    assert np.allclose(level_ratio(est, 8.8, span=0.5), 1.0, atol=0.02)
    assert abs(results[-1].bpm - 72.0) <= 1.0


def test_relock_with_no_earlier_data_changes_nothing():
    est = Estimator("CHROM")
    t, rgb = synth(seconds=3.0)
    est.push(t[0], rgb[0], True, relock=True)               # the very first sample: nothing to match against
    for ti, ci in zip(t[1:], rgb[1:]):
        est.push(ti, ci, True)
    assert np.allclose(est._gain, 1.0)
    assert np.allclose([v for _, v in est._buf], rgb)       # buffer holds the raw values


def test_face_loss_and_gaps_forget_the_gain():
    est, _ = seam_run(step=STEP)
    assert not np.allclose(est._gain, 1.0)                  # a seam was matched
    est.push(100.0, None, False)                            # face lost: buffer and gain reset
    assert np.allclose(est._gain, 1.0) and est.buffer_sec == 0.0
    est.push(101.0, np.array([100.0, 90.0, 80.0]), True)
    assert np.allclose(est._buf[-1][1], [100.0, 90.0, 80.0])
