"""
Complementos opcionales para ia_auto_trade_loop: sesion liquida, DXY, breakeven, trailing ATR, reentrada.

Todo desactivado por defecto (flags IA_*_ENABLE=0). Revisar el simbolo DXY en tu bróker (USDX, etc.).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from signal_analysis import _atr_series, _true_ranges
from mt5_prices import BOT_MAGIC


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
    r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, nbar)
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


def dxy_blocks_gold_buy(gold_symbol: str) -> bool:
    """
    Si el indice DXY (o proxy) sube con fuerza en M15, bloquear COMPRAS en oro (correlacion inversa).

    Modo pendiente simple (alineado con signal_analysis.obtener_bias_dxy):
      IA_DXY_SLOPE_MODE=simple|close|bias
    Por defecto: pendiente SMA (IA_DXY_SLOPE_FAST/SLOW).
    """
    del gold_symbol  # reservado p. ej. futuro multi-activo; el filtro usa IA_DXY_SYMBOL
    if os.environ.get("IA_DXY_FILTER_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return False
    dxy_sym = os.environ.get("IA_DXY_SYMBOL", "").strip()
    if not dxy_sym:
        return False
    mode = os.environ.get("IA_DXY_SLOPE_MODE", "sma").strip().lower()
    if mode in ("simple", "close", "bias"):
        from signal_analysis import obtener_bias_dxy

        b = obtener_bias_dxy(symbol=dxy_sym)
        return b == "BULLISH"
    sp = _dxy_slope_pct_m15(dxy_sym)
    if sp is None:
        return False
    try:
        thr = float(os.environ.get("IA_DXY_SLOPE_MIN_ABS_PCT", "0.02").strip() or "0.02")
    except ValueError:
        thr = 0.02
    return sp >= thr


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
    r = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
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


def manage_position_expert(
    position,
    *,
    atr_period: int,
    trail_mult: float,
    be_trigger_rr: float,
    be_buffer_pts: float,
    trailing_mode: bool,
) -> bool:
    """
    Breakeven al alcanzar be_trigger_rr * R; trailing ATR si trailing_mode.
    Devuelve True si se envio modificacion (para logging eventual).
    """
    sym = str(getattr(position, "symbol", "") or "")
    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        return False
    info = mt5.symbol_info(sym)
    if info is None:
        return False
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    point = float(getattr(info, "point", 0.0) or 0.0)
    digits = int(getattr(info, "digits", 5) or 5)
    if bid <= 0 or ask <= 0 or point <= 0:
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

    fav = _current_favorable_move(position, bid, ask)
    buf = be_buffer_pts * point

    new_sl = cur_sl
    changed = False

    # 1) Breakeven (~1R a favor -> SL a entrada +/- buffer para cubrir spread/comision)
    if os.environ.get("IA_BE_ENABLE", "0").strip().lower() in ("1", "true", "yes"):
        if fav >= risk * be_trigger_rr:
            if typ == mt5.POSITION_TYPE_BUY:
                be_sl = op + buf
                if be_sl > cur_sl + point * 0.25:
                    new_sl = max(new_sl, be_sl)
                    changed = True
            elif typ == mt5.POSITION_TYPE_SELL:
                be_sl = op - buf
                if cur_sl == 0 or be_sl < cur_sl - point * 0.25:
                    new_sl = min(cur_sl if cur_sl > 0 else 1e12, be_sl)
                    changed = True

    # 2) Trailing ATR (TP virtual; solo sube/baja SL a favor)
    if trailing_mode:
        atr = _atr_last(sym, mt5.TIMEFRAME_M5, atr_period)
        if atr and atr > 0:
            dist = atr * trail_mult
            if typ == mt5.POSITION_TYPE_BUY:
                trail = bid - dist
                trail = max(trail, op + buf * 0.5)
                if trail > cur_sl + point * 0.5:
                    new_sl = max(new_sl, trail)
                    changed = True
            elif typ == mt5.POSITION_TYPE_SELL:
                trail = ask + dist
                if cur_sl == 0 or trail < cur_sl - point * 0.5:
                    new_sl = min(cur_sl if cur_sl > 0 else 1e12, trail)
                    changed = True

    if not changed:
        return False

    new_sl = round(float(new_sl), digits)
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
    """Recorre posiciones BOT_MAGIC en symbols y aplica BE/trailing."""
    be_on = os.environ.get("IA_BE_ENABLE", "0").strip().lower() in ("1", "true", "yes")
    if not be_on and not _tp_mode_trailing():
        return
    try:
        atr_period = int(os.environ.get("IA_AUTO_ATR_PERIOD", "14").strip() or "14")
    except ValueError:
        atr_period = 14
    try:
        trail_mult = float(os.environ.get("IA_AUTO_TRAIL_ATR_MULT", "2.5").strip() or "2.5")
    except ValueError:
        trail_mult = 2.5
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
    for p in pos_list:
        if int(getattr(p, "magic", -1) or -1) != BOT_MAGIC:
            continue
        if str(getattr(p, "symbol", "")) not in sym_set:
            continue
        manage_position_expert(
            p,
            atr_period=atr_period,
            trail_mult=trail_mult,
            be_trigger_rr=be_rr,
            be_buffer_pts=be_buf,
            trailing_mode=trail,
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
