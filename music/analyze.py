"""Objective mix report for any render: loudness, band balance, stereo, stem levels.

Usage: python analyze.py [wav] [stem_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from dsp import bandpass, filt

HERE = Path(__file__).resolve().parent
BANDS = (("sub", 20, 60), ("low", 60, 200), ("lowmid", 200, 800), ("mid", 800, 3000), ("high", 3000, 16000))


def db(x: float) -> float:
    return 20.0 * np.log10(max(x, 1e-12))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def section_ranges(wav_name: str) -> list[tuple[str, float, float]]:
    """Pull section boundaries from whichever arrangement module matches the render."""
    if "hardtech" in wav_name:
        import hardtech_arrangement as module
    else:
        import arrangement as module
    out: list[tuple[str, float, float]] = []
    start_bar = 0
    for bar in range(1, module.BARS + 1):
        if bar == module.BARS or module.section_of(bar) != module.section_of(start_bar):
            out.append((module.SECTION_NAMES[module.section_of(start_bar)], start_bar * module.BAR, bar * module.BAR))
            start_bar = bar
    return out


def main() -> None:
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "hardtech_remix_152bpm.wav"
    if not wav.is_absolute():
        wav = HERE / wav
    stem_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / ("stems_hardtech" if "hardtech" in wav.name else "stems")
    if not stem_dir.is_absolute():
        stem_dir = HERE / stem_dir

    audio, sr = sf.read(wav, always_2d=True)
    audio = audio.T
    meter = pyln.Meter(sr)
    mono = audio.mean(axis=0)
    peak = float(np.abs(audio).max())
    print(f"file: {wav.name}  {audio.shape[1] / sr:.1f}s @ {sr} Hz")
    print(f"integrated {meter.integrated_loudness(audio.T):.1f} LUFS | peak {db(peak):.2f} dBFS | crest {db(peak / max(rms(audio), 1e-12)):.1f} dB")

    print("\nper-section loudness")
    for name, start, end in section_ranges(wav.name):
        seg = audio[:, int(start * sr) : int(end * sr)]
        if seg.shape[1] < sr:
            continue
        print(
            f"  {name:<10} {start:6.1f}-{end:6.1f}s  {meter.integrated_loudness(seg.T):6.1f} LUFS"
            f"  peak {db(float(np.abs(seg).max())):6.2f} dB"
        )

    print("\nband balance (dB relative to total)")
    total = rms(mono)
    for name, low, high in BANDS:
        band = filt(mono, "low", high, order=2) if low <= 20 else bandpass(mono, low, high, order=2)
        print(f"  {name:<7} {db(rms(band) / total):6.1f} dB")

    mid = (audio[0] + audio[1]) * 0.5
    side = (audio[0] - audio[1]) * 0.5
    print(f"\nstereo: side/mid {db(rms(side) / max(rms(mid), 1e-12)):.1f} dB")
    print(f"  sub side energy {db(rms(filt(side, 'low', 120.0, order=2)) / max(rms(side), 1e-12)):.1f} dB (lower is tighter)")
    print(f"  L/R correlation {float(np.corrcoef(audio[0], audio[1])[0, 1]):.3f}")

    if stem_dir.exists():
        print(f"\nstem levels ({stem_dir.name})")
        for path in sorted(stem_dir.glob("*.wav")):
            data, _ = sf.read(path, always_2d=True)
            print(f"  {path.stem:<10} rms {db(rms(data.T)):6.1f} dB  peak {db(float(np.abs(data).max())):6.1f} dB")


if __name__ == "__main__":
    main()
