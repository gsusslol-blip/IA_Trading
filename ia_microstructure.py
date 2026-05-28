"""
Microestructura oro: barrido de liquidez (stop hunt) y ventanas London Gold Fixing.

Variables:
  IA_STOP_HUNT_ENABLE=1
  IA_GOLD_FIXING_ENABLE=1
  IA_MICRO_GOLD_ONLY=1
  IA_GOLD_FIXING_AM_H=10  IA_GOLD_FIXING_AM_M=30
  IA_GOLD_FIXING_PM_H=15  IA_GOLD_FIXING_PM_M=0
  IA_GOLD_FIXING_BLOCK_MIN_BEFORE=10
  IA_GOLD_FIXING_BLOCK_MIN_AFTER=5
  IA_STOP_HUNT_M15_BARS=40
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Literal

BarridoEstado = Literal["SOLO_COMPRAS", "SOLO_VENTAS", "BLOQUEADO"]


def _gold_only() -> bool:
    return os.environ.get("IA_MICRO_GOLD_ONLY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _is_gold(symbol: str) -> bool:
    u = symbol.upper().replace(" ", "")
    return "XAU" in u or "GOLD" in u


def microstructure_applies(symbol: str) -> bool:
    if _gold_only() and not _is_gold(symbol):
        return False
    return stop_hunt_enabled() or gold_fixing_enabled()


def stop_hunt_enabled() -> bool:
    return os.environ.get("IA_STOP_HUNT_ENABLE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def gold_fixing_enabled() -> bool:
    return os.environ.get("IA_GOLD_FIXING_ENABLE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)).strip() or str(default))
    except ValueError:
        return default


def _high_low_ayer_d1(symbol: str) -> tuple[float, float] | None:
    from ia_d1_levels import high_low_ayer_d1

    return high_low_ayer_d1(symbol)


def _session_hi_lo_m15_live(symbol: str, bars: int) -> tuple[float, float] | None:
    try:
        import MetaTrader5 as mt5

        from mt5_prices import mt5_copy_rates_from_pos_cached

        tf = mt5.TIMEFRAME_M15
    except Exception:
        return None
    n = max(20, min(200, bars))
    r = mt5_copy_rates_from_pos_cached(symbol, tf, 0, n)
    if r is None or len(r) < 5:
        return None
    now = datetime.now(timezone.utc)
    day_key = now.date()
    lows: list[float] = []
    highs: list[float] = []
    for bar in r:
        try:
            t = int(bar["time"])
            if datetime.fromtimestamp(t, tz=timezone.utc).date() != day_key:
                continue
            lows.append(float(bar["low"]))
            highs.append(float(bar["high"]))
        except (TypeError, ValueError, KeyError):
            continue
    if not lows:
        lows = [float(x["low"]) for x in r]
        highs = [float(x["high"]) for x in r]
    return min(lows), max(highs)


def _session_hi_lo_from_df(df_m15: Any, ref_unix: int) -> tuple[float, float] | None:
    try:
        import pandas as pd
    except ImportError:
        return None
    if df_m15 is None or len(df_m15) < 5:
        return None
    work = df_m15.copy()
    if "time" not in work.columns:
        return float(work["low"].min()), float(work["high"].max())
    ref_day = datetime.fromtimestamp(int(ref_unix), tz=timezone.utc).date()
    mask = []
    for t in work["time"]:
        try:
            ts = int(t)
            if ts > 10_000_000_000:
                ts //= 1000
            mask.append(datetime.fromtimestamp(ts, tz=timezone.utc).date() == ref_day)
        except (TypeError, ValueError):
            mask.append(True)
    sub = work[mask] if any(mask) else work
    if sub.empty:
        sub = work
    return float(sub["low"].min()), float(sub["high"].max())


def validar_barrido_liquidez(
    symbol: str,
    precio_actual: float,
    *,
    df_m15: Any | None = None,
    ref_bar_unix: int | None = None,
    alto_ayer: float | None = None,
    bajo_ayer: float | None = None,
) -> BarridoEstado:
    """
    SOLO_COMPRAS: barrió mínimo D1 ayer y precio actual > mínimo ayer (rechazo alcista).
    SOLO_VENTAS: barrió máximo D1 ayer y precio actual < máximo ayer.
    """
    if not stop_hunt_enabled():
        return "NEUTRAL"

    px = float(precio_actual)
    if alto_ayer is None or bajo_ayer is None:
        hl = _high_low_ayer_d1(symbol)
        if hl is None:
            return "BLOQUEADO"
        alto_ayer, bajo_ayer = hl

    bars = _int_env("IA_STOP_HUNT_M15_BARS", 40)
    if df_m15 is not None and ref_bar_unix is not None:
        sess = _session_hi_lo_from_df(df_m15, ref_bar_unix)
    else:
        sess = _session_hi_lo_m15_live(symbol, bars)
    if sess is None:
        return "BLOQUEADO"
    minimo_hoy, maximo_hoy = sess

    barrido_compras = (minimo_hoy < float(bajo_ayer)) and (px > float(bajo_ayer))
    barrido_ventas = (maximo_hoy > float(alto_ayer)) and (px < float(alto_ayer))

    if barrido_compras and not barrido_ventas:
        return "SOLO_COMPRAS"
    if barrido_ventas and not barrido_compras:
        return "SOLO_VENTAS"
    if barrido_compras and barrido_ventas:
        return "BLOQUEADO"
    return "BLOQUEADO"


def barrido_permite_señal(
    symbol: str,
    side: str,
    precio_actual: float,
    *,
    df_m15: Any | None = None,
    ref_bar_unix: int | None = None,
    alto_ayer: float | None = None,
    bajo_ayer: float | None = None,
) -> tuple[bool, str]:
    estado = validar_barrido_liquidez(
        symbol,
        precio_actual,
        df_m15=df_m15,
        ref_bar_unix=ref_bar_unix,
        alto_ayer=alto_ayer,
        bajo_ayer=bajo_ayer,
    )
    s = side.upper()
    if estado == "NEUTRAL":
        return True, estado
    if estado == "BLOQUEADO":
        return False, estado
    if s == "BUY":
        return estado == "SOLO_COMPRAS", estado
    if s == "SELL":
        return estado == "SOLO_VENTAS", estado
    return False, estado


def verificar_ventana_gold_fixing(
    *,
    utc_hour: int | None = None,
    utc_minute: int | None = None,
) -> bool:
    """
    True = mercado libre para abrir; False = ventana de manipulación (London Fixing).
    """
    if not gold_fixing_enabled():
        return True

    if utc_hour is None or utc_minute is None:
        now = datetime.now(timezone.utc)
        h, m = now.hour, now.minute
    else:
        h, m = int(utc_hour) % 24, int(utc_minute) % 60

    am_h = _int_env("IA_GOLD_FIXING_AM_H", 10)
    am_m = _int_env("IA_GOLD_FIXING_AM_M", 30)
    pm_h = _int_env("IA_GOLD_FIXING_PM_H", 15)
    pm_m = _int_env("IA_GOLD_FIXING_PM_M", 0)
    before = _int_env("IA_GOLD_FIXING_BLOCK_MIN_BEFORE", 10)
    after = _int_env("IA_GOLD_FIXING_BLOCK_MIN_AFTER", 5)

    def _in_block(fix_h: int, fix_m: int) -> bool:
        start_m = fix_h * 60 + fix_m - before
        end_m = fix_h * 60 + fix_m + after
        cur = h * 60 + m
        return start_m <= cur <= end_m

    if _in_block(am_h, am_m) or _in_block(pm_h, pm_m):
        return False
    return True


def microestructura_permite_entrada(
    symbol: str,
    side: str,
    precio_actual: float,
    *,
    df_m15: Any | None = None,
    ref_bar_unix: int | None = None,
    utc_hour: int | None = None,
    utc_minute: int | None = None,
    alto_ayer: float | None = None,
    bajo_ayer: float | None = None,
) -> tuple[bool, str]:
    """
    Comprueba fixing + barrido alineado con ``side`` (BUY/SELL).
    """
    if not microstructure_applies(symbol):
        return True, ""

    if not verificar_ventana_gold_fixing(utc_hour=utc_hour, utc_minute=utc_minute):
        return False, "gold_fixing_bloqueado"

    if stop_hunt_enabled():
        ok, est = barrido_permite_señal(
            symbol,
            side,
            precio_actual,
            df_m15=df_m15,
            ref_bar_unix=ref_bar_unix,
            alto_ayer=alto_ayer,
            bajo_ayer=bajo_ayer,
        )
        if not ok:
            return False, f"stop_hunt_{est}"
    return True, ""
