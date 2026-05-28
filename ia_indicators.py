"""
Indicadores nativos para IA / auditoría: ADX M15, distancia EMA H4, ATR percentil.

Sin TA-Lib; reutiliza caché MT5 del proyecto (``mt5_price_engine`` / ``market_regime.fetch_rates``).
ADX alineado con Wilder de ``market_regime._adx_last`` (misma lógica que régimen y backtest).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import MetaTrader5 as mt5

from market_regime import (
    _adx_last,
    _atr_series,
    _percentile_rank,
    _true_ranges,
    fetch_rates,
)
from mt5_prices import spread_points_from_tick


def _ema_period_h4() -> int:
    try:
        return max(5, min(100, int(os.environ.get("IA_H4_EMA_PERIOD", "20").strip() or "20")))
    except ValueError:
        return 20


def _adx_period_m15() -> int:
    try:
        return max(5, min(50, int(os.environ.get("IA_REGIME_ADX_PERIOD", "14").strip() or "14")))
    except ValueError:
        return 14


def _atr_period_m15() -> int:
    try:
        return max(5, min(50, int(os.environ.get("IA_REGIME_ATR_PERIOD", "14").strip() or "14")))
    except ValueError:
        return 14


def _distancia_ema_h4_pct(symbol: str, *, use_closed_bar: bool = True) -> float:
    """
    Distancia porcentual precio vs EMA(H4). Por defecto usa la última vela **cerrada** (``-2`` en live).
    """
    try:
        use_pandas = os.environ.get("IA_INDICATORS_USE_PANDAS", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        )
    except Exception:
        use_pandas = True

    if use_pandas:
        try:
            from mt5_price_engine import get_price_engine

            pe = get_price_engine()
            df = pe.get_data(symbol, mt5.TIMEFRAME_H4, 55)
            if df.empty or len(df) < _ema_period_h4() + 2:
                return 0.0
            work = df.iloc[:-1] if use_closed_bar and len(df) >= 3 else df
            span = _ema_period_h4()
            ema_s = work["close"].ewm(span=span, adjust=False).mean()
            px = float(work["close"].iloc[-1])
            ema_v = float(ema_s.iloc[-1])
            if ema_v <= 0:
                return 0.0
            return round(((px - ema_v) / ema_v) * 100.0, 4)
        except Exception:
            pass

    pack = fetch_rates(symbol, mt5.TIMEFRAME_H4, 55)
    if pack is None:
        return 0.0
    _h, _l, closes = pack
    if len(closes) < _ema_period_h4() + 2:
        return 0.0
    if use_closed_bar and len(closes) >= 3:
        closes = closes[:-1]
    period = _ema_period_h4()
    # EMA recursiva ligera (Wilder-style alpha)
    alpha = 2.0 / (period + 1.0)
    ema = closes[0]
    for c in closes[1:]:
        ema = alpha * c + (1.0 - alpha) * ema
    px = closes[-1]
    if ema <= 0:
        return 0.0
    return round(((px - ema) / ema) * 100.0, 4)


def _adx_m15(symbol: str) -> float:
    pack = fetch_rates(symbol, mt5.TIMEFRAME_M15, 120)
    if pack is None:
        return 0.0
    highs, lows, closes = pack
    adx = _adx_last(highs, lows, closes, period=_adx_period_m15())
    if adx is None:
        return 0.0
    return round(float(adx), 4)


def _atr_percentil_m15(symbol: str) -> float:
    pack = fetch_rates(symbol, mt5.TIMEFRAME_M15, 120)
    if pack is None:
        return 0.0
    highs, lows, closes = pack
    if len(closes) < 50:
        return 0.0
    trs = _true_ranges(highs, lows, closes)
    atr_ser = _atr_series(trs, _atr_period_m15())
    if not atr_ser:
        return 0.0
    ref = float(closes[-1]) if closes[-1] else 1.0
    cur_pct = (atr_ser[-1] / ref) * 100.0 if ref else 0.0
    hist = [(atr_ser[i] / closes[i + 1]) * 100.0 for i in range(len(atr_ser) - 1) if closes[i + 1]]
    if not hist:
        return 0.0
    pctl = _percentile_rank(cur_pct, hist[-80:])
    return round(float(pctl), 4) if pctl is not None else 0.0


def obtener_metricas_ia(symbol: str, *, buy: bool = True) -> tuple[float, float]:
    """
    Devuelve ``(adx_m15, distancia_ema_h4_pct)``.

    ``buy=False`` invierte el signo de la distancia EMA (útil para ventas).
    """
    adx = _adx_m15(symbol)
    dist = _distancia_ema_h4_pct(symbol)
    if not buy:
        dist = -dist
    return adx, dist


def obtener_snapshot_completo(symbol: str, *, buy: bool = True) -> dict[str, float]:
    """
    Snapshot para ML / ``ia_audit_logger``: spread, hora UTC, ADX, EMA dist, ATR pctl.
    """
    adx, dist = obtener_metricas_ia(symbol, buy=buy)
    sp = spread_points_from_tick(symbol)
    spread_pts = float(sp) if sp is not None else 0.0
    now = datetime.now(timezone.utc)
    hour_utc = now.hour + now.minute / 60.0
    atr_pct = _atr_percentil_m15(symbol)
    return {
        "spread_pts": round(spread_pts, 4),
        "hora_utc": round(hour_utc, 4),
        "adx_m15": adx,
        "distancia_ema_h4": dist,
        "atr_m15_pct": atr_pct,
    }
