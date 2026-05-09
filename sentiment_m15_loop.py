"""
Bucle M15: volumen + patrón simple + sentimiento binario (analizar_sentimiento_basico).

No usa `mt5.message_send` (no existe en la API Python): alertas con Telegram (.env).
Las órdenes usan `enviar_orden` de ia_auto_trade_loop (SL/TP, spread, BOT_MAGIC, filling).

  python sentiment_m15_loop.py

Requiere: IA_SENTIMENT_M15_ENABLE=1
Recomendado: cuenta DEMO (misma comprobación que ia_auto_trade_loop).
"""

from __future__ import annotations

import os
import sys
import time

import MetaTrader5 as mt5
import pandas as pd

from ia_auto_trade_loop import _demo_only_or_exit, enviar_orden
from local_env import load_env_file
from m15_ma_scan import _resolve_scan_symbol
from mt5_price_engine import get_price_engine
from mt5_prices import _position_side_for_bot
from sentiment_news import analizar_sentimiento_basico


def enviar_alerta(mensaje: str) -> None:
    try:
        from mt5_prices import _telegram_configured, _telegram_send

        if _telegram_configured():
            _telegram_send(mensaje)
    except Exception as e:
        print(f"Telegram: {e}", file=sys.stderr)
    print(mensaje)


def _fail(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def loop_principal() -> None:
    load_env_file()
    if os.environ.get("IA_SENTIMENT_M15_ENABLE", "").strip().lower() not in ("1", "true", "yes"):
        _fail("Definí IA_SENTIMENT_M15_ENABLE=1 en .env para confirmar este modo.")

    raw = os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD")
    activos = [a.strip() for a in raw.split(",") if a.strip()]
    interval = float(os.environ.get("IA_SCAN_INTERVAL_S", "30"))
    cooldown = float(os.environ.get("IA_AUTO_COOLDOWN_S", "900"))

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        _fail(f"No se pudo inicializar MT5. ({code}) {msg}")

    try:
        ti = mt5.terminal_info()
        if ti is not None and not bool(getattr(ti, "trade_allowed", False)):
            _fail("trade_allowed=False: activá Algo Trading en MT5.")

        _demo_only_or_exit()

        resolved: list[tuple[str, str]] = []
        for req in activos:
            r = _resolve_scan_symbol(req)
            if not r:
                print(f"{req}: símbolo no operable.", file=sys.stderr)
                continue
            resolved.append((req, r))
        if not resolved:
            _fail("No hay símbolos válidos.")

        enviar_alerta("IA M15+sentimiento iniciada (DEMO).")

        while True:
            for requested, s in resolved:
                mt5.symbol_select(s, True)
                if _position_side_for_bot(s) is not None:
                    continue

                sentimiento = analizar_sentimiento_basico(s)

                df = get_price_engine().get_data(s, mt5.TIMEFRAME_M15, 4)
                if df is None or df.empty or len(df) < 4:
                    continue
                v_ant, v_act = df.iloc[-3], df.iloc[-2]

                vol_ok = int(v_act["tick_volume"]) > int(v_ant["tick_volume"])
                compra = (float(v_act["close"]) > float(v_ant["open"])) and sentimiento == "ALCISTA"
                venta = (float(v_act["close"]) < float(v_ant["open"])) and sentimiento == "BAJISTA"

                if vol_ok and compra:
                    if enviar_orden(s, buy=True):
                        enviar_alerta(f"Operación enviada COMPRA {requested} ({s})")
                        time.sleep(cooldown)
                        break
                elif vol_ok and venta:
                    if enviar_orden(s, buy=False):
                        enviar_alerta(f"Operación enviada VENTA {requested} ({s})")
                        time.sleep(cooldown)
                        break
            time.sleep(interval)

    except KeyboardInterrupt:
        print("Detenido.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    loop_principal()
