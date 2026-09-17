"""Street channel helpers for Telegram (local-first, no extra webhook server).

Polling lives in ``jarvis.telegram_bot`` / ``runtime`` — do NOT also launch this
module as a second ``run_polling`` process or Telegram will fight itself.
Use ``python -m jarvis.remote_bridge`` only when Ilaria is NOT already running.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from jarvis.brain_parser import log_to_diario
from jarvis.config import DATA_DIR, Settings, load_settings


def remote_username(settings: Settings | None = None) -> str:
    """Sandbox user for street notes (welcome_reporter + kitchen workspace)."""
    env = os.getenv("TELEGRAM_REMOTE_USER", "").strip().lower()
    if env:
        return re.sub(r"[^a-z0-9_-]+", "", env) or "guest"
    cfg = settings or load_settings()
    slug = re.sub(r"[^a-z0-9_-]+", "", (cfg.user_name or "").strip().lower())
    return slug or "guest"


def remote_workspace(username: str | None = None, settings: Settings | None = None) -> Path:
    user = (username or remote_username(settings)).strip().lower() or "guest"
    path = DATA_DIR / "users" / user / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_authorized_chat(chat_id: int | None, settings: Settings) -> bool:
    """Strict owner lock when TELEGRAM_USER_ID / TELEGRAM_ALLOWED_CHAT_ID is set."""
    allowed = settings.telegram_user_id
    if allowed is None:
        return True
    if chat_id is None:
        return False
    return int(chat_id) == int(allowed)


def try_street_shortcut(
    text: str,
    *,
    username: str | None = None,
    settings: Settings | None = None,
) -> str | None:
    """Fast local replies without LLM: recipes list + diario notes.

    Returns reply text, or None to fall through to Brain.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    user = remote_username(settings) if username is None else username
    workspace = remote_workspace(user, settings)

    if _wants_recipes(lower):
        from jarvis.kitchen_manager import listar_recetas_disponibles

        payload = json.loads(listar_recetas_disponibles(workspace))
        lines = ["TUS RECETAS DISPONIBLES:", ""]
        for item in payload.get("recetas") or []:
            nombre = str(item.get("nombre") or "?")
            tipo = str(item.get("tipo") or "")
            lines.append(f"• {nombre}" + (f" ({tipo})" if tipo else ""))
        if len(lines) <= 2:
            return "Todavía no hay recetas en el índice local ni en tu workspace."
        log_to_diario(user, "Listó recetas desde Telegram (calle).")
        return "\n".join(lines)

    from jarvis.tunnel_manager import sync_ack_message, wants_sync_request

    if wants_sync_request(raw):
        return sync_ack_message(settings)

    note = _extract_note(raw, lower)
    if note is not None:
        clean = note.strip()
        if not clean:
            return "Decime qué anoto. Ej: «anotá comprar carne para las milanesas»."
        log_to_diario(user, f"Nota remota desde Telegram: {clean}")
        return f"Registrado en tu bitácora de hoy: «{clean}». Te lo recuerdo al volver a la PC."

    return None


def handle_remote_text(
    text: str,
    *,
    brain: Any | None = None,
    settings: Settings | None = None,
    session_id: str = "telegram",
) -> str:
    """Street shortcuts first; otherwise Brain with client_surface=telegram."""
    cfg = settings or (getattr(brain, "settings", None) if brain is not None else None) or load_settings()
    user = remote_username(cfg)
    shortcut = try_street_shortcut(text, username=user, settings=cfg)
    if shortcut is not None:
        return shortcut
    if brain is None:
        return (
            "Comando libre recibido. Con Ilaria corriendo (run.bat) lo proceso el cerebro; "
            "desde la calle también podés usar «anotá …» o «qué recetas tengo»."
        )
    brain.actions.client_surface = "telegram"
    # Bind sandbox to the remote user workspace when possible.
    ws = remote_workspace(user, cfg)
    brain.actions.workspace = ws
    brain.actions._folders["workspace"] = [ws]
    return brain.reply(session_id, text)


def _wants_recipes(lower: str) -> bool:
    keys = (
        "recetas",
        "qué puedo cocinar",
        "que puedo cocinar",
        "qué cocino",
        "que cocino",
        "lista de recetas",
    )
    return any(k in lower for k in keys)


def _extract_note(raw: str, lower: str) -> str | None:
    """Match anotá / anotá / recordame / dejame una nota …"""
    patterns = (
        r"^(?:anot[aá]|anota|recordame|recordá|recorda)\s*[:\-]?\s*(.+)$",
        r"^(?:dejame|déjame|deja)\s+una\s+nota\s*[:\-]?\s*(.+)$",
        r"^(?:nota|pendiente)\s*[:\-]\s*(.+)$",
    )
    for pat in patterns:
        match = re.match(pat, raw.strip(), flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    # Soft: "recordame que …" / "anotá que …" already covered by first pattern.
    if lower.startswith("recordame ") or lower.startswith("anotá ") or lower.startswith("anota "):
        return None
    return None


def iniciar_bot_remoto() -> None:
    """Standalone polling (only if main Ilaria is NOT running)."""
    settings = load_settings()
    if not settings.has_telegram:
        print("[REMOTO] Ignorando Telegram: falta TELEGRAM_BOT_TOKEN en .env")
        return
    if settings.telegram_user_id is None:
        print(
            "[REMOTO] Aviso: sin TELEGRAM_USER_ID / TELEGRAM_ALLOWED_CHAT_ID "
            "el bot responde a cualquiera que le escriba."
        )

    from jarvis.bus import EventBus
    from jarvis.memory import Memory
    from jarvis.brain import Brain
    from jarvis.telegram_bot import build_telegram_app

    print("[REMOTO] Levantando canal persistente Telegram (polling standalone)...")
    brain = Brain(settings, Memory(DATA_DIR / "host_memory.json"), EventBus())
    brain.actions.client_surface = "telegram"
    brain.actions.workspace = remote_workspace(settings=settings)
    app = build_telegram_app(settings, brain)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    iniciar_bot_remoto()
