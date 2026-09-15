"""Reusable DSP building blocks: band-limited oscillators, filters, envelopes, bus tools."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.signal import butter, sosfilt, sosfiltfilt

SR = 44100
TABLE_N = 4096


def t_axis(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / SR


def midi_hz(m: float) -> float:
    return 440.0 * (2.0 ** ((m - 69.0) / 12.0))


@lru_cache(maxsize=32)
def _table(kind: str, harmonics: int) -> np.ndarray:
    """Band-limited single-cycle wavetable built additively."""
    phase = np.arange(TABLE_N, dtype=np.float64) / TABLE_N
    k = np.arange(1, harmonics + 1, dtype=np.float64)
    if kind == "square":
        k = k[::2]
    grid = 2.0 * np.pi * np.outer(k, phase)
    if kind == "saw":
        wave = (np.sin(grid) / k[:, None]).sum(axis=0) * (2.0 / np.pi)
    elif kind == "square":
        wave = (np.sin(grid) / k[:, None]).sum(axis=0) * (4.0 / np.pi)
    elif kind == "triangle":
        sign = np.where((k % 4) == 1, 1.0, -1.0)
        wave = ((sign[:, None] * np.sin(grid)) / (k[:, None] ** 2)).sum(axis=0) * (8.0 / np.pi**2)
    else:
        wave = np.sin(2.0 * np.pi * phase)
    return (wave / np.max(np.abs(wave))).astype(np.float64)


def _harmonic_budget(freq: float) -> int:
    """Largest power-of-two partial count that keeps the top harmonic under Nyquist."""
    limit = int(0.45 * SR / max(freq, 1.0))
    limit = max(min(limit, 128), 1)
    return 1 << int(np.floor(np.log2(limit)))


def osc(freq: float, n: int, kind: str = "saw", phase0: float = 0.0) -> np.ndarray:
    """Wavetable oscillator with linear interpolation."""
    table = _table(kind, _harmonic_budget(freq))
    pos = (freq * t_axis(n) + phase0) * TABLE_N
    idx = np.floor(pos).astype(np.int64)
    frac = pos - idx
    i0 = idx % TABLE_N
    i1 = (i0 + 1) % TABLE_N
    return table[i0] * (1.0 - frac) + table[i1] * frac


def supersaw(freq: float, n: int, voices: int = 7, detune_cents: float = 14.0, kind: str = "saw") -> np.ndarray:
    out = np.zeros(n, dtype=np.float64)
    for i, s in enumerate(np.linspace(-1.0, 1.0, voices)):
        f = freq * (2.0 ** (s * detune_cents / 1200.0))
        out += osc(f, n, kind, phase0=(i * 0.137) % 1.0) * (1.0 if abs(s) < 1e-6 else 0.82)
    return out / voices


def exp_env(n: int, decay: float) -> np.ndarray:
    return np.exp(-t_axis(n) / max(decay, 1e-6))


def adsr(n: int, a: float, d: float, s: float, r: float, curve: float = 1.6) -> np.ndarray:
    out = np.zeros(n, dtype=np.float64)
    a_n = min(max(int(a * SR), 1), n)
    out[:a_n] = np.linspace(0.0, 1.0, a_n, endpoint=False) ** (1.0 / curve)
    i = a_n
    if i >= n:
        return out
    d_n = min(max(int(d * SR), 1), n - i)
    out[i : i + d_n] = s + (1.0 - s) * np.linspace(1.0, 0.0, d_n, endpoint=False) ** curve
    i += d_n
    r_n = max(int(r * SR), 1)
    hold_end = max(n - r_n, i)
    if hold_end > i:
        out[i:hold_end] = s
    if n > hold_end:
        out[hold_end:] = s * np.linspace(1.0, 0.0, n - hold_end) ** curve
    return out


def _sos(kind: str, cutoff: float, order: int = 2) -> np.ndarray:
    wn = float(np.clip(cutoff / (0.5 * SR), 1e-4, 0.99))
    return butter(order, wn, btype=kind, output="sos")


def filt(x: np.ndarray, kind: str, cutoff: float, order: int = 2) -> np.ndarray:
    return sosfilt(_sos(kind, cutoff, order), x)


def filt_zero_phase(x: np.ndarray, kind: str, cutoff: float, order: int = 2) -> np.ndarray:
    if len(x) < order * 12:
        return filt(x, kind, cutoff, order)
    return sosfiltfilt(_sos(kind, cutoff, order), x)


def bandpass(x: np.ndarray, low: float, high: float, order: int = 2) -> np.ndarray:
    ny = 0.5 * SR
    lo = float(np.clip(low / ny, 1e-4, 0.98))
    hi = float(np.clip(high / ny, lo + 1e-4, 0.99))
    return sosfilt(butter(order, [lo, hi], btype="band", output="sos"), x)


def sweep_lowpass(x: np.ndarray, start_hz: float, end_hz: float, blocks: int = 64, order: int = 2) -> np.ndarray:
    """Block-wise lowpass with continuous filter state: an audible filter envelope."""
    n = len(x)
    if n < blocks * 4:
        return filt(x, "low", (start_hz + end_hz) * 0.5, order)
    out = np.empty(n, dtype=np.float64)
    edges = np.linspace(0, n, blocks + 1).astype(int)
    cuts = np.geomspace(max(start_hz, 25.0), max(end_hz, 25.0), blocks)
    zi = np.zeros((max(order // 2, 1), 2))
    for i in range(blocks):
        a, b = edges[i], edges[i + 1]
        if b <= a:
            continue
        sos = _sos("low", cuts[i], order)
        if zi.shape[0] != sos.shape[0]:
            zi = np.zeros((sos.shape[0], 2))
        seg, zi = sosfilt(sos, x[a:b], zi=zi)
        out[a:b] = seg
    return out


def smooth(x: np.ndarray, time_const: float) -> np.ndarray:
    """One-pole style smoothing via FFT convolution with an exponential kernel."""
    n = len(x)
    tau = max(time_const, 1e-4)
    k_len = int(min(max(int(tau * SR * 4.0), 8), max(n, 8)))
    kernel = np.exp(-np.arange(k_len) / (tau * SR))
    kernel /= kernel.sum()
    pad = n + k_len
    y = np.fft.irfft(np.fft.rfft(x, n=pad) * np.fft.rfft(kernel, n=pad), n=pad)
    return y[:n]


def envelope_follower(x: np.ndarray, attack: float = 0.004, release: float = 0.11) -> np.ndarray:
    env = np.maximum(smooth(np.abs(x), attack), smooth(np.abs(x), release))
    peak = env.max()
    return env / peak if peak > 0 else env


def formant(x: np.ndarray, vowel: str = "ah") -> np.ndarray:
    banks = {
        "ah": ((700, 1.0), (1220, 0.65), (2600, 0.32)),
        "oo": ((320, 1.0), (800, 0.5), (2400, 0.18)),
        "ee": ((270, 1.0), (2300, 0.7), (3000, 0.28)),
    }
    out = np.zeros_like(x)
    for center, gain in banks.get(vowel, banks["ah"]):
        out += bandpass(x, center * 0.86, center * 1.16, order=2) * gain
    return out


def saturate(x: np.ndarray, drive: float = 1.4, bias: float = 0.0) -> np.ndarray:
    """Asymmetric soft clip; bias adds gentle even harmonics."""
    y = np.tanh(x * drive + bias) - np.tanh(bias)
    return y / max(np.tanh(drive), 1e-6)


def hard_clip(x: np.ndarray, drive: float = 3.0, ceiling: float = 1.0) -> np.ndarray:
    """Aggressive clipper for hard techno kicks and basses."""
    return np.clip(x * drive, -ceiling, ceiling) / max(ceiling, 1e-9)


def noise(n: int, color: str = "white", rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng()
    w = rng.standard_normal(n)
    if color == "white":
        return w
    spec = np.fft.rfft(w)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    freqs[0] = freqs[1] if len(freqs) > 1 else 1.0
    if color == "pink":
        spec /= np.sqrt(freqs)
    elif color == "brown":
        spec /= freqs
    elif color == "blue":
        spec *= np.sqrt(freqs)
    out = np.fft.irfft(spec, n=n)
    peak = np.max(np.abs(out))
    return out / peak if peak > 0 else out


def haas_stereo(mono: np.ndarray, width: float = 0.22, delay_ms: float = 11.0) -> np.ndarray:
    d = int(delay_ms * 1e-3 * SR)
    delayed = np.zeros_like(mono)
    if d > 0:
        delayed[d:] = mono[:-d]
    return np.stack([mono + delayed * width, mono - delayed * width], axis=0)


def pan_stereo(mono: np.ndarray, pan: float) -> np.ndarray:
    """Constant-power panning, pan in [-1, 1]."""
    angle = (float(np.clip(pan, -1.0, 1.0)) + 1.0) * 0.25 * np.pi
    return np.stack([mono * np.cos(angle) * 1.414, mono * np.sin(angle) * 1.414], axis=0)


def mono_bass(stereo: np.ndarray, crossover: float = 140.0) -> np.ndarray:
    """Elliptical EQ: collapse the sub range to mono, keep highs wide."""
    mid = (stereo[0] + stereo[1]) * 0.5
    side = filt((stereo[0] - stereo[1]) * 0.5, "high", crossover, order=2)
    return np.stack([mid + side, mid - side], axis=0)


def widen(stereo: np.ndarray, amount: float = 1.4, above_hz: float = 220.0) -> np.ndarray:
    """Mid/side widening above a crossover, so the low end stays centred."""
    mid = (stereo[0] + stereo[1]) * 0.5
    side = (stereo[0] - stereo[1]) * 0.5
    side = side + filt(side, "high", above_hz, order=2) * (amount - 1.0)
    return np.stack([mid + side, mid - side], axis=0).astype(stereo.dtype)


def rms_db(x: np.ndarray) -> float:
    value = float(np.sqrt(np.mean(np.square(x.astype(np.float64)))))
    return 20.0 * np.log10(max(value, 1e-12))


def fit_level(stereo: np.ndarray, target_db: float) -> np.ndarray:
    """Gain-stage a bus to a target RMS so balance is set by numbers, not guesses."""
    current = rms_db(stereo)
    if not np.isfinite(current) or current < -200.0:
        return stereo
    return (stereo * (10.0 ** ((target_db - current) / 20.0))).astype(np.float32)


def fit_level_active(stereo: np.ndarray, target_db: float, threshold: float = 0.12) -> np.ndarray:
    """Gain-stage using only the parts that actually sound.

    A bus that plays a quarter of the time (a vocal hook, a fill) measures far too quiet when
    its RMS is averaged over the silence, which then makes it too loud after correction.
    """
    env = smooth(envelope_follower(np.abs(stereo).mean(axis=0), 0.01, 0.12), 0.05)
    peak = float(env.max())
    if peak <= 0.0:
        return stereo
    active = stereo[:, env > threshold * peak]
    if active.shape[1] < 1024:
        return fit_level(stereo, target_db)
    current = rms_db(active)
    return (stereo * (10.0 ** ((target_db - current) / 20.0))).astype(np.float32)


def crossfade_lowpass(stereo: np.ndarray, openness: np.ndarray, closed_hz: float = 550.0) -> np.ndarray:
    """Blend between a filtered and an open version of a bus using a 0..1 automation curve."""
    filtered = np.stack([filt(stereo[ch], "low", closed_hz, order=2) for ch in range(stereo.shape[0])], axis=0)
    curve = np.clip(openness, 0.0, 1.0)
    return (stereo * curve + filtered * (1.0 - curve)).astype(np.float32)
