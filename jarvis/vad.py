"""Local voice-activity detection. Prefer Silero ONNX; RMS+ZCR as fallback.

Torch is intentionally NOT a dependency (portable exe must stay small).
HUD Libre still filters client-side (RMS + wake regex in index.html).
"""

from __future__ import annotations

import io
import math
import struct
import wave
from functools import lru_cache
from pathlib import Path

from jarvis.config import DATA_DIR

_SILERO_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
)
_MODEL_PATH = DATA_DIR / "models" / "silero_vad.onnx"

# 16-bit PCM: discard near-silence before Whisper.
_ENERGY_MIN = 180.0
_ZCR_SPEECH_MIN = 0.02
_ZCR_SPEECH_MAX = 0.35


def wav_contains_speech(data: bytes, filename: str = "") -> bool:
    """Return False when the clip is clearly not human speech."""
    pcm, rate = _decode_pcm16(data, filename)
    if pcm is None or rate <= 0 or len(pcm) < int(rate * 0.25):
        # Compressed HUD blobs (webm): cannot decode here without ffmpeg.
        # Keep a size gate only — real VAD runs on wake WAV. HUD Libre
        # still filters client-side via RMS in index.html.
        return len(data) >= 1800
    rms = _rms(pcm)
    if rms < _ENERGY_MIN:
        return False
    silero = _silero_speech_ratio(pcm, rate)
    if silero is not None:
        return silero >= 0.12
    return _energy_speech(pcm, rate)


def _decode_pcm16(data: bytes, filename: str) -> tuple[list[int] | None, int]:
    lower = (filename or "").lower()
    if not (data[:4] == b"RIFF" or lower.endswith(".wav")):
        return None, 0
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            if wf.getsampwidth() != 2 or wf.getnchannels() < 1:
                return None, 0
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
            nchan = wf.getnchannels()
    except Exception:
        return None, 0
    samples = list(struct.unpack_from(f"{len(raw) // 2}h", raw))
    if nchan > 1:
        samples = samples[0::nchan]
    return samples, rate


def _mean_abs(pcm: list[int]) -> float:
    if not pcm:
        return 0.0
    return sum(abs(s) for s in pcm) / len(pcm)


def _rms(pcm: list[int]) -> float:
    if not pcm:
        return 0.0
    acc = 0.0
    for sample in pcm:
        acc += float(sample) * float(sample)
    return math.sqrt(acc / len(pcm))


def _zero_crossing_rate(pcm: list[int]) -> float:
    if len(pcm) < 2:
        return 0.0
    crosses = 0
    prev = pcm[0]
    for sample in pcm[1:]:
        if (prev >= 0) != (sample >= 0) and (prev != 0 or sample != 0):
            crosses += 1
        prev = sample
    return crosses / (len(pcm) - 1)


def _energy_speech(pcm: list[int], rate: int) -> bool:
    """RMS + zero-crossing heuristic when Silero ONNX is unavailable."""
    hop = max(1, rate // 50)
    voiced = 0
    total = 0
    for i in range(0, len(pcm) - hop, hop):
        window = pcm[i : i + hop]
        total += 1
        rms = _rms(window)
        zcr = _zero_crossing_rate(window)
        if rms >= _ENERGY_MIN and _ZCR_SPEECH_MIN <= zcr <= _ZCR_SPEECH_MAX:
            voiced += 1
        elif rms >= _ENERGY_MIN * 3.0 and zcr >= 0.01:
            voiced += 1
    if total == 0:
        return False
    if voiced / total >= 0.16:
        return True
    # Whole-clip fallback: some short utterances sit in few hops.
    zcr = _zero_crossing_rate(pcm)
    return _rms(pcm) >= _ENERGY_MIN and _ZCR_SPEECH_MIN <= zcr <= _ZCR_SPEECH_MAX


def _silero_speech_ratio(pcm: list[int], rate: int) -> float | None:
    pkg = _silero_pkg_ratio(pcm, rate)
    if pkg is not None:
        return pkg
    session = _silero_session()
    if session is None:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    audio = np.array(pcm, dtype=np.float32) / 32768.0
    if rate != 16000:
        n = int(len(audio) * 16000 / rate)
        if n < 160:
            return 0.0
        idx = np.linspace(0, len(audio) - 1, n)
        audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
    window = 512
    hops = 0
    speech = 0
    state = np.zeros((2, 1, 128), dtype=np.float32)
    sr = np.array(16000, dtype=np.int64)
    try:
        for i in range(0, len(audio) - window, window):
            chunk = audio[i : i + window]
            if chunk.shape[0] < window:
                break
            out = session.run(
                None,
                {
                    "input": chunk.reshape(1, -1),
                    "state": state,
                    "sr": sr,
                },
            )
            prob = float(out[0].reshape(-1)[0])
            if len(out) > 1:
                state = out[1]
            hops += 1
            if prob >= 0.5:
                speech += 1
    except Exception:
        return None
    if hops == 0:
        return 0.0
    return speech / hops


def _silero_pkg_ratio(pcm: list[int], rate: int) -> float | None:
    """Optional `silero-vad` pip package (ONNX). Skip if it pulls torch.hub."""
    try:
        from silero_vad import get_speech_timestamps, load_silero_vad
    except Exception:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    try:
        model = _silero_pkg_model()
        if model is None:
            return None
        audio = np.array(pcm, dtype=np.float32) / 32768.0
        if rate != 16000:
            n = int(len(audio) * 16000 / rate)
            if n < 160:
                return 0.0
            idx = np.linspace(0, len(audio) - 1, n)
            audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
        stamps = get_speech_timestamps(audio, model, sampling_rate=16000)
        if not stamps:
            return 0.0
        voiced = sum(int(item["end"]) - int(item["start"]) for item in stamps)
        return voiced / max(1, len(audio))
    except Exception:
        return None


@lru_cache(maxsize=1)
def _silero_pkg_model():
    try:
        from silero_vad import load_silero_vad

        return load_silero_vad()
    except Exception:
        return None


@lru_cache(maxsize=1)
def _silero_session():
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    path = _ensure_model()
    if path is None:
        return None
    try:
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
    except Exception:
        return None


def _ensure_model() -> Path | None:
    if _MODEL_PATH.is_file() and _MODEL_PATH.stat().st_size > 10_000:
        return _MODEL_PATH
    try:
        import httpx
    except ImportError:
        return None
    try:
        _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=40.0, follow_redirects=True) as client:
            response = client.get(_SILERO_URL)
            response.raise_for_status()
            content = response.content
        if len(content) < 10_000:
            return None
        _MODEL_PATH.write_bytes(content)
        return _MODEL_PATH
    except Exception:
        return None
