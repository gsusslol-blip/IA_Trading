"""
Complementos opcionales para ia_auto_trade_loop: sesion liquida, DXY, breakeven, trailing ATR, reentrada.

Todo desactivado por defecto (flags IA_*_ENABLE=0). Revisar el simbolo DXY en tu bróker (USDX, etc.).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from mt5_prices import mt5_copy_rates_from_pos_cached

from signal_analysis import _atr_series, _true_ranges
from market_regime import fetch_rates
from mt5_prices import BOT_MAGIC
from ia_mt5_normalize import normalizar_precio


_LAST_M15_MANAGED_CLOSE_TS: dict[str, int] = {}

# Cache DXY para enviar_orden (sin recalcular en hot path).
_DXY_GOLD_BLOCK_CACHE: bool = False
_DXY_BIAS_CACHE: str = "OFF"
_DXY_CACHE_MONO: float = 0.0


def m15_last_closed_bar_unix(symbol: str) -> int | None:
    """Unix time de la última vela M15 **cerrada** (rates[-2]); None si no hay datos."""
    r = mt5_copy_rates_from_pos_cached(symbol, mt5.TIMEFRAME_M15, 0, 4)
    if r is None or len(r) < 2:
        return None
    try:
        return int(r[-2]["time"])
    except (TypeError, ValueError, KeyError):
        return None


def m15_atr_last_closed(symbol: str, *, atr_period: int = 14) -> float | None:
    """ATR de la última vela M15 cerrada (misma fuente que gestión activa / SL unificado)."""
    trig = _m15_last_closed_trigger(symbol, atr_period=atr_period)
    if trig is None:
        return None
    try:
        atr = trig.get("atr")
        if atr is None:
            return None
        v = float(atr)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _m15_last_closed_trigger(symbol: str, *, atr_period: int, bars: int | None = None) -> dict | None:
    """
    Devuelve snapshot de la **última vela M15 cerrada** para gestión (cero decisiones intra-vela):
    ``{"time": int, "close": float, "atr": float|None}``.
    """
    try:
        per = int(atr_period)
    except (TypeError, ValueError):
        per = 14
    per = max(2, min(200, per))

    if bars is None:
        bars = max(120, per + 20)
    bars = max(50, min(500, int(bars)))

    r = mt5_copy_rates_from_pos_cached(symbol, mt5.TIMEFRAME_M15, 0, bars)
    if r is None or len(r) < max(per + 5, 10):
        return None

    n = len(r)
    idx = -2 if n >= 2 else -1  # última vela cerrada
    try:
        t = int(r[idx]["time"])
        close = float(r[idx]["close"])
    except Exception:
        return None
    if close <= 0:
        return None

    # ATR basado en TR de velas cerradas (usa close de la vela cerrada idx=-2).
    atr_val: float | None = None
    try:
        highs = [float(x["high"]) for x in r]
        lows = [float(x["low"]) for x in r]
        closes = [float(x["close"]) for x in r]
        trs = _true_ranges(highs, lows, closes)  # len = n-1; TR[j] corresponde a vela i=j+1
        atr_s = _atr_series(trs, per)
        # ATR[k] corresponde a vela i = k + per (índice en closes)
        i = (n + idx)  # idx -2 -> i=n-2
        k = i - per
        if 0 <= k < len(atr_s):
            atr_val = float(atr_s[k])
    except Exception:
        atr_val = None

    return {"time": t, "close": close, "atr": atr_val}


def pro_session_allows_order() -> bool:
    """
    Ventana de liquidez para nuevas órdenes si IA_PRO_SESSION_ENABLE=1.

    Por defecto hora **local del PC** (compat. IA_SCAN_HOUR_*).
    Si defines IA_PRO_SESSION_TZ (ej. America/New_York), la ventana usa esa zona (zoneinfo).
    """
    if os.environ.get("IA_PRO_SESSION_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return True
    try:
        h0 = int(os.environ.get("IA_PRO_SESSION_HOUR_START", "8").strip() or "8")
        h1 = int(os.environ.get("IA_PRO_SESSION_HOUR_END", "17").strip() or "17")
    except ValueError:
        return True
    tz_name = os.environ.get("IA_PRO_SESSION_TZ", "").strip()
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            h = datetime.now(ZoneInfo(tz_name)).hour
        except Exception:
            h = datetime.now().hour
    else:
        h = datetime.now().hour
    if h0 <= h1:
        return h0 <= h <= h1
    return h >= h0 or h <= h1


def _dxy_slope_pct_m15(symbol: str) -> float | None:
    mt5.symbol_select(symbol, True)
    try:
        nbar = int(os.environ.get("IA_DXY_M15_BARS", "64").strip() or "64")
    except ValueError:
        nbar = 64
    nbar = max(30, min(200, nbar))
    r = mt5_copy_rates_from_pos_cached(symbol, mt5.TIMEFRAME_M15, 0, nbar)
    if r is None or len(r) < 30:
        return None
    closes = [float(x["close"]) for x in r]
    try:
        fast = int(os.environ.get("IA_DXY_SLOPE_FAST", "10").strip() or "10")
        slow = int(os.environ.get("IA_DXY_SLOPE_SLOW", "20").strip() or "20")
    except ValueError:
        fast, slow = 10, 20
    if len(closes) < slow + 2:
        return None
    sma_now = sum(closes[-fast:]) / fast
    sma_prev = sum(closes[-slow - fast : -slow]) / slow if len(closes) >= slow + fast else sma_now
    if sma_prev <= 0:
        return None
    return ((sma_now - sma_prev) / sma_prev) * 100.0


def _compute_dxy_bias() -> str:
    """
    ``BULLISH`` | ``BEARISH`` | ``NEUTRAL`` | ``UNKNOWN`` | ``OFF`` (filtro desactivado).
    """
    if os.environ.get("IA_DXY_FILTER_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return "OFF"
    dxy_sym = os.environ.get("IA_DXY_SYMBOL", "").strip()
    if not dxy_sym:
        return "UNKNOWN"
    mode = os.environ.get("IA_DXY_SLOPE_MODE", "sma").strip().lower()
    if mode in ("simple", "close", "bias"):
        from signal_analysis import obtener_bias_dxy

        b = obtener_bias_dxy(symbol=dxy_sym)
        if b == "BULLISH":
            return "BULLISH"
        if b == "BEARISH":
            return "BEARISH"
        return "NEUTRAL"
    sp = _dxy_slope_pct_m15(dxy_sym)
    if sp is None:
        return "UNKNOWN"
    try:
        thr = float(os.environ.get("IA_DXY_SLOPE_MIN_ABS_PCT", "0.02").strip() or "0.02")
    except ValueError:
        thr = 0.02
    if sp >= thr:
        return "BULLISH"
    if sp <= -thr:
        return "BEARISH"
    return "NEUTRAL"


def _dxy_blocks_gold_buy_compute() -> bool:
    """Compat: oro bloqueado si DXY alcista."""
    return _compute_dxy_bias() == "BULLISH"


def refresh_dxy_bias_cache() -> str:
    """Actualiza cache global DXY (llamar 1× por ronda de escaneo)."""
    global _DXY_GOLD_BLOCK_CACHE, _DXY_BIAS_CACHE, _DXY_CACHE_MONO
    _DXY_BIAS_CACHE = _compute_dxy_bias()
    _DXY_GOLD_BLOCK_CACHE = _DXY_BIAS_CACHE == "BULLISH"
    _DXY_CACHE_MONO = time.monotonic()
    return _DXY_BIAS_CACHE


def refresh_dxy_gold_buy_cache() -> bool:
    """Alias histórico → ``refresh_dxy_bias_cache``."""
    return refresh_dxy_bias_cache() == "BULLISH"


def get_dxy_bias_cached() -> str:
    """Lectura de bias con TTL (misma política que ``dxy_blocks_gold_buy_cached``)."""
    if os.environ.get("IA_DXY_FILTER_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return "OFF"
    try:
        ttl = float(os.environ.get("IA_DXY_CACHE_TTL_S", "300").strip() or "300")
    except ValueError:
        ttl = 300.0
    if ttl <= 0 or _DXY_CACHE_MONO <= 0 or (time.monotonic() - _DXY_CACHE_MONO) > ttl:
        return refresh_dxy_bias_cache()
    return _DXY_BIAS_CACHE


def dxy_blocks_gold_buy_cached(gold_symbol: str) -> bool:
    """Lectura rápida en hot path; delega en ``ia_asset_profile.dxy_blocks_buy``."""
    from ia_asset_profile import dxy_blocks_buy

    return dxy_blocks_buy(gold_symbol)


def dxy_blocks_gold_buy(symbol: str) -> bool:
    """
    Recalcula bias DXY y devuelve si bloquea COMPRA para ``symbol`` (multi-activo).
    En envío caliente preferir ``dxy_blocks_gold_buy_cached`` (sin recalcular).
    """
    refresh_dxy_bias_cache()
    from ia_asset_profile import dxy_blocks_buy

    return dxy_blocks_buy(symbol)


def dxy_context_for_alert() -> str:
    """Texto corto para alertas (Telegram): contexto DXY / filtro desactivado."""
    if os.environ.get("IA_DXY_FILTER_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return "DXY: filtro off"
    sym = os.environ.get("IA_DXY_SYMBOL", "").strip()
    if not sym:
        return "DXY: sin IA_DXY_SYMBOL"
    mode = os.environ.get("IA_DXY_SLOPE_MODE", "sma").strip().lower()
    if mode in ("simple", "close", "bias"):
        from signal_analysis import obtener_bias_dxy

        b = obtener_bias_dxy(symbol=sym)
        return f"{sym} bias M15 {b}"
    sp = _dxy_slope_pct_m15(sym)
    if sp is None:
        return f"{sym}: sin datos M15"
    return f"{sym} slope M15 {sp:+.3f}%"


def session_context_for_alert() -> str:
    """Texto para alertas: sesion bancaria / liquidez (IA_PRO_SESSION_*)."""
    if os.environ.get("IA_PRO_SESSION_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return "Sesion pro: off"
    if pro_session_allows_order():
        return "Ventana liquidez: ABIERTA"
    return "Ventana liquidez: CERRADA"


def _sl_respects_stops_level(
    *,
    typ: int,
    ref_price: float,
    new_sl: float,
    point: float,
    stops_level: int,
) -> bool:
    """
    Valida distancia mínima bróker antes de TRADE_ACTION_SLTP (evita retcode Invalid Stops).
    """
    if ref_price <= 0 or new_sl <= 0 or point <= 0:
        return False
    min_dist = float(max(0, int(stops_level))) * point
    if min_dist <= 0:
        return True
    gap = abs(ref_price - new_sl)
    if gap < min_dist - point * 0.05:
        return False
    if typ == mt5.POSITION_TYPE_BUY:
        return new_sl < ref_price - min_dist * 0.99
    if typ == mt5.POSITION_TYPE_SELL:
        return new_sl > ref_price + min_dist * 0.99
    return False


def _initial_risk_price(position) -> float | None:
    """Distancia inicial entrada -> SL en precio (aprox.) para BUY/SELL."""
    typ = int(getattr(position, "type", -1))
    op = float(getattr(position, "price_open", 0.0) or 0.0)
    sl = float(getattr(position, "sl", 0.0) or 0.0)
    if op <= 0 or sl <= 0:
        return None
    if typ == mt5.POSITION_TYPE_BUY:
        if sl >= op:
            return None
        return op - sl
    if typ == mt5.POSITION_TYPE_SELL:
        if sl <= op:
            return None
        return sl - op
    return None


def _current_favorable_move(position, bid: float, ask: float) -> float:
    typ = int(getattr(position, "type", -1))
    op = float(getattr(position, "price_open", 0.0) or 0.0)
    if typ == mt5.POSITION_TYPE_BUY:
        return max(0.0, bid - op)
    if typ == mt5.POSITION_TYPE_SELL:
        return max(0.0, op - ask)
    return 0.0


def _atr_last(symbol: str, tf: int, period: int, bars: int = 120) -> float | None:
    r = mt5_copy_rates_from_pos_cached(symbol, tf, 0, bars)
    if r is None or len(r) < period + 5:
        return None
    highs = [float(x["high"]) for x in r]
    lows = [float(x["low"]) for x in r]
    closes = [float(x["close"]) for x in r]
    trs = _true_ranges(highs, lows, closes)
    ser = _atr_series(trs, period)
    if not ser:
        return None
    return float(ser[-1])


def gestionar_trailing_autonomo(
    posicion,
    atr_m15_cerrado: float,
    multiplicador_trail: float = 2.0,
) -> bool:
    """
    Trailing ATR M15 sobre la vela cerrada (misma política que ``manage_position_expert``).

    Usa precio de cierre M15, no tick en vivo, para evitar whipsaw intra-vela.
    """
    if atr_m15_cerrado <= 0:
        return False
    sym = str(getattr(posicion, "symbol", "") or "")
    try:
        atr_period = int(os.environ.get("IA_AUTO_ATR_PERIOD", "14").strip() or "14")
    except ValueError:
        atr_period = 14
    trigger = {"close": 0.0, "atr": float(atr_m15_cerrado)}
    pack = fetch_rates(sym, mt5.TIMEFRAME_M15, 5)
    if pack is not None:
        _h, _l, closes = pack
        if closes:
            trigger["close"] = float(closes[-2] if len(closes) >= 2 else closes[-1])
    if trigger["close"] <= 0:
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            return False
        typ = int(getattr(posicion, "type", -1))
        trigger["close"] = float(
            getattr(tick, "bid", 0) if typ == mt5.POSITION_TYPE_BUY else getattr(tick, "ask", 0)
        )
    return manage_position_expert(
        posicion,
        trail_mult=float(multiplicador_trail),
        be_trigger_rr=1.0,
        be_buffer_pts=0.0,
        trailing_mode=True,
        trigger=trigger,
    )


def manage_position_expert(
    position,
    *,
    trail_mult: float,
    be_trigger_rr: float,
    be_buffer_pts: float,
    trailing_mode: bool,
    trigger: dict,
) -> bool:
    """
    Breakeven al alcanzar be_trigger_rr * R; trailing ATR si trailing_mode.
    Devuelve True si se envio modificacion (para logging eventual).
    """
    sym = str(getattr(position, "symbol", "") or "")
    info = mt5.symbol_info(sym)
    if info is None:
        return False
    point = float(getattr(info, "point", 0.0) or 0.0)
    digits = int(getattr(info, "digits", 5) or 5)
    if point <= 0:
        return False

    risk = _initial_risk_price(position)
    if risk is None or risk <= 0:
        return False

    typ = int(getattr(position, "type", -1))
    vol = float(getattr(position, "volume", 0.0) or 0.0)
    ticket = int(getattr(position, "ticket", 0) or 0)
    cur_sl = float(getattr(position, "sl", 0.0) or 0.0)
    cur_tp = float(getattr(position, "tp", 0.0) or 0.0)
    op = float(getattr(position, "price_open", 0.0) or 0.0)

    try:
        close_px = float(trigger.get("close", 0.0) or 0.0)
    except Exception:
        close_px = 0.0
    if close_px <= 0:
        return False

    # Favorable move estimado al cierre de M15 (sin ruido intra-vela).
    if typ == mt5.POSITION_TYPE_BUY:
        fav = max(0.0, close_px - op)
    elif typ == mt5.POSITION_TYPE_SELL:
        fav = max(0.0, op - close_px)
    else:
        fav = 0.0
    buf = be_buffer_pts * point

    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        return False
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    ref_px = bid if typ == mt5.POSITION_TYPE_BUY else ask
    if ref_px <= 0:
        return False
    stops_level = int(getattr(info, "trade_stops_level", 0) or 0)

    new_sl = cur_sl
    changed = False
    be_changed = False

    # 1) Breakeven: RR fijo o distancia en ATR M15 (IA_BE_TRIGGER_MODE=atr)
    if os.environ.get("IA_BE_ENABLE", "0").strip().lower() in ("1", "true", "yes"):
        be_mode = os.environ.get("IA_BE_TRIGGER_MODE", "rr").strip().lower()
        try:
            atr_be_mult = float(os.environ.get("IA_BE_ATR_MULT", "1.5").strip() or "1.5")
        except ValueError:
            atr_be_mult = 1.5
        try:
            atr_trig = float(trigger.get("atr")) if trigger.get("atr") is not None else None
        except (TypeError, ValueError):
            atr_trig = None
        if be_mode == "atr" and atr_trig and atr_trig > 0:
            be_threshold = atr_trig * atr_be_mult
        else:
            be_threshold = risk * be_trigger_rr
        if fav >= be_threshold:
            if typ == mt5.POSITION_TYPE_BUY:
                be_sl = op + buf
                if be_sl > cur_sl + point * 0.25:
                    new_sl = max(new_sl, be_sl)
                    changed = True
                    be_changed = True
            elif typ == mt5.POSITION_TYPE_SELL:
                be_sl = op - buf
                if cur_sl == 0 or be_sl < cur_sl - point * 0.25:
                    new_sl = min(cur_sl if cur_sl > 0 else 1e12, be_sl)
                    changed = True
                    be_changed = True

    # 2) Trailing ATR (omitir en la misma vela si BE movió SL — evita arrastrar BE hacia atrás)
    pause_trail_after_be = os.environ.get("IA_BE_PAUSE_TRAILING", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if trailing_mode and not (be_changed and pause_trail_after_be):
        try:
            atr = float(trigger.get("atr")) if trigger.get("atr") is not None else None
        except Exception:
            atr = None
        if atr and atr > 0:
            dist = atr * trail_mult
            if typ == mt5.POSITION_TYPE_BUY:
                trail = close_px - dist
                trail = max(trail, op + buf * 0.5)
                if trail > cur_sl + point * 0.5:
                    new_sl = max(new_sl, trail)
                    changed = True
            elif typ == mt5.POSITION_TYPE_SELL:
                trail = close_px + dist
                if cur_sl == 0 or trail < cur_sl - point * 0.5:
                    new_sl = min(cur_sl if cur_sl > 0 else 1e12, trail)
                    changed = True

    if not changed:
        return False

    sl_norm = normalizar_precio(sym, float(new_sl), info=info)
    if sl_norm is None:
        return False
    new_sl = sl_norm
    if not _sl_respects_stops_level(
        typ=typ,
        ref_price=ref_px,
        new_sl=new_sl,
        point=point,
        stops_level=stops_level,
    ):
        return False

    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": sym,
        "volume": vol,
        "sl": new_sl,
        "tp": cur_tp,
    }
    r = mt5.order_send(req)
    if r is None:
        return False
    rc = int(getattr(r, "retcode", -1))
    if rc == mt5.TRADE_RETCODE_DONE:
        return True
    return False


def gestionar_posiciones_activas(symbols: list[str]) -> None:
    """Alias descriptivo: misma lógica que manage_all_bot_positions_expert (BE + trailing ATR)."""
    manage_all_bot_positions_expert(symbols)


def manage_all_bot_positions_expert(symbols: list[str]) -> None:
    """Recorre posiciones BOT_MAGIC en symbols y aplica BE/trailing **solo en cierre M15**."""
    be_on = os.environ.get("IA_BE_ENABLE", "0").strip().lower() in ("1", "true", "yes")
    if not be_on and not _tp_mode_trailing():
        return
    try:
        atr_period = int(os.environ.get("IA_AUTO_ATR_PERIOD", "14").strip() or "14")
    except ValueError:
        atr_period = 14
    try:
        be_rr = float(os.environ.get("IA_BE_TRIGGER_RR", "1.0").strip() or "1.0")
    except ValueError:
        be_rr = 1.0
    try:
        be_buf = float(os.environ.get("IA_BE_BUFFER_POINTS", "10").strip() or "10")
    except ValueError:
        be_buf = 10.0

    trail = _tp_mode_trailing()
    pos_list = mt5.positions_get()
    if not pos_list:
        return
    sym_set = set(symbols)
    # Agrupar por símbolo para calcular trigger una sola vez por M15 cerrado.
    by_sym: dict[str, list] = {}
    for p in pos_list:
        if int(getattr(p, "magic", -1) or -1) != BOT_MAGIC:
            continue
        s = str(getattr(p, "symbol", "") or "")
        if not s or s not in sym_set:
            continue
        by_sym.setdefault(s, []).append(p)

    for sym, positions in by_sym.items():
        ts = m15_last_closed_bar_unix(sym)
        if ts is None or ts <= 0:
            continue
        trig = _m15_last_closed_trigger(sym, atr_period=atr_period)
        if trig is None:
            continue
        trig_ts = int(trig.get("time", 0) or 0)
        if trig_ts > 0 and trig_ts != ts:
            continue  # descalce índice vs time: esperar próximo ciclo
        if _LAST_M15_MANAGED_CLOSE_TS.get(sym) == ts:
            continue  # ya se gestionó este cierre
        _LAST_M15_MANAGED_CLOSE_TS[sym] = ts

        from ia_asset_profile import symbol_trail_atr_mult

        for p in positions:
            sym_p = str(getattr(p, "symbol", "") or sym)
            trail_mult = symbol_trail_atr_mult(sym_p)
            manage_position_expert(
                p,
                trail_mult=trail_mult,
                be_trigger_rr=be_rr,
                be_buffer_pts=be_buf,
                trailing_mode=trail,
                trigger=trig,
            )


def _tp_mode_trailing() -> bool:
    return os.environ.get("IA_AUTO_TP_MODE", "").strip().lower() in ("trailing_atr", "trail", "trailing")


def last_loss_exit_time_direction(symbol: str) -> tuple[float, bool] | None:
    """Ultimo cierre con PnL neto < 0 por position_id; (unix_ts, posicion era COMPRA)."""
    utc_to = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(days=2)
    try:
        mt5.history_select(utc_from, utc_to)
    except Exception:
        pass
    deals = mt5.history_deals_get(utc_from, utc_to)
    if not deals:
        return None
    by_pid: dict[int, list] = {}
    for d in deals:
        if int(getattr(d, "magic", -1) or -1) != BOT_MAGIC:
            continue
        if str(getattr(d, "symbol", "") or "") != symbol:
            continue
        pid = int(getattr(d, "position_id", 0) or 0)
        if pid <= 0:
            continue
        by_pid.setdefault(pid, []).append(d)

    best: tuple[float, bool] | None = None
    for pid, dl in by_pid.items():
        dl.sort(key=lambda x: int(getattr(x, "time", 0) or 0))
        total = 0.0
        last_out_t = 0
        last_out_type = 0
        for d in dl:
            total += float(getattr(d, "profit", 0.0) or 0.0)
            total += float(getattr(d, "commission", 0.0) or 0.0)
            total += float(getattr(d, "swap", 0.0) or 0.0)
            if int(getattr(d, "entry", -1) or -1) == mt5.DEAL_ENTRY_OUT:
                last_out_t = int(getattr(d, "time", 0) or 0)
                last_out_type = int(getattr(d, "type", 0) or 0)
        if total >= 0 or last_out_t <= 0:
            continue
        pos_fue_compra = last_out_type == mt5.DEAL_TYPE_SELL
        cand = (float(last_out_t), pos_fue_compra)
        if best is None or last_out_t > best[0]:
            best = cand
    return best


def shakeout_reentry_window_active(symbol: str, want_buy: bool) -> bool:
    """
    Tras una perdida del bot, durante N velas M15 permite ignorar cooldown para misma direccion.

    Si IA_SHAKEOUT_USE_CSV=1, exige además un cierre 'bad' reciente del mismo símbolo en
    ia_auto_trade_memory.csv (memoria sincronizada con MT5).
    """
    if os.environ.get("IA_SHAKEOUT_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return False
    last = last_loss_exit_time_direction(symbol)
    if last is None:
        return False
    ts, pos_was_buy = last
    if pos_was_buy != want_buy:
        return False
    try:
        nb = int(os.environ.get("IA_SHAKEOUT_M15_BARS", "3").strip() or "3")
    except ValueError:
        nb = 3
    nb = max(1, min(12, nb))
    max_age = float(nb * 15 * 60)
    age = time.time() - ts
    if age < 0 or age > max_age:
        return False
    if os.environ.get("IA_SHAKEOUT_USE_CSV", "0").strip().lower() in ("1", "true", "yes"):
        try:
            from ia_auto_memory import memory_csv_recent_bad_within

            if not memory_csv_recent_bad_within(symbol, max_age):
                return False
        except Exception:
            return False
    return True
