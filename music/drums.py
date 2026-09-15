"""Drum and FX one-shots synthesized with numpy, including hard techno variants."""

from __future__ import annotations

import numpy as np

from dsp import (
    SR,
    adsr,
    bandpass,
    exp_env,
    filt,
    hard_clip,
    noise,
    osc,
    saturate,
    sweep_lowpass,
    t_axis,
)


def samples(seconds: float) -> int:
    return int(round(seconds * SR))


# ------------------------------------------------------------------ melodic techno kit


def kick(rng: np.random.Generator) -> np.ndarray:
    n = samples(0.52)
    t = t_axis(n)
    pitch = 46.0 + 120.0 * np.exp(-t / 0.019) + 20.0 * np.exp(-t / 0.085)
    body = np.sin(2.0 * np.pi * np.cumsum(pitch) / SR) * exp_env(n, 0.175)
    sub = np.sin(2.0 * np.pi * 45.0 * t) * exp_env(n, 0.28) * 0.5
    click_n = samples(0.007)
    click = filt(noise(click_n, "blue", rng), "high", 2600.0) * np.linspace(1.0, 0.0, click_n) ** 2
    out = saturate(body * 1.2 + sub, 1.75)
    out[:click_n] += click * 0.3
    return filt(out, "high", 27.0, order=2) * 0.98


def clap(rng: np.random.Generator) -> np.ndarray:
    n = samples(0.34)
    out = np.zeros(n)
    for offset, amp in ((0.0, 1.0), (0.010, 0.72), (0.019, 0.5), (0.028, 0.3)):
        burst_n = samples(0.02)
        burst = bandpass(noise(burst_n, "white", rng), 900.0, 6500.0)
        burst *= np.linspace(1.0, 0.0, burst_n) ** 1.4 * amp
        start = samples(offset)
        out[start : start + burst_n] += burst
    tail = bandpass(noise(n, "white", rng), 1100.0, 5200.0) * exp_env(n, 0.07) * 0.28
    return (out + tail) * 0.5


def hat(rng: np.random.Generator, open_hat: bool = False) -> np.ndarray:
    n = samples(0.26 if open_hat else 0.055)
    metallic = np.zeros(n)
    for freq in (6200.0, 8100.0, 9700.0, 11800.0):
        metallic += osc(freq, n, "square") * 0.25
    body = bandpass(noise(n, "white", rng) * 0.75 + metallic * 0.25, 6000.0, 14000.0)
    env = exp_env(n, 0.10 if open_hat else 0.015)
    return saturate(body * env, 1.3) * (0.22 if open_hat else 0.28)


def ride(rng: np.random.Generator) -> np.ndarray:
    n = samples(0.5)
    body = bandpass(noise(n, "white", rng), 4500.0, 12000.0)
    ping = osc(5300.0, n, "sine") * 0.18
    return (body + ping) * exp_env(n, 0.17) * 0.13


def rim(rng: np.random.Generator) -> np.ndarray:
    n = samples(0.07)
    tone = osc(1750.0, n, "triangle") + 0.5 * osc(2480.0, n, "sine")
    return saturate(tone * exp_env(n, 0.011), 2.0) * 0.2


def shaker(rng: np.random.Generator) -> np.ndarray:
    n = samples(0.09)
    body = bandpass(noise(n, "white", rng), 5200.0, 11000.0)
    return body * adsr(n, 0.008, 0.02, 0.25, 0.05) * 0.15


# ------------------------------------------------------------------ hard techno kit


def hard_kick(rng: np.random.Generator, root_hz: float = 51.0) -> np.ndarray:
    """Distorted kick with a long tuned tail: the backbone of hardtech."""
    n = samples(0.58)
    t = t_axis(n)
    pitch = root_hz + 210.0 * np.exp(-t / 0.012) + 46.0 * np.exp(-t / 0.05)
    punch = np.sin(2.0 * np.pi * np.cumsum(pitch) / SR) * exp_env(n, 0.09)
    tail = np.sin(2.0 * np.pi * root_hz * t) * exp_env(n, 0.30)
    tail += 0.35 * np.sin(2.0 * np.pi * root_hz * 2.0 * t) * exp_env(n, 0.16)
    click_n = samples(0.006)
    click = filt(noise(click_n, "blue", rng), "high", 3200.0) * np.linspace(1.0, 0.0, click_n) ** 2
    body = hard_clip(punch * 1.5 + tail * 1.1, drive=2.6)
    body = saturate(body, 2.2)
    body[:click_n] += click * 0.35
    return filt(body, "high", 32.0, order=2) * 0.95


def industrial_clap(rng: np.random.Generator) -> np.ndarray:
    n = samples(0.42)
    out = np.zeros(n)
    for offset, amp in ((0.0, 1.0), (0.008, 0.8), (0.016, 0.6), (0.026, 0.45), (0.036, 0.3)):
        burst_n = samples(0.024)
        burst = bandpass(noise(burst_n, "white", rng), 1400.0, 8000.0)
        burst *= np.linspace(1.0, 0.0, burst_n) ** 1.2 * amp
        start = samples(offset)
        out[start : start + burst_n] += burst
    tail = bandpass(noise(n, "white", rng), 1800.0, 7000.0) * exp_env(n, 0.11) * 0.35
    return saturate(out + tail, 2.0) * 0.55


def hard_snare(rng: np.random.Generator) -> np.ndarray:
    n = samples(0.24)
    t = t_axis(n)
    tone = np.sin(2.0 * np.pi * 190.0 * t) * exp_env(n, 0.045)
    tone += 0.6 * np.sin(2.0 * np.pi * 278.0 * t) * exp_env(n, 0.035)
    rattle = bandpass(noise(n, "white", rng), 1500.0, 9000.0) * exp_env(n, 0.08)
    return saturate(tone * 0.5 + rattle * 0.7, 2.4) * 0.6


def zap(rng: np.random.Generator) -> np.ndarray:
    """Short metallic blip used as offbeat percussion."""
    n = samples(0.11)
    pitch = np.geomspace(2600.0, 420.0, n)
    sig = np.sin(2.0 * np.pi * np.cumsum(pitch) / SR) * exp_env(n, 0.022)
    return saturate(sig, 2.6) * 0.28


def siren(dur: float, rng: np.random.Generator, low: float = 380.0, high: float = 1500.0) -> np.ndarray:
    n = samples(dur)
    t = t_axis(n)
    lfo = 0.5 + 0.5 * np.sin(2.0 * np.pi * (2.0 / max(dur, 0.1)) * t)
    pitch = low + (high - low) * lfo
    sig = np.sin(2.0 * np.pi * np.cumsum(pitch) / SR)
    env = adsr(n, dur * 0.15, dur * 0.2, 0.7, dur * 0.35)
    return saturate(sig * env, 2.2) * 0.22


def rumble(dur: float, rng: np.random.Generator, root_hz: float = 44.0) -> np.ndarray:
    """Reverb-style low rumble that glues hard kicks together."""
    n = samples(dur)
    t = t_axis(n)
    sig = np.sin(2.0 * np.pi * root_hz * t) * 0.7
    sig += np.sin(2.0 * np.pi * root_hz * 1.5 * t) * 0.25
    sig += filt(noise(n, "brown", rng), "low", 120.0) * 0.5
    tremolo = 0.75 + 0.25 * np.sin(2.0 * np.pi * 3.0 * t)
    return saturate(sig * tremolo, 1.4) * 0.3


# ------------------------------------------------------------------ transitions


def riser(dur: float, rng: np.random.Generator) -> np.ndarray:
    n = samples(dur)
    t = t_axis(n)
    prog = t / dur
    swept = sweep_lowpass(filt(noise(n, "white", rng), "high", 500.0), 900.0, 12000.0, blocks=96)
    tone = np.sin(2.0 * np.pi * np.cumsum(np.geomspace(180.0, 2400.0, n)) / SR) * 0.2
    trem = 0.65 + 0.35 * np.sin(2.0 * np.pi * (2.0 + 14.0 * prog**2) * t)
    return saturate((swept * 0.6 + tone) * prog**1.6 * trem, 1.2) * 0.4


def downlifter(dur: float, rng: np.random.Generator) -> np.ndarray:
    n = samples(dur)
    sweep = np.sin(2.0 * np.pi * np.cumsum(np.geomspace(2600.0, 90.0, n)) / SR)
    air = sweep_lowpass(filt(noise(n, "white", rng), "high", 300.0), 9000.0, 500.0, blocks=64)
    return (sweep * 0.4 + air * 0.5) * exp_env(n, dur * 0.45) * 0.33


def reverse_cymbal(dur: float, rng: np.random.Generator) -> np.ndarray:
    n = samples(dur)
    body = bandpass(noise(n, "white", rng), 3000.0, 13000.0)
    return body * np.linspace(0.0, 1.0, n) ** 2.4 * 0.28


def impact(rng: np.random.Generator) -> np.ndarray:
    n = samples(1.4)
    boom = np.sin(2.0 * np.pi * np.cumsum(np.geomspace(150.0, 38.0, n)) / SR) * exp_env(n, 0.4)
    crash = bandpass(noise(n, "white", rng), 1800.0, 12000.0) * exp_env(n, 0.5) * 0.32
    return saturate(boom * 0.9 + crash, 1.3) * 0.55


def sub_drop(rng: np.random.Generator) -> np.ndarray:
    n = samples(1.8)
    pitch = np.geomspace(110.0, 26.0, n)
    sig = np.sin(2.0 * np.pi * np.cumsum(pitch) / SR) * adsr(n, 0.01, 0.4, 0.5, 1.1)
    return saturate(sig, 1.2) * 0.75


def atmosphere(dur: float, rng: np.random.Generator, root_hz: float) -> np.ndarray:
    n = samples(dur)
    t = t_axis(n)
    bed = bandpass(noise(n, "pink", rng), 300.0, 4200.0)
    drift = 0.4 + 0.6 * (0.5 + 0.5 * np.sin(2.0 * np.pi * 0.045 * t))
    tone = osc(root_hz, n, "sine") * 0.08 * drift
    return (bed * 0.22 + tone) * drift * 0.2
