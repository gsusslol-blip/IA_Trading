"""
Sizing por riesgo (MT5): volumen dinámico para arriesgar un % fijo al tocar el SL.

Objetivo: mantener riesgo monetario estable aunque el SL (ATR / % precio) sea ancho o estrecho.
"""

from __future__ import annotations

import math
import os

import MetaTrader5 as mt5

from ia_mt5_normalize import normalizar_volumen
from mt5_prices import BOT_MAGIC, _allowed_filling_modes_symbol


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


def _margin_check_ok_retcodes() -> set[int]:
    codes = {0}
    for name in ("TRADE_RETCODE_DONE", "TRADE_RETCODE_PLACED", "TRADE_RETCODE_OK"):
        c = getattr(mt5, name, None)
        if c is not None:
            codes.add(int(c))
    return codes


def validar_margen_disponible(
    symbol: str,
    *,
    buy: bool,
    volume: float,
    entry_price: float,
    sl_price: float | None = None,
    tp_price: float = 0.0,
    deviation: int | None = None,
    magic: int | None = None,
) -> tuple[bool, str]:
    """
    Simula la orden con ``mt5.order_check`` antes del envío real.

    Bloquea si MT5 rechaza (p. ej. 10019 No Money) o si el margen libre residual
    quedaría por debajo de ``IA_MARGIN_MIN_FREE_RATIO`` × margen libre actual.
    """
    if os.environ.get("IA_MARGIN_CHECK_ENABLE", "1").strip().lower() in ("0", "false", "no"):
        return True, ""

    try:
        vol = float(volume)
        price = float(entry_price)
    except (TypeError, ValueError):
        return False, "volumen o precio inválido"
    if vol <= 0 or price <= 0:
        return False, "volumen o precio <= 0"

    acct = mt5.account_info()
    if acct is None:
        return False, "account_info=None"
    margin_free_now = float(getattr(acct, "margin_free", 0.0) or 0.0)
    if margin_free_now <= 0:
        return False, "sin margen libre"

    typ = mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL
    sl = float(sl_price) if sl_price is not None else 0.0
    tp = float(tp_price or 0.0)
    dev = int(deviation if deviation is not None else int(os.environ.get("DEVIATION", "20").strip() or "20"))
    mag = int(magic if magic is not None else BOT_MAGIC)

    filling_modes = _allowed_filling_modes_symbol(symbol)
    last_why = "order_check falló"
    ok_codes = _margin_check_ok_retcodes()

    for fm in filling_modes:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": vol,
            "type": typ,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": dev,
            "magic": mag,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": int(fm),
        }
        check = mt5.order_check(request)
        if check is None:
            code, msg = mt5.last_error()
            last_why = f"order_check=None ({code}) {msg}"
            continue

        retcode = int(getattr(check, "retcode", -1))
        if retcode not in ok_codes:
            last_why = f"retcode={retcode} comment={getattr(check, 'comment', '')}"
            if retcode == int(getattr(mt5, "TRADE_RETCODE_NO_MONEY", 10019)):
                break
            continue

        margin_after = getattr(check, "margin_free", None)
        if margin_after is None:
            need = mt5.order_calc_margin(typ, symbol, vol, price)
            if need is not None and float(need) > margin_free_now + 1e-8:
                last_why = f"margen requerido {float(need):.2f} > libre {margin_free_now:.2f}"
                continue
            return True, ""

        try:
            min_ratio = float(os.environ.get("IA_MARGIN_MIN_FREE_RATIO", "0.20").strip() or "0.20")
        except ValueError:
            min_ratio = 0.20
        min_ratio = max(0.05, min(0.95, min_ratio))
        threshold = margin_free_now * min_ratio
        if float(margin_after) < threshold:
            last_why = (
                f"margen libre post-orden {float(margin_after):.2f} < "
                f"umbral {threshold:.2f} ({min_ratio:.0%} del libre actual)"
            )
            try:
                from ia_autonomy_notify import notify_margin_blocked

                notify_margin_blocked(symbol, vol, last_why)
            except Exception:
                pass
            return False, last_why
        return True, ""

    return False, last_why

