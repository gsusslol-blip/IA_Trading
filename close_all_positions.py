from __future__ import annotations

import os
import sys
import time

import MetaTrader5 as mt5

from local_env import load_env_file


def _fail(msg: str, exit_code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(exit_code)


def _allowed_filling_modes(symbol_info) -> list[int]:
    mask = int(getattr(symbol_info, "filling_mode", 0) or 0)
    modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    allowed = [m for m in modes if mask & (1 << m)]
    return allowed if allowed else [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]


def close_position_ticket(ticket: int, deviation: int = 100) -> None:
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        code, message = mt5.last_error()
        _fail(f"No se encontró la posición ticket={ticket}. last_error=({code}) {message}")

    p = pos[0]
    symbol = str(getattr(p, "symbol", ""))
    vol = float(getattr(p, "volume", 0.0) or 0.0)
    ptype = int(getattr(p, "type", -1))
    magic = int(getattr(p, "magic", 0) or 0)

    if vol <= 0 or not symbol:
        _fail(f"Posición inválida ticket={ticket} symbol={symbol} volume={vol}")

    info = mt5.symbol_info(symbol)
    if info is None:
        code, message = mt5.last_error()
        _fail(f"symbol_info({symbol})=None. last_error=({code}) {message}")

    mt5.symbol_select(symbol, True)

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        code, message = mt5.last_error()
        _fail(f"No hay tick para {symbol}. last_error=({code}) {message}")

    # BUY position closes with SELL at bid; SELL position closes with BUY at ask
    if ptype == mt5.POSITION_TYPE_BUY:
        close_type = mt5.ORDER_TYPE_SELL
        price = float(getattr(tick, "bid", 0.0) or 0.0)
    elif ptype == mt5.POSITION_TYPE_SELL:
        close_type = mt5.ORDER_TYPE_BUY
        price = float(getattr(tick, "ask", 0.0) or 0.0)
    else:
        _fail(f"Tipo de posición desconocido ticket={ticket} type={ptype}")

    if price <= 0:
        _fail(f"Precio inválido para cerrar ticket={ticket} price={price}")

    comment = os.environ.get("CLOSE_COMMENT", "CLOSE_ALL")

    last_err = None
    for fm in _allowed_filling_modes(info):
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": vol,
            "type": close_type,
            "position": int(ticket),
            "price": price,
            "deviation": int(deviation),
            "magic": magic,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": int(fm),
        }

        result = mt5.order_send(request)
        if result is None:
            code, message = mt5.last_error()
            last_err = (code, message)
            continue

        retcode = int(getattr(result, "retcode", -999999))
        if retcode in (10009, 10008) or getattr(result, "deal", 0):
            print(f"[CLOSE] OK ticket={ticket} symbol={symbol} vol={vol} retcode={retcode} deal={getattr(result,'deal',0)}")
            return

        last_err = (retcode, getattr(result, "comment", ""))

        # transient no prices
        if "No prices" in str(getattr(result, "comment", "")):
            time.sleep(0.3)
            continue

    _fail(f"No se pudo cerrar ticket={ticket}. last={last_err}")


def main() -> None:
    load_env_file()
    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, message = mt5.last_error()
        _fail(f"No se pudo inicializar MT5. last_error=({code}) {message}")

    try:
        ti = mt5.terminal_info()
        if ti is None:
            code, message = mt5.last_error()
            _fail(f"terminal_info=None. last_error=({code}) {message}")

        if not bool(getattr(ti, "trade_allowed", False)):
            print(
                "Advertencia: trade_allowed=False. "
                "Activa AlgoTrading/AutoTrading en MT5 antes de cerrar posiciones.",
                file=sys.stderr,
            )

        deviation = int(os.environ.get("CLOSE_DEVIATION", "200"))

        positions = mt5.positions_get() or []
        if not positions:
            print("No hay posiciones abiertas.")
            return

        print(f"Cerrando posiciones: {len(positions)}")
        for p in positions:
            ticket = int(getattr(p, "ticket", 0) or 0)
            if ticket <= 0:
                continue
            try:
                close_position_ticket(ticket, deviation=deviation)
            except SystemExit as e:
                print(str(e), file=sys.stderr)

        remaining = mt5.positions_get() or []
        print(f"Posiciones restantes: {len(remaining)}")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
