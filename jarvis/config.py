"""Writable vs bundled paths (dev and frozen exe)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

_OLLAMA_PING_AT: float = 0.0
_OLLAMA_PING_OK: bool = False


def _ollama_reachable(base_url: str, timeout: float = 0.35) -> bool:
    """Cached ping so /api/me does not stall. Fail-closed if Ollama is down."""
    global _OLLAMA_PING_AT, _OLLAMA_PING_OK
    now = time.monotonic()
    if now - _OLLAMA_PING_AT < 8.0:
        return _OLLAMA_PING_OK
    _OLLAMA_PING_AT = now
    raw = (base_url or "http://127.0.0.1:11434/v1").rstrip("/")
    root = raw[:-3] if raw.endswith("/v1") else raw
    for url in (f"{root}/api/tags", f"{raw}/models"):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                _OLLAMA_PING_OK = getattr(resp, "status", 200) < 500
                if _OLLAMA_PING_OK:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    _OLLAMA_PING_OK = False
    return False


def bundle_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def writable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BUNDLE_DIR = bundle_dir()
ROOT = writable_root()


def search_roots() -> tuple[Path, ...]:
    """Install folder, PyInstaller bundle, and source tree — no drive-letter hardcoding."""
    seen: list[Path] = []
    for item in (ROOT, BUNDLE_DIR, Path(__file__).resolve().parent.parent):
        resolved = item.resolve()
        if resolved not in seen:
            seen.append(resolved)
    return tuple(seen)


def _seed_env() -> None:
    dest = ROOT / ".env"
    if dest.exists():
        return
    for candidate in (BUNDLE_DIR / ".env.example", ROOT / ".env.example"):
        if candidate.exists():
            dest.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
            break


_seed_env()
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

STATIC_DIR = BUNDLE_DIR / "jarvis" / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    openai_api_key: str
    gemini_api_key: str
    llm_provider: str
    telegram_bot_token: str
    telegram_user_id: int | None
    hud_host: str
    hud_port: int
    assistant_name: str
    user_name: str
    tts_voice: str
    timezone: str
    llm_model: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    ha_url: str
    ha_token: str
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = "gemma2:2b"
    stt_provider: str = "auto"
    faster_whisper_model: str = "base"
    whisper_device: str = "cpu"
    tts_provider: str = "piper"

    @property
    def has_llm(self) -> bool:
        if self.llm_provider in {"ollama", "llamacpp"}:
            return True
        if self.groq_api_key or self.openai_api_key or self.gemini_api_key:
            return True
        if self.llm_provider == "auto":
            return _ollama_reachable(self.ollama_base_url)
        return False

    @property
    def has_stt(self) -> bool:
        from jarvis.whisper_local import whisper_available

        local = whisper_available()
        if self.stt_provider in {"faster-whisper", "local"}:
            return local
        if local:
            return True
        return bool(self.groq_api_key or self.openai_api_key)

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def has_smtp(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    @property
    def has_ha(self) -> bool:
        return bool(self.ha_url and self.ha_token)


def load_settings() -> Settings:
    uid_raw = os.getenv("TELEGRAM_USER_ID", "").strip()
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        llm_provider=os.getenv("LLM_PROVIDER", "auto").strip().lower(),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_user_id=int(uid_raw) if uid_raw.isdigit() else None,
        # 0.0.0.0 = PC + phone on the same Wi-Fi. Use 127.0.0.1 to lock to this machine only.
        hud_host=os.getenv("HUD_HOST", "0.0.0.0").strip() or "0.0.0.0",
        hud_port=int(os.getenv("HUD_PORT", "8787")),
        assistant_name=os.getenv("ASSISTANT_NAME", "Ilaria").strip() or "Ilaria",
        user_name=os.getenv("USER_NAME", "señor").strip() or "señor",
        tts_voice=os.getenv("TTS_VOICE", "es-AR-ElenaNeural").strip(),
        timezone=os.getenv("TIMEZONE", "America/Argentina/Buenos_Aires").strip(),
        llm_model=os.getenv("LLM_MODEL", "").strip(),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587") or "587"),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        ha_url=os.getenv("HA_URL", "").strip(),
        ha_token=os.getenv("HA_TOKEN", "").strip(),
        ollama_base_url=(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").strip() or "http://127.0.0.1:11434/v1"),
        ollama_model=os.getenv("OLLAMA_MODEL", "").strip() or "gemma2:2b",
        stt_provider=os.getenv("STT_PROVIDER", "auto").strip().lower() or "auto",
        faster_whisper_model=os.getenv("FASTER_WHISPER_MODEL", "base").strip() or "base",
        whisper_device=os.getenv("WHISPER_DEVICE", "cpu").strip().lower() or "cpu",
        tts_provider=os.getenv("TTS_PROVIDER", "piper").strip().lower() or "piper",
    )
