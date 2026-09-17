"""Fallback ReAct JSON blob parser when the LLM skips native tool_calls.

Primary path remains OpenAI-compatible function calling in brain.py.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.config import DATA_DIR

_TOOL_ALIASES: dict[str, str] = {
    "trigger_undo": "undo_last",
    "undo": "undo_last",
    "win_action": "set_volume",
    "phone_action": "phone_hands",
    "get_weather": "weather",
    "workspace_scan": "analyze_workspace",
    "analyze_ws": "analyze_workspace",
    "kitchen_action": "kitchen_recipe",
    "kitchen": "kitchen_recipe",
    "receta": "kitchen_recipe",
    "music_action": "music_action",
    "none": "",
    "noop": "",
}


def try_parse_tool_blob(llm_raw: str) -> tuple[str, dict[str, Any]] | None:
    """Return (tool_name, params) if the text contains a tool JSON object."""
    raw = (llm_raw or "").strip()
    if not raw or "{" not in raw:
        return None
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        data = None
        for candidate in _json_candidates(raw):
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if data is None:
            return None
    if not isinstance(data, dict):
        return None
    tool = str(data.get("tool") or data.get("name") or "").strip()
    if not tool or tool.lower() in {"none", "noop", "text", "speech"}:
        return None
    params = data.get("params") or data.get("arguments") or data.get("args") or {}
    if not isinstance(params, dict):
        params = {}
    return _normalize_tool(tool, params)


def log_to_diario(usuario: str, message: str, *, timezone: str = "America/Argentina/Buenos_Aires") -> None:
    """Append a line to data/users/<user>/workspace/diario_YYYY-MM-DD.txt."""
    user = (usuario or "").strip().lower() or "guest"
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        now = datetime.now()
    folder = DATA_DIR / "users" / user / "workspace"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"diario_{now.strftime('%Y-%m-%d')}.txt"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now.strftime('%H:%M')}] - {message}\n")


def parse_and_execute(
    llm_raw_response: str,
    client_info: str = "hud",
    current_user: str | None = None,
    *,
    execute: bool = True,
) -> dict[str, Any]:
    """Parse JSON tool blob; optionally run kitchen/music against the user sandbox."""
    parsed = try_parse_tool_blob(llm_raw_response)
    if not parsed:
        return {"type": "speech", "content": (llm_raw_response or "").strip(), "client": client_info}

    name, params = parsed
    user = (current_user or "guest").strip().lower()
    workspace = DATA_DIR / "users" / user / "workspace"

    if name == "undo_last":
        if execute and current_user:
            log_to_diario(user, "Solicitud de reversión de comando (Undo Táctico).")
        return {"status": "success", "type": "action", "execute": "undo", "tool": name, "client": client_info}

    if name == "set_volume":
        if execute and current_user:
            log_to_diario(user, f"Hardware Action en Windows: volume -> {params.get('level')}")
        return {
            "status": "success",
            "type": "action",
            "execute": "windows",
            "action": "volume",
            "value": params.get("level"),
            "track_undo": True,
            "tool": name,
            "params": params,
            "client": client_info,
        }

    if name == "open_app":
        if execute and current_user:
            log_to_diario(user, f"Hardware Action en Windows: open_app -> {params.get('name')}")
        return {
            "status": "success",
            "type": "action",
            "execute": "windows",
            "action": "open_app",
            "value": params.get("name"),
            "tool": name,
            "params": params,
            "client": client_info,
        }

    if name == "kitchen_recipe":
        action_type = str(params.get("action") or "buscar").strip().lower()
        dish = str(params.get("dish") or params.get("comida") or "").strip()
        recipe_text = str(params.get("recipe_text") or params.get("receta_texto_completo") or "").strip() or None
        if execute and current_user:
            if action_type in {"listar", "list", "catalogo", "catálogo", "list_recipes"}:
                log_to_diario(user, "Listó su catálogo de recetas.")
                from jarvis.kitchen_manager import listar_recetas_disponibles

                raw = listar_recetas_disponibles(workspace)
            else:
                log_to_diario(user, f"Consulta de receta procesada: {dish}")
                from jarvis.kitchen_manager import buscar_o_generar_receta

                raw = buscar_o_generar_receta(dish, workspace, llm_fallback_content=recipe_text, save=True)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"status": "error", "raw": raw}
            payload["tool"] = name
            payload["client"] = client_info
            payload["action"] = action_type
            return payload
        return {
            "type": "kitchen",
            "action": action_type,
            "dish": dish,
            "tool": name,
            "params": params,
            "client": client_info,
        }

    if name in {"music_action", "mix_tracks"}:
        action = str(params.get("action") or ("mix_tracks" if name == "mix_tracks" else "play_standard"))
        if execute and current_user:
            log_to_diario(user, f"Comando de música ejecutado ({action}) vía {client_info}")
            # Dry structural result — full remix needs Actions + audio files
            from jarvis.music_day import _pick_workspace_audio

            available = _pick_workspace_audio(workspace)
            base = params.get("track_base") or params.get("base_file")
            overlay = params.get("track_overlay") or params.get("overlay_file")
            if action in {"mix_tracks", "mix", "hardtech"}:
                return {
                    "status": "mixing_started" if (base and overlay) or len(available) >= 2 else "error",
                    "action": action,
                    "base_detected": bool(base) or len(available) >= 1,
                    "overlay_detected": bool(overlay) or len(available) >= 2,
                    "available": available,
                    "output_target": params.get("output_file") or "remix_generado.mp3",
                    "bpm": params.get("target_bpm") or params.get("bpm_target") or 142,
                    "tool": name,
                    "client": client_info,
                }
            track = params.get("track_name") or params.get("query") or "Playlist"
            return {
                "status": "playing",
                "track": track,
                "mode": "standard",
                "tool": name,
                "client": client_info,
            }
        return {
            "type": "music",
            "job": action,
            "tool": name,
            "params": params,
            "client": client_info,
        }

    if name == "analyze_workspace":
        return {"type": "workspace", "tool": name, "params": params, "client": client_info}

    return {"type": "action", "tool": name, "params": params, "client": client_info}


def _normalize_tool(tool: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    key = tool.strip().lower()
    if key in {"win_action", "windows_action", "pc_action"}:
        action = str(params.get("action") or "").strip().lower()
        value = params.get("value")
        if action in {"volume", "set_volume"}:
            return "set_volume", {"level": value}
        if action in {"open_app", "app", "open"}:
            return "open_app", {"name": value}
        if action in {"media", "mute", "play", "pause", "next", "prev"}:
            return "media", {"action": value or action}
        if action in {"undo", "undo_last"}:
            return "undo_last", {}
    mapped = _TOOL_ALIASES.get(key, tool)
    if mapped == "undo_last":
        return "undo_last", {}
    if mapped == "mix_tracks":
        out = dict(params)
        if "track_base" in out and "base_file" not in out:
            out["base_file"] = out.pop("track_base")
        if "track_overlay" in out and "overlay_file" not in out:
            out["overlay_file"] = out.pop("track_overlay")
        if "target_bpm" in out and "bpm_target" not in out:
            out["bpm_target"] = out.pop("target_bpm")
        return "mix_tracks", out
    if mapped == "kitchen_recipe":
        out = dict(params)
        if "comida" in out and "dish" not in out:
            out["dish"] = out.pop("comida")
        if "receta_texto_completo" in out and "recipe_text" not in out:
            out["recipe_text"] = out.pop("receta_texto_completo")
        if not out.get("action"):
            out["action"] = "listar" if not out.get("dish") and not out.get("recipe_text") else "buscar"
        return "kitchen_recipe", out
    if mapped == "music_action":
        out = dict(params)
        action = str(out.get("action") or "").strip().lower()
        if action in {"mix_tracks", "mix", "hardtech"}:
            if "track_base" in out and "base_file" not in out:
                out["base_file"] = out["track_base"]
            if "track_overlay" in out and "overlay_file" not in out:
                out["overlay_file"] = out["track_overlay"]
        elif action in {"play_standard", "play", ""} and "query" not in out and out.get("track_name"):
            out["query"] = out["track_name"]
        return "music_action", out
    if mapped == "phone_hands" and "action" not in params and params.get("type"):
        params = {**params, "action": params.get("type")}
    return mapped, params


def _json_candidates(raw: str) -> list[str]:
    out: list[str] = []
    start = raw.find("{")
    while start >= 0:
        depth = 0
        for i in range(start, len(raw)):
            ch = raw[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(raw[start : i + 1])
                    break
        start = raw.find("{", start + 1)
    return out
