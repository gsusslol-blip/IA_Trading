"""
Conmutación automática de filtros según régimen M15 (ADX + percentil ATR).

Sobrescribe variables en ``os.environ`` cada ronda (no modifica el .env en disco).
"""

from __future__ import annotations

import os

import MetaTrader5 as mt5

from market_regime import (
    _adx_last,
    _atr_series,
    _percentile_rank,
    _true_ranges,
    fetch_rates,
)


def _env_on(key: str, default: str = "0") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")


def _m15_regime_metrics(symbol: str) -> tuple[float | None, float | None]:
    """ADX M15 y percentil ATR% (últimas ~100 velas cerradas)."""
    try:
        nbar = int(os.environ.get("IA_REGIME_AUTO_BARS", "120").strip() or "120")
    except ValueError:
        nbar = 120
    nbar = max(80, min(500, nbar))
    pack = fetch_rates(symbol, mt5.TIMEFRAME_M15, nbar)
    if pack is None:
        return None, None
    highs, lows, closes = pack
    if len(closes) < 50:
        return None, None
    try:
        p_adx = int(os.environ.get("IA_REGIME_ADX_PERIOD", "14").strip() or "14")
    except ValueError:
        p_adx = 14
    adx = _adx_last(highs, lows, closes, period=p_adx)
    try:
        p_atr = int(os.environ.get("IA_REGIME_ATR_PERIOD", "14").strip() or "14")
    except ValueError:
        p_atr = 14
    trs = _true_ranges(highs, lows, closes)
    atr_ser = _atr_series(trs, p_atr)
    atr_pct = None
    if atr_ser and len(atr_ser) > 30:
        cur_atr = atr_ser[-1]
        ref = float(closes[-1]) if closes[-1] else 1.0
        cur_pct = (cur_atr / ref) * 100.0 if ref else None
        hist_pct = [
            (atr_ser[i] / closes[i + 1]) * 100.0
            for i in range(len(atr_ser) - 1)
            if closes[i + 1]
        ]
        if cur_pct is not None and hist_pct:
            atr_pct = _percentile_rank(cur_pct, hist_pct[-100:])
    return adx, atr_pct


def apply_regime_autopilot(symbol: str) -> str:
    """
    Ajusta filtros en memoria según régimen M15.

    Rango: ADX < umbral bajo o ATR pctl < pctl bajo → soft trigger, RR menor.
    Tendencia: ADX > umbral alto → modo estricto, RR mayor.

    Retorna etiqueta corta: ``range`` | ``trend`` | ``neutral`` | ``off``.
    """
    if not _env_on("IA_REGIME_AUTO_ENABLE", "0"):
        return "off"

    adx, atr_pct = _m15_regime_metrics(symbol)
    try:
        adx_low = float(os.environ.get("IA_REGIME_AUTO_ADX_RANGE_MAX", "20").strip() or "20")
    except ValueError:
        adx_low = 20.0
    try:
        adx_high = float(os.environ.get("IA_REGIME_AUTO_ADX_TREND_MIN", "35").strip() or "35")
    except ValueError:
        adx_high = 35.0
    try:
        atr_low_pctl = float(os.environ.get("IA_REGIME_AUTO_ATR_LOW_PCTL", "25").strip() or "25")
    except ValueError:
        atr_low_pctl = 25.0
    try:
        rr_range = os.environ.get("IA_REGIME_AUTO_RR_RANGE", "1.5").strip() or "1.5"
        rr_trend = os.environ.get("IA_REGIME_AUTO_RR_TREND", "2.5").strip() or "2.5"
    except ValueError:
        rr_range, rr_trend = "1.5", "2.5"

    in_range = False
    if adx is not None and adx <= adx_low:
        in_range = True
    if atr_pct is not None and atr_pct <= atr_low_pctl:
        in_range = True

    in_trend = adx is not None and adx >= adx_high

    if in_range and not in_trend:
        os.environ["IA_SCAN_SOFT_TRIGGER"] = "1"
        os.environ["IA_SCAN_SKIP_BREAKOUT"] = os.environ.get(
            "IA_REGIME_AUTO_SKIP_BREAKOUT_RANGE", "1"
        ).strip() or "1"
        os.environ["RR"] = rr_range
        if _env_on("IA_REGIME_AUTO_RELAX_VOLUME", "1"):
            os.environ["IA_SCAN_VOLUME_RELAX"] = "1"
        return "range"

    if in_trend:
        os.environ["IA_SCAN_SOFT_TRIGGER"] = "0"
        os.environ["IA_SCAN_SKIP_BREAKOUT"] = "0"
        os.environ["RR"] = rr_trend
        if _env_on("IA_REGIME_AUTO_STRICT_TREND", "1"):
            os.environ["IA_H4_EMA_ALIGN_ENABLE"] = "1"
            os.environ["IA_M15_MOMENTUM_ENABLE"] = "1"
        return "trend"

    return "neutral"
