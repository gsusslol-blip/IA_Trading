"""Link smartwatch fatigue to Home Assistant lights (local-first).

Reads data/users/<user>/workspace/smartwatch_metrics.json (or live processor).
When energy is low / stress → turn_on configured light entities.
When energy is optimal → turn_off those lights (or a separate off list).

Requires HA_URL + HA_TOKEN. Uses ha_guard (lights on/off only).
Disabled by default until HA_FATIGUE_ENABLED=1.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import httpx

from jarvis.config import Settings, load_settings
from jarvis.ha_guard import HaDenied, authorize_ha_call
from jarvis.smartwatch_processor import procesar_datos_smartwatch

_lock = threading.Lock()
_started = False
_last_action: str | None = None


def _parse_entities(raw: str) -> list[str]:
    out: list[str] = []
    for part in (raw or "").replace(";", ",").split(","):
        eid = part.strip().lower()
        if eid and "." in eid:
            out.append(eid)
    return out


def classify_fatigue(energia: str) -> str:
    """Return low | optimal | moderate from energy blurb."""
    text = (energia or "").lower()
    if "baja" in text or "estrés" in text or "estres" in text:
        return "low"
    if "óptima" in text or "optima" in text:
        return "optimal"
    return "moderate"


def read_watch_energy(username: str) -> dict[str, Any]:
    raw = procesar_datos_smartwatch(username)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "error", "fatigue": "moderate"}
    if data.get("status") != "success":
        return {"status": data.get("status") or "no_data", "fatigue": "moderate"}
    energia = str(data.get("nivel_energia_estimado") or "")
    return {
        "status": "success",
        "fatigue": classify_fatigue(energia),
        "energia": energia,
        "pasos": data.get("pasos_hoy"),
        "hrv": data.get("hrv_ms"),
    }


def call_ha_light(settings: Settings, entity_id: str, service: str, *, is_owner: bool = True) -> str:
    domain = entity_id.split(".", 1)[0]
    spec = authorize_ha_call(
        domain=domain,
        service=service,
        entity_id=entity_id,
        is_owner=is_owner,
        temperature=None,
    )
    url = settings.ha_url.rstrip("/") + f"/api/services/{spec['domain']}/{spec['service']}"
    headers = {
        "Authorization": f"Bearer {settings.ha_token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.post(url, headers=headers, json=spec["payload"] or None)
        response.raise_for_status()
    return f"{spec['domain']}.{spec['service']} {entity_id}"


def apply_fatigue_lights(
    settings: Settings | None = None,
    *,
    username: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Evaluate watch energy and toggle configured HA lights. Idempotent per state."""
    global _last_action
    cfg = settings or load_settings()
    user = (username or os.getenv("TELEGRAM_REMOTE_USER") or cfg.user_name or "gsuss").strip().lower()
    snapshot = read_watch_energy(user)
    fatigue = snapshot.get("fatigue") or "moderate"

    on_entities = _parse_entities(os.getenv("HA_FATIGUE_ON_ENTITIES", os.getenv("HA_FATIGUE_LIGHTS", "")))
    off_entities = _parse_entities(os.getenv("HA_FATIGUE_OFF_ENTITIES", "")) or list(on_entities)

    desired: str | None = None
    targets: list[str] = []
    service = "turn_on"
    if fatigue == "low" and on_entities:
        desired = "fatigue_on"
        targets = on_entities
        service = "turn_on"
    elif fatigue == "optimal" and off_entities:
        desired = "fatigue_off"
        targets = off_entities
        service = "turn_off"

    result: dict[str, Any] = {
        "user": user,
        "fatigue": fatigue,
        "energia": snapshot.get("energia"),
        "desired": desired,
        "actions": [],
        "skipped": None,
    }

    if desired is None:
        result["skipped"] = "moderate_or_unconfigured"
        return result
    if desired == _last_action:
        result["skipped"] = "already_applied"
        return result
    if not cfg.has_ha:
        result["skipped"] = "ha_not_configured"
        if dry_run:
            result["actions"] = [f"dry-run {service} {e}" for e in targets]
        return result

    for entity in targets:
        try:
            if dry_run:
                msg = f"dry-run {service} {entity}"
            else:
                msg = call_ha_light(cfg, entity, service, is_owner=True)
            result["actions"].append(msg)
        except HaDenied as exc:
            result["actions"].append(f"denied {entity}: {exc}")
        except Exception as exc:  # noqa: BLE001
            result["actions"].append(f"error {entity}: {exc}")

    if result["actions"] and not dry_run and not any(a.startswith("error") or a.startswith("denied") for a in result["actions"]):
        _last_action = desired
    elif dry_run:
        pass
    elif result["actions"] and all(not a.startswith("error") and not a.startswith("denied") for a in result["actions"]):
        _last_action = desired

    print(f"[HA-FATIGUE] {user} fatigue={fatigue} -> {desired or 'noop'} {result['actions'] or result.get('skipped')}")
    return result


def start_ha_fatigue_watcher(settings: Settings | None = None) -> None:
    """Background poll of watch energy → HA lights."""
    global _started
    if os.getenv("HA_FATIGUE_ENABLED", "0").strip() not in {"1", "true", "yes", "on"}:
        print("[HA-FATIGUE] off (set HA_FATIGUE_ENABLED=1)")
        return
    cfg = settings or load_settings()
    with _lock:
        if _started:
            return
        _started = True

    try:
        interval = float(os.getenv("HA_FATIGUE_POLL_SEC", "45") or 45)
    except ValueError:
        interval = 45.0
    interval = max(15.0, min(600.0, interval))

    def _run() -> None:
        print(f"[HA-FATIGUE] vigilando energía del reloj cada {interval:.0f}s")
        while True:
            try:
                apply_fatigue_lights(cfg)
            except Exception as exc:  # noqa: BLE001
                print(f"[HA-FATIGUE] ciclo: {exc}")
            time.sleep(interval)

    threading.Thread(target=_run, name="ilaria-ha-fatigue", daemon=True).start()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Apply watch-fatigue → HA lights once")
    parser.add_argument("--user", default="gsuss")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(apply_fatigue_lights(username=args.user, dry_run=args.dry_run), ensure_ascii=False, indent=2))
