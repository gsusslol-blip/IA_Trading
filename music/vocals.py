"""Vocal pipeline: Demucs separation, phrase detection, key/tempo estimation, grid fitting.

Feed it a file you legally own in music/input/. Nothing is downloaded from streaming sites.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import time_stretch

from dsp import SR, bandpass, envelope_follower, filt, midi_hz, smooth

HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "input"
SEPARATED_DIR = HERE / "separated"
AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma")
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


@dataclass(slots=True)
class Phrase:
    start: float
    end: float
    peak_db: float

    @property
    def dur(self) -> float:
        return self.end - self.start


def find_input() -> Path | None:
    if not INPUT_DIR.exists():
        return None
    files = [p for p in sorted(INPUT_DIR.iterdir()) if p.suffix.lower() in AUDIO_EXTS]
    return files[0] if files else None


def separate(source: Path, model: str = "htdemucs", two_stems: str = "vocals") -> dict[str, Path]:
    """Run Demucs and return the produced stem paths (cached if already separated)."""
    out_root = SEPARATED_DIR / model / source.stem
    vocals = out_root / "vocals.wav"
    accompaniment = out_root / "no_vocals.wav"
    if vocals.exists() and accompaniment.exists():
        return {"vocals": vocals, "no_vocals": accompaniment}
    SEPARATED_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "demucs.separate",
        "-n",
        model,
        "--two-stems",
        two_stems,
        "-o",
        str(SEPARATED_DIR),
        str(source),
    ]
    print("  running:", " ".join(command[2:]))
    subprocess.run(command, check=True)
    return {"vocals": vocals, "no_vocals": accompaniment}


def load_mono(path: Path, target_sr: int = SR) -> np.ndarray:
    audio, sr = sf.read(path, always_2d=True, dtype="float32")
    mono = audio.mean(axis=1)
    if sr != target_sr:
        mono = np.asarray(
            time_stretch(mono[np.newaxis, :], sr, stretch_factor=sr / target_sr, pitch_shift_in_semitones=0.0)
        )[0]
    return mono.astype(np.float32)


def load_stereo(path: Path) -> np.ndarray:
    audio, sr = sf.read(path, always_2d=True, dtype="float32")
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    return audio.T[:2].astype(np.float32)


def detect_phrases(
    vocal: np.ndarray,
    threshold_db: float = -34.0,
    min_dur: float = 0.55,
    max_gap: float = 0.28,
) -> list[Phrase]:
    """Gate the vocal envelope into sung phrases, merging short gaps."""
    env = envelope_follower(bandpass(vocal, 150.0, 6000.0), attack=0.01, release=0.12)
    env_db = 20.0 * np.log10(np.maximum(smooth(env, 0.03), 1e-9))
    active = env_db > threshold_db
    edges = np.diff(active.astype(np.int8))
    starts = list((np.flatnonzero(edges == 1) + 1))
    ends = list(np.flatnonzero(edges == -1) + 1)
    if active[0]:
        starts.insert(0, 0)
    if active[-1]:
        ends.append(len(active))

    merged: list[list[int]] = []
    for s, e in zip(starts, ends):
        if merged and (s - merged[-1][1]) / SR <= max_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])

    phrases: list[Phrase] = []
    for s, e in merged:
        if (e - s) / SR < min_dur:
            continue
        peak = float(np.max(np.abs(vocal[s:e])))
        phrases.append(Phrase(s / SR, e / SR, 20.0 * np.log10(max(peak, 1e-9))))
    return phrases


def estimate_tempo(mono: np.ndarray, low_bpm: float = 60.0, high_bpm: float = 200.0) -> float:
    """Autocorrelation of the onset envelope; good enough to pick a stretch ratio."""
    band = filt(mono, "low", 4000.0, order=2)
    env = envelope_follower(band, attack=0.005, release=0.05)
    env = np.diff(smooth(env, 0.02), prepend=0.0)
    env = np.maximum(env, 0.0)
    hop = 256
    frames = env[: len(env) // hop * hop].reshape(-1, hop).mean(axis=1)
    frames -= frames.mean()
    corr = np.correlate(frames, frames, mode="full")[len(frames) - 1 :]
    frame_rate = SR / hop
    lag_min = int(frame_rate * 60.0 / high_bpm)
    lag_max = int(frame_rate * 60.0 / low_bpm)
    window = corr[lag_min:lag_max]
    if len(window) == 0:
        return 0.0
    best = int(np.argmax(window)) + lag_min
    return float(60.0 * frame_rate / best)


def estimate_key(mono: np.ndarray) -> tuple[str, bool, int]:
    """Chroma template match; returns (name, is_minor, tonic_midi_class)."""
    spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / SR)
    mask = (freqs > 55.0) & (freqs < 2200.0)
    spec, freqs = spec[mask], freqs[mask]
    midi = 69.0 + 12.0 * np.log2(np.maximum(freqs, 1e-6) / 440.0)
    chroma = np.zeros(12)
    np.add.at(chroma, np.round(midi).astype(int) % 12, spec)
    chroma /= max(chroma.sum(), 1e-9)

    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    major /= major.sum()
    minor /= minor.sum()

    best = (-1.0, 0, True)
    for tonic in range(12):
        for template, is_minor in ((minor, True), (major, False)):
            score = float(np.corrcoef(chroma, np.roll(template, tonic))[0, 1])
            if score > best[0]:
                best = (score, tonic, is_minor)
    _, tonic, is_minor = best
    return f"{NOTE_NAMES[tonic]}{'m' if is_minor else ''}", is_minor, tonic


def fit_to_grid(
    audio: np.ndarray,
    source_dur: float,
    target_dur: float,
    semitones: float = 0.0,
    preserve_formants: bool = True,
) -> np.ndarray:
    """Stretch a slice so it lands exactly on a musical length, optionally retuned."""
    if source_dur <= 0.0 or target_dur <= 0.0:
        return audio
    factor = float(source_dur / target_dur)
    mono_in = audio if audio.ndim == 2 else audio[np.newaxis, :]
    out = np.asarray(
        time_stretch(
            np.ascontiguousarray(mono_in, dtype=np.float32),
            SR,
            stretch_factor=factor,
            pitch_shift_in_semitones=float(semitones),
            high_quality=True,
            transient_mode="crisp",
            preserve_formants=preserve_formants,
        ),
        dtype=np.float32,
    )
    # the stretcher lands within ~1% of the request; force the exact musical length
    want = int(round(target_dur * SR))
    if out.shape[1] > want:
        fade = min(int(0.01 * SR), want // 4)
        out = out[:, :want].copy()
        out[:, want - fade :] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    elif out.shape[1] < want:
        out = np.pad(out, ((0, 0), (0, want - out.shape[1])))
    return out


def slice_phrase(stereo: np.ndarray, phrase: Phrase, pad: float = 0.05) -> np.ndarray:
    start = max(int((phrase.start - pad) * SR), 0)
    end = min(int((phrase.end + pad) * SR), stereo.shape[1])
    return stereo[:, start:end]


def report(source: Path) -> None:
    stems = separate(source)
    vocal_stereo = load_stereo(stems["vocals"])
    vocal_mono = vocal_stereo.mean(axis=0)
    full = load_mono(source)
    phrases = detect_phrases(vocal_mono)
    key, is_minor, tonic = estimate_key(full)
    print(f"source: {source.name}  ({full.shape[0] / SR:.1f}s)")
    print(f"tempo estimate: {estimate_tempo(full):.1f} BPM")
    print(f"key estimate: {key} (tonic pitch class {tonic}, {'minor' if is_minor else 'major'})")
    print(f"phrases detected: {len(phrases)}")
    for i, phrase in enumerate(phrases):
        print(f"  [{i:2d}] {phrase.start:7.2f}s - {phrase.end:7.2f}s  ({phrase.dur:4.2f}s, peak {phrase.peak_db:6.1f} dB)")


if __name__ == "__main__":
    found = find_input()
    if found is None:
        print(f"no audio found. Drop the song into: {INPUT_DIR}")
    else:
        report(found)
