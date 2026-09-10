"""Linux CI/dev stub for the Windows-only ``MetaTrader5`` package.

The IA_Trading project imports ``MetaTrader5`` at module load time and calls it
at runtime to talk to a local MetaTrader 5 terminal. That native package only
ships Windows wheels, so on a Linux Cloud Agent / CI box ``pip install
MetaTrader5`` fails and every project module becomes unimportable.

This stub provides the constants referenced at import time plus no-op versions of
the API functions so the modules import cleanly and the test suite (which mocks
these functions via ``unittest.mock.patch``) can run. It never connects to a
terminal and never places orders. On Windows, install the real package instead.
"""

from __future__ import annotations

from typing import Any

__all__: list[str] = []

# --- Timeframe constants (values mirror the real MetaTrader5 package) ---
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_H1 = 16385
TIMEFRAME_H4 = 16388
TIMEFRAME_D1 = 16408

# --- Order / trade constants ---
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
ORDER_TIME_GTC = 0

TRADE_ACTION_DEAL = 1
TRADE_ACTION_SLTP = 6
TRADE_ACTION_REMOVE = 8
TRADE_RETCODE_DONE = 10009

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1

DEAL_TYPE_SELL = 1
DEAL_ENTRY_OUT = 1

SYMBOL_TRADE_MODE_DISABLED = 0


def _unavailable(name: str) -> Any:
    """Return a callable that no-ops. The real terminal is unavailable here."""

    def _call(*_args: Any, **_kwargs: Any) -> None:
        return None

    _call.__name__ = name
    return _call


def initialize(*_args: Any, **_kwargs: Any) -> bool:
    """No terminal in this environment, so initialization always fails."""
    return False


def shutdown(*_args: Any, **_kwargs: Any) -> None:
    return None


def last_error() -> tuple[int, str]:
    return (-10001, "MetaTrader5 stub: no terminal available")


def version() -> tuple[int, int, str]:
    return (500, 0, "stub")


account_info = _unavailable("account_info")
terminal_info = _unavailable("terminal_info")
symbol_info = _unavailable("symbol_info")
symbol_info_tick = _unavailable("symbol_info_tick")
symbol_select = _unavailable("symbol_select")
symbols_get = _unavailable("symbols_get")
copy_rates_from_pos = _unavailable("copy_rates_from_pos")
copy_rates_range = _unavailable("copy_rates_range")
positions_get = _unavailable("positions_get")
orders_get = _unavailable("orders_get")
order_send = _unavailable("order_send")
order_check = _unavailable("order_check")
order_calc_margin = _unavailable("order_calc_margin")
order_calc_profit = _unavailable("order_calc_profit")
history_deals_get = _unavailable("history_deals_get")
history_select = _unavailable("history_select")
market_book_add = _unavailable("market_book_add")
market_book_get = _unavailable("market_book_get")
market_book_release = _unavailable("market_book_release")
message_send = _unavailable("message_send")
