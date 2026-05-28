"""
Estado diferido de órdenes MT5: no reintentar en el mismo ciclo; verificar en la siguiente.

``order_send`` sigue siendo síncrono en el API de MetaTrader5; este módulo evita bucles
bloqueantes de reintentos y registra tickets para sincronizar con ``positions_get`` /
``orders_get`` en la ronda siguiente.

Variables:
  IA_ORDER_ASYNC_ENABLE=1
  IA_ORDER_ASYNC_MAX_FILL_RETRIES=1
"""

from __future__ import annotations

import os
import time
from typing import Any

_PENDING_ORDERS: dict[int, dict[str, Any]] = {}
_PENDING_SLTP: dict[int, dict[str, Any]] = {}


def order_async_enabled() -> bool:
    return os.environ.get("IA_ORDER_ASYNC_ENABLE", "1").strip().lower() in ("1", "true", "yes")


def _max_fill_retries() -> int:
    try:
        return max(1, min(3, int(os.environ.get("IA_ORDER_ASYNC_MAX_FILL_RETRIES", "1").strip() or "1")))
    except ValueError:
        return 1


def _accepted_retcode(rc: int) -> bool:
    import MetaTrader5 as mt5

    done = int(getattr(mt5, "TRADE_RETCODE_DONE", 10009))
    placed = int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008))
    partial = int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010))
    return rc in (done, placed, partial)


def _deferred_retcode(rc: int) -> bool:
    import MetaTrader5 as mt5

    requote = int(getattr(mt5, "TRADE_RETCODE_REQUOTE", 10004))
    reject = int(getattr(mt5, "TRADE_RETCODE_REJECT", 10006))
    timeout = int(getattr(mt5, "TRADE_RETCODE_TIMEOUT", 10012))
    return rc in (requote, reject, timeout)


def register_pending_order(
    order_id: int,
    *,
    symbol: str,
    side: str,
    kind: str = "entry",
) -> None:
    if order_id <= 0:
        return
    _PENDING_ORDERS[int(order_id)] = {
        "symbol": symbol,
        "side": side,
        "kind": kind,
        "ts": time.time(),
    }


def register_pending_sltp(
    position_ticket: int,
    *,
    symbol: str,
    sl: float,
    tp: float,
) -> None:
    if position_ticket <= 0:
        return
    _PENDING_SLTP[int(position_ticket)] = {
        "symbol": symbol,
        "sl": float(sl),
        "tp": float(tp),
        "ts": time.time(),
    }


def order_send_tracked(request: dict[str, Any]) -> tuple[str, Any | None]:
    """
    Un único ``order_send``. Devuelve (estado, result).

    Estados: ``done`` | ``placed`` | ``deferred`` | ``failed``
    """
    import MetaTrader5 as mt5

    sym = str(request.get("symbol", "") or "")
    r = mt5.order_send(request)
    if r is None:
        return "failed", None
    rc = int(getattr(r, "retcode", -1))
    order_id = int(getattr(r, "order", 0) or 0)
    deal_id = int(getattr(r, "deal", 0) or 0)

    if _accepted_retcode(rc):
        if order_id > 0 and deal_id <= 0:
            register_pending_order(order_id, symbol=sym, side="entry", kind="limit")
        return ("placed" if deal_id <= 0 and order_id > 0 else "done"), r

    if order_async_enabled() and _deferred_retcode(rc) and order_id > 0:
        register_pending_order(order_id, symbol=sym, side="entry", kind="deferred")
        return "deferred", r

    return "failed", r


def modify_sltp_tracked(
    request: dict[str, Any],
    *,
    position_ticket: int,
) -> tuple[str, Any | None]:
    """Modificación SL/TP con registro diferido si el bróker no confirma al instante."""
    if not order_async_enabled():
        import MetaTrader5 as mt5

        r = mt5.order_send(request)
        if r is None:
            return "failed", None
        rc = int(getattr(r, "retcode", -1))
        if rc == int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)):
            return "done", r
        return "failed", r

    ticket = int(position_ticket)
    pending = _PENDING_SLTP.get(ticket)
    if pending is not None:
        target_sl = float(pending.get("sl", 0.0) or 0.0)
        try:
            import MetaTrader5 as mt5

            for p in mt5.positions_get(ticket=ticket) or []:
                cur = float(getattr(p, "sl", 0.0) or 0.0)
                if abs(cur - target_sl) < 1e-8 or (
                    target_sl > 0 and cur > 0 and abs(cur - target_sl) / max(target_sl, 1e-9) < 0.0001
                ):
                    _PENDING_SLTP.pop(ticket, None)
                    return "done", None
        except Exception:
            pass
        if time.time() - float(pending.get("ts", 0.0) or 0.0) < 2.0:
            return "deferred", None

    status, r = order_send_tracked(request)
    if status == "done":
        _PENDING_SLTP.pop(ticket, None)
        return "done", r
    if status in ("placed", "deferred"):
        register_pending_sltp(
            ticket,
            symbol=str(request.get("symbol", "") or ""),
            sl=float(request.get("sl", 0.0) or 0.0),
            tp=float(request.get("tp", 0.0) or 0.0),
        )
        return "deferred", r
    return status, r


def sync_deferred_mt5_states(magic: int, symbols: list[str] | None = None) -> int:
    """
    Resuelve órdenes/SLTP pendientes contra ``orders_get`` y ``positions_get``.
    Devuelve cantidad de entradas limpiadas de la caché local.
    """
    if not _PENDING_ORDERS and not _PENDING_SLTP:
        return 0

    import MetaTrader5 as mt5

    mag = int(magic)
    sym_set = set(symbols or [])
    open_order_ids: set[int] = set()
    open_pos: set[int] = set()

    for o in mt5.orders_get() or []:
        if int(getattr(o, "magic", -1) or -1) != mag:
            continue
        oid = int(getattr(o, "ticket", 0) or 0)
        if oid > 0:
            open_order_ids.add(oid)

    for p in mt5.positions_get() or []:
        if int(getattr(p, "magic", -1) or -1) != mag:
            continue
        s = str(getattr(p, "symbol", "") or "")
        if sym_set and s not in sym_set:
            continue
        tid = int(getattr(p, "ticket", 0) or 0)
        if tid > 0:
            open_pos.add(tid)

    cleared = 0
    for oid in list(_PENDING_ORDERS.keys()):
        if oid not in open_order_ids:
            _PENDING_ORDERS.pop(oid, None)
            cleared += 1

    for tid in list(_PENDING_SLTP.keys()):
        if tid not in open_pos:
            _PENDING_SLTP.pop(tid, None)
            cleared += 1
        else:
            try:
                for p in mt5.positions_get(ticket=tid) or []:
                    cur_sl = float(getattr(p, "sl", 0.0) or 0.0)
                    tgt = float(_PENDING_SLTP[tid].get("sl", 0.0) or 0.0)
                    if tgt > 0 and cur_sl > 0 and abs(cur_sl - tgt) < max(1e-5, tgt * 1e-4):
                        _PENDING_SLTP.pop(tid, None)
                        cleared += 1
            except Exception:
                pass

    return cleared


def pending_orders_count() -> int:
    return len(_PENDING_ORDERS) + len(_PENDING_SLTP)
