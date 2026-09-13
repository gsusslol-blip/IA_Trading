"""Text-to-speech: Piper on CPU (offline). Edge only if TTS_PROVIDER=edge."""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

from jarvis.config import DATA_DIR, Settings
from jarvis.security import safe_under

DEFAULT_VOICE = "es-AR-ElenaNeural"


def child_speech_pacing(text: str) -> str:
    """Pauses and spoken wording so Piper does not sound like a ticker."""
    clean = " ".join((text or "").split())
    clean = re.sub(
        r"^((?:hola|holi|ey)(?:\s+(?:pá|papá|papa))?)\s+(¿?(?:qué|que|cómo|como|vamos|hacemos)\b)",
        r"\1... \2",
        clean,
        count=1,
        flags=re.I,
    )
    clean = re.sub(r"\s*[–—]\s*", ", ", clean)
    clean = re.sub(r"\s*;\s*", ". ", clean)
    clean = re.sub(r"([!?]){2,}", r"\1", clean)
    clean = re.sub(r"\bOK[:.]?\b", "Okey.", clean, flags=re.I)
    clean = re.sub(r"\bwifi\b", "uai fai", clean, flags=re.I)
    clean = re.sub(r"\bhttps?\b", "enlace", clean, flags=re.I)
    return clean


def _for_speech(text: str) -> str:
    clean = " ".join(text.split())
    clean = re.sub(r"https?://\S+", "enlace", clean)
    clean = re.sub(r"[#*_`]+", "", clean)
    clean = child_speech_pacing(clean)
    if len(clean) > 1800:
        clean = clean[:1800] + "..."
    return clean


def _cleanup() -> None:
    now = time.time()
    files = list(DATA_DIR.glob("tts-*.mp3")) + list(DATA_DIR.glob("tts-*.wav"))
    for item in files:
        try:
            if now - item.stat().st_mtime > 900:
                item.unlink()
        except OSError:
            pass
    remain = [p for p in files if p.is_file()]
    remain.sort(key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in remain)
    while remain and (len(remain) > 48 or total > 80_000_000):
        victim = remain.pop(0)
        try:
            total -= victim.stat().st_size
            victim.unlink()
        except OSError:
            pass


def audio_api_path(filename: str) -> str:
    name = Path(filename).name
    _assert_audio_name(name)
    return f"/api/audio/{name}"


def resolve_audio_file(filename: str) -> Path:
    name = Path(filename).name
    _assert_audio_name(name)
    path = safe_under(DATA_DIR, name)
    if path.parent != DATA_DIR.resolve():
        raise ValueError("Path escapes data dir.")
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


def audio_media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    return "audio/mpeg"


def _assert_audio_name(name: str) -> None:
    if not name.startswith("tts-") or Path(name).suffix.lower() not in {".mp3", ".wav"}:
        raise ValueError("Invalid audio name.")


def _provider(settings: Settings) -> str:
    return (os.getenv("TTS_PROVIDER") or getattr(settings, "tts_provider", "piper") or "piper").strip().lower()


async def speak_to_file(settings: Settings, text: str, name: str | None = None) -> Path:
    clean = _for_speech(text)
    if not clean:
        raise ValueError("Nothing to speak.")
    _cleanup()
    stamp = name or f"tts-{time.time_ns()}"
    stamp = Path(stamp).name
    if not stamp.startswith("tts-"):
        stamp = f"tts-{stamp}"
    if _provider(settings) in {"edge", "edge-tts"}:
        return await _edge_mp3(settings, clean, stamp)
    from jarvis.piper_tts import synthesize_wav

    wav = DATA_DIR / (Path(stamp).stem + ".wav")
    await asyncio.to_thread(synthesize_wav, clean, wav)
    return wav


async def _edge_mp3(settings: Settings, clean: str, stamp: str) -> Path:
    import edge_tts

    path = DATA_DIR / (Path(stamp).stem + ".mp3")
    voice = (settings.tts_voice or "").strip() or DEFAULT_VOICE
    communicate = edge_tts.Communicate(clean, voice)
    await communicate.save(str(path))
    return path
