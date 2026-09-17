"""Local-first wellness: training, nutrition, cycle/pregnancy notes in user sandbox.

Sensitive logs stay under data/users/<user>/workspace/wellness_profile.json.
Always attach a safe health disclaimer on advice/summary surfaces.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.config import DATA_DIR

DISCLAIMER_SALUD = (
    "\n\n*Nota de Ilaria: Este reporte es informativo y basado en parámetros generales. "
    "No reemplaza la consulta con un profesional de la salud o médico especialista.*"
)

_ALLOWED_TIPOS = frozenset(
    {
        "menstruacion",
        "menstruación",
        "sintoma_embarazo",
        "embarazo",
        "entrenamiento",
        "nutricion",
        "nutrición",
        "comida",
        "sintoma",
        "síntoma",
        "general",
    }
)


def wellness_profile_path(usuario: str) -> Path:
    user = (usuario or "guest").strip().lower() or "guest"
    folder = DATA_DIR / "users" / user / "workspace"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "wellness_profile.json"


def ensure_disclaimer(text: str) -> str:
    """Append Safe-Disclaimer once (idempotent)."""
    body = (text or "").rstrip()
    marker = "No reemplaza la consulta"
    if marker.lower() in body.lower():
        return body
    return body + DISCLAIMER_SALUD


def _normalize_tipo(tipo: str) -> str:
    raw = (tipo or "general").strip().lower()
    aliases = {
        "periodo": "menstruacion",
        "período": "menstruacion",
        "menstruación": "menstruacion",
        "ciclo": "menstruacion",
        "regla": "menstruacion",
        "embarazo": "embarazo",
        "sintoma_embarazo": "sintoma_embarazo",
        "síntoma_embarazo": "sintoma_embarazo",
        "entrenamiento": "entrenamiento",
        "ejercicio": "entrenamiento",
        "gym": "entrenamiento",
        "nutricion": "nutricion",
        "nutrición": "nutricion",
        "dieta": "nutricion",
        "comida": "comida",
    }
    return aliases.get(raw, raw if raw in _ALLOWED_TIPOS else "general")


def _load_profile(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("historial_eventos", [])
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"historial_eventos": [], "ultima_actualizacion": 0}


def registrar_evento_ciclo_o_sintoma(
    usuario_activo: str,
    tipo_evento: str,
    notas: str = "",
    *,
    timezone: str = "America/Argentina/Buenos_Aires",
) -> str:
    """Append a private wellness event to the active user's sandbox JSON."""
    path = wellness_profile_path(usuario_activo)
    perfil = _load_profile(path)
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        now = datetime.now()
    tipo = _normalize_tipo(tipo_evento)
    nuevo = {
        "timestamp": now.strftime("%Y-%m-%d %H:%M"),
        "tipo": tipo,
        "notas": (notas or "").strip()[:800],
    }
    historial = list(perfil.get("historial_eventos") or [])
    historial.append(nuevo)
    perfil["historial_eventos"] = historial[-200:]
    perfil["ultima_actualizacion"] = time.time()
    path.write_text(json.dumps(perfil, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return json.dumps(
        {
            "status": "success",
            "evento_guardado": tipo,
            "path": str(path.name),
            "speech": (
                f"Entendido. Quedó registrado en tu perfil de bienestar: {tipo}."
                + DISCLAIMER_SALUD
            ),
        },
        ensure_ascii=False,
    )


def obtener_resumen_bienestar(usuario_activo: str) -> str:
    """Last events for HUD / LLM context (still sandboxed to that user)."""
    path = wellness_profile_path(usuario_activo)
    if not path.is_file():
        return json.dumps(
            {
                "status": "empty",
                "message": "No hay registros de bienestar todavía.",
                "speech": ensure_disclaimer("Todavía no hay hitos de bienestar guardados."),
            },
            ensure_ascii=False,
        )
    perfil = _load_profile(path)
    ultimos = list(perfil.get("historial_eventos") or [])[-5:]
    lines = []
    for item in ultimos:
        lines.append(f"- {item.get('timestamp')}: {item.get('tipo')} — {item.get('notas') or '—'}")
    speak = "Últimos registros de bienestar:\n" + ("\n".join(lines) if lines else "(vacío)")
    return json.dumps(
        {
            "status": "success",
            "resumen": ultimos,
            "speech": ensure_disclaimer(speak),
            "count": len(ultimos),
        },
        ensure_ascii=False,
    )


def consejo_placeholder(tema: str) -> str:
    """Orchestrator hint: LLM should free-text with disclaimer (no external APIs)."""
    return json.dumps(
        {
            "status": "trigger_llm_free_text",
            "tema": _normalize_tipo(tema),
            "disclaimer": DISCLAIMER_SALUD.strip(),
            "message": (
                "Respondé en markdown empático y objetivo sobre el tema solicitado; "
                "al final anexá obligatoriamente el Safe-Disclaimer de salud."
            ),
        },
        ensure_ascii=False,
    )
