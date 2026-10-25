# UI_TRACKER: monochrome dashboard restyle

Brief: restyle the PySide6 dashboard to match `docs/ui_reference.html`. UI only; signal code is frozen (`signal_proc.py`, `estimator.py`, `face_roi.py`, `capture.py`, `worker.py`, `recorder.py`, `config.py`, `tools/evaluate.py`). No git from the agent. No new dependencies or font files.

| Phase | Status |
|---|---|
| U0 Read, plan, conflicts | done (confirmed) |
| U1 Tokens, Panel, background, top bar, buttons and fields with hover animation | done (confirmed) |
| U2 Video overlays, signal quality panel, tests | done (confirmed) |
| U3 Hero, method cards, plots, spectrum hover | done (confirmed) |
| U4 Polish, 10 min mock run, README, differences note | gate met, awaiting confirmation (one unexplained 1.35 s stall in run 1, see section 12) |

## 1. What I read

`README.md`, `docs/PRD.md`, `docs/TRD.md`, `docs/TRACKER.md`, `ui/theme.py`, `ui/widgets.py`, `ui/main_window.py`, `tests/test_ui.py`, `tools/ui_shots.py`, `app.py`, `docs/ui_reference.html` (CSS, markup and script), and read-only `face_roi.py` / `capture.py` for the `relock` flag.

**The reference is the HTML only. `docs/ui_reference.png` does not exist.** The HTML also cannot be opened as it is: it loads `./vendor/react.js`, `./vendor/react-dom.js` and `./support.js`, none of which are in `docs/`, and it uses `{{pulsePath}}`-style placeholders that script fills in. I took every colour, size, spacing and timing from its CSS and markup. For the U3 visual check I plan a throw-away static render of the same markup in my scratchpad (placeholders filled with the same maths, scripts removed), never added to the repo.

Facts about the environment: PySide6 6.12.0. IBM Plex is **not installed** here, so the fallbacks (system sans, system monospace) will be what renders. Qt 6.12's `QStyleHints` exposes **no reduced-motion setting** (checked), so reduced motion will be a constant in `ui/theme.py` only.

## 2. Reference numbers I will use (from the HTML)

- Stage: `radial-gradient(900px 500px at 70% -10%, #1b1b1d 0, #0a0a0a 70%)`. Outer padding 24, gap 16. Text `#E8E8E8`.
- Panel: fill `rgba(255,255,255,.035)`, border `#26262a`, radius 12, inset top highlight `rgba(255,255,255,.05)`.
- Label (`.lbl`): mono 11 px, weight 500, letter-spacing .12 em, uppercase, `#9A9A9A`.
- Top bar 56 px high, padding 0 8 0 20; brand glyph 24 px (pulse path) and "PulseCam" 15 px weight 600; right side 12 px `#9A9A9A`, dot 7 px `#7FBF9E`.
- Button: 40 px, padding 0 16, radius 8, `#151516` / border `#333336`, 13 px weight 500; hover `#1f1f21` / `#4a4a4e`, scale 1.045 over .18 s `cubic-bezier(.2,.8,.2,1)`, pressed .97; primary `#EDEDED` on `#0A0A0A` (hover `#fff`). Focus ring 2 px `#BDBDBD`, offset 2. Field: 40 px, width 120, `#0e0e0f`, border `#333336`, placeholder `#7E7E82`.
- Video: panel padding 8, video 410 px high, radius 8, `#0d0d0e`; tags mono 11 px, `#C8C8C8` on `rgba(0,0,0,.55)`, 1 px `#2c2c2f`, radius 6, padding 7/9, at 14 px from the corners.
- Hero: 300 px high. BPM 112 px weight 300, letter-spacing -.04 em, white; "BPM" label 13 px; beat dot 12 px `#EDEDED` with a ring that grows 1 to 2.4 and fades .7 to 0 every .833 s (72 BPM); live pulse stroke 1.8 `#EDEDED` over a 54 px strip, dot r 3.5 white; stats column min 220, left border `#26262a`, values mono 14 px 500 white; light bar 4 px `#2a2a2d`, fill `#BDBDBD`, threshold tick 1 px `#8C8C8C`.
- Method cards: 96 px high, padding 14/18, number 32 px weight 300, letter-spacing -.02 em; hover scale 1.025 and border `#4a4a4e`; active border `#D6D6D6` (hover `#fff`).
- Plots: 290 px high, padding 16/18; waveform 1.7 px `#EDEDED` over a dashed zero line `rgba(255,255,255,.08)`; spectrum fill white .22 to 0, line 1.5 `#DADADA`, dashed peak `#9A9A9A`, cursor white; header right text 11 px mono (`#E8E8E8`, "Peak 72 BPM", becomes "NN BPM / N.NN Hz" on hover); x labels 54, 90, 120, 150, "180 BPM".
- Signal quality panel: padding 16/18/18, gap 16; scale 10 px high radius 5, zones poor 33.33% `#7A4450`, fair 16.67% `#8A7447`, good 50% `#477A60`; marker 2 x 20 px white; ticks mono 11 px at 0 / 33.33 / 50 / 100%; share bar 8 px, 2 px gaps; legend 12 px, 9 px swatches.
- The marker in the HTML sits at 67.5% for +4.1 dB: (4.1 + 4) / 12. So the scale is linear over -4 to +8 dB, and the zone widths (0 and +2 dB) agree with `config.SNR_FAIR_DB` and `config.SNR_GOOD_DB`.

## 3. Plan and files

**Files I will change:** `ui/theme.py`, `ui/widgets.py`, `ui/main_window.py`, `tests/test_ui.py`, `tools/ui_shots.py`, `README.md` (U4: screenshot instructions only), this file. `app.py` only if needed (I expect not). **New files** if the widgets file gets too large: `ui/panels.py` (Panel base, quality panel, hero) and `ui/animated.py` (hover-scale mixin, buttons, cards). I will say so in the phase report if I add them.

**U1.** `theme.py`: new tokens (names `BG`, `PANEL`, `BORDER`, `TEXT`, `MUTED`, `GOOD`, `FAIR`, `POOR`, `QUALITY_COLOR` etc. stay so imports and tests keep working; values change), size constants, `ANIMATIONS = True`, `HOVER_SCALE_BUTTON = 1.045`, `HOVER_SCALE_CARD = 1.025`, `PRESS_SCALE = 0.97`, `ANIM_MS = 180`, a font-family helper that uses IBM Plex Sans / Mono only if installed. `Panel` base widget (translucent fill, 1px border, faint top highlight, painted in `paintEvent`). Dashboard background widget with the radial highlight. Top bar. An animated-control mixin (`QVariantAnimation` driving a scale, applied with a `QPainter` transform inside `paintEvent`, a few px of margin reserved, hit area unchanged). `AnimButton` (QPushButton, custom painted, icons drawn with `QPainterPath`, no image files), a combo that looks like the reference's "Method: CHROM v" button (QComboBox subclass, custom painted, standard popup), restyled `QLineEdit`.

**U2.** `VideoView` gets two child `QLabel` overlays ("FACE LOCKED", "LIGHT n / FPS n"), never drawn into the frame. Signal quality panel: header dot and label, "SNR now" value, a custom-painted scale (zones from config, white marker, tick labels), the 60 s share bar and legend. Pure helper functions (marker position, zone fractions, share calculation, light bar fill and tick) so they are testable.

**U3.** Hero panel (state dot and text, 112 px BPM, "BPM", heartbeat dot, live pulse strip, stats list incl. Light bar), three method cards with hover scale, two restyled plots, spectrum hover crosshair and header readout. Then compare against a throw-away render of the reference at 1440x900.

**U4.** Polish, a 10 minute mock run (heartbeat of the event loop, memory), README screenshot instructions, a short "differs from the reference and why" note.

## 4. Conflicts, gaps and decisions needed

Each row says what I will do unless you say otherwise. Items marked **ASK** are the ones I would most like you to settle before U1/U2.

| # | Issue | Default I will use |
|---|---|---|
| 1 | **`ui_reference.png` is missing; the HTML cannot run standalone** (missing `vendor/` and `support.js`). "Matches the reference closely" can only be checked against the CSS numbers and my own static render. | Use the HTML numbers; static render in scratchpad for U3. Please add the PNG if you have it. |
| 2 | **ASK: colours the brief does not give.** The poor dot (brief gives good `#7FBF9E`, fair `#C9A85F` only), the error/warn text colour in the state line and status line, and the "checked" look of toggle buttons (Record, Light, Fullscreen). | Poor dot and error text: the zone colour `#7A4450` is very dim as text, so I would use a lighter `#B26A78`. Warn text `#C9A85F`. Checked buttons: border `#BDBDBD` and fill `#1F1F21`, no colour. Tell me if you want different values. |
| 3 | **ASK: "FACE LOCKED".** The UI does not receive a "frozen" flag, only `face_found` and `relock` (set on lock start and again on the freeze, per `face_roi.py` and `MockSource`). Showing "FACE LOCKED" whenever a face is found would overclaim during the 2 s lock phase. | Small UI state machine from the real flags: no face, then "LOCKING" after the lock-start flag, "FACE LOCKED" after the freeze flag, back to "LOCKING" on a re-lock, "NO FACE" when lost. Tested against the mock. If `FREEZE_ROI` were off it would stay "LOCKING". |
| 4 | **"Camera N fps" for the mock and file sources.** Saying "Camera" while the mock runs would be false. | Label follows the source: "Camera", "Mock", "File"; the number is `HRResult.fps`; "--" and a grey dot when stopped. |
| 5 | **The status line has no place in the reference or the brief** but tests and the user rely on it (record, log, camera errors, `window.status`). | A slim mono line at the bottom of the Controls panel with fixed height, so nothing jumps. |
| 6 | **Method and Source controls.** Reference draws them as buttons with a chevron ("Method: CHROM"), tests drive real `QComboBox`es (`setCurrentText`, `itemText`, `model().item(i)`). | Keep them as `QComboBox` (subclass, custom painted to look like the buttons, scale on hover too, standard popup). The separate "Method" / "Source" text labels go away. |
| 7 | **Live pulse strip "refreshes at `PLOT_REFRESH_MS`"** but `HRResult.pulse` only changes once per `UPDATE_SEC` (1 s). A smooth scroll between results would be invented data. The reference's scrolling animation is decorative. | The strip redraws when a new result arrives (same rule as the existing plots and `test_plots_redraw_only_when_a_new_result_arrives`), on the shared refresh timer; the dot sits on the newest real sample. The newest samples come from a zero-phase filter, so they carry the filter's edge effect; I will note that. |
| 8 | **Spectrum range.** PRD/TRD say 0.5 to 4 Hz with a Hz axis; the brief wants BPM ticks 54 to 180. | View 0.9 to 3.0 Hz (`config.BAND_LO/HI`), BPM axis only, ticks 54, 90, 120, 150, 180. This changes `SPECTRUM_VIEW_HZ`; I will note it in the final differences. The old band shading goes away (the whole view is the band). |
| 9 | **Spectrum fill.** Reference has a white 22% to 0 gradient; the brief says "a faint grey area" and "no gradients on text". | Flat translucent fill (about 12% white) under the `#DADADA` line. |
| 10 | **No peak on a poor window** (existing rule). What does the header say? | "No clear peak" (instead of "Peak NN BPM"); hover readout still works. |
| 11 | **Method card numbers.** Reference shows one decimal ("71.8"); current code shows integers and `test_window_walks_through_every_state` asserts `{"72"}`. | Follow the reference: one decimal from the real per-window BPM. Hero BPM stays an integer. Test updated (intentional change). |
| 12 | **SNR text.** Reference shows "+4.1 dB" (signed); current is "4.1 dB" (test asserts "6.0 dB"). | Signed, one decimal. Test updated. |
| 13 | **60 s shares.** The brief says per-update qualities in a rolling 60 s deque. `n/a` updates (warm-up, no face) are not a quality. Timestamps: I use `HRResult.t`. | Count only good / fair / poor; clear on Start/Stop; clear when the method changes (a mix of methods would mislead, as with the estimator's own smoothing history, D21); percentages by largest remainder so they sum to 100; "--" when empty. |
| 14 | **Light frame vs minimum size.** `config.LIGHT_FRAME_PX = 100` puts 100 px of white on every side; at the new minimum of 1100x720 the dashboard would have 900x520. | Panels declare real minimum sizes so the window grows instead of overlapping (Qt honours the central widget's minimum). The video panel is the flexible one. I will verify in U1 and report. |
| 15 | **Hero at narrow widths.** At 1100 wide the right column is about 500 px, but the hero needs about 600 (number, beat dot, 220 px stats column). | Below a width threshold the BPM font shrinks (still light, tight tracking) and the stats column narrows. Reported in U3 if it compromises the look. |
| 16 | **Default window size.** 1440x900 can exceed a laptop screen. | Start at 1440x900 clamped to the available screen; minimum 1100x720 as briefed. |
| 17 | **Animations.** No Qt reduced-motion API (checked), so the OS setting cannot be read. | `theme.ANIMATIONS = True`; set it to False and every hover/pulse animation is skipped. I will not add an environment variable unless you want one. |
| 18 | **Fonts.** IBM Plex is not installed here. Light weight 300 and letter-spacing depend on the fallback font. | Plex if installed, else the system sans (Segoe UI family on Windows) and monospace. Letter-spacing is set on the `QFont`, not in QSS, because QSS support is unreliable. Screenshots on this machine will not show Plex. |
| 19 | **Plot axes.** Reference waveform has no axis, only a dashed zero line; the current plot has a seconds axis. | Follow the reference (no axis, "last 15 s" in the header). |

## 5. Tests that will change (intentional) or be added

Existing tests reach into widgets; these assertions encode the old look and will be updated to the new behaviour, not weakened:

- `test_window_walks_through_every_state`: `panel.quality_text == "Good signal"` (the brief's header says Good / Fair / Poor, and moves to the quality panel), and the three cards' `.value.text() == "72"` (decision 11).
- `test_active_method_cell_follows_the_dropdown`: `panel.stat_method.text() == "Method GREEN"` (stats list becomes label + value). The `active` property check stays.
- `test_start_launches_the_worker...`: `int(p.stat_light.text().split()[-1])` (Light becomes "n / 255" plus a bar).
- `test_display_dims_held_value...`: `snr_text == "6.0 dB"` (decision 12).
- Names I will keep where possible so most tests are untouched: `panel.state_line`, `panel.number`, `panel.cells[...]`, `window.pulse_plot.set_result`, `window.status`, the controls' attribute names, `build_display`, `state_hint`, the `LightFrame` stylesheet behaviour.

New tests (U1 to U3): hover scale values and the animation switch; SNR marker fraction (including clamping below -4 and above +8); zone fractions from config; the 60 s share (window trimming, percentages sum to 100, `n/a` ignored, reset); light bar fill and threshold tick fraction; face-lock state machine; spectrum hover readout and reset; live pulse strip window (newest 5 s, empty state).

## 6. Risks

- Custom-painted buttons and combos replace QSS styling for those controls; keyboard focus ring and accessibility text must be handled by hand. I will paint the focus ring.
- Offscreen `grab()` screenshots do not run hover states or the heartbeat animation; those are checked by tests and by reading the animation values.
- Fallback fonts will change text widths compared with Plex, so fixed-width boxes need slack.
- A 10 minute mock run needs about 10 real minutes (U4).

## 7. Approvals received after U0

All 19 defaults in section 4 approved, with: (1) keep the NO FACE / LOCKING / FACE LOCKED state machine, driven only by the real `face_found` and `relock` flags; (2) source label "Camera / Mock / File N fps" by the actual source; (3) live pulse redraws when a new result arrives, dot on the newest real sample, no interpolation; (4) the 54-180 BPM spectrum range is recorded here only, **PRD.md and TRD.md are not edited** (PRD section 7 and TRD section 8 still say 0.5 to 4 Hz); (5) for every changed test assertion this file names the old and new behaviour, and no check is deleted, only replaced by an equivalent one on the new behaviour; (6) `ui/panels.py` and `ui/animated.py` approved; (7) poor dot and error text `#B26A78`, warn text `#C9A85F`, toggled border `#BDBDBD`; (8) build from the HTML's CSS, the PNG will be added for the U3 check. No git commands are suggested in this task.

## 8. U1 report (done)

**Files.** New: `ui/panels.py` (Panel, Dashboard background, TopBar, Lbl, PulseGlyph, StatusDot, `camera_text`), `ui/animated.py` (hover-scale mixin, `AnimButton`, `ComboButton`, drawn glyphs, `scale_target`, `mix_color`). Changed: `ui/theme.py` (rewritten: tokens, font helper, animation constants), `ui/widgets.py` (Card and BpmPanel now derive from Panel; card titles use Lbl), `ui/main_window.py` (new shell and controls), `tools/ui_shots.py`, `tests/test_ui.py` (new tests only; no existing assertion was changed in U1), this file. Nothing in the frozen list was touched.

**What now exists.** Window background `#0A0A0A` with the elliptical `#1B1B1D` highlight at 70% / -10% (reference `radial-gradient(900px 500px ...)`). Panels: translucent white 3.5% fill, 1 px `#26262A` border, radius 12, faint top highlight, all painted. Top bar 56 px: pulse glyph, "PulseCam", a status dot with "Camera / Mock / File N fps" (`HRResult.fps`, "--" and a grey dot when nothing is measured), "Not a medical device". Left column capped at 600 px: video panel and controls panel (row 1 Start/Stop, Method, Source; row 2 Record, Ref BPM, device, Log, Light and Fullscreen icon buttons; a fixed-height status line at the bottom). Buttons 40 px, radius 8, `#151516` / `#333336`, hover `#1F1F21` / `#4A4A4E`, primary `#EDEDED` on `#0A0A0A`, toggled border `#BDBDBD`, keyboard focus ring 2 px `#BDBDBD`. Method, Source and the device selector are real `QComboBox`es painted as buttons ("Method: CHROM" with a chevron). Hover: scale 1.045 (cards 1.025 later) over 180 ms on cubic-bezier(.2,.8,.2,1), 0.97 pressed, colours mix over 150 ms; the scaling is a `QPainter` transform in `paintEvent`, so the widget geometry and hit area do not change. `theme.ANIMATIONS = False` turns scaling off (colours still react). The right column (hero, cards, plots) is still the old content, restyled with the new tokens, until U3. Window: minimum 1100x720, starts at 1440x900 clamped to the screen.

**Things found and decided during U1 (please note):**
1. **Animation margin is 6 px, not the 4 I first reserved.** A test that renders every animated control at full hover scale caught the widest combo (200 px) touching the widget edge by half a pixel at 5 px. Controls are capped at 200 visible px (`theme.MAX_CONTROL_W`) so 4.5% growth (4.5 px) stays inside the 6 px margin. Layout spacing is negative (`CONTROL_GAP = 8 - 2 * margin`) so the drawn gap stays 8 px. A long Source label ("Source: File: long name") is elided; the tooltip keeps the full path.
2. **Light frame vs minimum size.** An explicit `setMinimumSize` stops Qt from enforcing the layout minimum, so with the white frame on at 1280x800 the hero was squeezed (digits cut off in a screenshot). Now, while the frame is on, the window minimum becomes 1100x720 plus the frame's 2 x 100 px on each axis (capped at the screen) and the window grows to it; turning the frame off restores 1100x720. Tested. On a screen smaller than that the frame still squeezes the dashboard.
3. **Known gap carried to U3:** with the frame off, the old right column's minimum height is about 761 px (layout minimum measured), above the 720 px window minimum, so at exactly 1100x720 the old hero can be squeezed. The U3 hero and plots must be flexible in height; the reference's fixed 300 px hero plus cards and 290 px plots need about 840 px and cannot fit 720 as drawn.
4. **Headless screenshots on Windows had no fonts** (Qt's offscreen platform reports zero font families, so every letter was an empty box, and the generic "Sans Serif" mapped to a font with missing glyphs). `tools/ui_shots.py` now sets `QT_QPA_FONTDIR` to the Windows fonts folder, and `theme.family()` falls back to Segoe UI / Consolas (or Helvetica Neue / Menlo, Arial, DejaVu) when the platform's generic name is not an installed family. Tests are unaffected. IBM Plex is still used first if installed (not installed here).
5. `ui_shots.py` shot 7 is now `7_light_frame_on_1440x1000.png` (the frame needs a window larger than the offscreen screen allows at 1280x800); the other shots are unchanged.
6. Letter-spacing is stored by Qt in 1/64 px, so the font test compares with a 0.02 px tolerance.

**Gate evidence.** `pytest -q`: 156 passed (the earlier 137 plus 19 new UI tests: theme tokens, font helper, scale targets and the animation switch, colour mixing, hover/press easing, animations off, geometry and hit area unchanged, no clipping of any control at hover scale, combo prefix and popup reset, keyboard-only focus ring, glyph follows Start/Stop, panel fill and border pixels, dashboard background pixels, top-bar text and dot, window sizes, 600 px cap, light-frame minimum). `python tools/ui_shots.py --dashboard` and `python tools/ui_shots.py` both run and write `debug/shots/`; `dashboard.png` shows the new shell. Not verified: real hover on a real mouse (offscreen has no pointer; the animation is tested through `set_hover` / `set_pressed` and by rendering at the target scale), IBM Plex rendering, a real desktop screen.

## 9. Decision for U3 (from you, after U1)

Keep the 1100x720 minimum (common laptops have only about 730 px of usable height). The right column's hero, method cards and plots become **flexible in height** (stretch factors with sensible minimums): they compress at 720 and take the reference sizes (hero 300, cards 96, plots 290) at 900 or taller. No scrolling and no raised minimum. At U3 I will report how it looks at **1100x720, 1366x768 and 1440x900** using `tools/ui_shots.py` (I will add those sizes to the script). Measured today: the old right column's layout minimum is 761 px; the left column's minimum is 546 px and fits 720.

## 10. U2 report (done)

**Files.** New: none (everything went into the approved `ui/panels.py`). Changed: `ui/theme.py` (tag colours, SNR scale range, 60 s window, light scale, `QUALITY_NAME`), `ui/panels.py` (pure helpers `snr_fraction`, `zone_fractions`, `tick_marks`, `light_bar`; `QualityShare`; `FaceLock`; widgets `SnrScale`, `ShareBar`, `Swatch`, `QualityPanel`), `ui/widgets.py` (`VideoTag`, `VideoView` tags, `Display` gained `snr_db` and `brightness`, signed SNR text), `ui/main_window.py` (quality panel in the left column; share and lock state; tags updated on every refresh), `tests/test_ui.py`, this file. Nothing in the frozen list was touched.

**What now exists.**
- **Video tags.** "FACE LOCKED" (top left) and "LIGHT n / FPS n" (bottom right) are child `QLabel`s 14 px from the corners: mono 11 px, `#C8C8C8` on black at 55%, 1 px `#2C2C2F`, radius 6, padding 7/9. They are never drawn into the frame data (tested: the pixmap is identical before and after the tags change) and hide when there is no video. Light is the existing 1 s ROI brightness average, FPS is `HRResult.fps`; both show "--" until measured.
- **Face lock.** `FaceLock` follows the real flags only: no face gives "NO FACE"; the lock-start flag gives "LOCKING"; the freeze flag gives "FACE LOCKED"; a re-lock goes back to "LOCKING". **One addition to your three states:** a face that appears with no lock flag at all (for example `FREEZE_ROI` off) shows "FACE FOUND", because "LOCKING" or "FACE LOCKED" would claim something the data does not show. With the mock it runs NO FACE, LOCKING (0 to 2 s), FACE LOCKED, NO FACE (52 to 56 s), LOCKING again.
- **Signal quality panel** (under the controls): header with the quality label (Good, Fair, Poor, or "No signal") and a dot; "SNR now" with the signed value (+4.1 dB); the scale from -4 to +8 dB with poor, fair and good zones from `config.SNR_FAIR_DB` and `config.SNR_GOOD_DB` (1/3, 1/6, 1/2 today), a white 2 x 20 px marker clamped to the ends, and tick labels "-4", "0 fair", "+2 good", "+8 dB" (the two middle ones follow config); "Last 60 s of windows" as a proportion bar with 2 px gaps and a legend (Good, Fair, Poor percentages).
- **60 s share.** `QualityShare` is a rolling record in the UI layer: one entry per `_estimate()` using `HRResult.t` and `HRResult.quality`; "n/a" updates (warm-up, no face) are not counted; a repeated timestamp (the same result refreshed again, for example after a method change or end of file) is ignored; entries older than 60 s leave (exactly 60 s old still counts); percentages are whole numbers that sum to 100 by largest remainder; no data shows "--". It is cleared on Start, Stop and when the method changes. The estimator is untouched.
- **Light bar** helper `light_bar(level)` gives the fill (level / 255, clamped) and the threshold tick (`config.LOW_LIGHT_LEVEL / 255`); its widget arrives with the hero in U3. 164 gives 64.3% and 47.1%, matching the reference.

**Changed test assertions** (old behaviour, new behaviour; nothing deleted):
1. `test_display_dims_held_value_and_drops_it_when_none`: `snr_text == "6.0 dB"` (unsigned, one decimal) became `snr_text == "+6.0 dB"` (signed, one decimal, decision 12). The rest of that line is unchanged. The old hero stats line therefore reads "SNR +9.3 dB" until U3.
No other existing assertion changed in U2.

**New tests (28):** SNR marker position (linear, 67.5% at +4.1 dB, clamping, no marker without a value, and a rendered check of the 2 px white marker and of the clamp), zone boundaries (the poor/fair and fair/good edges equal the fractions of the configured thresholds; widths follow monkey-patched thresholds; a good threshold below fair; tick labels and positions from config; rendered zone colours), the 60 s share (the reference's 46/38/16, largest remainder summing to 100 for many sizes, the 60 s boundary, "n/a" and repeated timestamps ignored, clear, bar segments and gaps in pixels), the light bar (64.3% and 47.1%, edges, threshold from config), the face-lock state machine (flag sequences, found-only, reset), the video tags (child widgets, frame untouched, position, hidden without video, follow resize), window integration (tags follow the real mock lock flags and numbers, panel shows the real quality, SNR, marker and share; no double counting; reset on method change and stop), the dot colours, and `Display` carrying the numbers behind its texts. I checked that the new tests can fail: breaking the scale mapping, the lock toggle and the 60 s boundary each made tests fail, and I restored the code.

**Gate evidence.** `pytest -q`: 184 passed (156 + 28). `ui_shots.py --dashboard` and `ui_shots.py` run. `dashboard.png` at 1440x900 shows the new panel and tags. At 1100x720 the left column fits (video 214 px tall, quality panel 206 px); the right column is still the old content and is squeezed, which U3 addresses.

**Observation, not a defect:** the mock's SNR is about +9 to +12 dB, above the +8 dB end of the scale, so the marker sits at the right edge and the displayed value is the real one. Real clips (about -4 to +6 dB) will land inside the scale.

**Not verified:** a real camera session (face-lock labels are verified only against the mock, which mimics `FaceROI`'s flags; I read `face_roi.py` to confirm the flag pattern), real hover, IBM Plex.

## 11. U3 report (done)

**Files.** New: none. Changed: `ui/theme.py` (hero, card and plot sizes and minimums, tick list, colours; obsolete QSS rules removed), `ui/panels.py` (`paint_glass`, shared by `Panel` and the cards), `ui/widgets.py` (the old `Card`, `MethodCell`, `Dot`, old plots and old hero replaced), `ui/main_window.py` (right column rebuilt; `self.cards`, `self.pulse_card`, `self.spectrum_card`), `tools/ui_shots.py` (size shots, quality-panel text), `tests/test_ui.py`, this file. Nothing in the frozen list was touched. PRD.md and TRD.md are not edited (they still say 0.5 to 4 Hz for the spectrum); the change to 54 to 180 BPM is recorded here only.

**What now exists.**
- **Hero panel:** "HEART RATE" with a state dot and the existing state text; the BPM number (light weight, -0.04 em tracking, 112 px at full size, `--` as before, dimmed when held); "BPM"; a heartbeat dot; the live pulse strip with its rate ("1.2 Hz" is the displayed BPM / 60); a stats list on the right: Method, SNR (signed), Light (`n / 255` over a bar filled to n/255 with a tick at `config.LOW_LIGHT_LEVEL / 255`), Window (`15 s`), Range (`54-180`).
- **Heartbeat dot:** a 12 px dot with a ring that grows 1 to 2.4 times and fades 0.7 to 0 once per beat, period `60000 / bpm_smooth` (833 ms at 72). It is **static when there is no number, and also when the number is a held, greyed value** (state "Hold still"): a dot beating for a stale value would imply a live heart rate. That is my reading of "static when there is no number"; say so if you want it to beat for held values too.
- **Live pulse strip:** the newest 5 s of the real `HRResult.pulse` (`t_sig`, `pulse`), scaled by the window's largest absolute value, drawn only from real samples (about 150 points; tested equal to the pulse samples times a constant), a white dot on the newest sample, "Waiting for signal" with no pulse. It redraws only when a new result arrives, on the shared refresh timer (tested). The newest samples come from the zero-phase filter, so they carry its edge effect; the strip shows exactly what the 15 s plot shows at its right-hand end.
- **Method cards:** GREEN, CHROM, POS, each painted as a glass panel (label, quality dot, one-decimal estimate from this window's analysis), scaling 2.5% up on hover and to 97% pressed through the same paint-transform mechanism as the buttons; the active card has a `#D6D6D6` outline and reads "CHROM, ACTIVE" (just the name when the card is too narrow; the outline still marks it).
- **Plots:** "Filtered pulse, last 15 s" (line `#EDEDED`, 1.7 px, dashed zero line, no axes; the "0.9-3.0 Hz" header text hides when the card is too narrow for both texts) and "Spectrum" (faint 12% white area, `#DADADA` 1.5 px line, dashed peak line, view 0.9 to 3.0 Hz = 54 to 180 BPM, tick labels 54, 90, 120, 150, 180 BPM placed in proportion and dropping labels that would touch). Hover shows a white vertical crosshair and "NN BPM / N.NN Hz" in the card header; on leave the header returns to "Peak NN BPM", or "No clear peak" on a poor window, or "--" with no spectrum. Hovering with no data does nothing. Both plots are transparent over the glass panel.
- **Flexible right column:** hero (300 px at the reference size, 190 minimum), cards (96, 72) and plots (290, 150) take stretch factors 300 / 96 / 290 and compress between those limits; the BPM number shrinks (112 px down to 56) to fit the room it has. No scrolling. The window minimum stays 1100x720 and the layout's own minimum is below it (about 1024 x 666 measured), so nothing is squeezed at the minimum.

**How it looks at the three sizes** (from `python tools/ui_shots.py`, files `debug/shots/size_*.png`, mock measuring at about 72 BPM; Windows fonts, not IBM Plex):

| Window | Hero | Cards | Plots | Number | Video | Notes |
|---|---|---|---|---|---|---|
| 1100x720 | 249 | 78 | 240 (219 + 201 wide) | 89 px | 214 | Everything visible, no overlap, no clipping. Plots are cramped but readable: the spectrum card is about 200 px wide and drops the "BPM" unit and middle tick labels where they would touch; the pulse card hides its "0.9-3.0 Hz" header. A 3-digit number (188) still fits (tested). |
| 1366x768 | 270 | 85 | 260 (343 wide each) | 112 px | 262 | Clean; all texts present. |
| 1440x900 | 300 | 96 | 290 (380 wide each) | 112 px | 394 | The reference sizes. The right column ends 87 px above the bottom of the window (the left column is taller), as in the reference. |

Above 900 the extra height goes to the bottom of the right column, because the plots are capped at 290 (at 1920x1080 the gap is about 267 px). One constant, `theme.PLOTS_MAX_H`, set to `None`, lets the plots fill the height instead. I kept the cap because you asked for the reference sizes at 900 or taller.

**Decisions and changes found while building (please note):**
1. **The cards moved out of the hero.** `window.panel.cells` became `window.cards.cells`; the cards are painted widgets (`value_text`, `quality`, `active`) rather than labels with a `.value`.
2. **Qt ignores negative layout margins** (checked: they are clamped to 0), so the cards' hover margin is handled by letting the right column reach 6 px past the hero and plots on each side and shortening the vertical gaps by 6 px; the dashboard's right margin and the top bar compensate. Panel and card edges line up (tested).
3. **pyqtgraph's default background cache (`CacheBackground`) paints an opaque pixmap**, which hid the glass panel behind the plots as a flat light-grey rectangle. The plots now use `CacheNone` (tested: the viewport renders with zero alpha).
4. **The left column is exactly 600 px at every window size** (`theme.LEFT_MIN_W = LEFT_MAX_W = 600`), because the controls rows need about 594 px; the Ref BPM field is 112 px instead of the reference's 120 to fit. At 1100 wide the right column therefore gets 448 px.
5. A bug found while testing the hero: the number was sized from the hero's own resize event, before the layout had given the number row its width, so it stayed at 112 px at the minimum window. A `NumberRow` now reports its own resize.
6. The dashed zero line is hidden while the pulse plot says "Waiting for signal".
7. Tests now set `QT_QPA_FONTDIR` on Windows (as `ui_shots.py` does) so text metrics are real; without fonts several size and text-fitting assertions would have been meaningless.

**Changed test assertions** (old behaviour, new behaviour; none deleted):
1. `test_window_walks_through_every_state`: `p.quality_text.text() == "Good signal"` (hero label) became `window.quality_panel.state_text.text() == "Good"` (the label lives in the quality panel). `{c.value.text() for c in p.cells.values()} == {"72"}` (integers) became a check that each of the three cards reads one decimal and lies within 0.5 of 72.
2. `test_active_method_cell_follows_the_dropdown`: `window.panel.cells[...]` became `window.cards.cells[...]`; `window.panel.stat_method.text() == "Method GREEN"` became `window.panel.stat_values["method"].text() == "GREEN"`. The `active` property checks are unchanged.
3. `test_start_launches_the_worker_and_samples_drive_the_display`: `int(p.stat_light.text().split()[-1])` (text "Light 164") became `int(p.light_value.text().split()[0])` (text "164 / 255"); the 150 to 170 range check is unchanged.

**New tests (40, some parametrised):** number size fitting; heartbeat period from the rate, and a static dot with no number, with a held value and with animations off; `Display.bpm_live`; the pulse tail (newest 5 s, real samples only, edge cases); the strip's dot on the newest sample, the waiting state, redraw-only-on-new-result, and real-pulse content in the window; the stats list; the light bar fill and crisp threshold tick; hero state dot colours; card hover and press scales, no clipping at hover scale, outline colours, one-decimal values, reset on stop; transparent axis-free plots with the specified line widths and colours; the 54 to 180 BPM view; tick labels and collision handling; hover readout text and clamping; peak text on poor windows; hover crosshair, readout and restore (direct, from scene coordinates, and in the window header); plot header text hiding; flexible heights at 1100x720, 1366x768, 1440x900 and 1600x1000 (limits, no overlap, reference sizes at 900+, compression at 720); layout minimum below the window minimum; a 3-digit number at the minimum; panel and card edges lined up; the zero line.

**Gate evidence.** `pytest -q`: 224 passed (184 before U3). `python tools/ui_shots.py` runs and writes every mock state and the three size shots; the mock cycle shows each state correctly (warming up, measuring, more light needed, hold still with a held grey number, hold still with dashes, no face; face tag LOCKING, FACE LOCKED, NO FACE). A real-time 6 s run of the mock through `MainWindow.start()` ran without errors. `tools/ui_shots.py --dashboard` is the 1440x900 steady shot.

**Not verified:** closeness to the reference by eye (the PNG is not in `docs/`; I compared against the HTML's numbers), real mouse hover, IBM Plex rendering (not installed, so all shots use Segoe UI and Consolas), and `python app.py --mock` on a real display (I ran the same window offscreen).

**Known differences from the reference so far:** no Live / Recordings / Evaluation tabs (as briefed); card values to one decimal as in the reference but computed from real analyses; Ref BPM field 112 px; the plots do not absorb extra height above 900 (the cap); the reference's decorative scrolling waveform and drawing animation are not replicated (real data only); the spectrum fill is flat, not a gradient; the Hz readout follows the reference's JavaScript rounding.

## 12. U4 report and final notes (done)

**Changes in U4.**
- Mock frame timer is now a `Qt.PreciseTimer` (`ui/main_window.py`). Qt's default coarse timer gave only about 21 fps from the mock on Windows (the real webcam and file sources are not driven by this timer); it now gives about 29 to 30 fps.
- Accessible names on the icon buttons, the three combo buttons and the Ref BPM field.
- Unused theme constants removed (`ACCENT`, `QUALITY_TEXT`, `BPM_FONT_PX`, `STATE_FONT_PX`).
- README: a "Reading the screen" section for the new panels, the Light frame and Fullscreen rows, the `ui/` file table row, and a "UI screenshots" section (commands, what each writes, the Windows font note, hover not captured).
- New tests (4): the three shortcuts L, F and Esc (checked through the `QShortcut` objects, because the offscreen platform has no active window to deliver key events to), accessible names, the low-light and no-face messages with the new tags and dots, and the font fallback to system fonts when IBM Plex is missing (and Plex when installed).
- `pytest -q`: **228 passed** (224 before U4). `ui_shots.py` and `ui_shots.py --dashboard` run.

**10-minute mock soak** (real time, offscreen, the real `MainWindow.start()` with the mock cycle; a script kept outside the repo). While it ran it did: 66 window resizes cycling 1100x720, 1366x768, 1440x900; 19 light-frame toggles; 26 method switches; 399 hover and press animations on buttons and cards; 1,476 spectrum hovers and leaves.

| | Run 1 | Run 2 |
|---|---|---|
| Frames processed | 16,888 (28.2 fps) | 17,000 (28.3 fps) |
| Event-loop lateness, 20 ms heartbeat: median / p99 / max | -2.6 / 81 / **1,351 ms** | -2.6 / 81 / 336 ms |
| Stalls over 100 ms | 191 | 179 |
| Stalls over 400 ms | at least 1 | 0 |
| Memory (working set) start / 60 s / end / max | 199 / 226 / 228 / 233 MB | 199 / 224 / 225 / 230 MB |
| Exceptions | 0 | 0 |
| States seen | warming up, measuring, more light needed, hold still, no face; tags LOCKING, FACE LOCKED, NO FACE | same |

Memory rises about 25 MB in the first minute and then stays flat (about +2 MB over the next nine minutes): no leak visible. No crash, no exception, every state and tag appeared.

**One freeze-sized stall in run 1 (1,351 ms) did not reproduce.** Run 2, identical apart from extra logging, had a worst stall of 336 ms. I did not capture what caused the first one. It happened while I was editing the README (the project folder is in OneDrive) and a monitor was running on the same machine, so it may be the machine and not the app, but I cannot show that. Treat "no freezes" as met on run 2 and as unproven for run 1.

**The routine stalls are real and have two sources, one of which is not UI code.** With no stress at all (120 s, plain mock cycle) the worst stall was 108 ms with 5 over 100 ms. Under the stress mix, once per second (the estimate tick) the loop stalls for about 110 to 260 ms in bursts. Timing one tick at 1440x900: `estimator.estimate()` about 8 ms; `estimator.analyze_all()` (all three methods, run on the UI thread so the cards can show them side by side) about 66 ms, median, up to 250 ms at the small size; the UI refresh and repaint about 45 to 55 ms. `analyze_all` is in the frozen signal code and its cost predates this restyle (TRD section 3 puts estimation on the main thread). The UI repaint share is mine; it is not zero but it is the smaller part. A fix would be to move estimation to a worker thread, which touches the frozen code and the threading model, so I have not done it.

**Final differences from the reference, and why:**
1. No Live / Recordings / Evaluation tabs: only live exists (as briefed).
2. IBM Plex is used only if installed; it is not installed here, so every shot uses Segoe UI and Consolas, with different text widths and a heavier light weight than Plex Light.
3. Glass is a translucent fill, a 1 px border and a top highlight: Qt has no backdrop blur.
4. Hover and press scaling is a paint transform with a 6 px reserved margin (a 200 px control grows 4.5 px per side), plus a 150 ms colour mix; controls are capped at 200 px wide so nothing clips. The reference's colour transition is 150 ms too. Animations stop with `theme.ANIMATIONS = False`; Qt 6.12 has no reduced-motion setting to read.
5. Method, Source and the device selector are real combo boxes painted like the reference's buttons, with Qt's standard popup.
6. The Ref BPM field is 112 px (reference 120) so the controls fit the 600 px column; the left column is exactly 600 px at every size (reference: flexible 520 to 600 and wraps).
7. Heights are flexible: the hero, cards and plots compress from the reference sizes (300, 96, 290) down to 190, 72 and 150, and the plots are capped at 290 above 900 px (`theme.PLOTS_MAX_H`, `None` makes them fill).
8. The live pulse strip and the 15 s plot show only real samples at 1 Hz updates; the reference's continuous scrolling and drawing animations are decorative and are not reproduced.
9. The heartbeat dot is static for a held value as well as for no number.
10. The face tag has a fourth text, FACE FOUND, for a face with no lock flag; the status line is an extra row in the controls panel; "No signal" is the quality label before any estimate.
11. The spectrum fill is a flat 12% white, not the reference's gradient; tick labels are placed in proportion (the reference spaces them evenly) and drop out when they would touch; the right-hand header text of the pulse card hides when narrow; a card's ", active" is dropped when the card is too narrow (the outline still shows it).
12. The SNR value is signed ("+4.1 dB"), the method estimates are one decimal, and the scale clamps the marker at its ends (the mock's +9 to +12 dB sits at the right end).
13. The spectrum range is 54 to 180 BPM instead of the PRD/TRD 0.5 to 4 Hz; PRD.md and TRD.md were not edited.

**Not verified (carried from earlier phases):** closeness to the reference by eye (the PNG was not in `docs/` at any point; everything was built from the HTML's CSS and markup), real mouse hover, IBM Plex rendering, and a run on a real display with a real webcam. The 10-minute runs were offscreen with the mock source.
