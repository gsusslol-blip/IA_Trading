"""Owner-only observe/act loop. Python decides; LLM is not polled every tick."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from jarvis.brain import Brain

# Cooldowns so a 2B model never nags every 30s.
_COOLDOWN_S = {
    "hot_pc": 45 * 60,
    "long_session": 90 * 60,
    "ha_light": 2 * 60 * 60,
}

_last_fire: dict[str, float] = {}
_heavy_since: float | None = None


@dataclass(frozen=True)
class Impulse:
    kind: str
    line: str
    tool: str = ""
    args: dict[str, Any] | None = None


def autonomy_enabled() -> bool:
    return os.getenv("AUTONOMY", "1").strip().lower() not in {"0", "false", "no"}


def ha_autonomy_enabled() -> bool:
    """Lights without occupancy sensors stay off unless explicitly enabled."""
    return os.getenv("AUTONOMY_HA", "0").strip().lower() in {"1", "true", "yes"}


def observe(brain: Brain) -> dict[str, Any]:
    """Cheap sensors: PC watchlist + optional HA states. No occupancy invention."""
    status = ""
    try:
        status = brain.actions.system_status()
    except Exception:
        status = ""
    ram_pct, cpu_hint = _win_pressure()
    ha = ""
    if brain.settings.has_ha and ha_autonomy_enabled():
        try:
            ha = brain.actions.home_states("binary_sensor")
            lights = brain.actions.home_states("light")
            ha = f"{ha}\n{lights}"
        except Exception:
            ha = ""
    return {
        "status": status,
        "ram_pct": ram_pct,
        "cpu_hint": cpu_hint,
        "ha": ha,
        "is_owner": brain.is_owner,
    }


def decide(snapshot: dict[str, Any], *, who: str) -> Impulse | None:
    """Rigid Python policy — Gemma is not the planner."""
    if not snapshot.get("is_owner"):
        return None
    name = (who or "pá").strip() or "pá"
    ram = float(snapshot.get("ram_pct") or 0)
    status = str(snapshot.get("status") or "")
    global _heavy_since
    heavy = any(tag in status for tag in ("Steam", "Excel", "Cursor", "VS Code"))
    if ram >= 86 or (ram >= 80 and "Steam" in status):
        if _ready("hot_pc"):
            return Impulse(
                kind="hot_pc",
                line=(
                    f"{name}... la RAM está al {int(ram)}%. "
                    "¿Cierro algo de fondo?"
                ),
            )
    if heavy:
        if _heavy_since is None:
            _heavy_since = time.monotonic()
        elif (time.monotonic() - _heavy_since) >= _COOLDOWN_S["long_session"] and _ready(
            "long_session"
        ):
            return Impulse(
                kind="long_session",
                line=(
                    f"{name}, llevás un rato en la estación. "
                    "Si querés, paro un toque el ruido."
                ),
            )
    else:
        _heavy_since = None
    ha = str(snapshot.get("ha") or "")
    if ha_autonomy_enabled() and "binary_sensor." in ha and "light." in ha:
        occupied = _ha_true(ha, "occupancy") or _ha_true(ha, "motion")
        dark_light = _first_light_off(ha)
        if occupied and dark_light and _ready("ha_light"):
            return Impulse(
                kind="ha_light",
                line=f"{name}, está oscuro... prendo el velador.",
                tool="control_device",
                args={"entity_id": dark_light, "action": "on"},
            )
    return None


def apply_impulse(brain: Brain, impulse: Impulse) -> str:
    if impulse.tool:
        payload = impulse.args or {}
        import json

        result = brain.execute(impulse.tool, json.dumps(payload, ensure_ascii=False))
        return f"{impulse.line} ({result})"
    return impulse.line


def tick(brain: Brain) -> str | None:
    notices: list[str] = []
    if brain.is_owner:
        try:
            from jarvis.self_healing import heal_stack

            healed = heal_stack(brain.settings)
        except Exception:
            healed = None
        if healed:
            notices.append(healed)
        if getattr(brain.memory, "recovered", False):
            brain.memory.recovered = False
            who = (brain.settings.user_name or "pá").strip() or "pá"
            notices.append(
                f"{who}, se había roto el cuaderno de notas pero ya lo arreglé con el backup."
            )
    if not autonomy_enabled() or not brain.is_owner:
        return " ".join(notices) if notices else None
    snap = observe(brain)
    who = (brain.settings.user_name or "pá").strip() or "pá"
    impulse = decide(snap, who=who)
    if impulse is None:
        return " ".join(notices) if notices else None
    _last_fire[impulse.kind] = time.monotonic()
    notices.append(apply_impulse(brain, impulse))
    return " ".join(notices)


def _ready(kind: str) -> bool:
    last = _last_fire.get(kind, 0.0)
    return (time.monotonic() - last) >= _COOLDOWN_S.get(kind, 3600)


def _ha_true(blob: str, needle: str) -> bool:
    for line in blob.splitlines():
        if needle in line.lower() and line.strip().lower().endswith(": on"):
            return True
    return False


def _first_light_off(blob: str) -> str:
    for line in blob.splitlines():
        if line.lower().startswith("light.") and line.strip().lower().endswith(": off"):
            return line.split(":", 1)[0].strip()
    return ""


def _win_pressure() -> tuple[float, str]:
    if os.name != "nt":
        return 0.0, ""
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return 0.0, ""
        return float(stat.dwMemoryLoad), f"ram:{stat.dwMemoryLoad}"
    except Exception:
        return 0.0, ""
