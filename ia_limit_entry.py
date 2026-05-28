"""
Entrada por orden límite (ahorro de spread) con expiración al cierre de la siguiente vela M15.

Variables:
  IA_LIMIT_ENTRY_ENABLE=0
  IA_LIMIT_ATR_DISCOUNT=0.15
  IA_LIMIT_FALLBACK_MARKET=1
  IA_LIMIT_EXPIRE_BARS=1   — velas M15 tras la señal antes de cancelar
"""

from __future__ import annotations

import os
import sys
import time



def limit_entry_enabled() -> bool:
    return os.environ.get("IA_LIMIT_ENTRY_ENABLE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _atr_discount() -> float:
    try:
        return max(0.05, min(0.5, float(os.environ.get("IA_LIMIT_ATR_DISCOUNT", "0.15").strip() or "0.15")))
    except ValueError:
        return 0.15


def _expire_bars() -> int:
    try:
        return max(1, min(4, int(os.environ.get("IA_LIMIT_EXPIRE_BARS", "1").strip() or "1")))
    except ValueError:
        return 1


def _fallback_market() -> bool:
    return os.environ.get("IA_LIMIT_FALLBACK_MARKET", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def m15_close_last(symbol: str) -> float | None:
    try:
        import MetaTrader5 as mt5

        from mt5_prices import mt5_copy_rates_from_pos_cached

        tf = mt5.TIMEFRAME_M15
    except Exception:
        return None
    r = mt5_copy_rates_from_pos_cached(symbol, tf, 0, 4)
    if r is None or len(r) < 2:
        return None
    try:
        return float(r[-2]["close"])
    except (TypeError, ValueError, KeyError):
        return None


def expiration_unix_after_m15_bars(symbol: str, bars: int | None = None) -> int | None:
    """Unix UTC: fin de la vela M15 ``bars`` después de la última cerrada."""
    try:
        import MetaTrader5 as mt5

        from mt5_prices import mt5_copy_rates_from_pos_cached

        tf = mt5.TIMEFRAME_M15
        period = 900
    except Exception:
        return None
    r = mt5_copy_rates_from_pos_cached(symbol, tf, 0, 5)
    if r is None or len(r) < 2:
        return None
    try:
        t_closed = int(r[-2]["time"])
    except (TypeError, ValueError, KeyError):
        return None
    n = bars if bars is not None else _expire_bars()
    return int(t_closed + period * (n + 1))


def calcular_entrada_limite_eficiente(
    symbol: str,
    tipo_señal: str,
    precio_cierre_m15: float,
    atr_m15: float,
    *,
    info=None,
) -> tuple[int, float]:
    """
    Devuelve ``(ORDER_TYPE_*_LIMIT, precio_límite normalizado)``.
    """
    import MetaTrader5 as mt5

    descuento = float(atr_m15) * _atr_discount()
    side = tipo_señal.upper()
    if side == "BUY":
        precio_limite = float(precio_cierre_m15) - descuento
        typ = mt5.ORDER_TYPE_BUY_LIMIT
    else:
        precio_limite = float(precio_cierre_m15) + descuento
        typ = mt5.ORDER_TYPE_SELL_LIMIT
    try:
        from ia_mt5_normalize import normalizar_precio

        px = normalizar_precio(symbol, precio_limite, info=info)
    except Exception:
        px = None
    if px is None:
        digits = int(getattr(info, "digits", 2) or 2) if info is not None else 2
        px = round(precio_limite, digits)
    return int(typ), float(px)


def _is_limit_order_type(typ: int) -> bool:
    import MetaTrader5 as mt5

    return typ in (
        int(getattr(mt5, "ORDER_TYPE_BUY_LIMIT", -1)),
        int(getattr(mt5, "ORDER_TYPE_SELL_LIMIT", -1)),
    )


def limite_precio_valido(
    symbol: str,
    buy: bool,
    limit_price: float,
    *,
    info=None,
) -> bool:
    import MetaTrader5 as mt5

    if info is None:
        info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return False
    point = float(getattr(info, "point", 0.0) or 0.0)
    stops = int(getattr(info, "trade_stops_level", 0) or 0)
    min_dist = stops * point if point > 0 else 0.0
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    if buy:
        return limit_price < ask - min_dist
    return limit_price > bid + min_dist


def count_bot_limit_orders(symbol: str, magic: int | None = None) -> int:
    """Cuenta BUY/SELL LIMIT pendientes del bot en el símbolo."""
    try:
        import MetaTrader5 as mt5
    except Exception:
        return 0
    from mt5_prices import BOT_MAGIC

    mag = int(magic if magic is not None else BOT_MAGIC)
    sym = symbol.strip()
    if not sym:
        return 0
    orders = mt5.orders_get(symbol=sym) or []
    limit_types = (
        int(getattr(mt5, "ORDER_TYPE_BUY_LIMIT", -1)),
        int(getattr(mt5, "ORDER_TYPE_SELL_LIMIT", -1)),
    )
    n = 0
    for o in orders:
        if int(getattr(o, "magic", -1) or -1) != mag:
            continue
        if int(getattr(o, "type", -1)) in limit_types:
            n += 1
    return n


def limit_pending_blocks(symbol: str, *, magic: int | None = None) -> tuple[bool, str]:
    """
    True si ya hay demasiadas límites pendientes (``IA_LIMIT_MAX_PENDING_PER_SYMBOL``).
    """
    if not limit_entry_enabled():
        return False, ""
    try:
        max_p = int(os.environ.get("IA_LIMIT_MAX_PENDING_PER_SYMBOL", "1").strip() or "1")
    except ValueError:
        max_p = 1
    if max_p <= 0:
        return False, ""
    n = count_bot_limit_orders(symbol, magic)
    if n >= max_p:
        return True, f"{n} límite(s) pendiente(s) (máx {max_p})"
    return False, ""


def cancelar_limites_expirados(symbols: list[str], magic: int | None = None) -> int:
    """Delega en ``ia_order_cleaner`` (expiración MT5 + tiempo M15)."""
    try:
        from ia_order_cleaner import limpiar_ordenes_limite_vencidas

        return limpiar_ordenes_limite_vencidas(symbols, magic)
    except Exception:
        return 0
