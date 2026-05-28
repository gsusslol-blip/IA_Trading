"""
Zonas de liquidez: proximidad al High/Low del día D1 anterior (± N × ATR M15).

Variables:
  IA_D1_LIQUIDITY_ENABLE=0
  IA_D1_LIQUIDITY_ATR_MULT=2.0
  IA_D1_LIQUIDITY_GOLD_ONLY=1
"""

from __future__ import annotations

import os


def d1_liquidity_enabled() -> bool:
    return os.environ.get("IA_D1_LIQUIDITY_ENABLE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _gold_only() -> bool:
    return os.environ.get("IA_D1_LIQUIDITY_GOLD_ONLY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _is_gold(symbol: str) -> bool:
    u = symbol.upper().replace(" ", "")
    return "XAU" in u or "GOLD" in u


def _atr_mult() -> float:
    try:
        return max(0.5, float(os.environ.get("IA_D1_LIQUIDITY_ATR_MULT", "2.0").strip() or "2.0"))
    except ValueError:
        return 2.0


def _high_low_ayer(symbol: str) -> tuple[float, float] | None:
    from ia_d1_levels import high_low_ayer_d1

    return high_low_ayer_d1(symbol)


def verificar_proximidad_liquidez_diaria(
    symbol: str,
    precio_actual: float,
    atr_m15: float,
    *,
    high_ayer: float | None = None,
    bajo_ayer: float | None = None,
) -> tuple[bool, str]:
    """
    True si el precio está cerca del máximo o mínimo del día anterior (zona ± atr_mult × ATR M15).
    """
    if not d1_liquidity_enabled():
        return True, ""
    if _gold_only() and not _is_gold(symbol):
        return True, ""

    try:
        px = float(precio_actual)
        atr = float(atr_m15)
    except (TypeError, ValueError):
        return True, ""
    if px <= 0 or atr <= 0:
        return True, ""

    if high_ayer is None or bajo_ayer is None:
        hl = _high_low_ayer(symbol)
        if hl is None:
            return True, "sin D1"
        high_ayer, bajo_ayer = hl

    zona = atr * _atr_mult()
    cerca_alto = abs(px - float(high_ayer)) <= zona
    cerca_bajo = abs(px - float(bajo_ayer)) <= zona
    if cerca_alto or cerca_bajo:
        return True, ""
    return False, f"lejos de H/L ayer (zona={zona:.2f})"
