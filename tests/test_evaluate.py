"""tools/evaluate.py on small synthetic clips: minute alignment, error sign, splits, confidence labels."""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import evaluate  # noqa: E402

import config  # noqa: E402
from test_signal_proc import synth  # noqa: E402

START = datetime(2026, 10, 21, 23, 7, 6)          # a clip that starts 6 s into 23:07
STAMP = START.strftime("%Y%m%d_%H%M%S")


def write_clip(directory, rgb_fn, seconds=100.0, meta=None, readings=None, relock_col=False, stamp=STAMP):
    """A synthetic clip on disk: means CSV (with or without the relock column), meta and an optional readings file."""
    t = np.arange(int(seconds * config.FS)) / config.FS
    rgb = rgb_fn(t)
    header = "t,R,G,B,face_found" + (",relock" if relock_col else "") + "\n"
    with open(directory / f"{stamp}_means.csv", "w") as f:
        f.write(header)
        for ti, (r, g, b) in zip(t, rgb):
            f.write(f"{ti:.6f},{r:.5f},{g:.5f},{b:.5f},1" + (",0" if relock_col else "") + "\n")
    m = {"stamp": stamp, "device": "smartwatch", "ref_bpm": None}
    m.update(meta or {})
    if readings is not None:
        with open(directory / f"{stamp}_ref_readings.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["minute", "bpm"])
            w.writerows(readings)
        m["ref_readings"] = f"{stamp}_ref_readings.csv"
    (directory / f"{stamp}_meta.json").write_text(json.dumps(m))
    return t


def steady(bpm, scale=255.0):
    return lambda t: scale * synth(bpm=bpm, seconds=len(t) / config.FS, seed=1)[1]


def stepped(bpm_a, bpm_b, switch_at):
    """72-ish BPM until `switch_at` seconds, then a different rate: a heart rate that changes during the clip."""
    def fn(t):
        a = steady(bpm_a)(t)
        b = steady(bpm_b)(t)
        return np.where((t < switch_at)[:, None], a, b)
    return fn


def test_time_aligned_reading_is_compared_with_the_minute_it_belongs_to(tmp_path):
    # 60 BPM for the first 54 s (= 23:07:06 to 23:08:00), 120 BPM after: the two minutes have different truths
    write_clip(tmp_path, stepped(60, 120, 54.0), seconds=106.0, readings=[("2026-10-21 23:07", 60), ("2026-10-21 23:08", 120)])
    res = evaluate.evaluate(tmp_path)
    t = res["timed"][0]
    assert t["covered"] == [datetime(2026, 10, 21, 23, 7), datetime(2026, 10, 21, 23, 8)]
    chrom = {r["minute"].minute: r for r in t["rows"] if r["method"] == "CHROM"}
    assert abs(chrom[7]["good_fair_error"]) < 3.0 and abs(chrom[8]["good_fair_error"]) < 3.0
    # the same readings, swapped between the minutes, must be badly wrong: alignment is real, not accidental
    write_clip(tmp_path, stepped(60, 120, 54.0), seconds=106.0, readings=[("2026-10-21 23:07", 120), ("2026-10-21 23:08", 60)])
    bad = evaluate.evaluate(tmp_path)["timed"][0]
    assert all(abs(r["good_fair_error"]) > 40 for r in bad["rows"] if r["method"] == "CHROM" and r["good_fair_error"] is not None)


def test_error_is_app_minus_reference(tmp_path):
    write_clip(tmp_path, steady(72), seconds=80.0, readings=[("2026-10-21 23:07", 60)])
    row = next(r for r in evaluate.evaluate(tmp_path)["timed"][0]["rows"] if r["method"] == "CHROM")
    assert 10.0 < row["good_fair_error"] < 14.0               # the app reads 72, the reference says 60: +12


def test_readings_in_minutes_the_clip_does_not_cover_are_not_scored(tmp_path):
    write_clip(tmp_path, steady(72), seconds=60.0, readings=[("2026-10-21 23:07", 72), ("2026-10-21 23:09", 99)])
    t = evaluate.evaluate(tmp_path)["timed"][0]
    assert t["skipped_minutes"] == [datetime(2026, 10, 21, 23, 9)]
    assert {r["ref"] for r in t["rows"]} == {72.0}


def test_mae_and_the_reading_floor(tmp_path):
    write_clip(tmp_path, steady(72), seconds=60.0, readings=[("2026-10-21 23:07", 70), ("2026-10-21 23:07", 74)])
    t = evaluate.evaluate(tmp_path)["timed"][0]
    mae, n = evaluate.mae(t["rows"], "CHROM", "good_fair")
    assert n == 2 and mae == pytest.approx(abs(72 - 70), abs=1.0)
    assert t["floor"] == pytest.approx(2.0)                   # readings 70 and 74 scatter 2 around their median 72


def test_pure_noise_gives_poor_windows_and_no_good_fair_median(tmp_path):
    rng = np.random.default_rng(0)
    write_clip(tmp_path, lambda t: 128 + rng.normal(0, 1.5, (len(t), 3)), seconds=60.0, readings=[("2026-10-21 23:07", 72)])
    t = evaluate.evaluate(tmp_path)["timed"][0]
    mae_gf, n_gf = evaluate.mae(t["rows"], "CHROM", "good_fair")
    mae_poor, n_poor = evaluate.mae(t["rows"], "CHROM", "poor")
    assert n_poor == 1 and n_gf <= 1                          # (a chance fair window is allowed; most are poor)
    md = evaluate.markdown(evaluate.evaluate(tmp_path))
    assert "n/a" in md or n_gf == 1                           # the report handles an empty split instead of crashing


def test_a_clip_clock_offset_is_reflected_in_the_sensitivity_table(tmp_path):
    write_clip(tmp_path, stepped(60, 120, 54.0), seconds=106.0, readings=[("2026-10-21 23:07", 60), ("2026-10-21 23:08", 120)])
    t = evaluate.evaluate(tmp_path)["timed"][0]
    assert set(t["sensitivity"]) == set(evaluate.SHIFTS_SEC)
    at0 = evaluate.mae(t["sensitivity"][0], "CHROM", "good_fair")[0]
    far = evaluate.mae(t["sensitivity"][10], "CHROM", "good_fair")[0]
    assert at0 < 3.0 and far is not None


def test_hand_count_references_are_labelled_lower_confidence(tmp_path):
    write_clip(tmp_path, steady(72), seconds=60.0, meta={"device": "pulse count", "ref_bpm": 90})
    write_clip(tmp_path, steady(72), seconds=60.0, meta={"device": "pulse oximeter", "ref_bpm": 72}, stamp="20261021_120000")
    res = evaluate.evaluate(tmp_path)
    conf = {(r["clip"], r["confidence"]) for r in res["single"]}
    assert (STAMP, "lower (hand count)") in conf and ("20261021_120000", "device") in conf
    md = evaluate.markdown(res)
    assert "Hand-count references are lower confidence" in md and "lower (hand count)" in md
    row = next(r for r in res["single"] if r["clip"] == STAMP and r["method"] == "CHROM")
    assert row["error"] == pytest.approx(72 - 90, abs=1.5)


def test_clips_without_meta_or_reference_are_skipped_with_a_reason(tmp_path):
    write_clip(tmp_path, steady(72), seconds=30.0)                                      # meta but no reference
    write_clip(tmp_path, steady(72), seconds=30.0, stamp="20261021_100000")
    (tmp_path / "20261021_100000_meta.json").unlink()                                   # no meta at all
    skipped = dict(evaluate.evaluate(tmp_path)["skipped"])
    assert "no reference" in skipped[STAMP] and "no meta" in skipped["20261021_100000"]


def test_relock_column_and_recovered_relock_times_are_both_used(tmp_path):
    write_clip(tmp_path, steady(72), seconds=30.0, relock_col=True, meta={"ref_bpm": 72})
    clip = evaluate.load_clip(tmp_path / f"{STAMP}_means.csv")
    assert clip.relock.shape == clip.t.shape and not clip.relock.any()
    stamp2 = "20261021_130000"
    write_clip(tmp_path, steady(72), seconds=30.0, meta={"ref_bpm": 72, "relock_times_sec": [7.3, 9.33]}, stamp=stamp2)
    clip2 = evaluate.load_clip(tmp_path / f"{stamp2}_means.csv")
    assert np.flatnonzero(clip2.relock).tolist() == [int(round(7.3 * 30)), int(round(9.33 * 30))]


def test_replay_reproduces_the_live_estimator_including_the_relock_seam(tmp_path):
    """A level step with its relock flag recovered from the meta file must not hurt SNR; without the flag it does."""
    step = np.array([1.08, 0.94, 1.03])
    def fn(t):
        rgb = steady(72)(t)
        rgb[int(8 * config.FS):] *= step
        return rgb
    write_clip(tmp_path, fn, seconds=25.0, meta={"ref_bpm": 72, "relock_times_sec": [8.0]})
    flagged = evaluate.replay(evaluate.load_clip(tmp_path / f"{STAMP}_means.csv"))
    (tmp_path / f"{STAMP}_meta.json").write_text(json.dumps({"stamp": STAMP, "device": "smartwatch", "ref_bpm": 72}))
    unflagged = evaluate.replay(evaluate.load_clip(tmp_path / f"{STAMP}_means.csv"))
    at_12s = lambda ws: next(w for w in ws if abs(w.t_end - 12.0) < 0.6).est["CHROM"][1]      # a window that contains the 8 s seam
    assert at_12s(flagged) > at_12s(unflagged) + 2.0
