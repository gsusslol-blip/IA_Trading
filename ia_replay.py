"""
Instantáneas de velas para backtest / replay: misma lógica que en vivo sin copy_rates en el instante t.

Uso típico desde ia_backtester: recortar cada DataFrame con time <= cierre de la vela M15 operativa
(evita lookahead). Requiere MT5 solo para cargar historia y symbol_info (digits); la señal usa replay.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import MetaTrader5 as mt5
import pandas as pd

from mt5_prices import mt5_copy_rates_from_pos_cached


def _mid_to_bid_ask(symbol: str, mid: float) -> tuple[float, float]:
    spread = 0.0
    try:
        raw_sym = os.environ.get("IA_BACKTEST_SYNTH_SPREAD_POINTS", "").strip()
        if raw_sym:
            pt = 0.01
            sym_i = symbol.strip() or os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").split(",")[0].strip()
            inf = mt5.symbol_info(sym_i)
            if inf is not None:
                pt = float(getattr(inf, "point", 0.01) or 0.01)
            spread = float(raw_sym) * pt
    except (TypeError, ValueError):
        spread = 0.0
    half = spread / 2.0 if spread > 0 else 0.0
    bid = mid - half
    ask = mid + half
    if spread <= 0:
        bid = ask = mid
    return float(bid), float(ask)


@dataclass(frozen=True)
class IAReplaySnapshot:
    """OHLC alineados al instante simulado + precio medio (bid/ask) de esa vela."""

    df_h4: pd.DataFrame
    df_m15: pd.DataFrame
    df_h1: pd.DataFrame
    df_m5: pd.DataFrame
    bid: float
    ask: float


def replay_from_m15_h4_windows(
    symbol: str,
    df_m15: pd.DataFrame,
    df_h4: pd.DataFrame,
) -> IAReplaySnapshot | None:
    """
    Construye IAReplaySnapshot desde ventanas M15+H4 ya recortadas (backtest rápido / overrides).

    Completa H1/M5 vía MT5 y recorta con time ≤ último cierre M15. Requiere terminal conectado.
    """
    if len(df_m15) < 60 or len(df_h4) < 20:
        return None
    if "time" not in df_m15.columns or "time" not in df_h4.columns:
        return None
    try:
        tc = int(df_m15["time"].iloc[-1])
    except (TypeError, ValueError):
        return None
    sym = symbol.strip() or os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").split(",")[0].strip()

    need_m5 = max(5000, len(df_m15) * 20)
    need_h1 = max(2500, len(df_m15) * 4)
    r5 = mt5_copy_rates_from_pos_cached(sym, mt5.TIMEFRAME_M5, 0, need_m5)
    rh = mt5_copy_rates_from_pos_cached(sym, mt5.TIMEFRAME_H1, 0, need_h1)
    if r5 is None or rh is None or len(r5) < 60 or len(rh) < 80:
        return None
    d5 = pd.DataFrame(r5)
    dh1_full = pd.DataFrame(rh)
    m15 = df_m15.copy()
    m5 = d5[d5["time"] <= tc].copy()
    h1 = dh1_full[dh1_full["time"] <= tc].copy()
    h4 = df_h4[df_h4["time"] <= tc].copy()
    if len(h4) < 20 or len(h1) < 80 or len(m5) < 60:
        return None

    mid = float(m15.iloc[-1]["close"])
    bid, ask = _mid_to_bid_ask(sym, mid)
    return IAReplaySnapshot(df_h4=h4, df_m15=m15, df_h1=h1, df_m5=m5, bid=bid, ask=ask)


def dataframe_for_regime(replay: IAReplaySnapshot) -> pd.DataFrame:
    """Elige el marco temporal de IA_REGIME_TIMEFRAME (M15/M30/H1/H4/D1) sobre los dfs del replay."""
    raw = os.environ.get("IA_REGIME_TIMEFRAME", "H1").strip().upper()
    if raw in ("M15",):
        return replay.df_m15
    if raw in ("H4",):
        return replay.df_h4
    if raw in ("D1",):
        return replay.df_h4
    if raw in ("M30",):
        return replay.df_h1
    return replay.df_h1


def slices_upto_m15_time(
    *,
    t_close: int | float,
    df_m15: pd.DataFrame,
    df_m5: pd.DataFrame,
    df_h1: pd.DataFrame,
    df_h4: pd.DataFrame,
) -> IAReplaySnapshot | None:
    """
    Construye replay sin mirar velas con time > t_close (cierre M15 de referencia).
    t_close: unix time de la columna 'time' de la vela M15 cerrada.
    """
    try:
        tc = int(t_close)
    except (TypeError, ValueError):
        return None

    m15 = df_m15[df_m15["time"] <= tc].copy()
    if len(m15) < 60:
        return None

    m5 = df_m5[df_m5["time"] <= tc].copy()
    h1 = df_h1[df_h1["time"] <= tc].copy()
    h4 = df_h4[df_h4["time"] <= tc].copy()
    if len(h4) < 20 or len(h1) < 80 or len(m5) < 60:
        return None

    last = m15.iloc[-1]
    mid = float(last["close"])
    sym0 = os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").split(",")[0].strip()
    bid, ask = _mid_to_bid_ask(sym0, mid)

    return IAReplaySnapshot(df_h4=h4, df_m15=m15, df_h1=h1, df_m5=m5, bid=bid, ask=ask)


def fetch_history_for_backtest(symbol: str, counts: tuple[int, int, int, int]) -> tuple[pd.DataFrame, ...]:
    """
    Descarga bloques grandes M5,M15,H1,H4 desde MT5 ya inicializado.
    counts: (m5, m15, h1, h4) número de velas desde posición 0.
    """
    c5, c15, c1, c4 = counts
    r5 = mt5_copy_rates_from_pos_cached(symbol, mt5.TIMEFRAME_M5, 0, c5)
    r15 = mt5_copy_rates_from_pos_cached(symbol, mt5.TIMEFRAME_M15, 0, c15)
    rh = mt5_copy_rates_from_pos_cached(symbol, mt5.TIMEFRAME_H1, 0, c1)
    r4 = mt5_copy_rates_from_pos_cached(symbol, mt5.TIMEFRAME_H4, 0, c4)
    if r5 is None or r15 is None or rh is None or r4 is None:
        raise RuntimeError("copy_rates_* devolvió None")
    df5 = pd.DataFrame(r5)
    df15 = pd.DataFrame(r15)
    dfh = pd.DataFrame(rh)
    df4 = pd.DataFrame(r4)
    return df5, df15, dfh, df4