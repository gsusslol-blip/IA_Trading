"""Android client vs PC channel compatibility."""

from __future__ import annotations

from typing import Any

from jarvis.pc_updater import min_required_android_client, version_gt


def android_app_version(device: dict[str, Any] | None) -> str:
    if not device:
        return ""
    for key in ("app_version", "versionName", "version_name"):
        raw = str(device.get(key) or "").strip()
        if raw:
            return raw
    return ""


def android_upgrade_hint(device: dict[str, Any] | None) -> str:
    """Friendly F.R.I.D.A.Y. note when the phone APK is too old for this PC core."""
    have = android_app_version(device)
    need = min_required_android_client()
    if not have or not need:
        return ""
    if not version_gt(need, have):
        return ""
    return (
        f"Jefe, el núcleo de la PC ya está listo, pero tu app ({have}) es anterior al mínimo "
        f"({need}). Actualizala desde Play Store (o instalá el APK nuevo) para los comandos "
        f"de infraestructura del celular."
    )
