"""Turn Piper TTS speech into a sung line: syllable segmentation, pitch mapping, vowel sustain.

The synth voice is generated locally with the project's own Piper voices, so no copyrighted
recording is involved: this is our own performance of the melody.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from pedalboard import time_stretch
from scipy.signal import find_peaks, resample_poly

from dsp import SR, bandpass, envelope_follower, filt, midi_hz, smooth

REPO = Path(__file__).resolve().parent.parent
PIPER_EXE = REPO / "bin" / "piper" / "piper.exe"
ESPEAK_DATA = REPO / "bin" / "piper" / "espeak-ng-data"
VOICE_DIR = REPO / "data" / "tts"
DEFAULT_VOICE = "es_AR-daniela-high"
CACHE_DIR = Path(__file__).resolve().parent / "cache_voice"


@dataclass(slots=True)
class SungNote:
    """One syllable pinned to one note of the melody."""

    beat: float
    midi: int
    beats: float
    text: str


def voice_model(name: str = DEFAULT_VOICE) -> Path:
    model = VOICE_DIR / f"{name}.onnx"
    if not model.is_file():
        raise FileNotFoundError(f"missing Piper voice: {model}")
    return model


def speak(text: str, voice: str = DEFAULT_VOICE, length_scale: float = 1.25) -> np.ndarray:
    """Synthesize one chunk of Spanish text, returned as mono float32 at SR."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() else "_" for ch in text.lower())[:48]
    cached = CACHE_DIR / f"{voice}_{length_scale:.2f}_{safe}.wav"
    if not cached.exists():
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.wav"
            command = [
                str(PIPER_EXE),
                "--model",
                str(voice_model(voice)),
                "--output_file",
                str(out),
                "--length_scale",
                f"{length_scale:.2f}",
                "--noise_scale",
                "0.55",
                "--noise_w",
                "0.6",
                "--quiet",
            ]
            if ESPEAK_DATA.is_dir():
                command += ["--espeak_data", str(ESPEAK_DATA)]
            subprocess.run(
                command,
                input=(text.strip() + "\n").encode("utf-8"),
                cwd=str(PIPER_EXE.parent),
                check=True,
                capture_output=True,
                timeout=60,
            )
            audio, sr = sf.read(out, always_2d=True, dtype="float32")
        mono = audio.mean(axis=1)
        if sr != SR:
            mono = resample_poly(mono, SR, sr).astype(np.float32)
        sf.write(cached, mono, SR, subtype="FLOAT")
    data, _ = sf.read(cached, dtype="float32")
    return np.asarray(data, dtype=np.float32)


def trim_silence(x: np.ndarray, floor_db: float = -42.0) -> np.ndarray:
    env = envelope_follower(x, 0.004, 0.05)
    loud = np.flatnonzero(20.0 * np.log10(np.maximum(env, 1e-9)) > floor_db)
    if len(loud) == 0:
        return x
    pad = int(0.01 * SR)
    return x[max(loud[0] - pad, 0) : min(loud[-1] + pad, len(x))]


def split_syllables(x: np.ndarray, count: int) -> list[np.ndarray]:
    """Cut a spoken word into `count` pieces, one per vowel nucleus.

    Spanish syllables carry exactly one vowel peak, so peaks are a far better anchor than
    valleys: word-final unstressed syllables are quiet and valley picking loses them.
    """
    if count <= 1:
        return [x]
    env = smooth(envelope_follower(bandpass(x, 250.0, 3000.0), 0.008, 0.035), 0.014)
    if len(env) < count * int(0.04 * SR):
        bounds = np.linspace(0, len(x), count + 1).astype(int)
        return [x[a:b] for a, b in zip(bounds[:-1], bounds[1:])]

    peaks: np.ndarray = np.array([], dtype=int)
    for distance_s, prominence in ((0.055, 0.008), (0.04, 0.004), (0.03, 0.0015), (0.02, 0.0004)):
        found, props = find_peaks(env, distance=max(int(distance_s * SR), 1), prominence=prominence)
        if len(found) >= count:
            order = np.argsort(props["prominences"])[::-1][:count]
            peaks = np.sort(found[order])
            break
    if len(peaks) < count:
        bounds = np.linspace(0, len(x), count + 1).astype(int)
        return [x[a:b] for a, b in zip(bounds[:-1], bounds[1:])]

    cuts = [int(peaks[i] + np.argmin(env[peaks[i] : peaks[i + 1]])) for i in range(count - 1)]
    bounds = [0, *cuts, len(x)]
    # two nuclei can sit very close together; keep every piece long enough to carry a vowel
    min_len = int(0.06 * SR)
    if len(x) >= count * min_len:
        for i in range(1, len(bounds) - 1):
            bounds[i] = max(bounds[i], bounds[i - 1] + min_len)
        for i in range(len(bounds) - 2, 0, -1):
            bounds[i] = min(bounds[i], bounds[i + 1] - min_len)
    pieces = [x[a:b] for a, b in zip(bounds[:-1], bounds[1:])]

    # unstressed syllables come out much quieter than stressed ones; even them out for singing
    levels = [float(np.sqrt(np.mean(np.square(p)))) if len(p) else 0.0 for p in pieces]
    reference = float(np.median([lvl for lvl in levels if lvl > 0.0] or [1.0]))
    balanced: list[np.ndarray] = []
    for piece, level in zip(pieces, levels):
        gain = min(reference / level, 4.0) if level > 1e-6 else 1.0
        balanced.append((piece * gain).astype(np.float32))
    return balanced


def pitch_of(x: np.ndarray, low_hz: float = 110.0, high_hz: float = 420.0) -> tuple[float, float]:
    """Autocorrelation pitch plus a 0..1 periodicity confidence, so unvoiced parts can be ignored."""
    if len(x) < int(0.05 * SR):
        return 0.0, 0.0
    env = envelope_follower(x, 0.005, 0.03)
    centre = int(np.argmax(env))
    half = int(0.035 * SR)
    seg = x[max(centre - half, 0) : centre + half]
    if len(seg) < int(0.02 * SR):
        return 0.0, 0.0
    seg = filt(seg - seg.mean(), "low", 1200.0, order=2)
    energy = float(np.dot(seg, seg))
    if energy <= 1e-9:
        return 0.0, 0.0
    corr = np.correlate(seg, seg, mode="full")[len(seg) - 1 :]
    lag_min, lag_max = int(SR / high_hz), min(int(SR / low_hz), len(corr) - 1)
    if lag_max <= lag_min:
        return 0.0, 0.0
    window = corr[lag_min:lag_max]
    peaks, _ = find_peaks(window)
    if len(peaks) == 0:
        return 0.0, 0.0
    best = float(window[peaks].max())
    if best <= 0.0:
        return 0.0, 0.0
    # shortest lag that is nearly as strong as the best one: avoids octave-down errors
    strong = [int(p) for p in peaks if window[p] >= 0.86 * best]
    lag = (strong[0] if strong else int(peaks[np.argmax(window[peaks])])) + lag_min
    return float(SR / lag), float(np.clip(best / energy, 0.0, 1.0))


def detect_f0(x: np.ndarray, low_hz: float = 110.0, high_hz: float = 420.0) -> float:
    return pitch_of(x, low_hz, high_hz)[0]


def sustain_to(x: np.ndarray, want: int, max_stretch: float = 2.4) -> np.ndarray:
    """Reach a long note by stretching moderately, then looping the vowel tail."""
    if want <= 0 or len(x) == 0:
        return np.zeros(max(want, 0), dtype=np.float32)
    stretched = x
    if want > len(x):
        factor = max(len(x) / min(want, int(len(x) * max_stretch)), 1e-3)
        stretched = np.asarray(
            time_stretch(x[np.newaxis, :], SR, stretch_factor=factor, high_quality=True, transient_mode="smooth"),
            dtype=np.float32,
        )[0]
    if len(stretched) >= want:
        return stretched[:want]
    tail_start = int(len(stretched) * 0.55)
    loop = stretched[tail_start:]
    if len(loop) < int(0.04 * SR):
        return np.pad(stretched, (0, want - len(stretched)))
    fade = min(int(0.03 * SR), len(loop) // 3)
    ramp_in = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    out = list(stretched)
    while len(out) < want:
        block = loop.copy()
        block[:fade] *= ramp_in
        overlap = np.asarray(out[-fade:], dtype=np.float32) * np.linspace(1.0, 0.0, fade, dtype=np.float32)
        out[-fade:] = list(overlap + block[:fade])
        out.extend(block[fade:])
    return np.asarray(out[:want], dtype=np.float32)


def pitch_to(x: np.ndarray, semitones: float, vibrato_cents: float = 0.0, vibrato_hz: float = 5.2) -> np.ndarray:
    """Formant-preserving pitch shift, with optional vibrato for held notes."""
    shift: float | np.ndarray = float(np.clip(semitones, -14.0, 14.0))
    if vibrato_cents > 0.0 and len(x) > int(0.25 * SR):
        t = np.arange(len(x)) / SR
        depth = np.clip((t - 0.18) / 0.35, 0.0, 1.0) * (vibrato_cents / 100.0)
        shift = float(np.clip(semitones, -14.0, 14.0)) + depth * np.sin(2.0 * np.pi * vibrato_hz * t)
    try:
        out = time_stretch(
            np.ascontiguousarray(x[np.newaxis, :], dtype=np.float32),
            SR,
            stretch_factor=1.0,
            pitch_shift_in_semitones=shift,
            high_quality=True,
            transient_mode="smooth",
            preserve_formants=True,
        )
    except Exception:
        out = time_stretch(
            np.ascontiguousarray(x[np.newaxis, :], dtype=np.float32),
            SR,
            stretch_factor=1.0,
            pitch_shift_in_semitones=float(np.clip(semitones, -14.0, 14.0)),
            high_quality=True,
            preserve_formants=True,
        )
    return np.asarray(out, dtype=np.float32)[0]


def syllable_audio(words: list[tuple[str, int]], voice: str = DEFAULT_VOICE) -> list[tuple[np.ndarray, float]]:
    """Synthesize each word and split it into syllables, tagging each with the word's own pitch.

    The word-level pitch is the reliable reference: a single plosive syllable like "to" is too
    short and too unvoiced to measure on its own.
    """
    pieces: list[tuple[np.ndarray, float]] = []
    for word, count in words:
        spoken = trim_silence(speak(word, voice))
        word_f0, _ = pitch_of(spoken)
        parts = split_syllables(spoken, count)
        while len(parts) < count:  # segmentation can under-deliver on very short words
            longest = int(np.argmax([len(p) for p in parts]))
            piece = parts.pop(longest)
            middle = len(piece) // 2
            parts[longest:longest] = [piece[:middle], piece[middle:]]
        pieces.extend((part, word_f0) for part in parts[:count])
    return pieces


def render_line(
    words: list[tuple[str, int]],
    melody: list[SungNote],
    beat_len: float,
    voice: str = DEFAULT_VOICE,
    vibrato_cents: float = 22.0,
    diagnostics: list[tuple[str, float, float, float]] | None = None,
) -> np.ndarray:
    """Sing one lyric line onto the melody; returns mono audio starting at beat 0."""
    pieces = syllable_audio(words, voice)
    if len(pieces) != len(melody):
        raise ValueError(f"{len(pieces)} syllables for {len(melody)} notes: {[n.text for n in melody]}")
    total = int(round((melody[-1].beat + melody[-1].beats + 1.0) * beat_len * SR))
    out = np.zeros(total, dtype=np.float32)
    for (piece, word_f0), note in zip(pieces, melody):
        own_f0, own_conf = pitch_of(piece)
        source_f0 = own_f0 if own_conf >= 0.35 and own_f0 > 0.0 else word_f0
        if source_f0 <= 0.0:
            continue
        want = int(round(note.beats * beat_len * SR * 0.96))
        shaped = sustain_to(piece, want)
        target_hz = midi_hz(note.midi)
        semis = 12.0 * np.log2(target_hz / source_f0)
        vibrato = vibrato_cents if note.beats >= 1.5 else 0.0
        tuned = pitch_to(shaped, semis, vibrato)
        # closed loop, but only when the result is clearly periodic: unvoiced pieces would mislead it
        achieved, conf = pitch_of(tuned, low_hz=90.0, high_hz=700.0)
        if conf >= 0.4 and achieved > 0.0:
            error = float(np.clip(12.0 * np.log2(target_hz / achieved), -6.0, 6.0))
            if abs(error) > 0.5:
                tuned = pitch_to(shaped, semis + error, vibrato)
                achieved, conf = pitch_of(tuned, low_hz=90.0, high_hz=700.0)
        if diagnostics is not None:
            diagnostics.append((note.text, target_hz, achieved, conf))
        fade = min(int(0.012 * SR), len(tuned) // 6)
        if fade > 2:
            tuned[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
            tuned[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
        start = int(round(note.beat * beat_len * SR))
        span = min(len(tuned), total - start)
        if span > 0:
            out[start : start + span] += tuned[:span]
    peak = float(np.abs(out).max())
    return (out / peak * 0.9).astype(np.float32) if peak > 0 else out


def check_tuning(
    words: list[tuple[str, int]], melody: list[SungNote], beat_len: float
) -> list[tuple[str, float, float, float]]:
    """Per-syllable target vs achieved pitch, measured on the isolated syllable renders."""
    diagnostics: list[tuple[str, float, float, float]] = []
    render_line(words, melody, beat_len, diagnostics=diagnostics)
    return diagnostics
