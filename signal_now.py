"""
Una lectura al momento: misma lógica que el bot (M5 + filtro M15) y envío por Telegram.

No predice el futuro; resume qué dice la estrategia ahora y el contexto en velas de 5 min.

Uso:
  python signal_now.py

Requiere MT5 abierto y .env con TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID (o variables de entorno).

Alerta corta tipo canal: TELEGRAM_STYLE=vip (opcional TELEGRAM_TZ_LABEL=UTC-03:00).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import MetaTrader5 as mt5

from local_env import load_env_file


def _outlook_es(signal: str, trend_ok_buy: bool, trend_ok_sell: bool) -> str:
    if signal == "BUY":
        return (
            "Sesgo alcista en la entrada (M5): el cruce favorece compras mientras las medias "
            "mantengan este orden y el filtro de tendencia en M15 siga alineado. "
            "Si el precio vuelve debajo de la SMA lenta en M5, la idea de entrada se debilita."
        )
    if signal == "SELL":
        return (
            "Sesgo bajista en la entrada (M5): el cruce favorece ventas mientras las medias "
            "mantengan este orden y M15 no contradiga. "
            "Si el precio recupera por encima de la SMA lenta en M5, el sesgo bajista se debilita."
        )
    parts = []
    if not trend_ok_buy and not trend_ok_sell:
        parts.append("La estrategia no ve entrada clara: filtro de tendencia en M15 no acompaña el cruce en M5.")
    else:
        parts.append("La estrategia está en espera (HOLD): sin cruce direccional claro en M5 o sin alineación con M15.")
    return " ".join(parts)


def main() -> None:
    load_env_file()

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        print(f"No se pudo inicializar MT5. ({code}) {msg}", file=sys.stderr)
        raise SystemExit(1)

    try:
        from mt5_prices import (
            _telegram_configured,
            _telegram_operation_guidance,
            _telegram_send,
            _telegram_signal_message_text,
            _telegram_signal_style,
            fetch_strategy_snapshot,
        )

        if not _telegram_configured():
            print(
                "Faltan TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env o en el entorno.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        try:
            snap = fetch_strategy_snapshot(os.environ.get("TRADE_SYMBOL", "XAUUSD"))
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            raise SystemExit(1)

        symbol = snap.symbol
        bid = snap.bid
        ask = snap.ask
        fast_sma = snap.fast_sma
        slow_sma = snap.slow_sma
        atr_val = snap.atr_val
        atr_period = snap.atr_period
        sl_atr_mult = snap.sl_atr_mult
        rr = snap.rr
        signal = snap.signal
        trend_detail_sn = snap.trend_detail
        secs_left = snap.secs_left_m5
        trend_ok_buy = snap.trend_ok_buy
        trend_ok_sell = snap.trend_ok_sell
        m_left, s_left = secs_left // 60, secs_left % 60

        mid = (bid + ask) / 2.0
        sl_hint = ""
        if atr_val and mid > 0:
            sd = float(atr_val * sl_atr_mult)
            sl_hint = (
                f"Referencia de volatilidad (ATR14 M5 × {sl_atr_mult}): ~{sd:.2f} "
                f"(~{(sd / mid) * 100:.3f}% del precio). RR típico del bot = {rr}. "
                "Vos decidís SL/TP según tu plan."
            )

        spread = ask - bid if ask >= bid else 0.0
        outlook = _outlook_es(signal, trend_ok_buy, trend_ok_sell)

        guidance = _telegram_operation_guidance(signal, "M5", "M15", trend_detail_sn)

        if _telegram_signal_style() in ("vip", "short", "channel", "resumen"):
            msg = _telegram_signal_message_text(
                symbol,
                signal,
                bid,
                ask,
                fast_sma,
                slow_sma,
                "M5",
                "M15",
                atr_val=atr_val,
                atr_period=atr_period,
                sl_atr_mult=sl_atr_mult,
                rr=rr,
                trend_detail=trend_detail_sn,
                m5_secs_left=secs_left,
            )
            msg += f"\nUTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            msg = (
                "Lectura ahora (marco ~5 min, velas M5)\n"
                f"{guidance}\n"
                f"Símbolo: {symbol}\n"
                f"Dirección sistema (último cierre M5): {signal}\n"
                f"Bid / Ask: {bid:.2f} / {ask:.2f} (spread {spread:.2f})\n"
                f"SMA rápida / lenta (M5): {fast_sma:.5f} / {slow_sma:.5f}\n"
                f"Tendencia M15 (filtro): fast vs slow coherente con BUY={trend_ok_buy}, con SELL={trend_ok_sell}\n"
                f"Próximo cierre de vela M5 (aprox.): en ~{m_left}m {s_left}s\n\n"
                f"Qué implica en el corto plazo (no garantía de resultado):\n{outlook}\n"
            )
            if sl_hint:
                msg += f"\n{sl_hint}\n"
            try:
                from signal_analysis import deep_analysis_enabled, format_deep_analysis

                if deep_analysis_enabled():
                    msg += format_deep_analysis(symbol, signal, bid, ask, atr_val, atr_period, sl_atr_mult, rr)
            except Exception:
                pass

            msg += f"\nUTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"

        if _telegram_send(msg):
            print("Señal enviada por Telegram.")
        else:
            print("No se pudo confirmar el envío (ver mensajes [TG] arriba).", file=sys.stderr)
            raise SystemExit(1)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
