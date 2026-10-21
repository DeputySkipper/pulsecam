# AI extension handoff: heart-rate tracking with an HMM

**For:** Jeet Munshi (B064) · **From:** Vinayak Rastogi (B078) · **Date:** 22 Oct 2026

Give this file to Claude Code together with `README.md`, `docs/PRD.md`, `docs/TRD.md` and `docs/TRACKER.md`. To start a session, say:

> Read docs/AI_HANDOFF.md, README.md and the docs/ folder. Then do phase H0 and stop at its gate.

---

## 1. Where the project stands

PulseCam measures heart rate from an ordinary webcam, without contact (remote photoplethysmography, rPPG). It was built with classical image and video processing for the IVP course and demoed on 22 Oct 2026.

**Pipeline, per second, over the last 15 s of video:**

1. Haar cascade finds the face; the box freezes after 2 s.
2. Mean R, G, B over two cheek regions.
3. Resample to a uniform 30 Hz using real timestamps, then detrend.
4. Chrominance method (CHROM by default; POS and GREEN selectable).
5. Butterworth bandpass, 0.9 to 3.0 Hz (54 to 180 BPM), zero-phase.
6. Hann window and FFT; the tallest in-band peak gives BPM; SNR gives a quality label (good / fair / poor).
7. Smoothing: median of recent estimates, jump rejection, and "--" when the signal stays poor.

**The weakness this task targets:** step 6 picks the tallest peak independently every second. When the pulse is weak, a noise peak can win for a few seconds. In our runs this was often a false peak near 50 BPM. The current fixes are hand-written rules (jump rejection, hold limits). Because of them, the app shows "--" in about 40% of windows even in good conditions.

---

## 2. The task: track heart rate over time with a Hidden Markov Model

Treat the true heart rate as a hidden state that changes smoothly from second to second. Treat each second's spectrum as noisy evidence about it. Then decode the most likely heart-rate path.

This replaces "tallest peak per second, plus rules" with probabilistic reasoning over time (HMMs, the forward algorithm and Viterbi), which is standard AI course material.

### Model

| Part | Specification |
|---|---|
| States | Heart rate on a grid from 54 to 180 BPM, 1 BPM steps (127 states) |
| Prior | Uniform over the grid |
| Emission | The window's in-band power spectrum, interpolated onto the BPM grid and normalised to sum to 1. Log-likelihood = `log(p + 1e-6)` |
| Transition | Gaussian on the change in BPM per 1 s step, **σ = 3 BPM**, plus a small uniform floor (1e-3) so the tracker can re-acquire after losing the pulse. Rows normalised |
| Offline decoding | Viterbi in log space over the whole recording |
| Online decoding | Forward algorithm (filtering), normalised every step; report the argmax and the max posterior probability |

**Fix σ = 3 BPM per second in advance.** Justify it physiologically: a resting or recovering heart rarely changes by more than a few BPM per second. **Do not tune it on the evaluation clip;** with only one device-referenced clip, tuning would make the result circular. You may report sensitivity for σ ∈ {1.5, 3, 6} as analysis, but σ = 3 is the headline.

**Why the online version matters:** Viterbi uses future data, so it can't run live. The forward filter can, so it's the version that could later replace the rules in the app. Its max posterior probability is also a candidate confidence measure to compare against the SNR label.

---

## 3. What's in the repo

### Code you will use (do not modify)

| File | What it gives you |
|---|---|
| `config.py` | Every setting: `BAND_LO` 0.9, `BAND_HI` 3.0, `WINDOW_SEC` 15, `MIN_SEC` 10, `FS` 30, `NFFT` 2048, `DEFAULT_METHOD` "CHROM", `SNR_FAIR_DB` 0.0, `SNR_GOOD_DB` 2.0 |
| `signal_proc.py` | Pure functions: resampling, GREEN / CHROM / POS, bandpass, spectrum, peak, SNR |
| `estimator.py` | `Estimator`: push samples, `estimate()` returns an `HRResult` with `freqs`, `power`, `bpm`, `bpm_smooth`, `snr_db`, `quality`; `set_method()` switches method |
| `tools/evaluate.py` | Replays the live `Estimator` on a means CSV and scores it against references. Watch readings are aligned per wall-clock minute (each 15 s window is placed by its centre time). Writes `results/eval_table.md`, `results/eval.csv`, `results/eval_readings.csv` |
| `tests/` | 114 passing tests (`pytest -q`) |

The webcam, UI and capture code (`app.py`, `capture.py`, `face_roi.py`, `worker.py`, `ui/`) are not needed for this task. No camera is required.

### Data (in `recordings/`)

Each recording has `<stamp>_means.csv` (`t, R, G, B, face_found`, and a `relock` column on newer clips) and usually `<stamp>_meta.json` (settings and reference). The videos were deleted on purpose; the CSVs are all the evaluation needs.

| Clip | Reference | Use |
|---|---|---|
| `20261021_230706` | **Apple Watch**, 19 readings in `20261021_230706_ref_readings.csv` (minute resolution; per-minute medians 92 then 89 BPM). 107 s, recorded after jumping jacks | **Main evaluation clip** |
| `20261021_185356` | Hand count, 90 BPM | Secondary, lower confidence. Clip where the false 50 BPM peak showed up |
| `20261021_215101` | Hand count, 76 BPM | Secondary, lower confidence |
| `20261021_212738` | None (20 s) | Qualitative checks only |
| `20261021_184800`, `20261021_185251` | None reliable | Qualitative checks only |

Clips 185356 and 215101 have no `relock` flags (the videos needed to recover them are gone). Replay them as they are and say so in the write-up.

### Baselines to compare against (clip 230706, from `results/eval_table.md`)

Mean absolute error in BPM against the watch:

| Method | Good/fair windows | Poor windows | All windows |
|---|---|---|---|
| CHROM | 2.3 | 8.1 | 2.9 |
| POS | 2.4 | 12.7 | 4.1 |
| GREEN | 5.2 | 10.0 | 5.4 |

- The watch's own scatter sets a floor of about 1.9 BPM.
- The app shows a number in about 59% of CHROM windows (57 of 97).

**The interesting question for the HMM:** can it give a number in close to 100% of windows with error near the good/fair baseline? That would mean a higher coverage at similar accuracy.

---

## 4. Rules for the coding agent

1. **One phase at a time.** Report against the phase gate, then stop and wait for confirmation.
2. **Don't modify existing code**, in particular `estimator.py`, `signal_proc.py`, `config.py`, `app.py` and `tools/evaluate.py`. The new work goes in new files: `tools/hmm_track.py`, `tests/test_hmm_track.py`, outputs under `results/hmm/`, and a log in `docs/AI_TRACKER.md`.
3. **Approved additions:** `matplotlib` for the figure (add it to `requirements.txt` with a comment that it is only for tools). Anything else needs approval.
4. **Report failures honestly.** If the HMM doesn't beat the baseline, say so with the numbers. Never tune parameters on the evaluation clip, weaken a test, or hide a bad result.
5. **Never run `git commit` or `git push`.** Jeet handles git. End each phase with the suggested `git add` and commit message.
6. **Keep `pytest -q` green.** All 114 existing tests must still pass alongside the new ones.

---

## 5. Phases (about 3.5 hours)

### H0 Setup and reproduce (20 min)

- [ ] Create a venv and install from `requirements.txt` (Python 3.11 or 3.12, see README).
- [ ] `pytest -q`: 114 pass.
- [ ] `python tools/evaluate.py`: confirm the CHROM / POS / GREEN numbers above on clip 230706.

**Gate:** tests pass and the baseline numbers match `results/eval_table.md`.

### H1 Export per-window spectra (30 min)

- [ ] Replay each means CSV through `Estimator` the same way `evaluate.py` does, once per method (`set_method`), so the windowing, re-lock handling and resets match the live app exactly.
- [ ] For every estimate, save: window centre time, raw `bpm`, `bpm_smooth`, `snr_db`, `quality`, and the in-band `power` interpolated onto the 54 to 180 BPM grid.
- [ ] Save to `results/hmm/spectra_<clip>_<method>.npz`.

**Gate:** the argmax of each saved spectrum matches the app's raw `bpm` for that window (within the 1 BPM grid).

### H2 HMM: Viterbi and forward filter (75 min)

- [ ] Implement the model in section 2 in `tools/hmm_track.py`, as pure numpy functions in log space.
- [ ] `tests/test_hmm_track.py`, all synthetic:
  - A true track drifting from 95 to 80 BPM, with a stronger distractor peak at 50 BPM in 30% of windows. Viterbi stays within 2 BPM of the truth; per-window argmax does not.
  - A clean constant 72 BPM track is recovered exactly.
  - A sudden real change (72 to 100 BPM, held for 30 s) is followed within a few seconds.
  - Flat or near-zero spectra don't crash and don't produce NaN.

**Gate:** all tests pass, new and existing.

### H3 Evaluation (45 min)

- [ ] On clip 230706, use the same per-minute alignment as `evaluate.py`. For each method, compare:
  1. **App baseline:** `bpm_smooth` on good/fair windows
  2. Raw per-window peak, all windows
  3. HMM forward filter, all windows
  4. HMM Viterbi, all windows

  Report MAE and coverage (the % of windows that get a number) for each.
- [ ] Check confidence: does the forward filter's max posterior probability separate accurate windows (within ±10 BPM) from inaccurate ones better than SNR does? Report AUC for both.
- [ ] Secondary clips (185356 at 90, 215101 at 76, both lower confidence): % of windows within ±10 BPM for raw peak vs HMM.
- [ ] Sensitivity: rerun with σ = 1.5 and 6 and report, but keep σ = 3 as the headline.
- [ ] Write `results/hmm/hmm_table.md`.

**Gate:** table written, with every number traceable to a script run.

### H4 Figure and write-up (30 min)

- [ ] One figure, `results/hmm/hmm_230706.png`: the spectrogram (time × BPM, colour = normalised power), with the raw peak per window, the app's `bpm_smooth`, the Viterbi track and the watch readings overlaid.
- [ ] A short summary in `docs/AI_TRACKER.md`: method, the headline numbers, and the caveats from section 6, written so it can go straight into the AI course report.

**Gate:** figure saved; summary written.

---

## 6. Caveats to keep in any write-up

- **Small evidence base.** One device-referenced clip from one person, about two minutes. With per-minute alignment, that is effectively two comparison points per method. Present it as a proof of concept, not a general accuracy claim.
- **Viterbi uses the future.** It can't run live. Only the forward filter is a fair comparison with the live app.
- **σ was fixed in advance** and not tuned on the evaluation clip.
- **Hand-count references are lower confidence** than the watch.

---

## 7. Possible follow-ups (each needs Vinayak's approval first)

- **Put the forward filter into the live app** as a display option. This touches `estimator.py`, so wait until the IVP demo is over.
- **More data.**
  - Record more sessions with the app's Record button, which writes the means CSV and meta file.
  - Wear an Apple Watch and add its readings as `<stamp>_ref_readings.csv` in the format described in the README.
  - Several people and several lighting setups would make every result here much stronger.
- **Learned quality classifier.** Once there are several watch-referenced sessions from different people, train a small model (logistic regression or random forest) on per-window features (SNR, agreement between methods, posterior confidence, brightness, re-locks) to predict whether a reading is within ±10 BPM. This isn't worth attempting on the current single clip; it would only memorise it.
