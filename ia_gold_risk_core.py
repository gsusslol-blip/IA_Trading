"""Núcleo matemático de lotaje oro (sin dependencia MT5)."""

from __future__ import annotations

import math
import os
import sys


def _margin_max_free_ratio() -> float:
    try:
        v = float(os.environ.get("IA_GOLD_MARGIN_MAX_FREE_RATIO", "0.50").strip() or "0.50")
    except ValueError:
        v = 0.50
    return max(0.10, min(0.90, v))


def _halve_on_margin_pressure() -> bool:
    return os.environ.get("IA_GOLD_MARGIN_HALVE_ENABLE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def lotaje_oro_desde_parametros(
    *,
    equity: float,
    margin_free: float,
    leverage: int,
    contract_size: float,
    precio_entrada: float,
    precio_sl: float,
    porcentaje_riesgo: float,
    volume_step: float,
    volume_min: float,
    volume_max: float,
) -> float:
    """
    Lotes = (equity × riesgo%) / (|entry−SL| × trade_contract_size),
    redondeo hacia abajo al step y tope por margen/apalancamiento.
    """
    if equity <= 0 or contract_size <= 0 or leverage <= 0:
        return 0.0
    distancia = abs(float(precio_entrada) - float(precio_sl))
    if distancia <= 0:
        return 0.0

    dinero_riesgo = float(equity) * (float(porcentaje_riesgo) / 100.0)
    lotes_brutos = dinero_riesgo / (distancia * float(contract_size))

    step = float(volume_step) if volume_step > 0 else 0.01
    lotes = math.floor(lotes_brutos / step) * step if step > 0 else lotes_brutos

    vmin = float(volume_min) if volume_min > 0 else step
    vmax = float(volume_max) if volume_max > 0 else lotes
    lotes = max(vmin, min(vmax, lotes)) if vmax > 0 else max(vmin, lotes)

    if lotes <= 0:
        return 0.0

    if _halve_on_margin_pressure() and margin_free > 0:
        apal = max(1, int(leverage))
        margen_req = (lotes * float(precio_entrada) * float(contract_size)) / apal
        ratio_lim = _margin_max_free_ratio()
        if margen_req > margin_free * ratio_lim:
            print(
                "[gold_risk] Margen alto vs libre: reduciendo lote "
                f"(req~{margen_req:.2f} > {ratio_lim:.0%} de libre {margin_free:.2f})",
                file=sys.stderr,
            )
            lotes_h = math.floor((lotes / 2.0) / step) * step if step > 0 else lotes / 2.0
            lotes = max(vmin, lotes_h)

    return float(lotes)
