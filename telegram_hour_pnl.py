"""
Después de operar (ej. una sesión de ~1 h), envía por Telegram el resumen de operaciones
cerradas del BOT_MAGIC en la ventana rolling de las últimas N horas.

  python telegram_hour_pnl.py

Variables opcionales:
  PNL_WINDOW_HOURS   — default 1.0 (última hora)

`send_pnl_window_telegram` — para otros scripts con MT5 ya inicializado (p. ej. ia_auto_trade_loop).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from local_env import load_env_file


def send_pnl_window_telegram(
    utc_from: datetime,
    utc_to: datetime,
    *,
    heading: str,
) -> bool:
    """
    Requiere MT5 inicializado. Envía por Telegram el PnL de posiciones cerradas del BOT_MAGIC
    cuyo último deal cae en [utc_from, utc_to] (UTC).
    """
    from mt5_prices import (
        BOT_MAGIC,
        _telegram_configured,
        _telegram_send,
        closed_positions_pnls_by_magic,
        closed_trade_winrate_stats,
    )

    if not _telegram_configured():
        return False

    uf = utc_from if utc_from.tzinfo else utc_from.replace(tzinfo=timezone.utc)
    ut = utc_to if utc_to.tzinfo else utc_to.replace(tzinfo=timezone.utc)

    pnls = closed_positions_pnls_by_magic(BOT_MAGIC, uf, ut)
    net = sum(pnls)
    wr, w, l, z = closed_trade_winrate_stats(pnls)
    ai = mt5.account_info()
    cur = str(getattr(ai, "currency", "") or "") if ai else ""
    bal = float(getattr(ai, "balance", 0.0) or 0.0) if ai else 0.0
    pct_line = (
        f"Sobre saldo actual: {(net / bal * 100):+.3f}%\n" if bal > 0 and pnls else ""
    )

    if not pnls:
        msg = (
            f"{heading}\n"
            f"Magic {BOT_MAGIC}\n"
            f"Sin operaciones cerradas en esta ventana.\n"
            f"UTC fin: {ut.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        msg = (
            f"{heading}\n"
            f"Magic {BOT_MAGIC}\n"
            f"PnL neto: {net:+.2f} {cur}\n"
            f"{pct_line}"
            f"Cerradas: {len(pnls)} (W{w} / L{l} / BE{z})\n"
            f"Aciertos: {wr * 100:.1f}%\n"
            f"UTC fin: {ut.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    return bool(_telegram_send(msg))


def main() -> None:
    load_env_file()
    try:
        hours = float(os.environ.get("PNL_WINDOW_HOURS", "1"))
    except ValueError:
        hours = 1.0

    from mt5_prices import _telegram_configured

    if not _telegram_configured():
        print("Configurá TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env", file=sys.stderr)
        raise SystemExit(1)

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        print(f"No se pudo inicializar MT5. ({code}) {msg}", file=sys.stderr)
        raise SystemExit(1)

    try:
        utc_to = datetime.now(timezone.utc)
        utc_from = utc_to - timedelta(hours=max(0.05, hours))
        ok_send = send_pnl_window_telegram(
            utc_from,
            utc_to,
            heading=f"Resumen últimas {hours:g} h",
        )
        if ok_send:
            print("Enviado por Telegram.")
        else:
            print("Falló envío Telegram.", file=sys.stderr)
            raise SystemExit(1)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
