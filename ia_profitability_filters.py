"""
Filtros de rentabilidad: ventana institucional (Londres/NY UTC) y spread vs típico del bróker.

Variables:
  IA_PROFIT_SESSION_ENABLE=1
  IA_PROFIT_SESSION_GOLD_ONLY=1   — solo XAU* / GOLD
  IA_PROFIT_LONDON_UTC_START=7    IA_PROFIT_LONDON_UTC_END=11
  IA_PROFIT_NY_UTC_START=12       IA_PROFIT_NY_UTC_END=17
  IA_PROFIT_SPREAD_MULT=1.5
  IA_PROFIT_SPREAD_CHECK=1
"""

from __future__ import annotations

import os
from datetime import datetime, timezone


def _enabled() -> bool:
    return os.environ.get("IA_PROFIT_SESSION_ENABLE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _gold_only() -> bool:
    return os.environ.get("IA_PROFIT_SESSION_GOLD_ONLY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _is_gold_symbol(symbol: str) -> bool:
    u = symbol.upper().replace(" ", "")
    return "XAU" in u or "GOLD" in u


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)).strip() or str(default))
    except ValueError:
        return default


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)).strip() or str(default))
    except ValueError:
        return default


def sesion_utc_alta_rentabilidad(hora_utc: int) -> bool:
    """
    Londres y Nueva York en UTC (ajustable por .env).
    Incluye extremos: [start, end] en cada ventana.
    """
    h = int(hora_utc) % 24
    l0 = _int_env("IA_PROFIT_LONDON_UTC_START", 7)
    l1 = _int_env("IA_PROFIT_LONDON_UTC_END", 11)
    n0 = _int_env("IA_PROFIT_NY_UTC_START", 12)
    n1 = _int_env("IA_PROFIT_NY_UTC_END", 17)
    l0, l1 = max(0, min(23, l0)), max(0, min(23, l1))
    n0, n1 = max(0, min(23, n0)), max(0, min(23, n1))
    en_londres = l0 <= h <= l1 if l0 <= l1 else (h >= l0 or h <= l1)
    en_ny = n0 <= h <= n1 if n0 <= n1 else (h >= n0 or h <= n1)
    return bool(en_londres or en_ny)


def spread_liquidez_ok(symbol: str) -> tuple[bool, str]:
    """
    Spread en puntos vs ``symbol_info.spread`` del bróker × mult (default 1.5).
    """
    if os.environ.get("IA_PROFIT_SPREAD_CHECK", "1").strip().lower() in ("0", "false", "no"):
        return True, ""
    import MetaTrader5 as mt5

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return False, "sin tick/symbol_info"
    point = float(getattr(info, "point", 0.0) or 0.0)
    if point <= 0:
        return False, "point inválido"
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    if bid <= 0 or ask <= 0:
        return False, "bid/ask inválido"
    spread_pts = (ask - bid) / point
    typical = float(getattr(info, "spread", 0) or 0)
    if typical <= 0:
        typical = spread_pts
    mult = _float_env("IA_PROFIT_SPREAD_MULT", 1.5)
    if spread_pts > typical * mult:
        return False, f"spread {spread_pts:.1f}pts > {typical:.1f}×{mult:g}"
    return True, ""


def validar_ventana_alta_rentabilidad(
    symbol: str,
    *,
    utc_hour: int | None = None,
) -> tuple[bool, str]:
    """
    True si la ventana UTC es operable y el spread no indica baja liquidez.
    """
    if not _enabled():
        return True, ""
    if _gold_only() and not _is_gold_symbol(symbol):
        return True, ""

    h = utc_hour if utc_hour is not None else datetime.now(timezone.utc).hour
    if not sesion_utc_alta_rentabilidad(h):
        return False, f"fuera de sesion Londres/NY (UTC h={h})"

    ok_sp, why_sp = spread_liquidez_ok(symbol)
    if not ok_sp:
        return False, why_sp
    return True, ""
