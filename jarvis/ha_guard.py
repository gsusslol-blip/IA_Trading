"""Hardcoded Home Assistant limits — run AFTER the LLM, BEFORE any HTTP call."""

from __future__ import annotations

import re
from typing import Any

ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")

THERMOSTAT_MIN = 18.0
THERMOSTAT_MAX = 26.0

MEMBER_DOMAINS = frozenset({"light", "switch", "fan", "input_boolean"})
OWNER_DOMAINS = frozenset(
    {"climate", "scene", "lock", "cover", "alarm_control_panel", "input_number"}
)
DENIED_DOMAINS = frozenset(
    {
        "shell_command",
        "python_script",
        "rest_command",
        "command_line",
        "hassio",
        "homeassistant",
        "recorder",
        "system_log",
        "persistent_notification",
        "script",
        "template",
    }
)
ON_OFF = frozenset({"turn_on", "turn_off", "toggle"})
ACTION_ALIASES = {
    "on": "turn_on",
    "off": "turn_off",
    "prender": "turn_on",
    "apagar": "turn_off",
    "encender": "turn_on",
    "toggle": "toggle",
    "lock": "lock",
    "unlock": "unlock",
    "open": "open_cover",
    "close": "close_cover",
}


class HaDenied(ValueError):
    pass


def normalize_action(raw: str) -> str:
    key = (raw or "").strip().lower()
    return ACTION_ALIASES.get(key, key)


def authorize_ha_call(
    *,
    domain: str,
    service: str,
    entity_id: str = "",
    is_owner: bool,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Return sanitized payload. Raises HaDenied if the LLM asked for something unsafe."""
    domain = (domain or "").strip().lower()
    service = normalize_action(service)
    entity = (entity_id or "").strip().lower()
    if domain in DENIED_DOMAINS:
        raise HaDenied("Esa acción de casa está bloqueada en código (no la puede pedir el modelo).")
    if domain not in MEMBER_DOMAINS and domain not in OWNER_DOMAINS:
        raise HaDenied(f"Dominio HA no permitido: {domain or '(vacío)'}.")
    if domain in OWNER_DOMAINS and not is_owner:
        raise HaDenied("Permiso denegado: esa parte de la casa es solo del dueño.")
    if entity:
        if not ENTITY_RE.match(entity):
            raise HaDenied("entity_id inválido.")
        prefix = entity.split(".", 1)[0]
        if prefix != domain:
            raise HaDenied("entity_id no coincide con el dominio.")
    payload: dict[str, Any] = {}
    if entity:
        payload["entity_id"] = entity

    if domain in MEMBER_DOMAINS:
        if service not in ON_OFF:
            raise HaDenied("Luces/enchufes: solo on, off o toggle.")
        return {"domain": domain, "service": service, "payload": payload}

    if domain == "climate":
        if service in ON_OFF:
            return {"domain": domain, "service": service, "payload": payload}
        if service == "set_temperature":
            if temperature is None:
                raise HaDenied("Falta temperatura.")
            temp = float(temperature)
            if temp < THERMOSTAT_MIN or temp > THERMOSTAT_MAX:
                raise HaDenied(
                    f"Termostato limitado a {THERMOSTAT_MIN:.0f}–{THERMOSTAT_MAX:.0f} °C "
                    "(tope de seguridad, no lo cambia el LLM)."
                )
            payload["temperature"] = temp
            return {"domain": domain, "service": service, "payload": payload}
        raise HaDenied("Clima: solo on/off o set_temperature 18–26.")

    if domain == "lock":
        if service not in {"lock", "unlock"}:
            raise HaDenied("Cerradura: solo lock o unlock.")
        return {"domain": domain, "service": service, "payload": payload}

    if domain == "cover":
        if service not in {"open_cover", "close_cover", "stop_cover"}:
            raise HaDenied("Cover: open_cover, close_cover o stop_cover.")
        return {"domain": domain, "service": service, "payload": payload}

    if domain == "alarm_control_panel":
        if service not in {"alarm_arm_home", "alarm_arm_away", "alarm_disarm"}:
            raise HaDenied("Alarma: arm_home, arm_away o disarm.")
        return {"domain": domain, "service": service, "payload": payload}

    if domain == "scene" and service == "turn_on":
        return {"domain": domain, "service": service, "payload": payload}

    if domain == "input_number" and service == "set_value":
        raise HaDenied("input_number bloqueado (evita inyectar rangos).")

    raise HaDenied(f"Servicio no permitido: {domain}.{service}")
