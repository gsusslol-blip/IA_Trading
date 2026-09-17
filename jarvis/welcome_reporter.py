"""Daily welcome report: stack-aware greeting + yesterday journal + time-of-day nudge."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def generar_welcome_report_cotidiano(
    username: str | None = None,
    *,
    display_name: str = "",
    workspace: Path | None = None,
    timezone: str = "America/Argentina/Buenos_Aires",
    stack: dict[str, Any] | None = None,
    usuario_activo: str | None = None,
) -> dict[str, Any]:
    """Build everyday welcome payload (merged into /api/welcome-report).

    Accepts either keyword workspace=… or a bare username (resolves
    data/users/<user>/workspace). ``usuario_activo`` is an alias for tests.
    """
    from jarvis.config import DATA_DIR

    user = (username or usuario_activo or "guest").strip().lower()
    who = (display_name or user).strip()
    root = Path(workspace) if workspace is not None else (DATA_DIR / "users" / user / "workspace")
    root.mkdir(parents=True, exist_ok=True)

    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    diario_ayer = root / f"diario_{yesterday}.txt"

    pendientes: list[str] = []
    if diario_ayer.is_file():
        try:
            lines = diario_ayer.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            low = line.lower()
            if any(k in low for k in ("nota", "recordatorio", "pendiente", "todo", "aviso")):
                clean = line.strip()
                if clean:
                    pendientes.append(clean)
        if not pendientes:
            pendientes = [ln.strip() for ln in lines if ln.strip()][-3:]

    hour = now.hour
    if hour < 12:
        saludo = f"Buen día, {who}"
        sugerencia = "¿Activamos un playlist enérgico para arrancar o planeamos el almuerzo?"
    elif hour < 20:
        saludo = f"Buenas tardes, {who}"
        sugerencia = "El entorno está estable. ¿Buscamos una receta o ponemos música de enfoque?"
    else:
        saludo = f"Buenas noches, {who}"
        sugerencia = "Ecosistema listo para el reporte de cierre de bitácora."

    stack_bits: list[str] = []
    if stack:
        if stack.get("ollama") is False:
            stack_bits.append("Ollama offline")
        if stack.get("udp_discover") is False:
            stack_bits.append("LAN UDP caído")
        ha = stack.get("home_assistant")
        if ha and ha not in {"SUCCESS", "NOT_CONFIGURED", True}:
            stack_bits.append("HA no responde")

    return {
        "saludo": saludo,
        "timestamp": now.strftime("%H:%M:%S"),
        "sugerencia": sugerencia,
        "sugerencia_cotidiana": sugerencia,
        "pendientes_detectados": pendientes[:3],
        "recordatorios_ayer": pendientes[:3],
        "stack_alerts": stack_bits,
        "username": user,
    }


def format_welcome_voice(cotidiano: dict[str, Any], base_voice: str = "") -> str:
    """Spoken line on HUD/APK boot: greeting only (no suggestions / stack chatter)."""
    saludo = str(cotidiano.get("saludo") or "").strip()
    if saludo:
        return saludo if saludo.endswith((".", "!", "…")) else saludo + "."
    base = (base_voice or "").strip()
    if base:
        # Use only the first sentence of legacy welcome_script if no cotidiano saludo.
        first = base.split(".")[0].strip()
        return first + "." if first else base
    return "Hola. Ya estoy acá."


def cotidiano_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
