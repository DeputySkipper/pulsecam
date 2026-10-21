"""Every tunable for PulseCam. No magic numbers elsewhere (TRD section 7)."""

# Capture
CAM_INDEX = 0
FRAME_W, FRAME_H = 640, 480
FPS_REQUEST = 30              # actual FPS is measured
TRY_LOCK_CAMERA = False       # AVFoundation ignores exposure/WB props (P1 check); see Decisions D12
CAM_WARMUP_SEC = 3.0

# Face and ROI
DETECT_EVERY_N = 3            # frames
BOX_EMA_ALPHA = 0.3
FACE_LOST_SEC = 1.0
MOTION_THRESH = 0.10          # fraction of face width
FREEZE_ROI = True             # lock the face box after ROI_LOCK_SEC so ROI jitter cannot enter the signal
ROI_LOCK_SEC = 2.0            # detect + EMA-smooth for this long after (re)acquiring the face, then freeze
RELOCK_CHECK_SEC = 1.0        # while frozen, compare a fresh detection against the frozen box this often
RELOCK_MOVE_FRAC = 0.08       # re-lock if the face centre moved more than this fraction of box width
RELOCK_CONFIRM_CHECKS = 2     # consecutive checks that must agree on the move before re-locking
SEAM_MATCH_SEC = 2.0          # on a re-lock the buffer is kept; the new segment is gain-matched over this long (about 2.4 pulse cycles)
SEAM_MIN_SEC = 0.5            # less than this much earlier data: nothing to match against
USE_SKIN_MASK = False         # Should item (S2), not built; needs approval

# Buffer and resampling
WINDOW_SEC = 15.0
MIN_SEC = 10.0                # time to first reading
GAP_RESET_SEC = 1.0
FS = 30.0                     # resample rate, Hz

# Filtering and spectrum
BAND_LO, BAND_HI = 0.9, 3.0   # Hz, i.e. 54 to 180 BPM (resting adults)
FILTER_ORDER = 3
POS_WIN_SEC = 1.6
NFFT = 2048

# Numerical guards (signal_proc returns None below these)
MIN_CHANNEL_MEAN = 1e-6       # mean of any RGB channel
MIN_PULSE_STD = 1e-9          # std of the filtered pulse

# Quality and smoothing
SNR_HALF_WIDTH_HZ = 0.15
SNR_GOOD_DB, SNR_FAIR_DB = 2.0, 0.0   # fair at 0 dB: above white-noise p99; good at +2 dB (offline sweep on a ground-truth clip)
SMOOTH_K = 5
MAX_JUMP_BPM = 15
HOLD_MAX_SEC = 5.0            # poor quality longer than this: drop the held BPM and the smoothing history
CONFIRM_ESTIMATES = 3         # a number is first displayed after this many consecutive non-poor estimates...
CONFIRM_AGREE_BPM = 5.0       # ...whose spread (max - min) is within this
JUMP_PERSIST = 5              # consecutive agreeing updates needed to accept a jump

# UI
UPDATE_SEC = 1.0
PLOT_REFRESH_MS = 100
LIGHT_FRAME_PX = 100
LIGHT_FRAME_DEFAULT = False   # Should item (M8 demoted): fixed phone torch is the lighting plan
LOW_LIGHT_LEVEL = 120.0       # provisional: mean ROI RGB (0-255) below this shows "More light needed". Tubelight runs (~107) were unstable or failed, torch (~156) passed
LOW_LIGHT_WINDOW_SEC = 1.0    # brightness is averaged over this long before comparing
DEFAULT_METHOD = "CHROM"

# Face geometry (TRD 5.1), fractions of the face box (x0, y0, x1, y1)
ROI_FRACTIONS = {
    "forehead": (0.30, 0.10, 0.70, 0.25),
    "left_cheek": (0.15, 0.50, 0.35, 0.70),
    "right_cheek": (0.65, 0.50, 0.85, 0.70),
}
ROI_SET = "cheeks"            # "all" (forehead + both cheeks) or "cheeks"
ROI_SETS = {
    "all": ("forehead", "left_cheek", "right_cheek"),
    "cheeks": ("left_cheek", "right_cheek"),
}
HAAR_SCALE_FACTOR = 1.1
HAAR_MIN_NEIGHBORS = 5
HAAR_MIN_SIZE = 80            # px at full resolution
DETECT_DOWNSCALE = 2
PREVIEW_W = 480               # preview width (px); height keeps the aspect ratio

# Mock source (TRD 6). Colour values are 0-1 fractions; samples are emitted on the 0-255 camera scale.
MOCK_BPM = 72.0
MOCK_BASE_RGB = (0.75, 0.60, 0.55)   # mean about 161 on the 0-255 scale, like the torch runs
RGB_MAX = 255.0
# Scenario cycle: (phase, seconds). Exercises every UI state:
#   measuring: face + clean pulse (10 s warm-up first, then readings)   dim: same, but darker (low-light hint)
#   poor: pulse buried in strong in-band interference (long enough for the hold limit to show "--")   no_face: no face
MOCK_SCENARIO = (("measuring", 30.0), ("dim", 8.0), ("poor", 14.0), ("no_face", 4.0))
MOCK_DIM_GAIN = 0.30          # brightness multiplier in the dim phase
MOCK_RAMP_SEC = 1.5           # brightness changes ramp over this long (no steps in the signal)
MOCK_POOR_TONES = (0.95, 3.0, 22)   # poor phase: flat-spectrum in-band interference (lo Hz, hi Hz, count), so no peak dominates
MOCK_POOR_TONE_AMP = 0.012    # each tone, relative units (the 22 together are about 10x the pulse power)
MOCK_AMPLITUDE = 0.005
MOCK_PULSE_DIR = (0.33, 0.77, 0.53)
MOCK_DRIFT_AMP = 0.01
MOCK_DRIFT_HZ = 0.05
MOCK_NOISE_SIGMA = 0.001
MOCK_HZ = 30.0

# Recording, offline mode and the reading logger (TRD section 9)
RECORDINGS_DIR = "recordings"
RESULTS_DIR = "results"
READINGS_CSV = "readings.csv"
RECORD_FPS_PROBE_FRAMES = 90  # frames (3 s) buffered to measure the real fps before the video writer opens; a header fps that is off by x% makes offline playback read x% off
RECORD_MJPG_QUALITY = 95      # fallback codec quality (lossy; logged as a warning)
REF_DEVICES = ("pulse count", "smartwatch", "pulse oximeter")
# How far to trust each reference when it is a single number for a whole clip (evaluation labels it in the table)
REF_CONFIDENCE = {"pulse count": "lower (hand count)", "smartwatch": "device", "pulse oximeter": "device"}
EVAL_TOLERANCE_BPM = 10.0     # a window counts as correct within this of the reference
