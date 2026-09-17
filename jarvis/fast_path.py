"""Zero-LLM Fast-Path Router — mechanical intents before Ollama/Groq.

Flexible enough for spoken variants; still fails closed on ambiguous chat.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

Execute = Callable[[str, str], str]

_WAKE = re.compile(
    r"^(?:hey\s+|ok\s+|hola\s+)?(?:ilaria|friday|fr[ií]day)\b[\s,.:\-]*",
    re.I,
)
_PHONE = frozenset({"android", "ios", "iphone", "ipad"})
_TRAIL_PUNCT = re.compile(r"[?!.,;:…]+$")


def _phone(surface: str) -> bool:
    return (surface or "").strip().lower() in _PHONE


def _clean(text: str) -> str:
    raw = _WAKE.sub("", (text or "").strip()).strip()
    raw = _TRAIL_PUNCT.sub("", raw).strip()
    return re.sub(r"\s+", " ", raw).strip()


def match_fast_path(
    text: str,
    *,
    surface: str = "hud",
) -> tuple[str, dict[str, Any], str] | None:
    """Return (tool, params, rule_name) or None."""
    compact = _clean(text)
    if not compact:
        return None
    lower = compact.lower()
    surf = (surface or "hud").strip().lower()

    # Volume level — allow short trailing politeness ("por favor")
    m = re.fullmatch(
        r"(?:pon(?:eme|[eé])?\s+(?:el\s+)?)?(?:el\s+)?(?:volumen|volume)"
        r"(?:\s+(?:al|a|en|del?|a\s+la))?\s+(\d{1,3})\s*%?"
        r"(?:\s+por\s+favor)?",
        lower,
    )
    if not m:
        m = re.search(
            r"(?:volumen|volume)\s+(?:al|a|en|del?)?\s*(\d{1,3})\s*%?",
            lower,
        )
        # Only accept search form if the phrase is still short/mechanical
        if m and len(lower) > 48:
            m = None
    if m:
        level = max(0, min(100, int(m.group(1))))
        if _phone(surf):
            return "phone_hands", {"action": "volume", "target": str(level)}, "volume_level"
        return "set_volume", {"level": level}, "volume_level"

    if re.fullmatch(
        r"(?:sub[ií]|aument[aá]|subime|subile)\s+(?:el\s+)?(?:volumen|volume|sonido)|"
        r"(?:volumen|volume)\s+(?:para?\s+)?arriba|vol\+|m[aá]s\s+volumen",
        lower,
    ):
        if _phone(surf):
            return "phone_hands", {"action": "volume", "target": "up"}, "volume_up"
        return "media", {"action": "vol_up"}, "volume_up"

    if re.fullmatch(
        r"(?:baj[aá]|reduc[ií]|bajame|bajale)\s+(?:el\s+)?(?:volumen|volume|sonido)|"
        r"(?:volumen|volume)\s+(?:para?\s+)?abajo|vol\-|menos\s+volumen",
        lower,
    ):
        if _phone(surf):
            return "phone_hands", {"action": "volume", "target": "down"}, "volume_down"
        return "media", {"action": "vol_down"}, "volume_down"

    if re.fullmatch(
        r"(?:silenci[aá]|silenciar|mute(?:ar)?|sin\s+sonido|callate|c[aá]llate)"
        r"(?:\s+por\s+favor)?",
        lower,
    ):
        if _phone(surf):
            return "phone_hands", {"action": "volume", "target": "mute"}, "mute"
        return "media", {"action": "mute"}, "mute"

    if re.fullmatch(r"(?:deshac[eé]r?|undo|arrepent(?:ite)?|volvé?\s+atr[aá]s)", lower):
        return "undo_last", {}, "undo"

    if re.fullmatch(
        r"(?:qu[eé]\s+hora\s+es(?:\s+por\s+favor)?|hora|fecha|qu[eé]\s+d[ií]a\s+es(?:\s+hoy)?|ahora)",
        lower,
    ):
        return "now", {}, "now"

    if re.fullmatch(
        r"(?:list[aá]|mostr[aá]|decime|dame)\s+(?:mis\s+)?recetas|"
        r"qu[eé]\s+recetas(?:\s+ten[eé]s)?|cat[aá]logo\s+de\s+recetas|recetas\s+disponibles",
        lower,
    ):
        return "kitchen_recipe", {"action": "listar", "dish": ""}, "kitchen_list"

    if re.fullmatch(
        r"(?:le[eé]r?\s+(?:el\s+)?reloj|reloj|smartwatch|m[eé]tricas(?:\s+del\s+reloj)?|"
        r"c[oó]mo\s+estoy(?:\s+de\s+energ[ií]a)?|pasos\s+de\s+hoy|hrv|"
        r"energ[ií]a\s+(?:de\s+)?hoy)",
        lower,
    ):
        return "wellness_action", {"action": "leer_reloj", "tipo_tema": "smartwatch"}, "watch"

    if re.fullmatch(
        r"(?:diario(?:\s+de\s+hoy)?|le[eé]r?\s+el\s+diario|mostr[aá]\s+el\s+diario|"
        r"bit[aá]cora(?:\s+de\s+hoy)?)",
        lower,
    ):
        return "read_daily_journal", {}, "journal_read"

    if re.fullmatch(r"(?:siguiente|next|pr[oó]xima(?:\s+canci[oó]n)?)", lower):
        return "media", {"action": "next"}, "media_next"

    if re.fullmatch(r"(?:anterior|previous|prev)", lower):
        return "media", {"action": "prev"}, "media_prev"

    if re.fullmatch(r"(?:paus[aá]|pause|play|reproduc[ií]|play[\s\-]?pause)", lower):
        return "media", {"action": "play_pause"}, "media_pause"

    if re.fullmatch(
        r"(?:estado(?:\s+de)?(?:\s+la)?\s+pc|system\s*status|qu[eé]\s+hay\s+abierto)",
        lower,
    ):
        return "system_status", {}, "pc_status"

    if re.fullmatch(
        r"(?:captura(?:\s+de\s+pantalla)?|screenshot|sac[aá]\s+(?:una\s+)?captura)",
        lower,
    ):
        if _phone(surf):
            return "phone_hands", {"action": "screenshot"}, "screenshot"
        return "screenshot", {}, "screenshot"

    return None


def try_fast_path(
    text: str,
    execute: Execute,
    *,
    surface: str = "hud",
    allowed: set[str] | None = None,
) -> str | None:
    """Execute a mechanical tool immediately. None → fall through to local/LLM."""
    t0 = time.perf_counter()
    hit = match_fast_path(text, surface=surface)
    if hit is None:
        return None
    tool, params, rule = hit
    if allowed is not None and tool not in allowed:
        return None
    result = execute(tool, json.dumps(params, ensure_ascii=False))
    ms = (time.perf_counter() - t0) * 1000.0
    print(f"[FAST_PATH] {rule} -> {tool} ({ms:.1f}ms)")
    if tool == "kitchen_recipe":
        try:
            data = json.loads(result)
            if isinstance(data, dict) and data.get("speakable"):
                return str(data["speakable"])
        except (json.JSONDecodeError, TypeError):
            pass
    if tool == "wellness_action":
        try:
            data = json.loads(result)
            if isinstance(data, dict) and data.get("speech"):
                return str(data["speech"])
            if isinstance(data, dict) and data.get("nivel_energia_estimado"):
                return (
                    f"{data.get('pasos_hoy', 0)} pasos · "
                    f"{str(data.get('nivel_energia_estimado', '')).split('.')[0]}"
                )
        except (json.JSONDecodeError, TypeError):
            pass
    return result


try_fast_path_router = try_fast_path
