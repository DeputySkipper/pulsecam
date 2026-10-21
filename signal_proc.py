"""Pure signal-processing functions: numpy in, numpy out (TRD section 5.2 to 5.5).

Methods take the uniformly resampled (N, 3) R, G, B array and return a 1-D signal, or None when
the input is degenerate (zero means, constant signal). Everything here is testable without a camera.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

import numpy as np
from scipy.signal import butter, detrend, sosfiltfilt

import config

_SOS = butter(config.FILTER_ORDER, [config.BAND_LO, config.BAND_HI],
              btype="band", fs=config.FS, output="sos")
_PADLEN = 3 * (2 * _SOS.shape[0] + 1)      # sosfiltfilt needs more samples than its default padding


class Analysis(NamedTuple):
    t_sig: np.ndarray        # uniform time axis (s, relative to the first sample)
    raw: np.ndarray          # (N, 3) normalised RGB
    pulse: np.ndarray        # detrended, bandpassed pulse signal
    freqs: np.ndarray        # Hz
    power: np.ndarray
    peak_hz: float
    bpm: float
    snr_db: float | None
    quality: str


def resample(t: np.ndarray, rgb: np.ndarray, fs: float = config.FS) -> tuple[np.ndarray, np.ndarray] | None:
    """Interpolate each channel onto a uniform grid using the real timestamps."""
    t = np.asarray(t, dtype=np.float64)
    rgb = np.asarray(rgb, dtype=np.float64)
    if len(t) < 2 or t[-1] - t[0] <= 0:
        return None
    n = int(np.floor((t[-1] - t[0]) * fs)) + 1
    t_uniform = t[0] + np.arange(n) / fs
    c = np.stack([np.interp(t_uniform, t, rgb[:, i]) for i in range(3)], axis=1)
    return t_uniform, c


def normalise(c: np.ndarray) -> np.ndarray | None:
    """Divide each channel by its temporal mean."""
    mean = c.mean(axis=0)
    if not np.all(np.isfinite(mean)) or np.any(mean < config.MIN_CHANNEL_MEAN):
        return None
    return c / mean


def green(c: np.ndarray) -> np.ndarray | None:
    """Baseline: the normalised green channel minus its mean level of 1."""
    cn = normalise(c)
    return None if cn is None else cn[:, 1] - 1.0


def bandpass(s: np.ndarray) -> np.ndarray | None:
    """Linear detrend, then zero-phase Butterworth bandpass over the heart-rate band."""
    if len(s) <= _PADLEN:
        return None
    return sosfiltfilt(_SOS, detrend(s, type="linear"))


def chrom(c: np.ndarray) -> np.ndarray | None:
    """CHROM (de Haan and Jeanne, 2013): two chrominance axes, combined to cancel common-mode motion."""
    cn = normalise(c)
    if cn is None:
        return None
    r, g, b = cn[:, 0], cn[:, 1], cn[:, 2]
    xf = bandpass(3 * r - 2 * g)
    yf = bandpass(1.5 * r + g - 1.5 * b)
    if xf is None or yf is None or yf.std() < config.MIN_PULSE_STD:
        return None
    return xf - (xf.std() / yf.std()) * yf


def pos(c: np.ndarray) -> np.ndarray | None:
    """POS (Wang et al., 2017): sliding-window projection orthogonal to the skin tone, overlap-added."""
    n = len(c)
    win = int(round(config.POS_WIN_SEC * config.FS))
    if win < 2 or n < win:
        return None
    h_total = np.zeros(n)
    used = 0
    for end in range(win, n + 1):
        w = c[end - win:end]
        mean = w.mean(axis=0)
        if np.any(mean < config.MIN_CHANNEL_MEAN):
            continue
        cw = w / mean                                # temporal normalisation per channel
        s1 = cw[:, 1] - cw[:, 2]
        s2 = cw[:, 1] + cw[:, 2] - 2 * cw[:, 0]
        sd2 = s2.std()
        if sd2 < config.MIN_PULSE_STD:
            continue
        h = s1 + (s1.std() / sd2) * s2
        h_total[end - win:end] += h - h.mean()
        used += 1
    return h_total if used else None


METHODS: dict[str, Callable[[np.ndarray], np.ndarray | None]] = {
    "GREEN": green,
    "CHROM": chrom,
    "POS": pos,
}


def spectrum(pulse: np.ndarray, fs: float = config.FS) -> tuple[np.ndarray, np.ndarray]:
    """Hann-windowed, zero-padded power spectrum."""
    x = np.fft.rfft(pulse * np.hanning(len(pulse)), n=config.NFFT)
    return np.fft.rfftfreq(config.NFFT, 1.0 / fs), np.abs(x) ** 2


def find_peak(freqs: np.ndarray, power: np.ndarray, fs: float = config.FS) -> float | None:
    """Peak frequency (Hz) inside the heart-rate band, refined by parabolic interpolation."""
    idx = np.flatnonzero((freqs >= config.BAND_LO) & (freqs <= config.BAND_HI))
    if len(idx) == 0:
        return None
    k = int(idx[np.argmax(power[idx])])
    if power[k] <= 0:
        return None
    if k == 0 or k == len(power) - 1:
        return float(freqs[k])
    a, b, c = power[k - 1], power[k], power[k + 1]
    denom = a - 2 * b + c
    p = 0.5 * (a - c) / denom if denom != 0 else 0.0
    return float((k + p) * fs / config.NFFT)


def snr_db(freqs: np.ndarray, power: np.ndarray, peak_hz: float) -> float | None:
    """Power within +-SNR_HALF_WIDTH_HZ of the peak vs. the rest of the in-band power."""
    in_band = (freqs >= config.BAND_LO) & (freqs <= config.BAND_HI)
    near = np.abs(freqs - peak_hz) <= config.SNR_HALF_WIDTH_HZ
    p_sig = power[in_band & near].sum()
    p_noise = power[in_band & ~near].sum()
    if p_sig <= 0 or p_noise <= 0:
        return None
    return float(10.0 * np.log10(p_sig / p_noise))


def classify_quality(snr: float | None) -> str:
    if snr is None:
        return "n/a"
    if snr >= config.SNR_GOOD_DB:
        return "good"
    if snr >= config.SNR_FAIR_DB:
        return "fair"
    return "poor"


def analyze(t: np.ndarray, rgb: np.ndarray, method: str) -> Analysis | None:
    """Timestamps + raw RGB samples -> pulse, spectrum, BPM, SNR. None if the input is degenerate."""
    resampled = resample(t, rgb)
    if resampled is None:
        return None
    t_uniform, c = resampled
    raw = normalise(c)
    s = METHODS[method](c)
    if raw is None or s is None:
        return None
    pulse = bandpass(s)
    if pulse is None or not np.all(np.isfinite(pulse)) or pulse.std() < config.MIN_PULSE_STD:
        return None
    freqs, power = spectrum(pulse)
    peak_hz = find_peak(freqs, power)
    if peak_hz is None:
        return None
    snr = snr_db(freqs, power, peak_hz)
    return Analysis(t_sig=t_uniform - t_uniform[0], raw=raw, pulse=pulse, freqs=freqs, power=power,
                    peak_hz=peak_hz, bpm=60.0 * peak_hz, snr_db=snr, quality=classify_quality(snr))
