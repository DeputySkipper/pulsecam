# TRD: PulseCam

Read with `PRD.md` (what and why) and `TRACKER.md` (order, timeboxes, agent rules).
**If anything here conflicts with the timeline, the timeline wins:** simplify, and record the change in the Decisions log in `TRACKER.md`.

---

## 1. Stack

- Python 3.11 or 3.12
- `numpy`, `scipy` for signal processing
- `opencv-python-headless` for capture, Haar detection, colour conversion and video I/O. Headless on purpose: PySide6 provides the GUI, and the regular OpenCV wheel bundles its own Qt, which can clash with PySide6.
- `PySide6` + `pyqtgraph` for the UI and fast live plots
- `pytest` for synthetic tests
- No ML frameworks.

`requirements.txt`

```
numpy>=1.26
scipy>=1.11
opencv-python-headless>=4.9
PySide6>=6.6
pyqtgraph>=0.13.4
pytest>=8
```

Setup

```
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## 2. Project structure

```
pulsecam/
├── app.py                 # entry: QApplication + MainWindow
├── config.py              # every tunable (section 7); no magic numbers elsewhere
├── models.py              # dataclasses: FrameSample, HRResult
├── capture.py             # WebcamSource, FileSource, MockSource
├── face_roi.py            # Haar detection, box smoothing, ROI geometry, skin mask, RGB means
├── signal_proc.py         # pure functions: resample, normalise, methods, filters, spectrum, SNR
├── estimator.py           # owns the buffer and method; produces HRResult every UPDATE_SEC
├── worker.py              # QThread: source -> face_roi -> emits FrameSample; paces files; feeds the recorder
├── recorder.py            # Recorder (means CSV + FFV1 video on its own thread + meta JSON), reading logger
├── ui/
│   ├── main_window.py     # layout, light frame, controls, shortcuts
│   ├── widgets.py         # VideoView, BpmPanel, plot widgets
│   └── theme.py           # colour tokens, fonts, stylesheet
├── tools/
│   ├── check_capture.py   # headless Phase 1 check: FPS, face %, annotated snapshots
│   ├── ui_shots.py        # headless UI screenshots of every mock state -> debug/shots/
│   └── evaluate.py        # batch: all methods x recordings -> results table
├── tests/
│   └── test_signal_proc.py
├── recordings/            # clips, means CSVs, ref JSONs (gitignored)
├── results/               # readings.csv, eval.csv, eval_table.md
├── debug/                 # snapshots (gitignored)
├── docs/                  # PRD.md, TRD.md, TRACKER.md
├── requirements.txt
└── README.md
```

## 3. Architecture and threading

```
[Webcam / video file / mock]
          │  frame + timestamp
          ▼
CaptureWorker (QThread)
  read frame, t = time.perf_counter()
  face_roi: detect every N frames -> smooth box -> ROIs -> (skin mask) -> mean RGB
  preview = downscaled copy of frame with overlays drawn
          │  Qt signal: FrameSample  (~30 Hz)
          ▼
Main thread (UI)
  VideoView.update(preview)               every frame
  Estimator.push(t, rgb, face_found)      every frame (cheap append)
  QTimer UPDATE_SEC  -> Estimator.estimate() -> HRResult -> BpmPanel
  QTimer PLOT_REFRESH_MS -> plots redraw from latest HRResult
```

- Estimation runs on at most ~300 samples, so it is cheap enough for the main thread (a few ms). If the UI stutters, move it into the worker.
- Never touch Qt widgets from the worker thread. Communicate only through signals.
- `MockSource` emits `FrameSample`s directly (bypassing face detection) so the UI can be built in parallel with the signal pipeline.

## 4. Data contracts (`models.py`)

```python
@dataclass
class FrameSample:
    t: float                                   # seconds; perf_counter() right after read (file: POS_MSEC / 1000)
    rgb: np.ndarray | None                     # shape (3,), mean R, G, B over ROI skin pixels, float64; None if no face
    face_found: bool
    face_box: tuple[int, int, int, int] | None # smoothed x, y, w, h
    rois: list[tuple[int, int, int, int]]      # x, y, w, h per ROI
    preview: np.ndarray                        # BGR uint8, downscaled, overlays drawn
    motion: bool = False
    relock: bool = False                       # ROI box was (re)locked or frozen this frame: the estimator level-matches across it

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
    t_sig: np.ndarray     # uniform time axis for plots (s, relative)
    raw: np.ndarray       # (N, 3) normalised RGB, for the optional raw plot
    pulse: np.ndarray     # filtered pulse signal
    freqs: np.ndarray     # Hz
    power: np.ndarray
    peak_hz: float | None
```

**OpenCV frames are BGR.** Convert so `rgb` is in R, G, B order. Every method below assumes R, G, B.

## 5. Processing pipeline

`signal_proc.py` contains pure functions (numpy in, numpy out) so everything is testable without a camera.

### 5.1 Face and ROI (`face_roi.py`)

- Detector: `cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")`.
- Run on a grayscale frame downscaled by 2, every `DETECT_EVERY_N` frames. `scaleFactor=1.1`, `minNeighbors=5`, min size about 80 px at full resolution. Pick the largest face.
- Box smoothing: exponential moving average on (x, y, w, h): `box = a * new + (1 - a) * box` with `a = BOX_EMA_ALPHA`. Between detections, reuse the smoothed box. Without this, box jitter becomes noise in the signal.
- Face missing for longer than `FACE_LOST_SEC`: `face_found = False`.
- Motion flag (Should): centre moves more than `MOTION_THRESH x w` between consecutive detections.
- ROIs as fractions of the face box `(x0, y0, x1, y1)`:
  - forehead `(0.30, 0.10, 0.70, 0.25)`
  - left cheek `(0.15, 0.50, 0.35, 0.70)`
  - right cheek `(0.65, 0.50, 0.85, 0.70)`
- Skin mask (Should, `USE_SKIN_MASK`): convert ROI to YCrCb, keep `133 <= Cr <= 173` and `77 <= Cb <= 127`. If fewer than 30% of ROI pixels survive, skip the mask for that frame.
- Output `rgb` = pixel-count-weighted mean over all ROIs, float64.
- **Compute means on the clean frame. Draw overlays only on the preview copy.** Overlay pixels inside an ROI would contaminate the signal.

### 5.2 Buffer and resampling (`estimator.py` + `signal_proc.py`)

- Ring buffer of `(t, rgb)` keeping the last `WINDOW_SEC`.
- Reset the buffer if the gap between samples exceeds `GAP_RESET_SEC` or the face is lost (state goes back to `warming_up`).
- Measured FPS = `(n - 1) / (t_last - t_first)`.
- Estimate only once the buffer holds at least `MIN_SEC`.
- Resample each channel to a uniform grid at `FS` with `np.interp` over the real timestamps. **Never assume the nominal camera FPS**: laptop webcams drop to about 15 fps in dim light.

### 5.3 Methods: RGB to a 1-D pulse signal

Let `C` be the `(N, 3)` uniformly resampled R, G, B. Guard every division (means and standard deviations near zero return `None`).

- **GREEN (baseline):** `Cn = C / mean(C, axis=0)`; `s = Cn[:, 1] - 1`.
- **CHROM** (de Haan and Jeanne, 2013), on `Cn`:
  `X = 3R - 2G`, `Y = 1.5R + G - 1.5B`;
  `Xf, Yf = bandpass(X), bandpass(Y)`; `alpha = std(Xf) / std(Yf)`; `s = Xf - alpha * Yf`.
- **POS** (Wang et al., 2017):
  ```
  l = round(POS_WIN_SEC * FS); H = zeros(N)
  for n in range(l, N + 1):
      Cw = C[n-l:n] / mean(C[n-l:n], axis=0)    # temporal normalisation per channel
      S1 = Gw - Bw
      S2 = Gw + Bw - 2*Rw
      h  = S1 + (std(S1) / std(S2)) * S2
      H[n-l:n] += h - mean(h)                   # overlap-add
  s = H
  ```

### 5.4 Detrend and bandpass

- `s = scipy.signal.detrend(s, type="linear")`
- `sos = butter(FILTER_ORDER, [BAND_LO, BAND_HI], btype="band", fs=FS, output="sos")`, designed once.
- `pulse = sosfiltfilt(sos, s)` (zero-phase, no lag). Apply to every method for a uniform pipeline.

### 5.5 Spectrum, BPM, SNR

- `X = np.fft.rfft(pulse * np.hanning(N), n=NFFT)`; `power = |X|^2`; `freqs = np.fft.rfftfreq(NFFT, 1/FS)`.
- Search for the peak only inside `[BAND_LO, BAND_HI]`.
- Parabolic interpolation around peak bin `k` with powers `a, b, c` at `k-1, k, k+1`:
  `p = 0.5 * (a - c) / (a - 2b + c)`; `f_peak = (k + p) * FS / NFFT`; `bpm = 60 * f_peak`.
- SNR (dB) = `10 * log10(P_sig / P_noise)` where `P_sig` is the power within `±SNR_HALF_WIDTH_HZ` of `f_peak`, and `P_noise` is the rest of the power inside the band.
- Quality: `good` if SNR ≥ `SNR_GOOD_DB`, `fair` if ≥ `SNR_FAIR_DB`, else `poor`. The thresholds are starting points: tune them on real recordings in P6 and log the final values.

### 5.6 Output smoothing

- `bpm_smooth` = median of the last `SMOOTH_K` accepted estimates whose quality is not `poor`. The first number after a reset or a stale clear needs `CONFIRM_ESTIMATES` consecutive non-poor estimates agreeing within `CONFIRM_AGREE_BPM` (a poor window breaks the run).
- On `poor`: keep showing the last good value, greyed out, with the state "Hold still". If no estimate has been accepted for `HOLD_MAX_SEC`, `bpm_smooth` becomes None (UI shows "--") and the history clears.
- Jump rejection (approved): ignore a new estimate more than `MAX_JUMP_BPM` from `bpm_smooth` unless `JUMP_PERSIST` consecutive held-back estimates agree with each other.
- ROI tracking (`FREEZE_ROI`): the face is tracked continuously (median of the last `TRACK_MEDIAN_N` detections, then an EMA of `TRACK_EMA`; this is the grey box in the preview). The measurement box (the accent ROIs) is held perfectly still while that live face stays within `RELOCK_MOVE_FRAC` of the box width of it, so detector jitter never enters the signal. Beyond that dead band, or after a lost face, the box glides to the face (`ROI_GLIDE_GAIN` of the gap per detection) until within `ROI_SETTLE_FRAC`. A leftover offset above `ROI_RECENTRE_FRAC` is corrected gently, without flags, once the face has been still for `ROI_STILL_SEC`. `FrameSample.relock` marks the start of a real move and, once the box has stayed settled for `ROI_SETTLE_HOLD_SEC`, its settle (continuous motion is one long follow, not many seams). **A re-lock does not reset the buffer.** The estimator keeps it and gain-matches the new segment: per channel, the mean of the new segment (provisional while it is shorter than `SEAM_MATCH_SEC`, final after) is scaled to continue from the mean of the last `SEAM_MATCH_SEC` before the seam, so the level step the ROI jump causes never reaches the filter. Matching uses 2 s windows (about 2.4 pulse cycles) because a short window's partial-cycle bias is as large as the pulse itself. Face loss and sample gaps still reset the buffer.

## 6. Sources (`capture.py`)

- **WebcamSource(index):** `cv2.VideoCapture(index)` (on Windows, try `cv2.CAP_DSHOW` if the default backend opens slowly). Request `FRAME_W x FRAME_H` at `FPS_REQUEST`.
  - Camera lock, best effort and platform-dependent: after `CAM_WARMUP_SEC` with auto settings, try `CAP_PROP_AUTO_EXPOSURE` (DirectShow: 0.25 manual, 0.75 auto) and `CAP_PROP_AUTO_WB = 0`. Read the values back and log them. If the image goes too dark or nothing changes, set `TRY_LOCK_CAMERA = False`. **Timebox: 15 minutes, then move on.**
- **FileSource(path):** timestamps from `CAP_PROP_POS_MSEC / 1000`; if that is unreliable, use `frame_index / CAP_PROP_FPS`. Paced to real time in the UI.
- **MockSource(bpm):** emits `FrameSample`s at 30 Hz with `face_found=True` and `rgb = base + A * sin(2*pi*f*t) * [0.33, 0.77, 0.53] + slow drift + noise`, and a dark preview frame labelled "MOCK". Lets UI work start in P0.

## 7. Config defaults (`config.py`)

| Name | Default | Notes |
|---|---|---|
| `CAM_INDEX` | 0 | |
| `FRAME_W`, `FRAME_H` | 640, 480 | |
| `FPS_REQUEST` | 30 | actual FPS is measured |
| `TRY_LOCK_CAMERA` | False | macOS ignores the exposure/WB properties |
| `CAM_WARMUP_SEC` | 3.0 | |
| `DETECT_EVERY_N` | 3 | frames |
| `BOX_EMA_ALPHA` | 0.3 | |
| `FACE_LOST_SEC` | 1.0 | |
| `MOTION_THRESH` | 0.10 | fraction of face width |
| `FREEZE_ROI` | True | lock the box after `ROI_LOCK_SEC` |
| `ROI_LOCK_SEC` | 2.0 | first lock |
| `RELOCK_MOVE_FRAC` | 0.05 | dead band, of box width |
| `ROI_SETTLE_FRAC`, `ROI_GLIDE_GAIN`, `ROI_SETTLE_HOLD_SEC` | 0.02, 0.5, 0.8 | glide end, glide speed, delay before the settle flag |
| `ROI_RECENTRE_FRAC`, `ROI_STILL_SEC`, `ROI_STILL_FRAC` | 0.035, 0.8, 0.025 | gentle flag-less re-centre |
| `TRACK_MEDIAN_N`, `TRACK_EMA` | 5, 0.5 | live face box smoothing |
| `SEAM_MATCH_SEC`, `SEAM_MIN_SEC` | 2.0, 0.5 | match window across a re-lock; less earlier data than the minimum: nothing to match |
| `ROI_SET` | "cheeks" | or "all" (forehead + cheeks) |
| `USE_SKIN_MASK` | False | Should item, not built |
| `WINDOW_SEC` | 15.0 | |
| `MIN_SEC` | 10.0 | buffer needed for the first estimate (the ROI lock phase is part of it); the first number shows about 2 s later |
| `GAP_RESET_SEC` | 1.0 | |
| `FS` | 30.0 | resample rate, Hz |
| `BAND_LO`, `BAND_HI` | 0.9, 3.0 | Hz, i.e. 54 to 180 BPM, resting adults |
| `FILTER_ORDER` | 3 | |
| `POS_WIN_SEC` | 1.6 | |
| `NFFT` | 2048 | |
| `SNR_HALF_WIDTH_HZ` | 0.15 | |
| `SNR_GOOD_DB`, `SNR_FAIR_DB` | 2.0, 0.0 | from the offline sweep on a ground-truth clip; retune in P6 |
| `SMOOTH_K` | 5 | |
| `MAX_JUMP_BPM` | 15 | |
| `JUMP_PERSIST` | 5 | agreeing held-back estimates needed to accept a jump |
| `HOLD_MAX_SEC` | 10.0 | no accepted estimate for this long: drop the held BPM |
| `UPDATE_SEC` | 1.0 | |
| `PLOT_REFRESH_MS` | 100 | |
| `LIGHT_FRAME_PX` | 100 | margin of white when the light frame is on |
| `LIGHT_FRAME_DEFAULT` | False | S8, off by default |
| `LOW_LIGHT_LEVEL` | 120.0 | provisional; mean ROI RGB (0-255) below which "More light needed" shows. Live value is shown as "Light" in the stats row |
| `DEFAULT_METHOD` | "CHROM" | |
| `CONFIRM_ESTIMATES`, `CONFIRM_AGREE_BPM` | 3, 5.0 | a number is first shown after 3 consecutive non-poor estimates within 5 BPM |
| `RECORD_FPS_PROBE_FRAMES` | 90 | frames used to measure the video's real fps |

## 8. UI spec (`ui/`)

- PySide6 `QMainWindow`; pyqtgraph plots with `pg.setConfigOptions(antialias=True)`; dark theme.
- **Light frame (S8, off by default):** an outer frame whose background is `#FFFFFF` (on) or the app background (off). When on it adds `LIGHT_FRAME_PX` of margin around the dark dashboard; when off the dashboard fills the window. Toggle with a button and the `L` key.
- **Video:** QLabel showing a QImage of the preview (convert BGR to RGB), aspect ratio kept. Face box in thin grey, ROIs in the accent colour.
- **BPM panel:** very large number (about 96 px, tabular figures), "BPM" label, a state line underneath ("Press Start", "No face detected", "More light needed", "Warming up x/10 s", "Hold still", "Measuring", in that priority), a quality dot (green, amber, red), a small stats row (method, SNR, FPS), and a row with GREEN / CHROM / POS side by side (active method outlined). The held value is greyed out while quality is poor and shows "--" after `HOLD_MAX_SEC`.
- **Plots:** filtered pulse waveform over the last 10 s; spectrum from 0.5 to 4 Hz with the axis also labelled in BPM and a vertical line at the peak. Optional (S5): raw normalised R, G, B traces as three thin lines.
- **Controls:** Start/Stop, Source (Webcam / File...), Method (GREEN / CHROM / POS), Light frame, plus Record and Reference BPM + Log (both Should).
- **Shortcuts (Should):** Space start/stop, `L` light frame, `M` cycle method, `R` record, `F` fullscreen, `Esc` exit fullscreen.
- **Refresh:** video every frame; text and plots at most every `PLOT_REFRESH_MS`. No animation that changes the brightness of large screen areas.
- **Theme tokens (`theme.py`):**

| Token | Value |
|---|---|
| bg | `#0E1116` |
| panel | `#161B22` |
| border | `#262C36` |
| text | `#E6EDF3` |
| muted | `#8B949E` |
| accent (pulse) | `#FF4D6D` |
| good / fair / poor | `#3FB950` / `#D29922` / `#F85149` |
| light frame | `#FFFFFF` |

Font: Segoe UI, Inter or the system sans-serif.

## 9. Recording, offline mode, evaluation

- **In-app recording (S3):** writes `recordings/<stamp>.mkv` with FFV1 (lossless) if the OpenCV build supports it, otherwise `.avi` MJPG at quality 95 with a warning in the meta file (lossy compression can erase the pulse signal). **Always** also writes `recordings/<stamp>_means.csv` (`t, R, G, B, face_found, relock`, `t` relative to the first frame; `relock` marks ROI lock starts and freezes, which the estimator needs to reproduce the live seam matching. Clips recorded before the column existed can carry `relock_times_sec` in their meta file instead), computed live from the uncompressed frames. Video encoding runs on its own thread so capture never waits for it. The video's header fps is measured over the first `RECORD_FPS_PROBE_FRAMES` frames, because a header fps that is off by x% makes offline playback read x% off. Lossless video is about 420 MB per minute at 640x480.
- **Clip metadata (replaces the separate ref file):** `recordings/<stamp>_meta.json`, written when recording starts and completed when it stops: `source`, `ref_bpm`, `device`, `light_frame`, `notes`, `settings` (`ROI_SET`, `FREEZE_ROI`, `BAND_LO`, `BAND_HI`, `WINDOW_SEC`, `MIN_SEC`, `method`), `method_at_stop`, a full `config` snapshot, `frames`, `duration_sec`, `measured_fps`, `video` (codec, fps), `files`, `warnings`. The reference fields can be typed during or after the recording and are written into that clip's meta file. Read the reference device at the start, middle and end of the clip and store the average.
- **Evaluation (`tools/evaluate.py`):** replays each clip's means CSV through the live `Estimator` (so warm-up, resets, re-lock matching and quality labels are the live ones), keeps every per-second window per method with its own good/fair/poor label, and writes `results/eval.csv`, `results/eval_readings.csv` and `results/eval_table.md`. Two reference types, both from the meta file: a time-aligned readings file (`ref_readings`, columns `minute,bpm`; each reading is compared with the app's median over the wall-clock minute it belongs to, windows placed by centre time, split good/fair vs poor, with the readings' own scatter as the MAE floor and a clock-offset sensitivity table) and a single `ref_bpm`. Each reference carries a confidence from `config.REF_CONFIDENCE`: device readings are `device`, a hand count is `lower (hand count)` and is labelled so in the table.
- **Replay vs live:** offline replay of the video does not reproduce the live means exactly: the ROI lock depends on time and on state from before the clip began (a clip started mid-stream begins with a different box). After the first face loss the two agree exactly. Evaluate from the means CSV (D7).
- **Offline mode (M9):** FileSource runs the full pipeline and UI on a recorded clip, paced to real time by the worker; at the end of the file the last result stays on screen ("End of file: press Start to replay").
- **`tools/evaluate.py` (S4):** for every clip with a ref JSON, run all methods **from the means CSV** (fast, and immune to codec damage). Take the median `bpm_smooth` after warm-up. Write `results/eval.csv` and `results/eval_table.md`: clip, reference, estimate and absolute error per method, then an MAE row per method.
- **Reading logger (S4):** the Log button appends to `results/readings.csv`: wall-clock time, method, `bpm_smooth`, `ref_bpm`, absolute error, `snr_db`, light frame on/off. It needs a typed reference and a current reading, and says so in the status line when it cannot log.

## 10. Testing

`tests/test_signal_proc.py` (the agent must run `pytest -q` at the P2 and P3 gates). Use fixed random seeds.

1. **Synthetic GREEN:** FS 30, 10 s, `rgb = 0.5 + 0.005 * sin(2*pi*1.2*t) * [0.33, 0.77, 0.53]` + linear drift + Gaussian noise (sigma 0.001). Expect within 1.0 BPM of 72.
2. **POS and CHROM** on the same signal, plus a common-mode intensity change applied equally to all channels: within 1.0 BPM.
3. **Irregular timestamps:** jitter sample times by ±5 ms and drop 10% of frames. Within 2 BPM after resampling.
4. **Range:** 50 BPM and 120 BPM both recovered within 1.5 BPM.
5. **Pure noise:** quality is not `good`, and SNR is clearly lower than in test 1.
6. **Edge cases:** constant input or near-zero means return `None` without crashing.

Live checks are manual and get logged in `TRACKER.md`: ROI stable on a still face; BPM within ±10 of reference in good light; app runs 10 minutes without freezing.

## 11. Performance targets

- Capture plus ROI: ≤ 15 ms per frame at 640x480
- One estimate: ≤ 10 ms
- Video display: ≥ 25 fps

## 12. Pitfalls checklist

- [ ] BGR vs RGB: OpenCV is BGR; the methods assume RGB.
- [ ] Use real timestamps and resample; do not trust the nominal FPS.
- [ ] Means come from live, uncompressed frames, never from re-decoded lossy video.
- [ ] Overlays are drawn on the preview copy only, after the means are computed.
- [ ] Guard divisions by zero (means, `std(S2)`, `std(Yf)`).
- [ ] Only filter once `MIN_SEC` of data exists (`sosfiltfilt` needs enough samples for padding).
- [ ] Smooth the Haar box; raw box jitter becomes signal noise.
- [ ] Qt widgets are touched only from the main thread.
- [ ] Keep large-area screen brightness constant: the screen lights the face.
- [ ] Use `opencv-python-headless` to avoid a Qt clash with PySide6.
