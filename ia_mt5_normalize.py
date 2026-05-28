"""
Normalización de precios y volumen según ``symbol_info`` de MT5 (multi-símbolo / multi-decimal).
"""

from __future__ import annotations

import math

import MetaTrader5 as mt5


def _volume_step_decimals(step: float) -> int:
    if step <= 0:
        return 2
    s = f"{step:.10f}".rstrip("0").rstrip(".")
    if "." not in s:
        return 0
    return len(s.split(".", 1)[1])


def normalizar_precio(symbol: str, precio: float, info=None) -> float | None:
    """Redondea al número de ``digits`` del símbolo (evita rechazos por precisión)."""
    try:
        p = float(precio)
    except (TypeError, ValueError):
        return None
    if info is None:
        info = mt5.symbol_info(symbol)
    if info is None:
        return None
    digits = int(getattr(info, "digits", 5) or 5)
    return round(p, digits)


def normalizar_volumen(symbol: str, lotes: float, info=None) -> float | None:
    """
    Ajusta al ``volume_step`` (redondeo hacia abajo), respeta min/max del bróker.
    """
    try:
        v = float(lotes)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if info is None:
        info = mt5.symbol_info(symbol)
    if info is None:
        return None
    step = float(getattr(info, "volume_step", 0.01) or 0.01)
    vmin = float(getattr(info, "volume_min", 0.01) or 0.01)
    vmax = float(getattr(info, "volume_max", 0.0) or 0.0)
    if step > 0:
        v = math.floor(v / step) * step
    v = max(vmin, v)
    if vmax > 0:
        v = min(v, vmax)
    dec = _volume_step_decimals(step)
    return round(v, dec)


def normalizar_operacion(
    symbol: str,
    precio_sl: float,
    lotes_brutos: float,
    *,
    info=None,
) -> tuple[float, float] | None:
    """
    Devuelve ``(lotes_normalizados, sl_normalizado)`` o ``None`` si no hay ``symbol_info``.
    """
    if info is None:
        info = mt5.symbol_info(symbol)
    if info is None:
        return None
    sl_n = normalizar_precio(symbol, precio_sl, info=info)
    vol_n = normalizar_volumen(symbol, lotes_brutos, info=info)
    if sl_n is None or vol_n is None:
        return None
    return float(vol_n), float(sl_n)
