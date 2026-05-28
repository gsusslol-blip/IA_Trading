"""
Sizing por riesgo (MT5): volumen dinámico para arriesgar un % fijo al tocar el SL.

Objetivo: mantener riesgo monetario estable aunque el SL (ATR / % precio) sea ancho o estrecho.
"""

from __future__ import annotations

import math

import MetaTrader5 as mt5

from ia_mt5_normalize import normalizar_volumen


def _round_down_to_step(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    return math.floor(float(value) / float(step)) * float(step)


def calcular_lotaje_dinamico(
    symbol: str,
    *,
    buy: bool,
    entry_price: float,
    sl_price: float,
    riesgo_percent: float,
    use_equity: bool = True,
    info=None,
) -> float | None:
    """
    Volumen (lotes) para arriesgar ~``riesgo_percent`` % al tocar SL.

    - Cálculo principal: ``mt5.order_calc_profit`` sobre 1 lote entre entry y SL (robusto para oro/forex/índices).
    - Ajuste a límites del bróker: ``volume_min/max/step``.
    - Fail-open: retorna ``None`` si no se puede calcular.
    """
    try:
        rp = float(riesgo_percent)
    except (TypeError, ValueError):
        return None
    if rp <= 0:
        return None
    try:
        ep = float(entry_price)
        sp = float(sl_price)
    except (TypeError, ValueError):
        return None
    if ep <= 0 or sp <= 0:
        return None

    acct = mt5.account_info()
    if acct is None:
        return None
    base = float(getattr(acct, "equity" if use_equity else "balance", 0.0) or 0.0)
    if base <= 0:
        return None
    risk_money = base * (rp / 100.0)

    if info is None:
        info = mt5.symbol_info(symbol)
    if info is None:
        return None

    typ = mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL
    pl = mt5.order_calc_profit(typ, symbol, 1.0, float(ep), float(sp))
    if pl is None:
        return None
    loss_mag = abs(min(0.0, float(pl)))
    if loss_mag <= 1e-12:
        return None

    vol = risk_money / loss_mag
    vol_n = normalizar_volumen(symbol, vol, info=info)
    if vol_n is None:
        vol_step = float(getattr(info, "volume_step", 0.01) or 0.01)
        vol_min = float(getattr(info, "volume_min", 0.01) or 0.01)
        vol_max = float(getattr(info, "volume_max", 0.0) or 0.0)
        vol = max(vol_min, _round_down_to_step(vol, vol_step))
        if vol_max > 0:
            vol = min(vol, vol_max)
        return float(vol)
    return float(vol_n)

