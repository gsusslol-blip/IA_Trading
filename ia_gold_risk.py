"""
Lotaje institucional para oro (XAU*): contract size MT5, riesgo % equity y tope de margen por apalancamiento.

Variables:
  IA_GOLD_RISK_ENABLE=1
  IA_GOLD_MARGIN_MAX_FREE_RATIO=0.50
  IA_GOLD_MARGIN_HALVE_ENABLE=1
"""

from __future__ import annotations

import sys

from ia_gold_risk_core import lotaje_oro_desde_parametros
from ia_mt5_normalize import normalizar_volumen


def calcular_lotaje_oro_institucional(
    symbol: str,
    precio_entrada: float,
    precio_sl: float,
    porcentaje_riesgo: float,
    *,
    use_equity: bool = True,
    info=None,
) -> float:
    """
    Volumen en lotes para oro: riesgo monetario / (distancia SL × ``trade_contract_size``),
    normalizado al bróker y acotado por margen según apalancamiento de la cuenta.
    """
    import MetaTrader5 as mt5

    cuenta = mt5.account_info()
    if info is None:
        info = mt5.symbol_info(symbol)
    if cuenta is None or info is None:
        print("[gold_risk] Sin account_info o symbol_info.", file=sys.stderr)
        return 0.0

    base = float(
        getattr(cuenta, "equity" if use_equity else "balance", 0.0) or 0.0
    )
    margin_free = float(getattr(cuenta, "margin_free", 0.0) or 0.0)
    leverage = int(getattr(cuenta, "leverage", 1) or 1)

    contract_size = float(getattr(info, "trade_contract_size", 0.0) or 0.0)
    if contract_size <= 0:
        contract_size = 100.0

    vol = lotaje_oro_desde_parametros(
        equity=base,
        margin_free=margin_free,
        leverage=leverage,
        contract_size=contract_size,
        precio_entrada=float(precio_entrada),
        precio_sl=float(precio_sl),
        porcentaje_riesgo=float(porcentaje_riesgo),
        volume_step=float(getattr(info, "volume_step", 0.01) or 0.01),
        volume_min=float(getattr(info, "volume_min", 0.01) or 0.01),
        volume_max=float(getattr(info, "volume_max", 0.0) or 0.0),
    )
    if vol <= 0:
        return 0.0

    vol_n = normalizar_volumen(symbol, vol, info=info)
    return float(vol_n if vol_n is not None else vol)
