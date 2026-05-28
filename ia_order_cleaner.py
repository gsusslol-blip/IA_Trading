"""
Cancelación de órdenes límite pendientes vencidas (trampas estadísticas).

Variables:
  IA_ORDER_CLEANER_ENABLE=1
  IA_ORDER_CLEANER_MAX_M15_BARS=1
"""

from __future__ import annotations

import os
import time


def cleaner_enabled() -> bool:
    return os.environ.get("IA_ORDER_CLEANER_ENABLE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _max_velas_espera() -> int:
    try:
        return max(1, min(8, int(os.environ.get("IA_ORDER_CLEANER_MAX_M15_BARS", "1").strip() or "1")))
    except ValueError:
        return 1


def _m15_seconds() -> int:
    return 900


def _is_limit_type(typ: int) -> bool:
    import MetaTrader5 as mt5

    return typ in (
        int(getattr(mt5, "ORDER_TYPE_BUY_LIMIT", -1)),
        int(getattr(mt5, "ORDER_TYPE_SELL_LIMIT", -1)),
        int(getattr(mt5, "ORDER_TYPE_BUY_STOP", -1)),
        int(getattr(mt5, "ORDER_TYPE_SELL_STOP", -1)),
    )


def limpiar_ordenes_limite_vencidas(
    symbol: str | list[str] | None = None,
    magic_number: int | None = None,
    *,
    max_velas_espera: int | None = None,
) -> int:
    """
    Cancela pendientes del ``magic`` cuyo ``time_setup`` supera ``max_velas_espera`` velas M15.

    También cancela si ``time_expiration`` ya pasó.
    """
    if not cleaner_enabled():
        return 0

    import MetaTrader5 as mt5

    from mt5_prices import BOT_MAGIC

    mag = int(magic_number if magic_number is not None else BOT_MAGIC)
    if isinstance(symbol, str):
        symbols = [symbol] if symbol.strip() else []
    elif symbol is None:
        symbols = []
    else:
        symbols = [s for s in symbol if s]

    max_velas = max_velas_espera if max_velas_espera is not None else _max_velas_espera()
    tiempo_limite = max_velas * _m15_seconds()
    ahora = int(time.time())
    n_cancel = 0

    if symbols:
        orders_all: list = []
        for sym in symbols:
            part = mt5.orders_get(symbol=sym)
            if part:
                orders_all.extend(part)
    else:
        orders_all = list(mt5.orders_get() or [])

    seen: set[int] = set()
    for orden in orders_all:
        ticket = int(getattr(orden, "ticket", 0) or 0)
        if ticket <= 0 or ticket in seen:
            continue
        seen.add(ticket)
        if int(getattr(orden, "magic", -1) or -1) != mag:
            continue
        typ = int(getattr(orden, "type", -1))
        if not _is_limit_type(typ):
            continue
        t_setup = int(getattr(orden, "time_setup", 0) or 0)
        t_exp = int(getattr(orden, "time_expiration", 0) or 0)
        vencida = False
        if t_exp > 0 and ahora >= t_exp:
            vencida = True
        elif t_setup > 0 and (ahora - t_setup) >= tiempo_limite:
            vencida = True
        if not vencida:
            continue
        r = mt5.order_send(
            {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": ticket,
                "comment": "IA limit vencida",
            }
        )
        if r is not None and int(getattr(r, "retcode", -1)) == mt5.TRADE_RETCODE_DONE:
            n_cancel += 1
            sym_o = str(getattr(orden, "symbol", "") or "")
            print(
                f"[cleaner] Límite cancelada ticket={ticket} {sym_o} "
                f"(espera>{tiempo_limite}s)",
                flush=True,
            )
    return n_cancel
