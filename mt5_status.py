from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from local_env import load_env_file


def main() -> None:
    load_env_file()
    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, message = mt5.last_error()
        raise SystemExit(f"No se pudo inicializar MT5. last_error=({code}) {message}")

    try:
        ti = mt5.terminal_info()
        ai = mt5.account_info()
        print(
            "terminal="
            + ("OK" if ti else "N/A")
            + f" trade_allowed={getattr(ti, 'trade_allowed', 'N/A')}"
            + f" login={getattr(ai, 'login', 'N/A')}"
            + f" server={getattr(ai, 'server', 'N/A')}"
            + f" balance={getattr(ai, 'balance', 'N/A')}"
            + f" equity={getattr(ai, 'equity', 'N/A')}"
            + f" margin_free={getattr(ai, 'margin_free', 'N/A')}"
        )

        positions = mt5.positions_get() or []
        print(f"positions={len(positions)}")
        for p in positions[:50]:
            print(
                "POS",
                f"ticket={getattr(p, 'ticket', None)}",
                f"symbol={getattr(p, 'symbol', None)}",
                f"type={getattr(p, 'type', None)}",
                f"volume={getattr(p, 'volume', None)}",
                f"price_open={getattr(p, 'price_open', None)}",
                f"sl={getattr(p, 'sl', None)}",
                f"tp={getattr(p, 'tp', None)}",
                f"profit={getattr(p, 'profit', None)}",
                f"magic={getattr(p, 'magic', None)}",
                f"comment={getattr(p, 'comment', None)}",
            )

        orders = mt5.orders_get() or []
        print(f"orders={len(orders)}")
        for o in orders[:50]:
            print(
                "ORD",
                f"ticket={getattr(o, 'ticket', None)}",
                f"symbol={getattr(o, 'symbol', None)}",
                f"type={getattr(o, 'type', None)}",
                f"volume_initial={getattr(o, 'volume_initial', None)}",
                f"state={getattr(o, 'state', None)}",
            )

        utc_to = datetime.now(timezone.utc)
        utc_from = utc_to - timedelta(days=3)
        try:
            mt5.history_select(utc_from, utc_to)
        except Exception:
            pass
        deals = mt5.history_deals_get(utc_from, utc_to) or []
        print(f"deals_last_3d={len(deals)}")
        for d in deals[-30:]:
            print(
                "DEAL",
                f"ticket={getattr(d, 'ticket', None)}",
                f"order={getattr(d, 'order', None)}",
                f"symbol={getattr(d, 'symbol', None)}",
                f"type={getattr(d, 'type', None)}",
                f"volume={getattr(d, 'volume', None)}",
                f"price={getattr(d, 'price', None)}",
                f"profit={getattr(d, 'profit', None)}",
                f"magic={getattr(d, 'magic', None)}",
                f"comment={getattr(d, 'comment', None)}",
            )
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
