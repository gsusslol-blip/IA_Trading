"""Local process/data heal — Python only, no LLM, no process massacre."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from jarvis.config import Settings

_CREATE_NO_WINDOW = 0x08000000
_last_ollama_launch = 0.0
_ha_was_down = False


def heal_stack(settings: Settings) -> str | None:
    if os.getenv("SELF_HEAL", "1").strip().lower() in {"0", "false", "no"}:
        return None
    notice = ensure_ollama(settings)
    ping_home_assistant(settings)
    return notice


def ensure_ollama(settings: Settings) -> str | None:
    global _last_ollama_launch
    base = settings.ollama_base_url or "http://127.0.0.1:11434/v1"
    if _ping_ollama(base):
        return None
    now = time.monotonic()
    if now - _last_ollama_launch < 90:
        return None
    exe = _ollama_exe()
    if not exe:
        return None
    try:
        kwargs: dict[str, object] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = _CREATE_NO_WINDOW
        subprocess.Popen([str(exe), "serve"], **kwargs)
        _last_ollama_launch = now
        print("[self-heal] ollama serve launched")
        return "Pá, el cerebro local se había dormido. Lo desperté."
    except OSError as exc:
        print(f"[self-heal] could not start Ollama: {exc}")
        return None


def ping_home_assistant(settings: Settings) -> bool:
    global _ha_was_down
    if not settings.has_ha:
        return False
    url = settings.ha_url.rstrip("/") + "/api/"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {settings.ha_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            ok = getattr(resp, "status", 200) < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        ok = False
    if ok:
        _ha_was_down = False
        return True
    if not _ha_was_down:
        print("[self-heal] Home Assistant not reachable on LAN")
    _ha_was_down = True
    return False


def _ping_ollama(base_url: str, timeout: float = 1.2) -> bool:
    raw = (base_url or "http://127.0.0.1:11434/v1").rstrip("/")
    root = raw[:-3] if raw.endswith("/v1") else raw
    for url in (f"{root}/api/tags", f"{raw}/models"):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if getattr(resp, "status", 200) < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def _ollama_exe() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if local.is_file():
        return local
    return None
