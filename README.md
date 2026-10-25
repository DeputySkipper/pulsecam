# PulseCam

Contactless heart rate from an ordinary webcam, using remote photoplethysmography (rPPG). Each heartbeat changes how much light the facial skin absorbs, by a fraction of a percent. PulseCam finds the face, averages the skin colour over the cheeks in every frame, cleans the resulting signal and reads the heart rate off its dominant frequency. The whole pipeline is shown live: the video with the ROI boxes, the filtered pulse waveform and the frequency spectrum with the detected peak.

Course project for Image & Video Processing (IVP). Classical image and signal processing only, no machine learning. **Not a medical device.**

Screenshots are not kept in the repository. Regenerate them with the commands under [UI screenshots](#ui-screenshots): `python tools/ui_shots.py --dashboard` writes `debug/shots/dashboard.png`, taken from the mock source at a steady 72 BPM, so the video pane is the mock's placeholder.

## Limits you should know about

- **Range 54 to 180 BPM, resting adults.** The band floor is 0.9 Hz, so a heart rate below 54 BPM cannot be measured.
- **Frontal face, one person.** The face detector is a frontal Haar cascade. Turning the head, looking away, talking or laughing loses the face, and each loss restarts the warm-up.
- **Lighting is the dominant factor.** Overhead room light alone gave unstable or failed readings; a fixed phone torch in front gave good/fair windows with an MAE of 2.3 BPM against an Apple Watch (one clip). See [Demo setup](#demo-setup).
- **About 12 to 13 s to the first number** on a clean signal (10 s of buffer, then 3 agreeing estimates to confirm it). Many windows are still labelled poor and show `--`; that is deliberate.
- Evidence so far is **one device-referenced clip** (107 s, one subject). See `results/eval_table.md`.

## Setup

Python 3.11 or 3.12 (the system Python on macOS is too old).

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` pins `opencv-python-headless` below 5: OpenCV 5 no longer ships the Haar cascade files the face detector needs, and the headless build avoids a Qt clash with PySide6.

On macOS the first run asks for camera permission for your terminal. If the camera cannot be opened, the app says so in the status line.

## Run

```bash
python app.py                # live webcam (the default)
python app.py --mock         # synthetic source that cycles through every state; no camera needed
python app.py --steady       # synthetic source, a steady clean 72 BPM
```

The window opens stopped. Press **Start**.

### Offline mode (a recorded clip)

1. Set **Source** to **File...** and pick a clip (`.mkv`, `.avi`, `.mp4`, `.mov`). Cancelling the dialog returns to the previous source.
2. Press **Start**. The clip plays in real time through the same pipeline and UI, and ends with "End of file: press Start to replay", keeping the last result on screen.

Clips recorded by the app go to `recordings/`. The lossless videos from the build were removed afterwards to save disk space (only the means CSVs, meta files and reference readings are kept), so there is no sample clip to play; record one first. Note that replaying a video does not reproduce the live numbers exactly (the ROI lock depends on time and on state from before the clip began); evaluation uses the means CSV instead.

## Controls

| Control | What it does |
|---|---|
| **Start / Stop** | Starts or stops the selected source. The source cannot be changed while running. |
| **Method** | GREEN (baseline), CHROM (default) or POS. All three are also shown side by side in the cards under the heart-rate panel (the active one has a white outline). |
| **Source** | Mock, Webcam or File... |
| **Light frame** (`L`, the sun icon) | Optional white border around the dashboard. Off by default; the fixed torch is the lighting plan. While it is on, the window's minimum size grows by the border so the panels are not squeezed. |
| **Fullscreen** (`F`, `Esc` to leave; the corners icon) | Fullscreen toggle. |
| **Record** | Webcam only. Writes a lossless clip, a means CSV and a meta file (see below). |
| **Ref BPM**, device, **Log** | Type a reference reading and pick its device. **Log** appends the current reading and the reference to `results/readings.csv`. The reference is also written into the last recording's meta file. |

These are the only keyboard shortcuts.

### Reading the screen

Everything shown comes from the live estimator output (nothing is simulated).

- **Top bar:** the source and its measured rate ("Camera 30 fps", "Mock ...", "File ..."; "--" when nothing is measured).
- **Video:** two tags sit on top of the picture, never in the frame data. The top-left tag shows the face state taken from the capture flags: NO FACE, LOCKING (the face box is being locked), FACE LOCKED (frozen after the lock phase), or FACE FOUND if a face is present but no lock flag has been seen. The bottom-right tag shows the live ROI brightness and the measured FPS.
- **Signal quality panel:** the current quality (Good, Fair, Poor), the SNR on a -4 to +8 dB scale with the poor, fair and good zones (the boundaries are `SNR_FAIR_DB` and `SNR_GOOD_DB`), and the share of good, fair and poor windows over the last 60 s.
- **Heart-rate panel:** the smoothed BPM, the state line, a heartbeat dot that beats at the displayed rate (still when there is no number or only a held value), the last 5 s of the filtered pulse, and Method, SNR, Light (live brightness out of 255, with a tick at the low-light threshold), Window and Range.
- **Plots:** the filtered pulse over the last 15 s, and the spectrum from 54 to 180 BPM. Move the pointer over the spectrum for a crosshair and the BPM and Hz under it; the header returns to the detected peak when the pointer leaves.

The big number is the smoothed BPM. The state line says what is going on:

| State line | Meaning |
|---|---|
| Press Start / Starting... | Stopped, or waiting for the first estimate. |
| No face detected | Nothing to measure. The buffer restarts when the face returns. |
| More light needed | The ROI brightness (the **Light** value in the stats row) is below `LOW_LIGHT_LEVEL` in `config.py`. Provisional: calibrate it on your laptop. |
| Warming up x/10 s | Filling the first 10 s of signal. |
| Hold still | The signal is poor. The last value is greyed out and replaced by `--` after 5 s. |
| Measuring | A usable signal. The dot shows good (green) or fair (amber). |

`--` next to "Measuring" is normal for 2 or 3 s: a number is only shown after 3 consecutive non-poor estimates that agree within 5 BPM.

### Recordings

Pressing **Record** (live webcam only) writes three files to `recordings/`, sharing a timestamp:

| File | Contents |
|---|---|
| `<stamp>_means.csv` | `t, R, G, B, face_found, relock` for every frame, computed live from the uncompressed frames. This is what evaluation uses. |
| `<stamp>.mkv` | Lossless FFV1 video, about **420 MB per minute**. Falls back to lossy MJPG with a warning if FFV1 is unavailable. |
| `<stamp>_meta.json` | The settings the clip used (ROI set, band, window, method, a full config snapshot), the reference fields, frame count, fps, codec and warnings. |

## Demo setup

Set these up before presenting; the checklist is in `docs/TRACKER.md`.

- **Light: a phone torch on a stand**, 40 to 50 cm in front of the subject, slightly above eye level, diffused through tissue or bounced off white paper. Not hand-held. Both cheeks evenly lit, no side shadow. Do not rely on room light or on the screen.
- **Subject:** sits **30 to 45 cm** from the screen, **head rested against a chair or wall**, facing the camera, no glasses, hair off the forehead. The subject stays **silent and neutral** while measuring; the presenter does the talking.
- **Camera (macOS):** **Center Stage off**, and Studio Light, Portrait and other background effects off. They crop and re-frame the video and move the ROI.
- **Let the camera settle** for 10 to 15 s before measuring: auto-exposure keeps moving for a while after the camera opens.
- **Screen:** brightness 100%, night light and blue-light filter off. If projecting, mirror the display (do not extend).
- **Reference:** wear the Apple Watch as the live reference and keep it already reading.
- Close other camera apps (Teams, Zoom, browser tabs). Launch the app once before presenting.
- Free disk space if you will record: lossless video is about 420 MB per minute.

## Evaluate recorded clips

```bash
python tools/evaluate.py
```

For every clip in `recordings/` that has a meta file and a reference, this replays the means CSV through the same estimator the app uses (so warm-up, resets, re-lock matching and the good/fair/poor labels are the live ones) and writes:

- `results/eval_table.md`: the readable report (read this one)
- `results/eval.csv`: one row per clip and method, for clips with a single reference number
- `results/eval_readings.csv`: one row per reading and method, for clips with a time-aligned reference

Two kinds of reference:

- **Time-aligned readings**, e.g. from an Apple Watch. Put them in `recordings/<stamp>_ref_readings.csv` with columns `minute,bpm` (for example `2026-10-21 23:07,91`, one row per reading) and name the file in the clip's meta as `"ref_readings"`. Each reading is compared with the app's median over the wall-clock minute it belongs to, split by whether the app labelled the windows good/fair or poor. The report also gives the readings' own scatter as an MAE floor and a clock-offset sensitivity table, because the readings carry only the minute.
- **A single number for the whole clip** (`ref_bpm` and `device` in the meta file). A hand count is labelled **lower confidence** in the report, since it is good to a few BPM at best and hides any change in rate during the count.

Clips without a meta file or without a reference are listed under "Skipped".

## Other tools

```bash
python -m pytest -q                       # the test suite (no camera needed)
python tools/check_capture.py             # 10 s camera check: FPS, % frames with a face, box jitter, snapshots in debug/
python tools/check_capture.py --file clip.mkv
python estimator.py                       # console demo: all three methods side by side, with a summary
python estimator.py --save-means          # the same, also writing recordings/<stamp>_means.csv
python tools/ui_shots.py                  # UI screenshots (see below) into debug/shots/
python tools/ui_shots.py --dashboard      # one steady 72 BPM dashboard shot -> debug/shots/dashboard.png
```

### UI screenshots

`tools/ui_shots.py` drives the real window against the mock source without a screen and saves PNGs to `debug/shots/` (not committed):

| Command | Writes |
|---|---|
| `python tools/ui_shots.py --dashboard` | `dashboard.png`: steady 72 BPM at 1440x900 |
| `python tools/ui_shots.py` | `1_warming_up.png` to `6_no_face.png` (every mock state at 1280x800), `7_light_frame_on_1440x1000.png`, and `size_1100x720.png`, `size_1366x768.png`, `size_1440x900.png` (the layout at the minimum, a common laptop and the design size; each prints the heights the hero, cards and plots took) |

On Windows the script points Qt's offscreen platform at `C:\Windows\Fonts` (set `QT_QPA_FONTDIR` to override), because that platform finds no fonts on its own and every letter would be an empty box. The look uses IBM Plex Sans and IBM Plex Mono if they are installed and otherwise the system sans-serif and monospace, so a shot taken on a machine without Plex differs slightly in text widths. Hover states are not captured (there is no pointer offscreen).

## How it works

```
webcam / file / mock
        |  frame + timestamp
        v
CaptureWorker (thread): Haar face box -> smoothed, then frozen after 2 s -> cheek ROIs -> mean R, G, B
        |  FrameSample, about 30 per second
        v
Estimator: 15 s buffer -> resample to a uniform rate -> normalise -> CHROM / POS / GREEN
           -> detrend -> Butterworth bandpass 0.9-3.0 Hz -> Hann window, zero-padded FFT -> peak -> BPM
           -> SNR and quality label -> median smoothing, jump rejection, confirmation of the first number
        |
        v
Dashboard: video, BPM, state line, waveform, spectrum
```

- Means are computed on the clean frame; overlays are drawn only on the preview copy.
- The ROI box is frozen after a 2 s lock so detector jitter cannot enter the signal. If the face moves, it re-locks, and the new segment is gain-matched to the old one so the level step does not look like a pulse.
- Every tunable is in `config.py`. Nothing else holds a magic number.

| File | Role |
|---|---|
| `app.py`, `ui/` | The dashboard (PySide6 and pyqtgraph): `theme.py` (colours, fonts, sizes, the `ANIMATIONS` switch for hover and heartbeat animation), `panels.py` (glass panel, top bar, signal-quality panel), `animated.py` (hover-scaled buttons), `widgets.py` (video, heart-rate panel, method cards, plots), `main_window.py` |
| `worker.py`, `capture.py` | Capture thread; webcam, file and mock sources |
| `face_roi.py` | Face detection, ROI geometry, per-frame mean RGB |
| `signal_proc.py` | Pure signal-processing functions |
| `estimator.py` | Buffer, method, smoothing and states |
| `recorder.py` | Recording, meta files, the reading logger |
| `tools/` | Camera check, evaluation, UI screenshots |

Design documents (`docs/PRD.md`, `docs/TRD.md`, `docs/TRACKER.md`) are kept locally and not committed.
