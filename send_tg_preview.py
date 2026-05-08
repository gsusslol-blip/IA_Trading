"""Envía por Telegram un ejemplo del mensaje VIP actual (sin MT5 en vivo)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from local_env import load_env_file


def main() -> None:
    load_env_file()
    os.environ["TELEGRAM_STYLE"] = "vip"
    if not os.environ.get("TELEGRAM_TZ_LABEL"):
        os.environ["TELEGRAM_TZ_LABEL"] = "UTC-03:00"

    from mt5_prices import _telegram_configured, _telegram_signal_message_text, _telegram_send

    if not _telegram_configured():
        print("Configurá TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env", file=sys.stderr)
        raise SystemExit(1)

    raw_sym = os.environ.get("TRADE_SYMBOL", "XAUUSD")
    sym = raw_sym.split("-")[0] if "-" in raw_sym else raw_sym

    body = _telegram_signal_message_text(
        sym,
        "BUY",
        2650.25,
        2650.48,
        2652.3,
        2648.1,
        "M5",
        "M15",
        atr_val=12.45,
        atr_period=14,
        trend_detail="Texto de ejemplo (no es señal en vivo del mercado).",
    )
    msg = body

    if _telegram_send(msg):
        print("Enviado a Telegram.")
    else:
        print("Falló el envío (revisá consola [TG]).", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
