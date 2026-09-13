"""Optional camera / YOLO loop. OFF unless VISION_ENABLED=1.

Does not ship placeholder LAN IPs. Lights go through the existing
home_assistant tool when HA_URL + HA_TOKEN are set.
ultralytics / torch are never imported unless already installed.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from jarvis.state import AppState

_STARTED = False


def vision_enabled() -> bool:
    raw = os.getenv("VISION_ENABLED", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def start_vision(state: AppState | None = None) -> None:
    """No-op stub unless VISION_ENABLED=1. Never probes default camera IPs."""
    global _STARTED
    if _STARTED:
        return
    if not vision_enabled():
        print("[+] Vision disabled (VISION_ENABLED=0).")
        return
    cameras = _cameras_from_env()
    if not cameras:
        print(
            "[-] Vision enabled but VISION_CAMERAS is empty. "
            "Set a JSON list of {id, ha_entity?} — no default 192.168.x URLs."
        )
        return
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        print(
            "[-] Vision: ultralytics/YOLO not installed (skipped on purpose). "
            "Lights: use HA_URL + home_assistant tool if configured."
        )
        _STARTED = True
        return
    _STARTED = True
    thread = threading.Thread(
        target=_vision_loop,
        args=(state, cameras),
        name="ilaria-vision",
        daemon=True,
    )
    thread.start()
    print(f"[+] Vision stub: {len(cameras)} camera(s) configured (no fake IPs).")


def _cameras_from_env() -> list[dict[str, Any]]:
    raw = os.getenv("VISION_CAMERAS", "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("[-] Vision: VISION_CAMERAS is not valid JSON.")
        return []
    if not isinstance(payload, list):
        print("[-] Vision: VISION_CAMERAS must be a JSON list.")
        return []
    cameras: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        cam_id = str(item.get("id") or item.get("name") or "").strip()
        if not cam_id:
            continue
        source = str(item.get("source") or item.get("url") or "").strip()
        ha_entity = str(item.get("ha_entity") or item.get("entity_id") or "").strip()
        cameras.append({"id": cam_id, "source": source, "ha_entity": ha_entity})
    return cameras


def _vision_loop(state: AppState | None, cameras: list[dict[str, Any]]) -> None:
    # Intentionally idle: do not open cameras or hit the network unless a
    # future revision wires a real capture backend the user opted into.
    names = ", ".join(str(cam["id"]) for cam in cameras)
    print(f"[+] Vision loop idle (no capture). Cameras: {names}")
    if state is not None and state.settings.has_ha:
        print("[+] Vision: HA_URL is set — use the home_assistant tool for lights.")
    _ = state
