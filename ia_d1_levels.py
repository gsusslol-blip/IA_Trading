"""
High/Low del último día D1 cerrado (ayer operativo), con caché TTL para evitar dobles lecturas MT5.

Variables:
  IA_D1_LEVELS_CACHE_TTL_S=60
"""

from __future__ import annotations

import os
import time

_CACHE: dict[str, tuple[tuple[float, float], float]] = {}


def _cache_ttl_s() -> float:
    try:
        return max(10.0, float(os.environ.get("IA_D1_LEVELS_CACHE_TTL_S", "60").strip() or "60"))
    except ValueError:
        return 60.0


def invalidate_d1_levels(symbol: str | None = None) -> None:
    if symbol is None:
        _CACHE.clear()
        return
    _CACHE.pop(symbol.strip(), None)


def high_low_ayer_d1(symbol: str) -> tuple[float, float] | None:
    """
    (high_ayer, low_ayer) de la penúltima vela D1 (última cerrada = «ayer»).
    """
    sym = symbol.strip()
    if not sym:
        return None
    now = time.time()
    hit = _CACHE.get(sym)
    if hit is not None and (now - hit[1]) < _cache_ttl_s():
        return hit[0]

    try:
        import MetaTrader5 as mt5

        tf = mt5.TIMEFRAME_D1
    except Exception:
        return None

    from market_regime import fetch_rates

    pack = fetch_rates(sym, tf, 3)
    if pack is None:
        return None
    highs, lows, _closes = pack
    if len(highs) < 2:
        return None
    result = (float(highs[-2]), float(lows[-2]))
    _CACHE[sym] = (result, now)
    return result
