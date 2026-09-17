"""Text-to-speech: Piper on CPU (offline). Edge only if TTS_PROVIDER=edge."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import time
from pathlib import Path

from jarvis.config import DATA_DIR, ROOT, Settings
from jarvis.security import safe_under

DEFAULT_VOICE = "es-AR-ElenaNeural"
_CACHE_DIR = DATA_DIR / "tts-cache"
_PHRASE_CACHE_DIR = Path(
    os.getenv("TTS_CACHE_DIR", "").strip() or str(DATA_DIR / "assets" / "tts_cache")
)
if not _PHRASE_CACHE_DIR.is_absolute():
    _PHRASE_CACHE_DIR = ROOT / _PHRASE_CACHE_DIR
_CACHE_MAX_CHARS = 140


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


def _cache_key(clean: str, settings: Settings) -> str:
    provider = _provider(settings)
    voice = (settings.tts_voice or "").strip() or DEFAULT_VOICE
    raw = f"{provider}|{voice}|{clean}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:28]


def _cache_path(clean: str, settings: Settings, suffix: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{_cache_key(clean, settings)}{suffix}"


def _phrase_slug(clean: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9áéíóúüñÁÉÍÓÚÜÑ ]+", "", clean.lower()).strip()
    return re.sub(r"\s+", "_", slug)[:80]


def phrase_cache_dir() -> Path:
    _PHRASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _PHRASE_CACHE_DIR


def phrase_cache_count() -> int:
    folder = phrase_cache_dir()
    try:
        return sum(1 for p in folder.iterdir() if p.suffix.lower() in {".wav", ".mp3"} and p.is_file())
    except OSError:
        return 0


def _phrase_hit(clean: str, suffix: str) -> Path | None:
    """Exact common-phrase WAV/MP3 under data/assets/tts_cache (0 ms Piper)."""
    slug = _phrase_slug(clean)
    if not slug:
        return None
    folder = phrase_cache_dir()
    for ext in (suffix, ".wav", ".mp3"):
        name = f"{slug}{ext if ext.startswith('.') else '.' + ext}"
        candidate = folder / name
        if candidate.is_file() and candidate.stat().st_size > 64:
            return candidate
    return None


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


def first_speakable_sentence(text: str) -> str | None:
    """Return first speakable chunk when enough text arrived for early TTS."""
    clean = " ".join((text or "").split())
    if len(clean) < 8:
        return None
    match = re.search(r"^(.+?[.!?…])(?:\s|$)", clean)
    if match:
        first = match.group(1).strip()
        if len(first) >= 12:
            return first
        rest = clean[len(first) :].lstrip()
        if rest:
            nxt = re.search(r"^(.+?[.!?…])(?:\s|$)", rest)
            if nxt:
                both = f"{first} {nxt.group(1).strip()}".strip()
                if len(both) >= 10:
                    return both
            if len(clean) >= 18:
                return clean if len(clean) <= 96 else clean[:96].rsplit(" ", 1)[0]
        elif clean.endswith((".", "!", "?", "…")) and len(clean) >= 8:
            return clean
    if len(clean) >= 48:
        cut = clean[:72]
        sp = cut.rfind(" ")
        return (cut[:sp] if sp > 24 else cut).strip()
    return None


async def speak_to_file(settings: Settings, text: str, name: str | None = None) -> Path:
    clean = _for_speech(text)
    if not clean:
        raise ValueError("Nothing to speak.")
    _cleanup()
    stamp = name or f"tts-{time.time_ns()}"
    stamp = Path(stamp).name
    if not stamp.startswith("tts-"):
        stamp = f"tts-{stamp}"

    use_edge = _provider(settings) in {"edge", "edge-tts"}
    suffix = ".mp3" if use_edge else ".wav"
    dest = DATA_DIR / (Path(stamp).stem + suffix)

    hit = _phrase_hit(clean, suffix)
    if hit is not None:
        shutil.copy2(hit, dest)
        return dest

    if len(clean) <= _CACHE_MAX_CHARS:
        cached = _cache_path(clean, settings, suffix)
        if cached.is_file() and cached.stat().st_size > 64:
            shutil.copy2(cached, dest)
            return dest

    if use_edge:
        path = await _edge_mp3(settings, clean, stamp)
    else:
        from jarvis.piper_tts import synthesize_wav

        path = DATA_DIR / (Path(stamp).stem + ".wav")
        await asyncio.to_thread(synthesize_wav, clean, path)

    if len(clean) <= _CACHE_MAX_CHARS:
        try:
            cached = _cache_path(clean, settings, path.suffix.lower())
            if not cached.is_file():
                shutil.copy2(path, cached)
        except OSError:
            pass
        try:
            from jarvis.tts_phrases import COMMON_PHRASES

            normalized = " ".join(clean.split()).lower().rstrip(".")
            known = {" ".join(p.split()).lower().rstrip(".") for p in COMMON_PHRASES}
            if normalized in known or len(clean) <= 48:
                slug_path = phrase_cache_dir() / f"{_phrase_slug(clean)}{path.suffix.lower()}"
                if not slug_path.is_file():
                    shutil.copy2(path, slug_path)
                    try:
                        from jarvis.tts_warmer import incrementar_contador_tts

                        incrementar_contador_tts(1)
                    except Exception:
                        pass
        except Exception:
            pass
    return path


async def warm_phrase_cache(settings: Settings, limit: int = 24) -> int:
    """Pre-generate WAV for common acks (run once / on demand)."""
    from jarvis.tts_phrases import COMMON_PHRASES

    done = 0
    for phrase in COMMON_PHRASES[: max(1, limit)]:
        try:
            await speak_to_file(settings, phrase, f"tts-warm-{done}")
            done += 1
        except Exception:
            continue
    return done


async def _edge_mp3(settings: Settings, clean: str, stamp: str) -> Path:
    import edge_tts

    path = DATA_DIR / (Path(stamp).stem + ".mp3")
    voice = (settings.tts_voice or "").strip() or DEFAULT_VOICE
    communicate = edge_tts.Communicate(clean, voice)
    await communicate.save(str(path))
    return path
