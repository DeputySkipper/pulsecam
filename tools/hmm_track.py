"""HMM heart-rate tracking, extension of PulseCam (see docs/AI_HANDOFF.md).

    python tools/hmm_track.py export     # H1: per-window spectra -> results/hmm/spectra_<clip>_<method>.npz
    python tools/hmm_track.py evaluate   # H3: export, run the HMM, write results/hmm/hmm_table.md and hmm_results.csv
    python tools/hmm_track.py figure     # H4: results/hmm/hmm_230706.png (run `evaluate` first)

H1 replays every means CSV through the live Estimator, once per method, the same way tools/evaluate.py does
(same tick loop, same re-lock handling, same resets), and saves for every per-second window the window centre
time, the raw and smoothed BPM, the SNR, the quality label and the in-band power spectrum interpolated onto a
1 BPM grid.

H2 adds the HMM (pure numpy, log space): the true heart rate is a hidden state on the 54-180 BPM grid, each
window's spectrum is the evidence, the transition is a Gaussian on the BPM change per 1 s step.
  * viterbi(): the most likely path over the whole recording (offline, uses future windows);
  * forward_filter(): the online filtering posterior (what a live display could use).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import signal_proc  # noqa: E402
from estimator import Estimator  # noqa: E402
import evaluate as ev  # noqa: E402

RECORDINGS = ROOT / "recordings"
OUT_DIR = ROOT / "results" / "hmm"
METHODS = tuple(signal_proc.METHODS)

# HMM settings, fixed in advance (docs/AI_HANDOFF.md section 2). SIGMA_BPM is NOT to be tuned on clip 20261021_230706:
# a resting or recovering heart rarely changes by more than a few BPM per second, so 3 BPM per 1 s step.
SIGMA_BPM = 3.0
TRANSITION_FLOOR = 1e-3        # uniform floor added to the (peak = 1) Gaussian before normalising: lets the tracker re-acquire
EMISSION_EPS = 1e-6            # log-likelihood = log(p + EMISSION_EPS)

BPM_STEP = 1.0                                                      # grid spacing of the HMM states
BPM_GRID = np.arange(round(config.BAND_LO * 60), round(config.BAND_HI * 60) + BPM_STEP, BPM_STEP)   # 54..180


# ---------------------------------------------------------------- H1: replay and export

def load_means(means_path: Path) -> dict:
    """t, rgb, found, relock of a means CSV. Re-lock flags come from the sixth column or, for older clips, from
    `relock_times_sec` in the meta file (as in tools/evaluate.py). Clips without a meta file are replayed without."""
    stamp = means_path.name.removesuffix("_means.csv")
    d = np.genfromtxt(means_path, delimiter=",", skip_header=1)
    relock = np.zeros(len(d), dtype=bool)
    if d.shape[1] >= 6:
        relock = np.nan_to_num(d[:, 5]) > 0
    else:
        meta_path = means_path.with_name(f"{stamp}_meta.json")
        if meta_path.exists():
            for ft in json.loads(meta_path.read_text()).get("relock_times_sec", []):
                relock[int(np.argmin(np.abs(d[:, 0] - ft)))] = True
    return {"stamp": stamp, "t": d[:, 0], "rgb": d[:, 1:4], "found": d[:, 4] > 0, "relock": relock}


def spectrum_on_grid(freqs: np.ndarray, power: np.ndarray) -> np.ndarray:
    """In-band power linearly interpolated onto the BPM grid."""
    return np.interp(BPM_GRID, freqs * 60.0, power)


def replay_method(clip: dict, method: str) -> dict:
    """Run a fresh live Estimator for one method over the clip; collect every per-second window that has an
    analysis. The tick loop is the one in tools/evaluate.py, so the windows are the same ones."""
    est = Estimator(method)
    rows, tick = [], config.UPDATE_SEC
    for t, rgb, found, relock in zip(clip["t"], clip["rgb"], clip["found"], clip["relock"]):
        est.push(float(t), None if np.isnan(rgb[0]) else rgb, bool(found), bool(relock))
        while t >= tick:
            snap = est.snapshot()
            if snap is not None:
                r = est.estimate()
                has = r.bpm is not None and len(r.freqs) > 0
                rows.append({
                    "t_center": float((snap[0][0] + snap[0][-1]) / 2), "t_end": float(snap[0][-1]),
                    "bpm": np.nan if r.bpm is None else r.bpm,
                    "bpm_smooth": np.nan if r.bpm_smooth is None else r.bpm_smooth,
                    "snr_db": np.nan if r.snr_db is None else r.snr_db,
                    "quality": r.quality if has else "none",
                    "power": spectrum_on_grid(r.freqs, r.power) if has else np.full(len(BPM_GRID), np.nan)})
            tick += config.UPDATE_SEC
    return {k: (np.array([r[k] for r in rows]) if rows else np.array([])) for k in
            ("t_center", "t_end", "bpm", "bpm_smooth", "snr_db", "quality")} | {
        "power": np.array([r["power"] for r in rows]).reshape(len(rows), len(BPM_GRID))}


def export_spectra(directory: Path = RECORDINGS, out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for means in sorted(directory.glob("*_means.csv")):
        clip = load_means(means)
        for method in METHODS:
            res = replay_method(clip, method)
            path = out_dir / f"spectra_{clip['stamp']}_{method}.npz"
            np.savez(path, clip=clip["stamp"], method=method, bpm_grid=BPM_GRID, **res)
            written.append(path)
    return written


def check_argmax(path: Path) -> dict:
    """H1 gate: the argmax of each saved spectrum against the app's raw bpm for that window."""
    z = np.load(path)
    ok = ~np.isnan(z["bpm"])
    diff = np.abs(z["bpm_grid"][np.argmax(np.nan_to_num(z["power"]), axis=1)] - z["bpm"])[ok]
    ratio = [np.interp(b, z["bpm_grid"], p) / p.max() for b, p in zip(z["bpm"][ok], z["power"][ok])]
    return {"windows": len(z["bpm"]), "with_spectrum": int(ok.sum()),
            "max_diff": float(diff.max()) if len(diff) else 0.0, "over_1": int((diff > 1.0).sum()),
            "min_ratio": float(min(ratio)) if ratio else 1.0}


# ---------------------------------------------------------------- H2: HMM

def log_emission(power: np.ndarray, eps: float = EMISSION_EPS) -> np.ndarray:
    """(T, K) log-likelihoods from (T, K) in-band power. Each row is normalised to sum 1 first. A row that is
    all zero or non-finite carries no evidence and becomes uniform, so it can never produce NaN."""
    p = np.atleast_2d(np.asarray(power, dtype=np.float64)).copy()
    p[~np.isfinite(p)] = 0.0
    p = np.clip(p, 0.0, None)
    tot = p.sum(axis=1, keepdims=True)
    p = np.where(tot > 0, p / np.where(tot > 0, tot, 1.0), 1.0 / p.shape[1])
    return np.log(p + eps)


def transition_matrix(grid: np.ndarray = BPM_GRID, sigma: float = SIGMA_BPM, floor: float = TRANSITION_FLOOR) -> np.ndarray:
    """(K, K) row-stochastic A[i, j] = P(state j next | state i): exp(-d^2 / (2 sigma^2)) + floor, rows normalised,
    d being the BPM change over one 1 s step."""
    d = grid[None, :] - grid[:, None]
    a = np.exp(-0.5 * (d / sigma) ** 2) + floor
    return a / a.sum(axis=1, keepdims=True)


def viterbi(loglik: np.ndarray, trans: np.ndarray) -> np.ndarray:
    """Most likely state-index path for (T, K) log-likelihoods, uniform prior, log space. Returns (T,) ints."""
    T, K = loglik.shape
    if T == 0:
        return np.zeros(0, dtype=int)
    log_a = np.log(trans)
    delta = np.full(K, -np.log(K)) + loglik[0]
    back = np.zeros((T, K), dtype=int)
    for t in range(1, T):
        scores = delta[:, None] + log_a
        back[t] = np.argmax(scores, axis=0)
        delta = scores[back[t], np.arange(K)] + loglik[t]
    path = np.zeros(T, dtype=int)
    path[-1] = int(np.argmax(delta))
    for t in range(T - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path


def forward_filter(loglik: np.ndarray, trans: np.ndarray) -> np.ndarray:
    """Filtering posteriors P(state_t | windows 0..t), shape (T, K), normalised at every step. Uses no future window."""
    T, K = loglik.shape
    post = np.zeros((T, K))
    belief = np.full(K, 1.0 / K)
    for t in range(T):
        pred = belief if t == 0 else belief @ trans
        w = pred * np.exp(loglik[t] - loglik[t].max())          # shifting by the max cancels in the normalisation
        s = w.sum()
        belief = w / s if s > 0 and np.isfinite(s) else np.full(K, 1.0 / K)
        post[t] = belief
    return post


def track(power: np.ndarray, grid: np.ndarray = BPM_GRID, sigma: float = SIGMA_BPM) -> dict:
    """Run both decoders on (T, K) in-band power. Returns the Viterbi BPM path, the forward-filter BPM (argmax of
    the posterior), its max posterior probability, and the posteriors."""
    ll = log_emission(power)
    a = transition_matrix(grid, sigma)
    post = forward_filter(ll, a)
    return {"viterbi_bpm": grid[viterbi(ll, a)], "forward_bpm": grid[np.argmax(post, axis=1)],
            "forward_conf": post.max(axis=1), "posterior": post}


# ---------------------------------------------------------------- H3: evaluation

SIGMAS = (1.5, SIGMA_BPM, 6.0)       # SIGMA_BPM is the headline; the others are sensitivity analysis only
MAIN_CLIP = "20261021_230706"
SECONDARY = {"20261021_185356": 90.0, "20261021_215101": 76.0}      # hand counts: lower confidence
TOL = config.EVAL_TOLERANCE_BPM
GOOD_FAIR = ("good", "fair")


def load_spectra(clip: str, method: str, directory: Path = OUT_DIR) -> dict:
    z = np.load(directory / f"spectra_{clip}_{method}.npz")
    return {k: z[k] for k in z.files}


def auc(score: np.ndarray, label: np.ndarray) -> float | None:
    """Probability that a random positive window scores higher than a random negative one (Mann-Whitney, ties count
    half). None if either class is empty."""
    score, label = np.asarray(score, float), np.asarray(label, bool)
    n1, n0 = int(label.sum()), int((~label).sum())
    if n1 == 0 or n0 == 0:
        return None
    ranks = rankdata(score)
    return float((ranks[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def window_minutes(start: datetime, t_center: np.ndarray) -> list[datetime]:
    """Wall-clock minute of each window, placed by its centre time (as in tools/evaluate.py)."""
    return [(start + timedelta(seconds=float(t))).replace(second=0, microsecond=0) for t in t_center]


def minute_medians(minutes: list[datetime], values: np.ndarray) -> dict:
    """{minute: median of the finite values in that minute}; minutes with no number are absent."""
    out: dict = {}
    for mn, v in zip(minutes, values):
        if np.isfinite(v):
            out.setdefault(mn, []).append(v)
    return {mn: float(np.median(v)) for mn, v in out.items()}


def reading_mae(readings: list, medians: dict) -> tuple[float | None, int]:
    """MAE of (median over the minute - watch reading) over the readings whose minute has a number."""
    errs = [abs(medians[mn] - ref) for mn, ref in readings if mn in medians]
    return (float(np.mean(errs)) if errs else None), len(errs)


def sources(sp: dict, sigma: float) -> tuple[dict, dict]:
    """Per-window BPM series (NaN = no number) for each thing compared, and the HMM tracks."""
    tr = track(sp["power"], sigma=sigma)
    good = np.isin(sp["quality"], GOOD_FAIR)
    nan = np.nan
    series = {
        "App bpm_smooth, good/fair windows": np.where(good, sp["bpm_smooth"], nan),
        "Raw peak, good/fair windows (the evaluate.py baseline)": np.where(good, sp["bpm"], nan),
        "Raw peak, all windows": sp["bpm"],
        "HMM forward filter, all windows": tr["forward_bpm"].astype(float),
        "HMM Viterbi, all windows": tr["viterbi_bpm"].astype(float)}
    return series, tr


def evaluate_main(sigma: float, directory: Path = RECORDINGS) -> dict:
    """Clip 230706 against the watch: per method, MAE and coverage of every source, the per-minute medians, and the
    AUC of the forward filter's max posterior and of the SNR as confidence measures."""
    clip = ev.load_clip(directory / f"{MAIN_CLIP}_means.csv")
    readings = ev.load_readings(clip)
    by_min: dict = {}
    for mn, v in readings:
        by_min.setdefault(mn, []).append(v)
    clip_minutes = set(window_minutes(clip.start, load_spectra(MAIN_CLIP, METHODS[0])["t_center"]))
    ref_med = {mn: float(np.median(v)) for mn, v in by_min.items() if mn in clip_minutes}     # minutes the clip covers
    out = {"floor": None, "methods": {}}
    for method in METHODS:
        sp = load_spectra(MAIN_CLIP, method)
        minutes = window_minutes(clip.start, sp["t_center"])
        series, tr = sources(sp, sigma)
        covered = sorted({mn for mn in minutes if mn in ref_med})
        if out["floor"] is None:
            out["floor"] = ev.reading_floor(readings, covered)
        rows = {}
        for name, s in series.items():
            med = minute_medians(minutes, s)
            m, n = reading_mae(readings, med)
            rows[name] = {"mae": m, "n_readings": n, "windows_with_number": int(np.isfinite(s).sum()),
                          "windows": len(s), "coverage": 100.0 * float(np.isfinite(s).mean()), "minute_medians": med}
        ref = np.array([ref_med.get(mn, np.nan) for mn in minutes])
        use = np.isfinite(ref) & np.isfinite(sp["snr_db"]) & np.isfinite(sp["bpm"])
        fwd_ok = np.abs(tr["forward_bpm"] - ref) <= TOL
        raw_ok = np.abs(sp["bpm"] - ref) <= TOL
        conf = {"posterior -> forward within 10": auc(tr["forward_conf"][use], fwd_ok[use]),
                "SNR -> raw peak within 10": auc(sp["snr_db"][use], raw_ok[use]),
                "SNR -> forward within 10": auc(sp["snr_db"][use], fwd_ok[use]),
                "posterior -> raw peak within 10": auc(tr["forward_conf"][use], raw_ok[use])}
        out["methods"][method] = {
            "rows": rows, "conf_auc": conf, "windows_used": int(use.sum()),
            "forward_ok": int(fwd_ok[use].sum()), "raw_ok": int(raw_ok[use].sum()),
            "ref_median": ref_med, "tracks": {**tr, "t_center": sp["t_center"], "ref": ref}}
    return out


def evaluate_secondary(sigma: float) -> list[dict]:
    """% of windows within +-10 BPM of the hand count, raw peak vs HMM, all windows."""
    rows = []
    for clip, ref in SECONDARY.items():
        for method in METHODS:
            sp = load_spectra(clip, method)
            series, _ = sources(sp, sigma)
            r = {"clip": clip, "ref": ref, "method": method, "windows": len(sp["bpm"])}
            for key, name in (("raw", "Raw peak, all windows"), ("forward", "HMM forward filter, all windows"),
                              ("viterbi", "HMM Viterbi, all windows")):
                s = series[name]
                r[key] = 100.0 * float(np.mean(np.abs(s - ref) <= TOL))      # NaN counts as not within
            rows.append(r)
    return rows


def evaluate_all() -> dict:
    export_spectra()
    res = {"main": {}, "secondary": {}}
    for sigma in SIGMAS:
        res["main"][sigma] = evaluate_main(sigma)
        res["secondary"][sigma] = evaluate_secondary(sigma)
    for method, m in res["main"][SIGMA_BPM]["methods"].items():
        t = m["tracks"]
        np.savez(OUT_DIR / f"tracks_{MAIN_CLIP}_{method}.npz", sigma=SIGMA_BPM, t_center=t["t_center"], ref=t["ref"],
                 viterbi_bpm=t["viterbi_bpm"], forward_bpm=t["forward_bpm"], forward_conf=t["forward_conf"])
    return res


def f1(v, na="n/a") -> str:
    return na if v is None else f"{v:.1f}"


def f2(v, na="n/a") -> str:
    return na if v is None else f"{v:.2f}"


def markdown(res: dict) -> str:
    head = res["main"][SIGMA_BPM]
    L = ["# HMM heart-rate tracking: results", "",
         f"Generated by `python tools/hmm_track.py evaluate` on {datetime.now():%Y-%m-%d %H:%M}. Every number below comes from "
         "that run: it replays the means CSVs through the live Estimator (the H1 export), runs the HMM on the saved "
         "spectra, and scores them. Error = estimate minus reference, in BPM.", "",
         f"**Headline setting: sigma = {SIGMA_BPM:g} BPM per 1 s step, fixed in advance and not tuned on the evaluation clip.** "
         "sigma = 1.5 and 6 are sensitivity analysis only. Transition floor 1e-3, emission `log(p + 1e-6)`, "
         "54-180 BPM grid, uniform prior.", "",
         "**Read this first.** One device-referenced clip from one person (107 s). With per-minute alignment the 19 watch "
         "readings share two app medians, so every MAE below rests on effectively two comparison points per method. "
         "This is a proof of concept, not an accuracy claim. Viterbi uses future windows and cannot run live; only the "
         "forward filter is comparable with the app. Hand-count references are lower confidence than the watch.", "",
         f"## 1. Clip {MAIN_CLIP} against the Apple Watch (sigma = {SIGMA_BPM:g})", "",
         "Each watch reading is compared with the median of a source's per-window numbers over the wall-clock minute it "
         "belongs to (windows placed by centre time, as in `tools/evaluate.py`). Coverage = share of the clip's per-second "
         f"windows that get a number. Floor for one number per minute (the readings' own scatter): **{f1(head['floor'])}** BPM.", ""]
    for method in METHODS:
        m = head["methods"][method]
        L += [f"### {method}", "", "| Source | MAE (BPM) | Readings scored | Coverage | Windows with a number |", "|---|---|---|---|---|"]
        for name, r in m["rows"].items():
            L.append(f"| {name} | {f1(r['mae'])} | {r['n_readings']} | {r['coverage']:.0f}% | {r['windows_with_number']}/{r['windows']} |")
        L += ["", "Per-minute medians (watch median in brackets):", "", "| Source | " + " | ".join(
            f"{mn:%H:%M} ({m['ref_median'][mn]:.0f})" for mn in sorted(m["ref_median"])) + " |",
            "|---|" + "---|" * len(m["ref_median"])]
        for name, r in m["rows"].items():
            L.append(f"| {name} | " + " | ".join(f1(r["minute_medians"].get(mn)) for mn in sorted(m["ref_median"])) + " |")
        L.append("")
    L += [f"## 2. Confidence: AUC for telling accurate windows from inaccurate ones (sigma = {SIGMA_BPM:g})", "",
          f"Label: the window's estimate is within {TOL:g} BPM of the watch median for its minute. AUC 0.5 = no separation, 1.0 = "
          "perfect. The two headline columns score each confidence measure against the estimate it describes (the forward "
          "filter's max posterior against the forward filter's estimate; SNR against the raw peak). The cross columns use "
          "the same label for both measures. Windows are 1 s apart and overlap by 14 s, so they are strongly correlated; "
          "the counts show how lopsided the classes are.", "",
          "| Method | Posterior -> forward | SNR -> raw peak | SNR -> forward | Posterior -> raw peak | Windows | Forward within 10 | Raw within 10 |",
          "|---|---|---|---|---|---|---|---|"]
    for method in METHODS:
        m = head["methods"][method]
        c = m["conf_auc"]
        L.append(f"| {method} | {f2(c['posterior -> forward within 10'])} | {f2(c['SNR -> raw peak within 10'])} | "
                 f"{f2(c['SNR -> forward within 10'])} | {f2(c['posterior -> raw peak within 10'])} | {m['windows_used']} | "
                 f"{m['forward_ok']} | {m['raw_ok']} |")
    L += ["", "n/a = every window is in one class, so AUC is undefined.", "",
          "## 3. Secondary clips (hand counts, lower confidence)", "",
          f"Share of all windows within {TOL:g} BPM of the single hand-count number. Neither clip has re-lock flags (they "
          "were recorded before the column existed), so the replay is approximate. Windows are strongly overlapping.", "",
          "| Clip | Reference | Method | Windows | Raw peak | HMM forward | HMM Viterbi |", "|---|---|---|---|---|---|---|"]
    for r in res["secondary"][SIGMA_BPM]:
        L.append(f"| {r['clip']} | {r['ref']:g} (hand count) | {r['method']} | {r['windows']} | {r['raw']:.0f}% | "
                 f"{r['forward']:.0f}% | {r['viterbi']:.0f}% |")
    L += ["", "## 4. Sensitivity to sigma (analysis only; the headline stays at sigma = 3)", "",
          f"Clip {MAIN_CLIP}, MAE in BPM against the watch (all windows, HMM) and the max-posterior AUC.", "",
          "| Method | sigma | Forward MAE | Viterbi MAE | Posterior -> forward AUC | 185356 forward / Viterbi within 10 | 215101 forward / Viterbi within 10 |",
          "|---|---|---|---|---|---|---|"]
    for method in METHODS:
        for sigma in SIGMAS:
            m = res["main"][sigma]["methods"][method]["rows"]
            sec = {r["clip"]: r for r in res["secondary"][sigma] if r["method"] == method}
            s1, s2 = sec["20261021_185356"], sec["20261021_215101"]
            L.append(f"| {method} | {sigma:g}{' (headline)' if sigma == SIGMA_BPM else ''} | "
                     f"{f1(m['HMM forward filter, all windows']['mae'])} | {f1(m['HMM Viterbi, all windows']['mae'])} | "
                     f"{f2(res['main'][sigma]['methods'][method]['conf_auc']['posterior -> forward within 10'])} | "
                     f"{s1['forward']:.0f}% / {s1['viterbi']:.0f}% | {s2['forward']:.0f}% / {s2['viterbi']:.0f}% |")
    L += ["", "## 5. Notes", "",
          "- Windows with no spectrum would give the HMM no evidence (uniform emission); on these clips every window has a spectrum, and no clip has a gap between windows, so each window is a 1 s step.",
          "- The app baseline row is `bpm_smooth` on good/fair windows, as the handoff specifies. The next row, the raw peak on good/fair windows, is what `tools/evaluate.py` scores (CHROM 2.3, POS 2.4, GREEN 5.2) and is included as a check that this script reproduces it.",
          "- The sigma = 3 forward and Viterbi tracks for the main clip are saved in `results/hmm/tracks_<clip>_<method>.npz` for the H4 figure.",
          "", "Reproduce: `python tools/hmm_track.py evaluate`.", ""]
    return "\n".join(L)


def write_csv(res: dict, path: Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["section", "sigma", "clip", "method", "source", "metric", "value", "n"])
        for sigma, r in res["main"].items():
            for method, m in r["methods"].items():
                for name, row in m["rows"].items():
                    w.writerow(["main", sigma, MAIN_CLIP, method, name, "mae", f2(row["mae"], ""), row["n_readings"]])
                    w.writerow(["main", sigma, MAIN_CLIP, method, name, "coverage_pct", f"{row['coverage']:.1f}", row["windows"]])
                for k, v in m["conf_auc"].items():
                    w.writerow(["confidence", sigma, MAIN_CLIP, method, k, "auc", f2(v, ""), m["windows_used"]])
        for sigma, rows in res["secondary"].items():
            for r in rows:
                for key in ("raw", "forward", "viterbi"):
                    w.writerow(["secondary", sigma, r["clip"], r["method"], key, "pct_within_10", f"{r[key]:.1f}", r["windows"]])


# ---------------------------------------------------------------- H4: figure

def plot_figure(path: Path, method: str = config.DEFAULT_METHOD, directory: Path = RECORDINGS) -> None:
    """Spectrogram of clip 230706 (time x BPM, colour = power normalised to each window's maximum) with the raw peak,
    the app's bpm_smooth, the Viterbi track and the watch readings on top. Needs the files from `evaluate`."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    clip = ev.load_clip(directory / f"{MAIN_CLIP}_means.csv")
    sp = load_spectra(MAIN_CLIP, method)
    tr = np.load(OUT_DIR / f"tracks_{MAIN_CLIP}_{method}.npz")
    t = sp["t_center"]
    P = sp["power"] / np.nanmax(sp["power"], axis=1, keepdims=True)
    dt = float(np.median(np.diff(t)))

    fig, ax = plt.subplots(figsize=(11, 5.6), dpi=150)
    im = ax.imshow(P.T, origin="lower", aspect="auto", cmap="magma", interpolation="nearest",
                   extent=[t[0] - dt / 2, t[-1] + dt / 2, BPM_GRID[0] - BPM_STEP / 2, BPM_GRID[-1] + BPM_STEP / 2])
    ax.plot(t, sp["bpm"], ".", ms=3.5, color="#7fd0ff", label="Raw peak, per window (app, before smoothing)")
    ax.plot(t, sp["bpm_smooth"], "-", lw=1.8, color="#7CFC8A", label="App bpm_smooth (held value)")
    ax.plot(t, tr["viterbi_bpm"], "-", lw=2.2, color="white", label=f"HMM Viterbi (sigma = {float(tr['sigma']):g} BPM)")

    readings = ev.load_readings(clip)
    first = True
    for mn in sorted({mn for mn, _ in readings}):
        vals = [v for m, v in readings if m == mn]
        lo = (mn - clip.start).total_seconds()                     # clip time of the minute's start and end
        x0, x1 = max(lo, t[0]), min(lo + 60, t[-1])
        if x1 <= x0:
            continue                                               # minute not covered by the clip
        ax.fill_between([x0, x1], min(vals), max(vals), color="#ffb000", alpha=0.35, lw=0,
                        label="Apple Watch: range of readings in the minute" if first else None)
        ax.plot([x0, x1], [np.median(vals)] * 2, "--", lw=2, color="#ffb000",
                label="Apple Watch: median of the minute" if first else None)
        first = False

    ax.set_xlim(t[0] - dt / 2, t[-1] + dt / 2)
    ax.set_ylim(BPM_GRID[0], BPM_GRID[-1])
    ax.set_xlabel("Window centre time in the clip (s)")
    ax.set_ylabel("Heart rate (BPM)")
    ax.set_title(f"Clip {MAIN_CLIP}, {method}: per-window spectrum and the tracks decoded from it")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85)
    fig.colorbar(im, ax=ax, pad=0.01).set_label("Power, normalised to the window's maximum")
    fig.text(0.01, 0.005, "Watch readings carry only the minute, so each is drawn as a band across its whole minute. "
             "One clip, one person: a proof of concept.", fontsize=7, color="#555555")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["export", "evaluate", "figure"])
    cmd = ap.parse_args().command
    if cmd == "figure":
        plot_figure(OUT_DIR / f"hmm_{MAIN_CLIP[-6:]}.png")
        print(f"wrote {OUT_DIR / f'hmm_{MAIN_CLIP[-6:]}.png'}")
        return 0
    if cmd == "evaluate":
        res = evaluate_all()
        (OUT_DIR / "hmm_table.md").write_text(markdown(res), encoding="utf-8")
        write_csv(res, OUT_DIR / "hmm_results.csv")
        print(f"wrote {OUT_DIR / 'hmm_table.md'} and {OUT_DIR / 'hmm_results.csv'}")
        return 0
    paths = export_spectra()
    print(f"{'file':54s} {'windows':>7s} {'spectra':>7s} {'max |argmax-bpm|':>17s} {'>1 BPM':>6s} {'min P(bpm)/Pmax':>15s}")
    for p in paths:
        c = check_argmax(p)
        print(f"{p.name:54s} {c['windows']:7d} {c['with_spectrum']:7d} {c['max_diff']:17.3f} {c['over_1']:6d} {c['min_ratio']:15.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
