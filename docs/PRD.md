# PRD: PulseCam (working name)

**Contactless Heart Rate Estimation from Facial Video using Remote Photoplethysmography (rPPG)**

| | |
|---|---|
| Course | Image & Video Processing (IVP) |
| Team | Vinayak Rastogi (B078), Jeet Munshi (B064) |
| Doc date | Wed 21 Oct 2026 |
| Demo | Thu 22 Oct 2026 |
| Build budget | **8 hours total** |
| Related docs | `TRD.md` (how to build it), `TRACKER.md` (timeline, status, rules for the coding agent) |

---

## 0. The one rule: timeline first

We have one working session before the demo. **A basic project that works reliably, looks clean, and processes the signal well beats an ambitious one that breaks on stage.**

- When in doubt, cut features. Never cut the quality of the core pipeline or the UI polish.
- Everything outside **Must** is optional. It starts only after every Must passes its gate in `TRACKER.md`.
- No new features without explicit approval from the team.

---

## 1. Summary

PulseCam estimates a person's heart rate from an ordinary laptop webcam, without any contact.

Each heartbeat pushes blood into the facial skin, which slightly changes how much light the skin absorbs (most strongly in the green channel). The change is invisible to the eye, a fraction of a percent of pixel intensity, but it is measurable. We:

1. Locate the face and pick skin regions (forehead, cheeks).
2. Average the skin pixel colour in every frame, giving an R, G, B time series.
3. Clean the series (resample, detrend, bandpass to the heart-rate band).
4. Find the dominant frequency with an FFT and convert it to beats per minute.

The whole pipeline is shown live on screen, so the image and video processing is visible, not hidden.

## 2. Motivation (for the intro slide)

- Contactless vital signs matter where contact sensors are a problem: burn patients, newborns, infection control, telehealth, driver monitoring.
- It needs only commodity hardware (a webcam).
- It is distinct from every other project on the class list: it is the only one that extracts a physiological signal from **temporal** pixel variation in video.

## 3. Goals and non-goals

**Goals**

- **G1** Live BPM from a webcam within about 10 s for a still subject facing the camera.
- **G2** Show the pipeline visually: ROIs, filtered pulse waveform, frequency spectrum with the detected peak.
- **G3** Compare signal extraction methods (GREEN baseline vs POS, plus CHROM if time allows) against a reference device.
- **G4** A clean, responsive, dark dashboard. An optional on-screen white light frame exists (S8, off by default); lighting comes from a fixed phone torch (see §8).

**Non-goals**

- Not a medical device. No clinical accuracy claims.
- No machine learning or deep learning. Pure IVP plus signal processing. (The Haar cascade is a classical detector used only to locate the face.)
- Single person only.
- No HRV, SpO2, blood pressure or respiration in this build.
- No mobile app, no web deployment.
- Not a full-range monitor: **range 54 to 180 BPM, resting adults**. Heart rates below 54 BPM cannot be measured (band floor 0.9 Hz).

## 4. Demo scenario (about 4 minutes)

1. **Intro (30 s):** the idea and the one-line physics.
2. **Live reading:** subject sits close to the laptop (30 to 45 cm) with a phone torch fixed on a stand in front, diffused. ROI boxes lock onto the face. The app shows "Warming up" for about 8 s, then a BPM that updates every second. Compare with a smartwatch or pulse oximeter.
3. **Pipeline walkthrough:** filtered pulse waveform and spectrum with the peak marked.
4. **Method switch:** GREEN to CHROM (default) and POS, shown side by side under the BPM. The methods agree when the signal is good.
5. **Lighting comparison** (optional): torch off vs on, or the light frame (S8) on vs off, to show the effect on signal quality.
6. **Results slide:** error vs reference across recorded clips, per method.
7. **Limitations:** range 54 to 180 BPM (resting adults), motion, lighting, camera auto-exposure, skin tone, compression.

**Backup:** a screen recording of steps 2 to 4 working, plus recorded clips that play through offline mode.

## 5. Requirements

### Must (the demo fails without these)

| ID | Requirement |
|---|---|
| M1 | Live webcam capture with real per-frame timestamps; measured FPS displayed |
| M2 | Face detection (Haar cascade) with a smoothed bounding box; forehead and two cheek ROIs drawn on the video |
| M3 | Per-frame mean R, G, B over the ROIs feeding a sliding 10 s buffer |
| M4 | Processing: resample to a uniform rate, detrend, Butterworth bandpass 0.9 to 3.0 Hz (54 to 180 BPM), FFT peak to BPM, update every 1 s, smoothed output |
| M5 | Methods: GREEN (baseline) and POS, plus CHROM (S1, built). CHROM is the default; all three are selectable |
| M6 | SNR-based signal quality indicator and clear states: No face / Warming up / Measuring / Poor signal |
| M7 | Dashboard: live video with ROI overlay, large BPM readout, filtered waveform plot, spectrum plot with peak marker |
| M9 | Offline mode: run the same pipeline on a recorded video file |
| M10 | Backup screen recording of the app working live |

### Should (only after all Musts pass)

| ID | Requirement |
|---|---|
| S1 | CHROM method and a live method dropdown |
| S2 | YCrCb skin mask inside the ROIs |
| S3 | In-app recording: raw clip plus ROI-mean CSV |
| S4 | Reference BPM logger to CSV; evaluation script producing a results table (MAE per method) |
| S5 | Raw normalised RGB trace plot |
| S6 | Motion flag when the face box jumps |
| S7 | Keyboard shortcuts |
| S8 | Light frame (was M8): static white border around the dashboard, toggleable, **off by default**. Demoted because a white screen alone gave poor signal throughout; a fixed phone torch is the lighting plan |

### Could (stretch, needs explicit approval)

C1 Measure mode (full white screen, small BPM) · C2 MediaPipe face mesh ROI · C3 small heart icon pulsing at the detected rate · C4 Eulerian Video Magnification view on a recorded clip · C5 respiration rate

### Won't (this build)

ML models for heart rate, multiple faces, HRV, web or mobile versions.

## 6. Success metrics

| Metric | Target | Acceptable |
|---|---|---|
| MAE vs reference, POS, still subject, good light (at least 3 clips of 60 s) | ≤ 5 BPM | ≤ 10 BPM |
| Time to first reading (currently about 12 to 13 s: 10 s buffer + 2 s to confirm the first number) | ≤ 10 s | ≤ 15 s |
| BPM update interval | 1 s | 2 s |
| Video display FPS | ≥ 25 | ≥ 15 |
| UI stability | 10 min, no freeze or crash | 5 min |
| Synthetic test (known 72 BPM) | within 1 BPM | within 2 BPM |

Report results honestly, including misses. A clear limitations slide is better than an overclaimed number.

## 7. UI requirements

Dark theme, single window, no clutter.

```
┌──────────────────────── white light frame (toggle) ─────────────────────────┐
│ ┌──────────────────────────────┐  ┌───────────────────────────────────────┐ │
│ │                              │  │   72 BPM               ● Good signal  │ │
│ │   Live video + ROI boxes     │  │   Method: POS   SNR: 4.1 dB   FPS: 29 │ │
│ │                              │  ├───────────────────────────────────────┤ │
│ │                              │  │   Filtered pulse waveform (10 s)      │ │
│ └──────────────────────────────┘  ├───────────────────────────────────────┤ │
│  [Start] [Method ▾] [Light] [Rec] │   Spectrum 0.5 to 4 Hz, peak marked   │ │  (Light = optional S8, off by default)
│                                   └───────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

- The BPM number is the largest element, readable from the back of a classroom.
- Under the BPM: a small row with GREEN / CHROM / POS side by side (this window's estimate each, active method outlined).
- Plots refresh at most 10 times a second. No flashing or large brightness changes.
- Plain-words state line: "Press Start", "Warming up x/10 s", "No face detected", "More light needed", "Hold still", "Measuring".
- It must look intentional: consistent spacing, one accent colour, readable type.

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Faculty does not approve the topic switch (registered title is the football project) | High | Confirm before or at the start of the demo |
| Dim or uneven classroom lighting | High | Phone torch fixed on a stand 40 to 50 cm in front, slightly above eye level, diffused; face the window; backup recording |
| Webcam auto-exposure and white balance drift | Medium | Try to lock them; detrending; POS is robust to intensity changes |
| Subject moves or talks | Medium | Subject stays still; motion flag; quality indicator |
| Projector in extended mode moves the light frame off the laptop (only if S8 is used) | Low | Mirror the display; test during setup |
| Glare on glasses | Low | Demo subject without glasses |
| Over-scoping | High | Cut triggers in `TRACKER.md`; Musts only until gates pass |
| OpenCV and PySide6 Qt library clash | Low | Use `opencv-python-headless` |

## 9. IVP concepts covered (for the report and viva)

- Colour spaces: RGB, YCrCb (skin segmentation), chrominance projections (CHROM, POS)
- Haar-like features, integral images and cascade classifiers (face localisation)
- ROI selection and spatial averaging (noise reduction by pooling pixels)
- Building a temporal signal from video: frame timestamps, resampling to a uniform rate
- Detrending, Butterworth bandpass filtering, zero-phase filtering
- Hann windowing, FFT, zero-padding, peak interpolation, SNR
- Video I/O and how lossy compression destroys subtle signals

## 10. Timeline

The 8-hour phase plan, gates and cut triggers live in `TRACKER.md`. That file is the source of truth for status.
