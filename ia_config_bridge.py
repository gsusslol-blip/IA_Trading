"""
Puente de control: inyectar parámetros del scanner en memoria (sin tocar .env en disco).

Usado por ``ia_auto_trade_loop`` antes de ``analizar_ia(..., config=...)``.
"""

from __future__ import annotations

import os
from typing import Any

from local_env import load_optuna_flat_params

# Claves que el scanner / loop leen vía ``config`` o ``os.environ``.
_SCANNER_BRIDGE_KEYS: tuple[str, ...] = (
    "IA_SCAN_SOFT_TRIGGER",
    "IA_SCAN_VOLUME_RELAX",
    "IA_SCAN_SKIP_BREAKOUT",
    "IA_SCAN_SKIP_VOLUME_CONFIRM",
    "IA_M15_MOMENTUM_MIN_BODY_RATIO",
    "IA_BREAKOUT_LOOKBACK",
    "m15_context_bars",
    "breakout_lookback",
    "vol_roll_bars",
    "vol_factor",
    "RR",
)


def snapshot_scanner_config_base() -> dict[str, Any]:
    """
    Base para inyección: JSON Optuna (sin escribir disco) + variables actuales del proceso.
    """
    base: dict[str, Any] = dict(load_optuna_flat_params())
    for key in _SCANNER_BRIDGE_KEYS:
        raw = os.environ.get(key, "").strip()
        if raw:
            base[key] = raw
    return base


def inyectar_configuracion_autonoma(
    config_base: dict[str, Any] | None,
    regimen: str,
    rr_calculado: float,
) -> dict[str, Any]:
    """
    Adapta gatillo / volumen / breakout y RR según régimen de mercado.

    ``regimen``: ``RANGO`` | ``TENDENCIA_FUERTE`` | ``ESTANDAR`` (u homólogos ``range`` / ``trend``).
    """
    cfg = dict(config_base or {})
    reg = (regimen or "ESTANDAR").strip().upper()
    if reg in ("RANGE", "RANGO"):
        cfg["IA_SCAN_SOFT_TRIGGER"] = 1
        cfg["IA_SCAN_VOLUME_RELAX"] = 1
        cfg["IA_SCAN_SKIP_BREAKOUT"] = 1
        cfg["RR_ACTUAL"] = float(rr_calculado)
        print("[config-bridge] RANGO: gatillo SUAVE, breakout omitido.", flush=True)
    elif reg in ("TREND", "TENDENCIA", "TENDENCIA_FUERTE"):
        cfg["IA_SCAN_SOFT_TRIGGER"] = 0
        cfg["IA_SCAN_VOLUME_RELAX"] = 0
        cfg["IA_SCAN_SKIP_BREAKOUT"] = 0
        cfg["RR_ACTUAL"] = float(rr_calculado)
        print("[config-bridge] TENDENCIA: gatillo ESTRICTO.", flush=True)
    else:
        cfg["IA_SCAN_SOFT_TRIGGER"] = int(
            os.environ.get("IA_REGIME_AUTO_STD_SOFT", "0").strip() or "0"
        )
        cfg["IA_SCAN_VOLUME_RELAX"] = 1
        cfg["IA_SCAN_SKIP_BREAKOUT"] = 0
        cfg["RR_ACTUAL"] = float(rr_calculado)
        print("[config-bridge] ESTANDAR: configuración equilibrada.", flush=True)
    return cfg


def aplicar_config_en_memoria(config_dinamica: dict[str, Any]) -> None:
    """
    Sincroniza el dict dinámico con ``os.environ`` (p. ej. ``RR`` para ``enviar_orden``).
    No escribe el archivo ``.env``.
    """
    for key, val in config_dinamica.items():
        if val is None:
            continue
        if key == "RR_ACTUAL":
            os.environ["RR"] = str(val)
            continue
        if key.startswith("IA_") or key == "RR":
            os.environ[str(key)] = str(int(val)) if isinstance(val, bool) else str(val)
