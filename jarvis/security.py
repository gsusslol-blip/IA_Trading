"""Immutable sandbox and secret redaction — no FastAPI types here."""

from __future__ import annotations

import os
import re
from pathlib import Path

from jarvis.config import Settings

_ESCAPE = "Path escapes workspace"
_SECRET = "[SECRET_REDACTED]"
_PATTERNS = (
    re.compile(r"jarvis_sid=[A-Za-z0-9_\-]+", re.I),
    re.compile(r"gsk_[A-Za-z0-9]{20,}", re.I),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{12,}", re.I),
)


def safe_under(base_dir: str | Path, relative_path: str | None) -> Path:
    """Return a path that is strictly inside base_dir after resolve()."""
    base = Path(base_dir).resolve()
    raw = (relative_path or ".").replace("\x00", "").strip()
    raw = raw.replace("\\", "/")
    if raw.startswith("/") or raw.startswith("//"):
        raise ValueError(_ESCAPE)
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError(_ESCAPE)
        if len(part) >= 2 and part[1] == ":":
            raise ValueError(_ESCAPE)
        if "/" in part or "\\" in part:
            raise ValueError(_ESCAPE)
        parts.append(part)
    target = (base.joinpath(*parts) if parts else base).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(_ESCAPE) from exc
    return target


def secret_values(settings: Settings | None = None) -> tuple[str, ...]:
    found: list[str] = []
    env_keys = (
        "HA_TOKEN",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "SMTP_PASSWORD",
        "PICOVOICE_ACCESS_KEY",
        "OWNER_PASSWORD",
    )
    for key in env_keys:
        value = (os.getenv(key) or "").strip()
        if len(value) >= 8:
            found.append(value)
    if settings is not None:
        for value in (
            settings.ha_token,
            settings.groq_api_key,
            settings.openai_api_key,
            settings.gemini_api_key,
            settings.telegram_bot_token,
            settings.smtp_password,
        ):
            text = (value or "").strip()
            if len(text) >= 8:
                found.append(text)
    # Longest first so overlapping tokens redact fully.
    unique = sorted(set(found), key=len, reverse=True)
    return tuple(unique)


def redact_secrets(text: str, extra: tuple[str, ...] | list[str] = ()) -> str:
    if not text:
        return text
    out = text
    needles = list(extra) + list(secret_values())
    seen: set[str] = set()
    for needle in sorted(needles, key=len, reverse=True):
        if needle in seen or len(needle) < 8:
            continue
        seen.add(needle)
        if needle in out:
            out = out.replace(needle, _SECRET)
    for pattern in _PATTERNS:
        out = pattern.sub(_SECRET, out)
    return out
