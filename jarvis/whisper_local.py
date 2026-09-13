"""Local Faster-Whisper singleton (CUDA if available, else CPU int8)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from threading import Lock

from jarvis.config import DATA_DIR, Settings

_lock = Lock()
_model = None
_device = ""


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def whisper_device() -> str:
    # Default CPU: keep the 6 GB GTX 1660 Ti free for Ollama (gemma2:2b / llama3:8b).
    forced = os.getenv("WHISPER_DEVICE", "cpu").strip().lower()
    if forced in {"cuda", "gpu"}:
        return "cuda"
    if forced == "cpu":
        return "cpu"
    try:
        import ctranslate2

        if int(ctranslate2.get_cuda_device_count()) > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _load(settings: Settings):
    global _model, _device
    with _lock:
        if _model is not None:
            return _model
        from faster_whisper import WhisperModel

        forced = (getattr(settings, "whisper_device", None) or "").strip().lower()
        _device = forced if forced in {"cpu", "cuda", "gpu"} else whisper_device()
        if _device == "gpu":
            _device = "cuda"
        name = (getattr(settings, "faster_whisper_model", None) or "base").strip() or "base"
        compute = "float16" if _device == "cuda" else "int8"
        print(f"[+] Faster-Whisper local: model={name} device={_device} compute={compute}")
        _model = WhisperModel(name, device=_device, compute_type=compute)
        return _model


def transcribe_local(settings: Settings, data: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".wav"
    if suffix not in {".webm", ".wav", ".mp3", ".ogg", ".mp4", ".m4a", ".flac"}:
        suffix = ".wav"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="stt-", suffix=suffix, dir=DATA_DIR, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        model = _load(settings)
        segments, _info = model.transcribe(
            path,
            beam_size=1,
            language="es",
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return " ".join(text.split())
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
