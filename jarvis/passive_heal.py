"""Lightweight passive heal on LLM timeout / 5xx — no extra LLM calls."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from jarvis.config import DATA_DIR, Settings
from jarvis.self_healing import ensure_ollama

_last_at = 0.0
_last_kind = ""
_COOLDOWN_S = 75.0


def heal_enabled() -> bool:
    return (os.getenv("ILARIA_PASSIVE_HEAL") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def classify_llm_fault(exc: BaseException) -> str | None:
    """Return timeout | http_5xx | connection | None."""
    text = str(exc).lower()
    code = getattr(exc, "status_code", None)
    if code is None:
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
    try:
        code_i = int(code) if code is not None else 0
    except (TypeError, ValueError):
        code_i = 0
    if code_i >= 500 or any(n in text for n in ("502", "503", "504", "500")):
        return "http_5xx"
    if any(n in text for n in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(
        n in text
        for n in (
            "connection",
            "connecterror",
            "connection refused",
            "connection reset",
            "name or service not known",
            "nodename nor servname",
            "actively refused",
        )
    ):
        return "connection"
    return None


def on_llm_exception(settings: Settings, exc: BaseException) -> dict[str, Any]:
    """
    Soft-heal Ollama after timeout/5xx/connection. Rate-limited.
    Never raises; safe to call from the chat except path.
    """
    global _last_at, _last_kind
    kind = classify_llm_fault(exc)
    if kind is None or not heal_enabled():
        return {"status": "skipped", "kind": kind or ""}
    now = time.monotonic()
    if now - _last_at < _COOLDOWN_S and _last_kind == kind:
        return {"status": "cooldown", "kind": kind}
    _last_at = now
    _last_kind = kind
    notice = None
    try:
        notice = ensure_ollama(settings)
    except Exception as heal_exc:  # noqa: BLE001
        payload = {
            "status": "error",
            "kind": kind,
            "message": str(heal_exc),
            "at": time.time(),
        }
        _write_log(payload)
        return payload
    payload = {
        "status": "healed" if notice else "checked",
        "kind": kind,
        "message": notice or "Ollama respondió tras el fallo (o ya estaba en pie).",
        "at": time.time(),
    }
    _write_log(payload)
    return payload


def owner_hint(result: dict[str, Any]) -> str:
    if result.get("status") not in {"healed", "checked", "error"}:
        return ""
    kind = result.get("kind") or "fallo"
    msg = result.get("message") or ""
    if result.get("status") == "healed":
        return f"[auto-heal {kind}] {msg}"
    if result.get("status") == "error":
        return f"[auto-heal {kind} falló] {msg}"
    return f"[auto-heal {kind}] revisé Ollama."


def _write_log(payload: dict[str, Any]) -> None:
    folder = DATA_DIR / "updates"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "passive_heal.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def reset_for_tests() -> None:
    global _last_at, _last_kind
    _last_at = 0.0
    _last_kind = ""
