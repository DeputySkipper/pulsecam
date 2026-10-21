# TRACKER: PulseCam build

**Demo:** Thu 22 Oct 2026 · **Build budget:** 8 hours · **Start time:** ________

The goal is a basic project with a clean UI and solid processing. Feature count is not the goal. When time runs short, cut scope, not quality.

---

## Instructions for the coding agent (Claude Code)

Read `PRD.md` and `TRD.md` before writing any code. Then follow these rules:

1. **One phase at a time, in order.** At the end of each phase, report against its gate and **stop and wait for confirmation** before starting the next phase.
2. **Respect the timebox.** If a phase is about to overrun, stop and say so, and propose the matching cut from "Cut triggers" instead of pushing on.
3. **No scope creep.** Build Must items only, unless the team explicitly approves a Should or Could item. No features, dependencies or files beyond `TRD.md` without asking.
4. **Report failures honestly.** If something does not work (a failing test, an unsupported camera property, a BPM far off the reference), say exactly what failed and what you tried. Never hardcode a BPM, fake output, or weaken a test to make it pass.
5. **Never run `git commit` or `git push`.** The team handles git. At the end of each phase, list suggested git commands (files to add and a commit message) for them to run.
6. **Verify your own work** where you can: run `pytest -q` at test gates and `python tools/check_capture.py` for camera checks. If you cannot access a camera, say so and hand the live check to the team.
7. **Keep this file current:** tick checkboxes, fill in Status and Actual, and add entries to the Decisions and Issues logs.
8. **Config-driven:** every tunable lives in `config.py`. No magic numbers in modules.

---

## Status overview

Legend: ☐ not started · ◐ in progress · ☑ done · ✂ cut

| Phase | Timebox | Track | Status | Actual |
|---|---|---|---|---|
| P0 Setup and contracts | 0:20 | Both | ☑ | about 0:05 (agent time) |
| P1 Capture and face ROI | 1:00 | A (signal) | ☑ | about 0:10 (agent time) |
| P2 Signal core and tests | 1:30 | A (signal) | ☑ plumbing PASS; live accuracy deferred to P3 | about 0:15 (agent time) |
| P3 POS, CHROM, quality | 1:00 | A (signal) | ☑ live accuracy confirmed against an Apple Watch (see P5/P6 live gate); the literal 3 x 30 s POS checks were not run in that form | about 0:15 + 0:30 tuning + 0:30 ROI-lock pass (agent time) |
| P4 Dashboard UI (on MockSource) | 2:00 | B (UI), parallel with P1 to P3 | ☑ gate met; the demo-laptop fullscreen look is the team's to confirm (not stated as done) | about 1:00 (agent time) |
| P5 Integration, offline mode, recording | 1:00 | Both | ☑ gate met: live check against an Apple Watch, CHROM MAE 2.3 BPM on good/fair windows (clip 20261021_230706) | about 2:00 (agent time) |
| P6 Evaluation and demo prep | 1:00 | Both | ◐ evaluate.py, results table, README and slides done; known gap: 1 device-referenced clip, not 3; screen recording and rehearsal are the team's and not confirmed to me | about 1:00 (agent time) |
| Buffer | 0:10 | | | |
| **Total** | **8:00** sequential, about **6:00** wall-clock with two people | | | |

With two people: after P0, one person drives Track A (P1 to P3) while the other drives Track B (P4 against `MockSource`). Both join for P5 and P6.

---

## Phase details

### P0 Setup and contracts (0:20) · Both

- [x] Create venv and `requirements.txt` (TRD §1); install
- [x] Create the folder structure (TRD §2) and `.gitignore` (`.venv/`, `recordings/`, `debug/`, `__pycache__/`)
- [x] `config.py` with every default (TRD §7)
- [x] `models.py` with `FrameSample` and `HRResult` (TRD §4)
- [x] `MockSource` emitting `FrameSample`s at 30 Hz (TRD §6), so UI work can start immediately

**Gate:** `python -c "import cv2, PySide6, pyqtgraph, scipy"` succeeds; models import; MockSource emits samples at about 30 Hz.

### P1 Capture and face ROI (1:00) · Track A · M1, M2, M3

- [x] `WebcamSource` with real timestamps and measured FPS
- [x] Camera lock attempt (best effort, 15 minutes max, log the result)
- [x] Haar detection every N frames, largest face, EMA box smoothing
- [x] Forehead and cheek ROIs; mean RGB in R, G, B order; overlays drawn on the preview copy only
- [x] `FileSource` with timestamps from the file
- [x] `tools/check_capture.py`: runs 10 s, prints measured FPS, % of frames with a face and the std of the G trace, saves 3 annotated snapshots to `debug/`

**Gate:** FPS printed; face found in ≥ 90% of frames for a still subject; snapshots show ROIs on the forehead and cheeks; the G trace is not flat.

### P2 Signal core and tests (1:30) · Track A · M4, M5 (GREEN)

- [x] Ring buffer with gap reset and measured FPS
- [x] Resample (`np.interp`), normalise, detrend, Butterworth `sosfiltfilt`
- [x] GREEN method
- [x] Hann window, zero-padded FFT, in-band peak search, parabolic interpolation
- [x] SNR and quality classification
- [x] `Estimator` producing an `HRResult` every `UPDATE_SEC`, with states
- [x] Tests 1, 3, 4, 6 from TRD §10 pass
- [x] Console demo: live webcam prints BPM and SNR every second

**Gate:** `pytest -q` is green; the live console BPM is within ±15 of the reference for a still subject in good light (rough check; P3 tightens it).

### P3 POS, CHROM, quality (1:00) · Track A · M5 (POS), M6, S1

- [x] POS (TRD §5.3) · **Must**
- [x] CHROM · **Should**, only if P2 finished on time
- [x] Median smoothing over the last K estimates; poor-signal handling
- [x] Runtime method switch (`Estimator.set_method`)
- [x] Tests 2 and 5 pass

**Gate:** tests green; live POS within ±10 BPM of the reference on 3 consecutive 30 s checks, logged in the results table below.

### P4 Dashboard UI (2:00) · Track B, against MockSource · M7, M8

- [x] `theme.py` tokens and stylesheet (TRD §8)
- [x] Main window layout: video on the left; BPM panel and plots on the right; controls row
- [x] BPM panel: large number, state line, quality dot, stats row
- [x] Pulse waveform plot; spectrum plot with peak line
- [x] Light frame: white border, toggle, **default OFF** (S8, demoted from M8)
- [x] Start/Stop, Method dropdown, Source (Webcam / File)
- [x] Text and plots refresh at most every 100 ms; video every frame
- [x] Fullscreen toggle

**Gate:** runs 10 minutes on MockSource without freezing; the displayed BPM matches the mock's BPM; the light frame toggles; it looks clean fullscreen on the demo laptop.

### P5 Integration, offline mode, recording (1:00) · Both · M9, S3, S4 logger

- [x] Swap MockSource for the real `CaptureWorker` in the UI
- [x] File source wired into the UI (offline mode)
- [x] Record button: means CSV always, plus lossless video if available (TRD §9) · **Should**
- [x] Reference BPM field and Log button to `results/readings.csv` · **Should**

**Gate:** the live app shows BPM within ±10 of the reference; a recorded clip plays through offline mode; a 10-minute run is stable.

### P6 Evaluation and demo prep (1:00) · Both · M10, S4

- [ ] Record at least 3 clips of 60 s (still subject, good light, reference reading for each). If time allows, one more with the light frame off for comparison. **NOT MET (known gap):** one device-referenced clip (107 s, Apple Watch) plus two hand-count clips; no more device-referenced clips tonight
- [x] `tools/evaluate.py` writes `results/eval_table.md` with MAE per method · **Should** (fallback: fill the table by hand from `readings.csv`)
- [x] Tune the SNR thresholds on the recordings; log the final values in Decisions (final values `SNR_FAIR_DB = 0.0`, `SNR_GOOD_DB = +2.0` in D37; on the Apple Watch clip the labels separate good from bad windows, so they stay unchanged; code freeze)
- [ ] Screen-record the app working live: warm-up, reading, method switch, spectrum (OBS, Win+G, or Cmd+Shift+5 on macOS) (the team's own recording, kept outside the project; not confirmed to me)
- [x] Slides: problem, physics, pipeline diagram, methods, UI screenshot, results table, limitations (built separately, outside the repo, per the team)
- [ ] One full rehearsal using the demo-day checklist (the team's; not confirmed to me)

**Gate:** backup recording saved in two places; results table filled in; rehearsal done.

**Gate status:** results table filled in (`results/eval_table.md`). Backup recording in two places and the rehearsal are the team's and not confirmed to me.

---

## Cut triggers

| Checkpoint | If | Then |
|---|---|---|
| P1 | Camera lock not working after 15 min | Drop it. Rely on detrending and POS |
| End of P2 | Tests not green | Stop adding features; fix only. Drop CHROM and the skin mask |
| End of P3 | POS not within ±10 BPM live | Ship GREEN and POS as they are and present it honestly as a limitation; spend the time on the lighting setup instead |
| End of P4 / start of P5 | UI not ready to integrate | Drop Record and the Logger; keep video, BPM, waveform, spectrum and light frame |
| Mid P6 | `evaluate.py` not done | Fill the results table by hand from logged readings |
| Always | | **Never cut:** the backup screen recording, the fixed lighting setup (phone torch on a stand), the honest results slide |

---

## Live results log

| # | Phase | Method | Light frame | Ref BPM | App BPM | Error | SNR (dB) | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | P3 run A | GREEN | n/a (UI not built) | 87 | 57.4 | 29.6 | n/a | ROI all, window 10 s, MIN_SEC 8. Right cheek shadowed. Median over run |
| 2 | P3 run A | CHROM | n/a | 87 | 71.0 | 16.0 | n/a | as run A. FAIL |
| 3 | P3 run A | POS | n/a | 87 | 51.0 | 36.0 | n/a | as run A. FAIL |
| 4 | P3 run B | GREEN | n/a | 85 | 54.5 | 30.5 | n/a | ROI cheeks, window 15 s, MIN_SEC 10. Tubelight in front and above, both cheeks evenly lit. Median over run |
| 5 | P3 run B | CHROM | n/a | 85 | 78.9 | 6.1 | n/a | as run B. Within ±10 on median. When CHROM and POS agree in the last 20 s they read 85-89 |
| 6 | P3 run B | POS | n/a | 85 | 77.0 | 8.0 | n/a | as run B. Within ±10 on median. Estimate flips to a 49-56 BPM competitor peak for 3-5 updates at a time. Run B changed ROI, window and lighting together, so the cause of the improvement is not isolated. Gate as written (3 consecutive 30 s checks) not run in that form; reference by pulse count |
| 7 | P3 re-check | GREEN | n/a | [not given] | 50.2 | n/a | n/a | New defaults (cheeks, 15 s, new thresholds, jump rejection), before ROI freeze. All methods locked onto a 49-56 BPM peak. FPS drifted 30 -> 29.1 (room darker than run B). FAIL |
| 8 | P3 re-check | CHROM | n/a | [not given] | 53.6 | n/a | n/a | as above |
| 9 | P3 re-check | POS | n/a | [not given] | 51.5 | n/a | n/a | as above. 84% of windows poor. smooth(POS) held 59.1 for 27 s, then 49.5 |
| 10 | ROI-lock run (agent, 60 s) | GREEN | n/a | none | 51.0 | n/a | n/a | FREEZE_ROI on, cheeks, 15 s. Medians over non-poor windows. 89% poor, 2% good |
| 11 | ROI-lock run (agent, 60 s) | CHROM | n/a | none | 64.2 | n/a | n/a | 64% poor, 36% fair |
| 12 | ROI-lock run (agent, 60 s) | POS | n/a | none | 64.3 | n/a | n/a | 75% poor, 26% fair. No reference device during this run, so no error. Saved as recordings/20261021_184800_means.csv |
| 13 | P3 phone-torch run (60 s) | GREEN | n/a (phone torch, hand-held, in front) | 90 | 82.8 | 7.2 | +3 to +5 (34-42 s) | recordings/20261021_185356_means.csv. cheeks, FREEZE_ROI on, sat close. Ref = 60 s pulse count 89-92, used 90. Live medians |
| 14 | P3 phone-torch run (60 s) | CHROM | as above | 90 | 81.1 | 8.9 | as above | Within ±10. 34-42 s all three methods agreed at 83-88 BPM |
| 15 | P3 phone-torch run (60 s) | POS | as above | 90 | 84.1 | 5.9 | as above | Within ±10. Earlier white-screen attempt was poor throughout; overhead tubelight alone failed (runs A and C) |
| 16 | P6 Apple Watch clip 20261021_230706 (107 s) | GREEN | n/a (torch on stand, head rested) | watch 86-96 (median 92 at 23:07, 89 at 23:08) | good/fair medians 90.4 / 82.0 | MAE 5.2 (19 readings) | n/a | Poor-window MAE 10.0; all-window 5.4. See eval_table.md |
| 17 | P6 Apple Watch clip 20261021_230706 | CHROM | as above | as above | good/fair medians 90.8 / 87.4 | MAE 2.3 (floor 1.9) | as above | Poor-window MAE 8.1; all-window 2.9. 57 of 97 windows good/fair |
| 18 | P6 Apple Watch clip 20261021_230706 | POS | as above | as above | good/fair medians 90.7 / 87.4 | MAE 2.4 | as above | Poor-window MAE 12.7; all-window 4.1 |
| 19 | P6 hand-count clip 20261021_215101 (64 s) | CHROM | n/a | 76 (pulse count: lower confidence) | 84.8 | +8.8 | n/a | GREEN +8.9, POS +8.7. Opposite sign to the 90 clip (-7.0): hand-count error |

### Offline sweep on recordings/20261021_185356_means.csv (ref 90, 15 s windows stepped 1 s, 43 windows, face found, after the ROI freeze)

Windows overlap, so the 43 windows are only about 3-4 independent segments: read as indicative. One clip, one subject, ref 90 BPM (far from the 49-56 BPM artefact zone, so the cost of a higher `BAND_LO` on slow heart rates is not tested).

| BAND_LO | Method | Median BPM | Error vs 90 | % windows within ±10 |
|---|---|---|---|---|
| 0.7 | GREEN | 82.6 | -7.4 | 51% |
| 0.7 | CHROM | 82.3 | -7.7 | 65% |
| 0.7 | POS | 81.6 | -8.4 | 47% |
| 0.8 | GREEN | 82.9 | -7.1 | 58% |
| 0.8 | CHROM | 82.7 | -7.3 | 74% |
| 0.8 | POS | 83.4 | -6.6 | 67% |
| 0.9 | GREEN | 83.1 | -6.9 | 74% |
| 0.9 | CHROM | 84.1 | -5.9 | 95% |
| 0.9 | POS | 83.4 | -6.6 | 67% |

All methods and all `BAND_LO` values sit 6-8 BPM below the 60 s count, while agreeing with each other (83-88 BPM at high SNR). The synthetic estimator bias is under 0.3 BPM. Either the pulse count (+-a few BPM by hand) or the true rate drifted over the minute; this clip cannot tell which. A pulse oximeter or watch would.

SNR vs ground truth (windows within ±10 of 90 = ok, otherwise wrong). Share of ok / wrong windows kept at each threshold, and precision:

| BAND_LO | Method | AUC | SNR >= -1 dB (current FAIR) | SNR >= 0 dB | SNR >= +2 dB (current GOOD) |
|---|---|---|---|---|---|
| 0.7 | GREEN | 0.60 | 86% / 52%, precision 63% | 41% / 33%, 56% | 0% / 19%, 0% |
| 0.7 | CHROM | 0.50 | 39% / 47%, 61% | 32% / 27%, 69% | 25% / 0%, 100% |
| 0.7 | POS | 0.69 | 45% / 9%, 82% | 40% / 0%, 100% | 35% / 0%, 100% |
| 0.9 | GREEN | 0.87 | 88% / 36%, 88% | 72% / 18%, 92% | 66% / 0%, 100% |
| 0.9 | CHROM | 0.45 (only 2 wrong windows) | 51% / 100%, 91% | 39% / 0%, 100% | 22% / 0%, 100% |
| 0.9 | POS | 0.73 | 69% / 21%, 87% | 45% / 14%, 87% | 28% / 0%, 100% |

At `BAND_LO = 0.7`, SNR_FAIR_DB = -1.0 does not separate right from wrong for GREEN or CHROM (AUC 0.50-0.60). At 0.9 it separates GREEN and POS reasonably. `SNR_GOOD_DB = +2.0` held up in every case where a window reached it: no wrong window scored +2 or more, apart from GREEN at 0.7 (4 wrong windows). Suggestion, not applied: `SNR_FAIR_DB = 0.0` (above the white-noise p99 of -0.5 dB and the best fair/precision trade in the table), `SNR_GOOD_DB` unchanged at +2.0. Defaults for `BAND_LO` and the thresholds are unchanged pending the team's choice.

### P4 gate evidence (agent, offscreen, real timers, MockSource scenario cycle)

10-minute run: 18,728 frames = 31.2 fps (PRD target >= 25); `_on_sample` mean 1.10 ms, p99 1.68 ms; event-loop heartbeat lateness p99 23 ms, max 43 ms (no freeze); memory 287 -> 296 MB (+8.5 MB, flat after warm-up); displayed BPM matched the mock's 72 in all 385 checks while measuring. Not tested: the real display / GPU path and the demo laptop's fullscreen look.

### P5 gate evidence (agent; no reference device, so no accuracy claim)

- **10-minute run, real webcam through `CaptureWorker` and the full window** (offscreen): 17,928 frames = 29.9 fps; event-loop heartbeat p99 24 ms, max 69 ms (no freeze); threads 1 -> 1 after stop (none leaked); one 20 s recording mid-run and one stop/start restart at 5 min, both clean. Peak RSS 497 MB, then 670 MB after the recording and flat for the remaining 8 minutes (the figure is a high-water mark, so this is the recording queue's one-time peak, not growth). The subject was in front intermittently, so states varied; readings of 72-86 BPM appeared when settled, none checkable.
- **Offline mode:** the recorded clip plays through the real window and worker in real time (20.1 s for a 20.0 s clip), ends with "End of file: press Start to replay" and keeps the last result on screen.
- **Recording:** 600 frames in 19.95 s (30.02 fps measured), video header fps 29.98 (error under 0.2%), lossless FFV1, no warnings, largest inter-frame gap 55-58 ms (was 330 ms before the encoder moved to its own thread).
- **Replay vs live means:** on a 24 s clip, replay with the live timestamps agreed on 100% of face-found flags and on every frame after the first face loss (median difference 0.0). The first stretch (frames 0-138) differed because the live ROI had been locked for 3 s before Record was pressed. See TRD §9.
- **Time to first reading (clean signal, mock through the real Estimator):** first displayed number 14.0-14.9 s after the face appears (12.0-12.9 s before the 3-estimate confirmation).
- **Not verified:** the live +-10 BPM check against a reference, and the demo laptop.

### P5/P6 live gate result (team)

Live check with the torch on a stand and an Apple Watch as the reference: clip `20261021_230706` (107 s, 23:07:06-23:08:53, 19 watch readings scored over 23:07-23:08). **CHROM MAE 2.3 BPM on good/fair windows** (POS 2.4, GREEN 5.2), against a floor of 1.9 BPM set by the readings' own scatter; per-minute medians within 1.2-1.6 BPM of the watch median for CHROM and POS. The PRD target (MAE <= 5 BPM, at least 3 clips of 60 s) is met on this clip but **not in the form written**: only one device-referenced clip exists (known gap, issue 16). Full numbers: `results/eval_table.md`.

## Decisions log

| # | Decision | Reason |
|---|---|---|
| D1 | Topic switched from football analysis to rPPG | Football scope too large for the timeline. Needs faculty approval |
| D2 | Haar cascade for the face, not MediaPipe | Ships with OpenCV, no extra install, pure classical IVP. EMA smoothing handles jitter. MediaPipe is stretch C2 |
| D3 | PySide6 + pyqtgraph for the UI | Real-time plots and full control of the layout and light frame |
| D4 | `opencv-python-headless` | Avoids a Qt clash with PySide6 |
| D5 | POS as the default method, GREEN as baseline | **Default superseded by D36 (CHROM).** POS is the most robust classical method to lighting and intensity changes |
| D6 | Band 0.7 to 3.0 Hz | **Superseded by D35.** Resting heart rate 42 to 180 BPM; a narrower band means less noise. Widen to 4.0 Hz if the subject has just exercised |
| D7 | Evaluate from the means CSV, not re-decoded video | Lossy video compression can erase the pulse signal |
| D8 | Project root is `IVP Proj/` itself; PRD/TRD/TRACKER stay in the root instead of `docs/` | Avoids moving files the team already references. Move later if wanted |
| D9 | venv uses Python 3.12 (Homebrew); system `python3` is 3.9 and too old | TRD §1 requires 3.11 or 3.12. Run with `.venv/bin/python` |
| D10 | Extra tunables added to `config.py` (ROI fractions, Haar params, preview width, mock params) | Rule 8: no magic numbers in modules. Values are the TRD defaults |
| D11 | `opencv-python-headless>=4.9,<5` | OpenCV 5.0 no longer ships the Haar cascade XMLs, which D2 relies on. 4.14 does |
| D12 | `TRY_LOCK_CAMERA = False` on macOS | Camera lock attempted: AVFoundation reports (0,0) before and after setting auto-exposure/WB, so the driver ignores it. Rely on detrending and POS |
| D13 | Skin mask (S2) not built; `USE_SKIN_MASK = False` | Should item, not approved. ROI means use all pixels |
| D14 | Added `pytest.ini` (`pythonpath = .`) | Lets tests import root modules without a conftest hack |
| D15 | Console demo lives in `estimator.py` (`python estimator.py`), not a new tools file | TRD §2 lists no console tool; avoids an extra file |
| D16 | `ROI_SET` (`all` / `cheeks`) in config, `ROI_SETS` maps names to ROIs | Requested by team to compare forehead+cheeks vs cheeks only. Console demo prints the active set |
| D17 | P2 `bpm_smooth` is always None; median smoothing and `set_method` stay in P3 | Per phase scope. `test_estimator_rejects_unimplemented_method` must be replaced in P3 when POS lands |
| D18 | Center Stage OFF (and Studio Light / Portrait / background effects OFF) during measurement | Center Stage crops and re-frames the video, moving the face region. G std 3.95 with it off vs 5.18 with it on (team measurement) |
| D19 | CHROM built in P3 | P2 finished on time; Should item approved by the team ("CHROM if on time") |
| D20 | P2 gate logged as: plumbing PASS, live accuracy deferred to P3 | Live GREEN was unusable (BPM 47-122, SNR mostly -7 to -1 dB), consistent with the 0.97 R/G/B correlation, i.e. common-mode noise that GREEN cannot remove. No reference device yet. Cheeks-vs-all ROI comparison deferred to POS |
| D21 | Smoothing history (last `SMOOTH_K` non-poor BPMs) is cleared on face loss, a sample gap, and `set_method` | A median across a reset or across methods would mix unrelated estimates. Jump rejection (Should) not built |
| D22 | Console demo computes every method on the same buffer each update and prints a per-method summary at the end | Team request: direct GREEN / CHROM / POS comparison on identical data |
| D23 | New defaults: `ROI_SET = "cheeks"`, `WINDOW_SEC = 15`, `MIN_SEC = 10` | Team live run B (cheeks, 15 s) got CHROM/POS within ±10 BPM on median. Time to first reading is now 10 s (PRD target is ≤ 10 s, acceptable ≤ 15 s) |
| D24 | `SNR_HALF_WIDTH_HZ` 0.10 -> 0.15 | Hann main-lobe half-width is about 2/T = 0.13 Hz at 15 s; 0.1 cut off part of the real peak |
| D25 | `SNR_FAIR_DB` -4.0 -> -1.0, `SNR_GOOD_DB` 0.0 -> +2.0 | White-noise SNR, 15 s window, 0.15 Hz half-width, 500 seeds per method: p95 GREEN -1.51, CHROM -1.44, POS -1.78 dB; max 1.06 / 1.36 / -0.20. Fair set just above the worst p95 (-1.44, rounded up to -1.0), good = fair + 3 dB. Noise is labelled fair 2.8 / 3.4 / 1.2 % and never good. Clean 72 BPM reads 19.0 / 9.6 / 9.4 dB. White noise is the best case: real low-frequency motion and exposure noise is peakier, so retune on real clips in P6 |
| D26 | Jump rejection (TRD §5.6) with `JUMP_PERSIST = 5`. A candidate counts toward a jump only if each held-back estimate is within `MAX_JUMP_BPM` of the previous one; poor windows are skipped, not counted. On acceptance the history is replaced by the agreeing run | "Persists" read as persisting at a similar value, otherwise a wandering noise peak could eventually be accepted. Cost: a real change in heart rate takes about 5 updates (5 s) to show |
| D27 | Cheek ROI y-range stays at (0.50, 0.70) | Team checked snapshots: both cheek boxes sit on bare skin above the beard line. The optional move to (0.40, 0.55) is not needed |
| D28 | `FREEZE_ROI = True`: detect and EMA-smooth for `ROI_LOCK_SEC = 2` s, then freeze the box. While frozen, a fresh detection is compared with the box every `RELOCK_CHECK_SEC = 1` s; a centre move above `RELOCK_MOVE_FRAC = 8%` of box width, or a lost face, starts a new lock | Hypothesis: ROI jitter from re-detection and EMA smoothing becomes low-frequency noise. Frozen segments have exactly 0.00 px centre jitter (live check) |
| D29 | **Superseded by D49 (a re-lock no longer resets the buffer).** `FrameSample.relock: bool = False` added to the contract; `Estimator.push(..., relock)` reset the buffer and smoothing history when it was True. The flag fires at lock start and again at freeze | Re-lock must reset the buffer, and the buffer cannot otherwise know the ROI moved. Cost: the first reading arrives about 2 s later (about 12 s after the face appears) |
| D30 | `HOLD_MAX_SEC = 5`: poor quality for more than 5 s makes `bpm_smooth` None and clears the smoothing and jump-rejection history | A stale or wrong value must not stick (smooth(POS) previously held 59.1 for 27 s) |
| D31 | `estimator.py --save-means` pulled forward from P5: writes `recordings/<stamp>_means.csv` (`t,R,G,B,face_found`, one row per frame, blank RGB when no face, t relative to the first frame) | Re-analyse runs offline with different settings. The file does not record `ROI_SET` / `FREEZE_ROI`; note them when you record |
| D32 | `tools/check_capture.py` also prints box-centre std (after the first 3 s) and, with the freeze on, the freeze times and the max centre std inside a frozen segment | Centre std across the whole run includes jumps between locks, so it is not a jitter measure on its own |
| D33 | Re-lock needs `RELOCK_CONFIRM_CHECKS = 2` consecutive 1 s checks that both see a move beyond `RELOCK_MOVE_FRAC` and agree with each other (within the same limit); a check back inside the limit clears the run | Issue 6: one outlier detection (seen jumping 173 px) must not trigger a re-lock and buffer reset. Cost: a real move re-locks about 1 s later |
| D34 | Lighting is the dominant factor for signal quality | Same pipeline: overhead tubelight alone failed (runs A and C), a white screen as the light source was poor throughout, a phone torch in front gave all three methods within ±10 BPM of the reference (errors 7.2 / 8.9 / 5.9) and SNR +3 to +5 dB when they agreed. Demo plan must control light before anything else |

| D35 | `BAND_LO = 0.9` (54-180 BPM). PRD now states "range 54-180 BPM, resting adults" as a limitation | Offline sweep on the ground-truth clip (ref 90): % windows within ±10 rose with `BAND_LO` for every method (CHROM 65% -> 74% -> 95% at 0.7 / 0.8 / 0.9). Cost: heart rates below 54 BPM cannot be measured. Narrower band also raises white-noise SNR (p99 now +0.24 dB pooled) |
| D36 | `DEFAULT_METHOD = "CHROM"`; POS and GREEN stay selectable | Best % within ±10 at every `BAND_LO` on the ground-truth clip. One clip, one subject: revisit with P6 recordings |
| D37 | `SNR_FAIR_DB = 0.0`, `SNR_GOOD_DB = +2.0` | Offline SNR-vs-ground-truth analysis. With the 0.9 band, white noise reads fair-or-better in 1.1 / 2.8 / 1.1 % of windows (GREEN / CHROM / POS) and good in 0.00 / 0.25 / 0.15 % (2000 seeds each) |
| D38 | Light frame demoted from M8 (Must) to S8 (Should), default OFF (`LIGHT_FRAME_DEFAULT = False`). When off the dashboard has no margin | A white screen alone gave poor signal throughout; a fixed phone torch is the lighting plan (D34). Departure from TRD §8: margins only exist while the frame is on, so the default layout uses the whole window |
| D39 | `HOLD_MAX_SEC` clock runs from the last estimate accepted into the history, not from the start of a poor run (refines D30) | The mock showed a 10-second-old value surviving a poor stretch: intermittent noise windows reading "fair" reset a poor-run timer while jump rejection kept rejecting them. For an uninterrupted poor stretch the behaviour is identical to D30 |
| D40 | P4 UI choices: system sans-serif font (no missing-font fallback); Source dropdown lists Mock / Webcam / File... with the last two disabled until P5; Start is explicit (window opens stopped, "Press Start"); keys L (light frame), F (fullscreen), Esc (leave fullscreen); peak marker hidden on a poor window; BPM number in a fixed-width box; `LOW_LIGHT_LEVEL = 70` (mean ROI RGB, 0-255) is a placeholder | Keeps P4 to the listed items. L / F / Esc are the minimum for the light-frame and fullscreen toggles, not the S7 shortcut set |
| D41 | MockSource cycles measuring (30 s: 10 s warm-up, then readings) -> dim (8 s) -> poor (14 s) -> no_face (4 s), on the 0-255 camera scale, with `relock` flags at face start and 2 s later like FaceROI. The poor phase is 22 equal in-band tones with random per-channel directions; `--steady` gives a clean 72 BPM | Exercises every UI state through the real Estimator. White noise and four tones were tried first: noise read fair in 1-3% of windows and a few tones read as a clean pulse after projection (a strong periodic interferer scores like a pulse, issue 3) |

| D42 | `CaptureWorker` (QThread: source -> FaceROI -> `FrameSample` signal) drives webcam and file sources; files are paced to real time; the window defaults to the webcam (`--mock` / `--steady` for the mock). The Source dropdown offers Mock / Webcam / File...; File... opens a file dialog (cancel returns to the previous source); the source cannot change while running. A finished file keeps its last result on screen | TRD §3, M9. Signals are disconnected before the worker is stopped so late frames cannot repaint a stopped window |
| D43 | New files beyond TRD §2, approved by scope: `recorder.py` (Recorder, meta helpers, reading logger; no Qt) and `tools/ui_shots.py` (writes `debug/shots/`) | The recorder needed a Qt-free home so it can be tested and used from the capture thread; the screenshot tool is item 4 of the P5 brief |
| D44 | Video encoding runs on its own thread behind a queue; the video header fps is measured over the first 90 frames (`RECORD_FPS_PROBE_FRAMES`) | Measured live: with encoding on the capture thread, opening the writer and flushing the 30 probe frames stalled capture for 0.33 s at the start of every recording. A 30-frame probe also mis-set the header fps by 4% (one 55 ms hiccup), which would make offline playback read 4% low; 90 frames gives under 1% |
| D45 | `<stamp>_meta.json` (settings, config snapshot, reference fields, frames, fps, codec, warnings) replaces the separate `_ref.json` of TRD §9. The reference fields can be typed during or after recording and are written into that clip's meta file | Team request: P6 evaluation must know what each clip used |
| D46 | First displayed number needs `CONFIRM_ESTIMATES = 3` consecutive non-poor estimates within `CONFIRM_AGREE_BPM = 5` BPM, at warm-up and after a stale clear; a poor window breaks the run. Time to first number was 14.0-14.9 s on a clean signal (12.0-12.9 s before) while a re-lock restarted the warm-up; with D49 it is 12.0-12.9 s again | Issue 10: a noise window scoring fair must not become the displayed number. Cost: about 2 s, and the 15 s acceptable limit now has almost no margin |
| D47 | `LOW_LIGHT_LEVEL = 120` (provisional) and the live ROI brightness shown as "Light n" in the stats row | Tubelight runs (about 107) were unstable or failed, torch (about 156) passed. Mock base brightness raised to about 161 so the normal and dim phases straddle the threshold |
| D48 | Recording is available only for the running live webcam (the mock and files have no frames to record); the status line reports saves, logs and errors; the window says "Starting..." before the first estimate | Keeps Record honest about what it writes |

| D49 | **Supersedes D29.** A re-lock no longer resets the buffer (`SEAM_MATCH_SEC = 2.0`, `SEAM_MIN_SEC = 0.5`): `Estimator` keeps the buffer and gain-matches the new ROI segment per channel to the last 2 s before the seam, provisionally while the segment is short and finally after 2 s. `RELOCK_MOVE_FRAC` stays 0.08. The warm-up counter is now x/10 (the lock phase is part of the buffer), and a re-lock no longer restarts it | Issue 11 decision. Measured on synthetic data: an 8% per-channel step costs about 5 dB SNR unmatched and nothing matched; even a 2% step costs about 3 dB. On the real 20 s clip (two re-locks) the old reset gave no estimate at all; now the first estimate arrives at 10.0 s. Matching uses 2 s windows because a short window's partial-cycle bias is as large as the pulse. Face loss and sample gaps still reset |

| D50 | The means CSV gains a sixth column, `relock` (1 on a ROI lock start or freeze). For `20261021_230706`, recorded before the column existed, the re-lock times (7.3, 9.33, 57.6, 59.6 s) were recovered by replaying the lossless video with the live timestamps and stored in its meta file (`relock_times_sec`) | D49 made the estimator depend on the re-lock flags, so a CSV without them cannot reproduce what the app did live. The replay matched the live means on every frame from 7.3 s, so the recovered times are the live ones from there on (the first 7.3 s depend on ROI state from before Record was pressed) |
| D51 | `tools/evaluate.py` replays each clip through the live Estimator and writes `results/eval.csv`, `results/eval_readings.csv`, `results/eval_table.md`. Time-aligned references are scored per reading against the app's median over the wall-clock minute (windows placed by centre time), split by each window's own good/fair/poor label, with the readings' scatter as an MAE floor and a +-10 s clock-offset sensitivity check | P6 item 1. Watch readings are stored with the clip as `<stamp>_ref_readings.csv` (minute, bpm) |
| D52 | Single-number references carry a confidence by device (`config.REF_CONFIDENCE`): a hand count is `lower (hand count)` and is labelled so in `eval_table.md`. `20261021_185356` (hand count 90) got a retroactive meta file; `20261021_215101` (hand count 76) keeps its `device` field at the default `pulse count`, so it is treated as a hand count | P6 item 2 |

| D53 | `20261021_215101`'s reference (76) was a hand count: kept as lower confidence (D52). **Code freeze on signal processing until after the demo** | Team instruction |
| D54 | `README.md` written (setup, run, offline mode, controls, demo setup, evaluation). `tools/ui_shots.py --dashboard` saves a steady 72 BPM dashboard shot to `debug/shots/dashboard.png` for slides | P6 remainder. `debug/` is gitignored, so the README links to the screenshot by path instead of embedding it |

| D55 | P5/P6 live gate logged as met on clip `20261021_230706`: CHROM MAE 2.3 BPM on good/fair windows against an Apple Watch. **Known gap, accepted:** no more device-referenced clips tonight, so the evidence is one 107 s clip (plus two hand-count clips, lower confidence) | Team instruction. The slides and the results slide should say "one clip" |
| D56 | **Cleanup.** The re-lock flags for `20261021_230706` were written into its means CSV (`relock` column; the original five columns verified unchanged) and removed from its meta. Then all videos in `recordings/` (3, 1,437.8 MB), everything in `debug/` (12 files), my scratchpad screenshots and clips (11 files) and the clips my test runs left in the pytest temp folder (42 files) were moved to the macOS Trash: 68 files, 1,453 MB. A 3.4 KB scratch file used to test the Trash mechanism, and 14 test clips that a later pytest run regenerated, were trashed too: 83 files in all, about 1.36 GiB, plus two emptied folders (`debug/shots`, scratchpad `shots`). Running the test suite regenerates small synthetic clips in pytest's temp folder (pytest deletes them after three runs). Kept: means CSVs, meta files, reference readings, `results/` (including `readings.csv`, the app's live Log output from the 215101 session), `docs/`, code, and the team's two Apple Health screenshots in the session temp folder (not made during the build). `evaluate.py` output was identical before and after (diffed), and all 114 tests pass with the files gone | Team instruction. `evaluate.py` never read a video. Supersedes the earlier "keep the offline test clip 20261021_212738" instruction: no test read it, and the team asked to remove every video. Its means CSV and meta are kept. The README now says to record a clip to try offline mode |

## Issues log

| # | Issue | Status | Resolution |
|---|---|---|---|
| 1 | Forehead ROI lands on eyebrows/hairline when hair covers the forehead (seen in P1 snapshots) | open | Demo checklist: hair off the forehead. Revisit ROI fractions in P6 if it hurts SNR |
| 2 | Face lost for long stretches in live runs (98% found in the P1 run, 59% in the 15 s baseline, repeated `no_face` resets in the console demos). Each loss > FACE_LOST_SEC (1 s) resets the buffer, so a BPM may never appear | open | Not changed (team asked for report only). Candidates: raise `FACE_LOST_SEC`, lower `minNeighbors`, check subject posture / lighting |
| 4 | Estimate flips to a 49-56 BPM competitor peak (low-frequency motion / exposure noise) for 3-5 updates at a time (P3 run B) | mitigated, not verified live | Jump rejection (D26) holds the smoothed value through such runs. Needs a live re-check; the raw per-window BPM will still flip |
| 5 | Live re-check FAILED: with cheeks, 15 s, new thresholds and jump rejection, medians GREEN 50.2 / CHROM 53.6 / POS 51.5 (reference value not supplied), POS 84% poor. All methods lock onto a 49-56 BPM peak. Offline re-analysis of an agent recording (FREEZE_ROI on): 37-49% of GREEN/POS windows peak below 50 BPM (the band edge) and 15-27% of in-band power sits in 0.7-0.9 Hz, which is 9% of the band width. With `BAND_LO = 0.9` offline, no window peaks below 54 BPM, but the three methods then disagree (medians 72.0 / 84.1 / 67.2), so this removes the artefact without showing the heart rate is found | addressed by D35 (`BAND_LO = 0.9`); re-check in P6 | Consistent with the low-frequency-hump hypothesis, not a fix. Next: record a clip with a known reference, then compare `BAND_LO` values offline. A higher `BAND_LO` excludes resting rates below 54 BPM |
| 6 | One raw Haar detection jumped 173 px in a 20 s run (typical step 1.4 px, p95 4.9 px). If such an outlier lands on the 1 s re-lock check it triggers a false re-lock and a buffer reset | fixed | D33: two consecutive agreeing checks. Tested with a mutation check; live smoke test re-locked once after a real move |
| 7 | Time to first reading is 12.0-12.9 s on a clean signal (10 s `MIN_SEC` + 2 s to confirm the first number), above the 10 s PRD target, inside the 15 s acceptable limit | open | Option: `CONFIRM_ESTIMATES` 2 would give 11-12 s |
| 3 | SNR is not a correctness check, and the `fair` band overlaps pure noise. Synthetic: GREEN under in-band common-mode noise reads 60.4 BPM (true 72) at +5.7 dB "good". Pure Gaussian noise gives SNR -6.2 to -1.2 dB (10 seeds, all methods), while `fair` is -4 to 0 dB | partly addressed | `fair` no longer overlaps white noise (D25). On the Apple Watch clip the labels separate good from bad windows: CHROM MAE 2.3 on good/fair windows vs 8.1 on poor ones. A wrong but dominant peak can still read good, so SNR still cannot confirm correctness. Retune on real recordings in P6 |

| 8 | 6-8 BPM bias: on the ground-truth clip every method and every `BAND_LO` read 82-84 against a 60 s pulse count of 90 (synthetic bias under 0.3 BPM) | **resolved: hand-count error** | Against an Apple Watch (clip `20261021_230706`, 19 readings over 23:07-23:08), good/fair windows give MAE 2.3 (CHROM) / 2.4 (POS) / 5.2 (GREEN), against a floor of 1.9 set by the readings' own scatter; per-minute medians are within 1.2-1.6 BPM of the watch median for CHROM and POS, and the app followed the change in rate between the two minutes. A second hand-count clip (`20261021_215101`, count 76) reads +8.8, the opposite sign to the first (-7.0), which an estimator bias cannot do. A residual of about -1 to -2 BPM in CHROM/POS is inside the watch's own accuracy. Hand counts are marked lower confidence in `eval_table.md`
| 9 | `LOW_LIGHT_LEVEL = 70` is a guess: the metric is mean ROI brightness in camera pixel values, and the camera's auto-exposure may brighten a dim scene, so it may never fire (or fire at the wrong time). Seen so far: tubelight run about 107, phone torch about 156 | open | Calibrate on the demo laptop in P5/P6: note the value with the room light only and with the torch |
| 10 | After the hold limit clears a stale value, the next non-poor window was adopted immediately, so a noise window scoring fair (about 1-3% of white-noise windows) could show a number | fixed | D46: three consecutive agreeing non-poor estimates are needed |

| 11 | The ROI re-lock threshold (8% of box width = 16 px) trips on ordinary head sway, and each confirmed re-lock reset the buffer, so a 10 s buffer could not fill (clean 20 s clip, face found 100%, centre moved 50 px, two re-locks: no estimate possible) | **fixed by D49** | Threshold kept at 0.08. The buffer is kept and level-matched across the seam. Verified on a synthetic clip with the real clip's ROI events: first estimate 10.0-10.9 s, first number 12.0-12.9 s (old behaviour: never). **Not confirmed on real data**: the clip has no usable signal (issue 15)
| 12 | A head turn, looking away, laughing or talking loses the frontal Haar detector (70% face found, five lost stretches of up to 2.7 s in a 24 s test clip where the subject turned and laughed) | known limitation | Software behaved correctly (confirmed on the frames). Demo checklist already says still and silent; add: face the camera |
| 13 | Lossless video is about 420 MB per minute (141 MB for 20 s at 640x480). Three 60 s clips in P6 take about 1.3 GB | open | Check free disk before P6. The means CSV, which evaluation uses, is a few tens of KB |
| 14 | Offline replay of a video does not reproduce the live means exactly (ROI lock depends on time and on state from before the clip started) | documented | TRD §9. Evaluate from the means CSV (D7) |

| 15 | The offline test clip (`recordings/20261021_212738`, 20 s, face found 100%; its video was removed in the cleanup, D56, the means CSV and meta remain) has no usable signal: every window is poor (CHROM 93-97 BPM at -2 to -4.2 dB, GREEN about 70 BPM at -3 to +0.9 dB, POS jumping 63-117 BPM), so no number is displayed. Brightness rose from 124 to 180 during the clip (camera auto-exposure still settling after start). Gain-matching changed mean SNR by 0.1 dB (-3.39 matched vs -3.51 unmatched) | open | The clip proves offline mode and the re-lock handling, not accuracy. The live check needs the torch on its stand and a settled camera (let it run 10-15 s before measuring) |

| 16 | The first device-referenced result rests on one clip: 107 s, two wall-clock minutes (so the 19 readings share two app medians), a still subject with the torch on a stand and the head rested. About 40% of CHROM windows were still poor even in this good clip (57 good/fair of 97) | **known gap, accepted (D55)** | P6 needs more device-referenced clips: different people or conditions, and a still resting clip. The reference carries only the minute, so alignment cannot be finer; the sensitivity table shows CHROM/POS barely move for a +-10 s clock offset (2.3-2.4) |

| 17 | Clips `20261021_215101` and `20261021_185356` are evaluated without re-lock flags: both were recorded before the `relock` column existed, and for `215101` a replay of the video never re-synchronised with the live means (it differed on all 1,913 frames), so the live re-lock events could not be recovered. Both are hand-count references (lower confidence) | known limitation | Stated in each clip's meta notes. The numbers for these two clips are therefore approximate; the Apple Watch clip is unaffected (its flags are in the CSV) |

---

## Demo-day checklist

- [ ] Center Stage OFF; Studio Light / Portrait / background effects OFF; sit ~30-45 cm from the screen
- [ ] Subject sits back with head resting against chair or wall; presenter talks, subject stays silent and neutral during measurement
- [ ] Face the camera: do not turn the head, talk or laugh while measuring (the detector is frontal-only)
- [ ] Free disk space for P6 recordings (about 420 MB per minute of lossless video)
- [ ] Faculty OK on the topic switch (the registered title on the sheet is the football project)
- [ ] App tested on the exact demo laptop; laptop charged; charger packed; battery saver off
- [ ] Screen brightness 100%; night light or blue-light filter **off**
- [ ] Projector set to **mirror**, not extend (and, if the light frame is used, so it stays on the laptop screen)
- [ ] Subject: no glasses, hair off the forehead, 50 to 70 cm away, still and silent while measuring
- [ ] Light in front and above the subject, both cheeks evenly lit, no side shadow
- [ ] Phone torch fixed on a stand 40-50 cm in front, slightly above eye level, diffused through tissue or bounced off white paper. Not hand-held
- [ ] Facing the window or the brightest light; no strong light from behind
- [ ] Reference device (smartwatch or pulse oximeter) worn and already reading
- [ ] Wear the Apple Watch as the live reference
- [ ] Other camera apps closed (Teams, Zoom, browser tabs)
- [ ] Backup screen recording on the laptop and on a phone or Drive
- [ ] App launched once before presenting, so the camera has warmed up
