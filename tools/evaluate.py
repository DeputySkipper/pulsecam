"""Evaluate recorded clips against their references. Writes results/eval.csv, results/eval_readings.csv and
results/eval_table.md.

    python tools/evaluate.py

Every clip is analysed from its means CSV (not the video: lossy compression can erase the pulse) by running the
same Estimator the app uses, so warm-up, face-loss resets, ROI re-lock matching and the quality labels are the
live ones. Each 15 s window the app computes once per second is kept, per method, with its own quality label.

Two kinds of reference, taken from the clip's meta file:
  * a time-aligned readings file (`ref_readings`, columns minute,bpm): each reading is compared with the app's
    median estimate over the wall-clock minute it belongs to;
  * a single `ref_bpm` for the whole clip (a hand count or a device average), labelled with how far to trust it.
"""
from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import signal_proc  # noqa: E402
from estimator import Estimator  # noqa: E402

METHODS = tuple(signal_proc.METHODS)
GOOD_FAIR = ("good", "fair")
SPLITS = ("good_fair", "poor", "all")
SHIFTS_SEC = (-10, -5, 0, 5, 10)        # clock-offset sensitivity for minute-resolution references


@dataclass
class Clip:
    stamp: str
    start: datetime
    t: np.ndarray
    rgb: np.ndarray
    found: np.ndarray
    relock: np.ndarray
    meta: dict
    directory: Path


@dataclass
class Window:
    t_end: float
    t_center: float
    est: dict            # method -> (bpm or None, snr or None, quality: good | fair | poor | none)


# ---------------------------------------------------------------- loading and replay

def load_clip(means_path: Path) -> Clip | None:
    """None if the clip has no meta file (nothing is known about its reference)."""
    stamp = means_path.name.removesuffix("_means.csv")
    meta_path = means_path.with_name(f"{stamp}_meta.json")
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    d = np.genfromtxt(means_path, delimiter=",", skip_header=1)
    relock = np.zeros(len(d), dtype=bool)
    if d.shape[1] >= 6:
        relock = np.nan_to_num(d[:, 5]) > 0
    else:                                            # older clips: recovered times are in the meta file, if any
        for ft in meta.get("relock_times_sec", []):
            relock[int(np.argmin(np.abs(d[:, 0] - ft)))] = True
    return Clip(stamp=stamp, start=datetime.strptime(stamp, "%Y%m%d_%H%M%S"), t=d[:, 0], rgb=d[:, 1:4],
                found=d[:, 4] > 0, relock=relock, meta=meta, directory=means_path.parent)


def replay(clip: Clip) -> list[Window]:
    """Run the live Estimator over the clip; keep every per-second window for every method."""
    est = Estimator(config.DEFAULT_METHOD)
    windows, tick = [], config.UPDATE_SEC
    for t, rgb, found, relock in zip(clip.t, clip.rgb, clip.found, clip.relock):
        est.push(float(t), None if np.isnan(rgb[0]) else rgb, bool(found), bool(relock))
        while t >= tick:
            snap = est.snapshot()
            if snap is not None:
                analyses = est.analyze_all()
                windows.append(Window(
                    t_end=float(snap[0][-1]), t_center=float((snap[0][0] + snap[0][-1]) / 2),
                    est={m: ((None, None, "none") if a is None else (a.bpm, a.snr_db, a.quality))
                         for m, a in analyses.items()}))
            tick += config.UPDATE_SEC
    return windows


def load_readings(clip: Clip) -> list[tuple[datetime, float]]:
    name = clip.meta.get("ref_readings")
    if not name:
        return []
    with open(clip.directory / name) as f:
        return [(datetime.strptime(r["minute"], "%Y-%m-%d %H:%M"), float(r["bpm"])) for r in csv.DictReader(f)]


def confidence(meta: dict) -> str:
    return config.REF_CONFIDENCE.get(meta.get("device", ""), "unknown")


# ---------------------------------------------------------------- time-aligned references

def minute_medians(clip: Clip, windows: list[Window], shift_sec: float = 0.0) -> dict:
    """{minute: {method: {split: (median bpm or None, windows with an estimate, windows in the split)}}}"""
    out: dict = {}
    for w in windows:
        wall = clip.start + timedelta(seconds=w.t_center + shift_sec)
        minute = wall.replace(second=0, microsecond=0, tzinfo=None)
        for m, (bpm, _, quality) in w.est.items():
            slot = out.setdefault(minute, {}).setdefault(m, {s: [[], 0] for s in SPLITS})
            labels = ["all", "good_fair" if quality in GOOD_FAIR else "poor"]
            for s in labels:
                slot[s][1] += 1
                if bpm is not None:
                    slot[s][0].append(bpm)
    return {mn: {m: {s: (float(np.median(v[0])) if v[0] else None, len(v[0]), v[1]) for s, v in splits.items()}
                 for m, splits in per.items()} for mn, per in out.items()}


def reading_errors(readings, medians) -> list[dict]:
    """One row per reading and method: error (app minus reference) for each split. Readings in a minute the clip
    does not cover are left out."""
    rows = []
    for minute, ref in readings:
        if minute not in medians:
            continue
        for m in METHODS:
            splits = medians[minute].get(m)
            if splits is None:
                continue
            row = {"minute": minute, "ref": ref, "method": m}
            for s in SPLITS:
                med, n, n_all = splits[s]
                row[f"{s}_median"], row[f"{s}_n"] = med, n
                row[f"{s}_error"] = None if med is None else med - ref
            rows.append(row)
    return rows


def mae(rows: list[dict], method: str, split: str) -> tuple[float | None, int]:
    errs = [abs(r[f"{split}_error"]) for r in rows if r["method"] == method and r[f"{split}_error"] is not None]
    return (float(np.mean(errs)) if errs else None), len(errs)


def reading_floor(readings, covered_minutes) -> float | None:
    """The smallest MAE any single number per minute could reach: the readings' own scatter around their median."""
    devs = []
    for minute in covered_minutes:
        vals = [v for mn, v in readings if mn == minute]
        devs += [abs(v - float(np.median(vals))) for v in vals]
    return float(np.mean(devs)) if devs else None


# ---------------------------------------------------------------- single-number references

def clip_row(clip: Clip, windows: list[Window]) -> list[dict]:
    ref = clip.meta.get("ref_bpm")
    rows = []
    for m in METHODS:
        est = [(w.est[m][0], w.est[m][2]) for w in windows]
        nonpoor = [b for b, q in est if q in GOOD_FAIR]
        allb = [b for b, _ in est if b is not None]
        tol = config.EVAL_TOLERANCE_BPM
        med = float(np.median(nonpoor)) if nonpoor else None
        rows.append({
            "clip": clip.stamp, "ref_bpm": ref, "device": clip.meta.get("device", ""), "confidence": confidence(clip.meta),
            "method": m, "windows": len(est), "good_fair_windows": len(nonpoor), "median_good_fair": med,
            "error": None if med is None else med - ref,
            "pct_within_all": 100.0 * np.mean([abs(b - ref) <= tol for b, _ in est if b is not None]) if allb else None,
            "pct_within_good_fair": 100.0 * np.mean([abs(b - ref) <= tol for b in nonpoor]) if nonpoor else None})
    return rows


# ---------------------------------------------------------------- report

def f1(v, signed=False, na="n/a") -> str:
    return na if v is None else (f"{v:+.1f}" if signed else f"{v:.1f}")


def evaluate(directory: Path) -> dict:
    results = {"timed": [], "single": [], "skipped": []}
    for means in sorted(directory.glob("*_means.csv")):
        clip = load_clip(means)
        stamp = means.name.removesuffix("_means.csv")
        if clip is None:
            results["skipped"].append((stamp, "no meta file, so no reference is known"))
            continue
        readings = load_readings(clip)
        has_single = clip.meta.get("ref_bpm") is not None
        if not readings and not has_single:
            results["skipped"].append((stamp, "no reference (no ref_bpm and no readings file)"))
            continue
        windows = replay(clip)
        if readings:
            med = minute_medians(clip, windows)
            rows = reading_errors(readings, med)
            covered = sorted({r["minute"] for r in rows})
            results["timed"].append({
                "clip": clip, "readings": readings, "rows": rows, "medians": med, "covered": covered,
                "skipped_minutes": sorted({mn for mn, _ in readings} - set(covered)),
                "floor": reading_floor(readings, covered),
                "sensitivity": {s: reading_errors(readings, minute_medians(clip, windows, s)) for s in SHIFTS_SEC},
                "windows": windows})
        if has_single:
            results["single"] += clip_row(clip, windows)
    return results


def write_csvs(results: dict, out_dir: Path) -> None:
    out_dir.mkdir(exist_ok=True)
    cols = ["clip", "ref_bpm", "device", "confidence", "method", "windows", "good_fair_windows", "median_good_fair",
            "error", "pct_within_all", "pct_within_good_fair"]
    with open(out_dir / "eval.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results["single"]:
            w.writerow({k: ("" if v is None else (f"{v:.2f}" if isinstance(v, float) else v)) for k, v in r.items()})
    rcols = ["clip", "minute", "ref", "method"] + [f"{s}_{k}" for s in SPLITS for k in ("median", "n", "error")]
    with open(out_dir / "eval_readings.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(rcols)
        for t in results["timed"]:
            for r in t["rows"]:
                w.writerow([t["clip"].stamp, r["minute"].strftime("%Y-%m-%d %H:%M"), r["ref"], r["method"]] + [
                    "" if r[f"{s}_{k}"] is None else (f"{r[f'{s}_{k}']:.2f}" if k != "n" else r[f"{s}_{k}"])
                    for s in SPLITS for k in ("median", "n", "error")])


def markdown(results: dict) -> str:
    L = ["# Evaluation", "",
         f"Generated by `tools/evaluate.py` on {datetime.now():%Y-%m-%d %H:%M}. Analysed from each clip's means CSV with the "
         f"live Estimator (settings now: band {config.BAND_LO}-{config.BAND_HI} Hz, window {config.WINDOW_SEC:.0f} s, ROI set "
         f"`{config.ROI_SET}`, SNR good >= {config.SNR_GOOD_DB} dB, fair >= {config.SNR_FAIR_DB} dB). "
         "Error = app minus reference, in BPM. Methods are GREEN / CHROM (default) / POS.", "",
         "**Reference confidence.** `device` = read from a device (Apple Watch, oximeter). `lower (hand count)` = a pulse "
         "counted by hand over about a minute: good to a few BPM at best, and it hides any change in rate during the count. "
         "Earlier offsets of 6-8 BPM against hand counts (issue 8) were most likely hand-count error, not an estimator bias.", ""]

    for t in results["timed"]:
        clip, rows = t["clip"], t["rows"]
        L += [f"## Clip {clip.stamp}: time-aligned reference ({clip.meta.get('ref_source', clip.meta.get('device', ''))})", "",
              f"Clip starts {clip.start:%H:%M:%S} and lasts {clip.t[-1]:.0f} s. Reference confidence: **{confidence(clip.meta)}**. "
              "Each reading is compared with the app's **median window estimate over the wall-clock minute it belongs to**; "
              "a window is placed in a minute by its centre time. Windows are split by their own quality label: "
              "*good/fair* (shown as a number in the app) vs *poor* (hidden).", ""]
        if t["skipped_minutes"]:
            L += ["Readings in " + ", ".join(m.strftime("%H:%M") for m in t["skipped_minutes"]) +
                  " are not scored: the clip does not cover those minutes.", ""]
        L += ["### App medians per minute", "",
              "| Minute | Watch readings | " + " | ".join(f"{m} good/fair (n) | {m} poor (n)" for m in METHODS) + " |",
              "|---|---|" + "---|---|" * len(METHODS)]
        for minute in t["covered"]:
            vals = [v for mn, v in t["readings"] if mn == minute]
            cells = []
            for m in METHODS:
                gf, po = t["medians"][minute][m]["good_fair"], t["medians"][minute][m]["poor"]
                cells += [f"{f1(gf[0])} ({gf[1]}/{gf[2]})", f"{f1(po[0])} ({po[1]}/{po[2]})"]
            L.append(f"| {minute:%H:%M} | {len(vals)} readings, {min(vals):.0f}-{max(vals):.0f}, median {np.median(vals):.0f} | "
                     + " | ".join(cells) + " |")
        L += ["", "n = windows with an estimate / windows in that split.", "", "### Error per reading", "",
              "Each cell: error vs the app's good/fair median / error vs its poor median.", "",
              "| Minute | Watch | " + " | ".join(METHODS) + " |", "|---|---|" + "---|" * len(METHODS)]
        by_reading: dict = {}
        for r in rows:
            by_reading.setdefault((r["minute"], r["ref"]), {})[r["method"]] = r
        for r0 in sorted((x for x in t["readings"] if x[0] in t["covered"]), key=lambda x: x[0]):   # stable: keeps the order within a minute
            minute, ref = r0
            cells = [f"{f1(by_reading[(minute, ref)][m]['good_fair_error'], True)} / {f1(by_reading[(minute, ref)][m]['poor_error'], True)}"
                     for m in METHODS]
            L.append(f"| {minute:%H:%M} | {ref:.0f} | " + " | ".join(cells) + " |")
        L += ["", "### MAE per method", "",
              "| Method | good/fair windows | poor windows | all windows |", "|---|---|---|---|"]
        for m in METHODS:
            cells = []
            for s in SPLITS:
                v, n = mae(rows, m, s)
                cells.append(f"{f1(v)} (n={n})")
            L.append(f"| {m} | " + " | ".join(cells) + " |")
        L += ["", f"n = readings scored. Floor for a single number per minute (the readings' own scatter around their "
              f"median): **{f1(t['floor'])}** BPM, so an MAE close to that is as good as this reference can show.", "",
              "### Sensitivity to a clock offset between watch and computer", "",
              "The readings carry only the minute, and the two clocks may differ. MAE (good/fair windows) when the app clock "
              "is shifted by the stated number of seconds:", "",
              "| Method | " + " | ".join(f"{s:+d} s" for s in SHIFTS_SEC) + " |", "|---|" + "---|" * len(SHIFTS_SEC)]
        for m in METHODS:
            L.append(f"| {m} | " + " | ".join(f1(mae(t["sensitivity"][s], m, "good_fair")[0]) for s in SHIFTS_SEC) + " |")
        L.append("")

    if results["single"]:
        L += ["## Clips with a single reference number", "",
              "Median of the good/fair window estimates against one number for the whole clip. "
              "**Hand-count references are lower confidence** (see above).", "",
              "| Clip | Reference | Confidence | Method | Good/fair windows | Median (good/fair) | Error | Within +-"
              f"{config.EVAL_TOLERANCE_BPM:.0f}: good/fair windows | Within +-{config.EVAL_TOLERANCE_BPM:.0f}: all windows |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in results["single"]:
            pct = lambda v: "n/a" if v is None else f"{v:.0f}%"
            L.append(f"| {r['clip']} | {r['ref_bpm']:g} ({r['device']}) | {r['confidence']} | {r['method']} | "
                     f"{r['good_fair_windows']}/{r['windows']} | {f1(r['median_good_fair'])} | {f1(r['error'], True)} | "
                     f"{pct(r['pct_within_good_fair'])} | {pct(r['pct_within_all'])} |")
        L.append("")
        for conf in sorted({r["confidence"] for r in results["single"]}):
            per_method = []
            for m in METHODS:
                errs = [abs(r["error"]) for r in results["single"]
                        if r["confidence"] == conf and r["method"] == m and r["error"] is not None]
                per_method.append(f"{m} {f1(float(np.mean(errs)) if errs else None)}")
            n_clips = len({r["clip"] for r in results["single"] if r["confidence"] == conf})
            L += [f"MAE of the median error, {conf} references: " + ", ".join(per_method) + f" (over {n_clips} clips)", ""]

    if results["skipped"]:
        L += ["## Skipped clips", ""] + [f"- `{s}`: {why}" for s, why in results["skipped"]] + [""]
    return "\n".join(L)


def main() -> int:
    results = evaluate(ROOT / config.RECORDINGS_DIR)
    out = ROOT / config.RESULTS_DIR
    write_csvs(results, out)
    (out / "eval_table.md").write_text(markdown(results))
    print((out / "eval_table.md").read_text())
    print(f"\nwrote {out / 'eval_table.md'}, {out / 'eval.csv'}, {out / 'eval_readings.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
