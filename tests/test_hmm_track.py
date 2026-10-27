"""Tests for tools/hmm_track.py (H2). All synthetic, fixed seeds; no recordings needed."""
import itertools
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import hmm_track as H  # noqa: E402

GRID = H.BPM_GRID
REAL_OUT = H.OUT_DIR              # the committed results folder, captured before any test redirects OUT_DIR
PEAK_WIDTH = 2.0       # BPM, roughly the width of a 15 s Hann-windowed peak
DISTRACTOR_BPM = 56.0  # the false low-frequency peak seen near the band edge (issues 4 and 5)


def spectra(truth, distractor_mask=None, true_amp=1.0, distractor_amp=1.6, noise=0.02, seed=0):
    """(T, K) power: a Gaussian peak at each window's true BPM, an optional stronger distractor, a noise floor."""
    rng = np.random.default_rng(seed)
    P = np.zeros((len(truth), len(GRID)))
    for i, b in enumerate(truth):
        P[i] = true_amp * np.exp(-0.5 * ((GRID - b) / PEAK_WIDTH) ** 2)
        if distractor_mask is not None and distractor_mask[i]:
            P[i] += distractor_amp * np.exp(-0.5 * ((GRID - DISTRACTOR_BPM) / PEAK_WIDTH) ** 2)
    return P + noise * rng.random(P.shape)


def test_grid_is_54_to_180_in_1_bpm_steps():
    assert GRID[0] == 54 and GRID[-1] == 180 and len(GRID) == 127 and np.all(np.diff(GRID) == 1)


def test_transition_matrix_rows_sum_to_one_and_peak_on_the_diagonal():
    A = H.transition_matrix()
    assert np.allclose(A.sum(axis=1), 1.0)
    assert np.all(A > 0)                                       # the floor keeps every jump possible
    assert np.all(np.argmax(A, axis=1) == np.arange(len(GRID)))


def test_sigma_is_fixed_at_3_bpm():
    assert H.SIGMA_BPM == 3.0


def test_viterbi_matches_brute_force_on_a_tiny_model():
    rng = np.random.default_rng(1)
    K, T = 4, 5
    grid = np.arange(K, dtype=float)
    A = H.transition_matrix(grid, sigma=1.0, floor=1e-3)
    ll = np.log(rng.random((T, K)) + 0.05)
    best = max(itertools.product(range(K), repeat=T),
               key=lambda p: -np.log(K) + ll[0, p[0]] + sum(np.log(A[p[t - 1], p[t]]) + ll[t, p[t]] for t in range(1, T)))
    assert tuple(H.viterbi(ll, A)) == best


def test_forward_filter_matches_direct_computation_on_a_tiny_model():
    rng = np.random.default_rng(2)
    K, T = 4, 6
    A = H.transition_matrix(np.arange(K, dtype=float), sigma=1.0, floor=1e-3)
    ll = np.log(rng.random((T, K)) + 0.05)
    post = H.forward_filter(ll, A)
    belief = np.full(K, 1.0 / K)
    for t in range(T):
        belief = (belief if t == 0 else belief @ A) * np.exp(ll[t])
        belief /= belief.sum()
        assert np.allclose(post[t], belief)


def test_forward_posteriors_are_distributions():
    post = H.track(spectra(np.full(20, 80.0)))["posterior"]
    assert np.allclose(post.sum(axis=1), 1.0) and np.all(post >= 0)


def test_viterbi_ignores_a_stronger_distractor_that_argmax_follows():
    T = 60
    truth = np.linspace(95, 80, T)
    mask = np.random.default_rng(3).random(T) < 0.30
    P = spectra(truth, mask)
    peak = GRID[np.argmax(P, axis=1)]
    path = H.track(P)["viterbi_bpm"]
    assert mask.sum() >= 10
    assert np.abs(peak - truth).max() > 20                    # per-window argmax is fooled
    assert np.abs(path - truth).max() <= 2.0                  # Viterbi is not


def test_forward_filter_also_stays_near_the_truth_with_the_distractor():
    T = 60
    truth = np.linspace(95, 80, T)
    mask = np.random.default_rng(3).random(T) < 0.30
    fwd = H.track(spectra(truth, mask))["forward_bpm"]
    assert np.abs(fwd[3:] - truth[3:]).max() <= 3.0           # after a few windows of evidence


def test_clean_constant_72_is_recovered_exactly():
    r = H.track(spectra(np.full(40, 72.0)))
    assert np.all(r["viterbi_bpm"] == 72) and np.all(r["forward_bpm"] == 72)


def test_sudden_real_change_is_followed_within_a_few_seconds():
    truth = np.r_[np.full(40, 72.0), np.full(30, 100.0)]       # 72 for 40 s, then 100 held for 30 s
    r = H.track(spectra(truth, seed=5))
    for key in ("viterbi_bpm", "forward_bpm"):
        assert np.all(np.abs(r[key][:40] - 72) <= 1), key
        assert np.all(np.abs(r[key][43:] - 100) <= 1), key     # within 3 s of the change


@pytest.mark.parametrize("make", [
    lambda: np.zeros((30, len(GRID))),
    lambda: np.full((30, len(GRID)), 1e-12),
    lambda: np.ones((30, len(GRID))),
    lambda: np.full((30, len(GRID)), np.nan),
    lambda: np.r_[spectra(np.full(10, 80.0)), np.zeros((5, len(GRID))), np.full((5, len(GRID)), np.nan),
                  spectra(np.full(10, 80.0))],
    lambda: spectra(np.full(1, 80.0)),
])
def test_flat_or_degenerate_spectra_do_not_crash_or_give_nan(make):
    r = H.track(make())
    for k in ("viterbi_bpm", "forward_bpm", "forward_conf", "posterior"):
        assert np.all(np.isfinite(r[k])), k
    assert np.all((r["viterbi_bpm"] >= 54) & (r["viterbi_bpm"] <= 180))
    assert np.allclose(r["posterior"].sum(axis=1), 1.0)


def test_empty_input_returns_empty():
    r = H.track(np.zeros((0, len(GRID))))
    assert len(r["viterbi_bpm"]) == 0 and len(r["forward_bpm"]) == 0


def test_flat_spectrum_gives_low_confidence_and_a_clear_peak_gives_high():
    flat = H.track(np.ones((20, len(GRID))))["forward_conf"][-1]
    clear = H.track(spectra(np.full(20, 80.0)))["forward_conf"][-1]
    assert flat < 0.02                                         # about 1/127 for no evidence at all
    assert clear > 10 * flat                                   # a peak a few bins wide spreads the mass over those bins


# ---------------------------------------------------------------- H3 helpers

def test_auc_perfect_inverted_tied_and_undefined():
    lab = np.array([0, 0, 1, 1], bool)
    assert H.auc(np.array([1, 2, 3, 4]), lab) == 1.0
    assert H.auc(np.array([4, 3, 2, 1]), lab) == 0.0
    assert H.auc(np.ones(4), lab) == 0.5
    assert H.auc(np.array([1, 2, 3, 4]), np.ones(4, bool)) is None


def test_auc_matches_pairwise_definition():
    rng = np.random.default_rng(4)
    s, lab = rng.integers(0, 6, 40).astype(float), rng.random(40) < 0.4
    pairs = [(a > b) + 0.5 * (a == b) for a in s[lab] for b in s[~lab]]
    assert H.auc(s, lab) == pytest.approx(np.mean(pairs))


def test_window_minutes_and_minute_medians_ignore_nan():
    from datetime import datetime
    start = datetime(2026, 10, 21, 23, 6, 50)
    mins = H.window_minutes(start, np.array([5.0, 15.0, 70.0]))
    assert [m.strftime("%H:%M") for m in mins] == ["23:06", "23:07", "23:08"]
    med = H.minute_medians(mins, np.array([90.0, np.nan, 80.0]))
    assert med == {mins[0]: 90.0, mins[2]: 80.0}


def test_reading_mae_skips_minutes_without_a_number():
    from datetime import datetime
    a, b = datetime(2026, 10, 21, 23, 7), datetime(2026, 10, 21, 23, 8)
    mae, n = H.reading_mae([(a, 92.0), (a, 90.0), (b, 80.0)], {a: 91.0})
    assert n == 2 and mae == pytest.approx(1.0)


def test_figure_is_written(tmp_path):
    pytest.importorskip("matplotlib")          # only the figure needs it; a missing package must skip, not fail
    if not (H.OUT_DIR / f"tracks_{H.MAIN_CLIP}_{H.config.DEFAULT_METHOD}.npz").exists():
        pytest.skip("run `python tools/hmm_track.py evaluate` first")
    out = tmp_path / "fig.png"
    H.plot_figure(out)
    assert out.stat().st_size > 10_000


# ---------------------------------------------------------------- gaps: after a reset the windows are not 1 s apart

def test_window_steps_counts_whole_seconds_and_is_never_below_one():
    t = np.array([0.0, 1.0, 2.02, 17.0, 17.4, 18.5])           # differences 1, 1.02, 14.98, 0.4, 1.1
    assert H.window_steps(t).tolist() == [1, 1, 15, 1, 1]


def test_gap_aware_filter_follows_a_rate_change_across_a_gap_at_once():
    truth = np.r_[np.full(20, 80.0), np.full(10, 100.0)]       # 80 BPM, a 15 s gap during which the rate rose, then 100
    t = np.r_[np.arange(20.0), 35.0 + np.arange(10.0)]
    P = spectra(truth, seed=1)
    old = H.track(P)["forward_bpm"]
    new = H.track(P, steps=H.window_steps(t))["forward_bpm"]
    assert abs(new[20] - 100) <= 2                              # the very first window after the gap
    assert abs(old[20] - 100) > 5                               # the one-second assumption is still anchored near 80
    assert np.all(np.abs(new[:20] - 80) <= 1) and np.all(np.abs(new[21:] - 100) <= 1)


def test_steps_of_one_are_the_same_as_no_steps():
    P = spectra(np.linspace(95, 80, 30), np.random.default_rng(3).random(30) < 0.3)
    a, b = H.track(P), H.track(P, steps=np.ones(29, dtype=int))
    assert np.array_equal(a["viterbi_bpm"], b["viterbi_bpm"]) and np.allclose(a["posterior"], b["posterior"])


@pytest.mark.parametrize("bad", [np.ones(3, dtype=int), np.array([1, 0, 1, 1]), np.array([1, -2, 1, 1])])
def test_steps_are_validated(bad):
    with pytest.raises(ValueError):
        H.track(spectra(np.full(5, 80.0)), steps=bad)


def test_transition_across_a_gap_is_a_flatter_distribution():
    A = H.transition_matrix()
    for k in (2, 15, 500):
        Ak = np.linalg.matrix_power(A, k)
        assert np.allclose(Ak.sum(axis=1), 1.0) and np.all(Ak > 0)
    assert np.diag(np.linalg.matrix_power(A, 15)).max() < np.diag(A).min()      # a long gap forgets the old rate


def test_viterbi_and_forward_with_gaps_match_brute_force_on_a_tiny_model():
    rng = np.random.default_rng(6)
    K, T = 4, 5
    A = H.transition_matrix(np.arange(K, dtype=float), sigma=1.0, floor=1e-3)
    steps = np.array([1, 3, 1, 2])
    mats = [np.linalg.matrix_power(A, int(k)) for k in steps]
    ll = np.log(rng.random((T, K)) + 0.05)
    best = max(itertools.product(range(K), repeat=T),
               key=lambda p: -np.log(K) + ll[0, p[0]] + sum(np.log(mats[t - 1][p[t - 1], p[t]]) + ll[t, p[t]] for t in range(1, T)))
    assert tuple(H.viterbi(ll, A, steps)) == best
    post, belief = H.forward_filter(ll, A, steps), np.full(K, 1.0 / K)
    for t in range(T):
        belief = (belief if t == 0 else belief @ mats[t - 1]) * np.exp(ll[t])
        belief /= belief.sum()
        assert np.allclose(post[t], belief)


# ---------------------------------------------------------------- paths and reproducibility

def _results_listing():
    return sorted((p.name, p.stat().st_mtime_ns) for p in REAL_OUT.iterdir()) if REAL_OUT.exists() else None


def _tiny_recordings(tmp_path):
    from test_evaluate import steady, write_clip
    rec = tmp_path / "rec"
    rec.mkdir()
    write_clip(rec, steady(72), seconds=40.0, meta={"ref_bpm": 72})
    return rec


def test_output_paths_are_looked_up_when_called_not_when_imported(tmp_path, monkeypatch):
    rec, out = _tiny_recordings(tmp_path), tmp_path / "out"
    monkeypatch.setattr(H, "RECORDINGS", rec)
    monkeypatch.setattr(H, "OUT_DIR", out)
    before = _results_listing()
    paths = H.export_spectra()
    assert len(paths) == len(H.METHODS) and all(p.parent == out for p in paths)
    assert H.load_spectra("20261021_230706", "CHROM")["power"].shape[1] == len(GRID)
    assert _results_listing() == before                          # the committed results were not touched


def test_command_line_flags_redirect_input_and_output(tmp_path, capsys):
    rec, out = _tiny_recordings(tmp_path), tmp_path / "elsewhere"
    before = _results_listing()
    assert H.main(["export", "--recordings", str(rec), "--out", str(out)]) == 0
    assert len(list(out.glob("spectra_*.npz"))) == len(H.METHODS)
    assert "spectra_20261021_230706_CHROM.npz" in capsys.readouterr().out
    assert _results_listing() == before


def test_evaluate_reproduces_the_committed_results(tmp_path):
    """The whole pipeline from the means CSVs to hmm_results.csv, run in a scratch folder, must equal what is committed."""
    committed = REAL_OUT / "hmm_results.csv"
    clips = [H.RECORDINGS / f"{c}_means.csv" for c in (H.MAIN_CLIP, *H.SECONDARY)]
    if not committed.exists() or not all(p.exists() for p in clips):
        pytest.skip("needs the committed results and the recordings (recordings/ is not in git)")
    rec, out = tmp_path / "rec", tmp_path / "out"
    shutil.copytree(H.RECORDINGS, rec)
    res = H.evaluate_all(rec, out)
    H.write_csv(res, out / "hmm_results.csv")
    assert (out / "hmm_results.csv").read_text().splitlines() == committed.read_text().splitlines()
