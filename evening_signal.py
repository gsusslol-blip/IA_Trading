"""
Análisis diario (~21:00 hora local): mercado MT5 + veredicto claro de entrada + mismo formato VIP que el bot.

Uso recomendado (Windows): Programador de tareas → cada día 21:00:
  python evening_signal.py

Modo espera (opcional, corre en segundo plano):
  python evening_signal.py --daemon

Prueba inmediata (sin esperar las 21:00):
  python evening_signal.py --now

Variables .env:
  EVENING_LOCAL_HOUR=21
  EVENING_LOCAL_MINUTE=0
  EVENING_TZ=America/Argentina/Buenos_Aires
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from local_env import load_env_file


def _safe_evening_int(key: str, default: int) -> int:
    try:
        raw = os.environ.get(key, str(default))
        if raw is None or str(raw).strip() == "":
            return default
        return int(str(raw).strip())
    except ValueError:
        return default


def _seconds_until_evening() -> float:
    hour = _safe_evening_int("EVENING_LOCAL_HOUR", 21)
    minute = _safe_evening_int("EVENING_LOCAL_MINUTE", 0)
    tz_name = os.environ.get("EVENING_TZ", "America/Argentina/Buenos_Aires").strip()
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        tz = None
    if tz is not None:
        now = datetime.now(tz)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()
    now_l = datetime.now()
    target = now_l.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_l:
        target += timedelta(days=1)
    return (target - now_l).total_seconds()


def _local_time_label() -> str:
    tz_name = os.environ.get("EVENING_TZ", "America/Argentina/Buenos_Aires").strip()
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M")


def build_evening_message() -> str:
    from mt5_prices import _telegram_signal_message_text, fetch_strategy_snapshot

    snap = fetch_strategy_snapshot()
    hour_disp = os.environ.get("EVENING_LOCAL_HOUR", "21")
    header = f"📌 Análisis {hour_disp}:00 · {_local_time_label()} (hora local)\n"

    if snap.signal == "BUY":
        verdict = (
            "▶ ENTRADA SUGERIDA: COMPRA 🟢 — cruce alcista en M5 y filtro M15 favorable a largos."
        )
    elif snap.signal == "SELL":
        verdict = (
            "▶ ENTRADA SUGERIDA: VENTA 🔴 — cruce bajista en M5 y filtro M15 favorable a cortos."
        )
    else:
        verdict = (
            "▶ Sin entrada clara (HOLD ⚪) — no hay alineación M5+M15 para operar direccional ahora."
        )

    extra = ""
    try:
        from signal_analysis import analyze_market_pack

        pack = analyze_market_pack(
            snap.symbol,
            snap.signal,
            snap.bid,
            snap.ask,
            snap.atr_val,
            snap.atr_period,
            snap.sl_atr_mult,
            snap.rr,
        )
        rsi_txt = f"{pack.rsi_m5:.1f}" if pack.rsi_m5 is not None else "N/D"
        extra = f"\n📊 Confianza ~{pack.confidence}/100 · RSI M5 ≈ {rsi_txt}"
    except Exception:
        pass

    os.environ.setdefault("TELEGRAM_STYLE", "vip")
    body = _telegram_signal_message_text(
        snap.symbol,
        snap.signal,
        snap.bid,
        snap.ask,
        snap.fast_sma,
        snap.slow_sma,
        "M5",
        "M15",
        atr_val=snap.atr_val,
        atr_period=snap.atr_period,
        sl_atr_mult=snap.sl_atr_mult,
        rr=snap.rr,
        trend_detail=snap.trend_detail,
        m5_secs_left=snap.secs_left_m5,
    )
    return (
        header
        + verdict
        + extra
        + "\n\n"
        + body
        + f"\nUTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
    )


def send_evening() -> bool:
    from mt5_prices import _telegram_configured, _telegram_send

    if not _telegram_configured():
        print("Faltan TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.", file=sys.stderr)
        return False
    msg = build_evening_message()
    if _telegram_send(msg):
        print("Análisis 21:00 enviado por Telegram.")
        return True
    print("Falló envío Telegram.", file=sys.stderr)
    return False


def main() -> None:
    load_env_file()
    ap = argparse.ArgumentParser(description="Análisis diario ~21:00 → Telegram")
    ap.add_argument(
        "--daemon",
        action="store_true",
        help="Bucle: espera cada día a la hora EVENING_* y envía (segundo plano)",
    )
    ap.add_argument("--now", action="store_true", help="Enviar en cuanto inicia MT5 (prueba; ignora reloj)")
    args = ap.parse_args()

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        print(f"No se pudo inicializar MT5. ({code}) {msg}", file=sys.stderr)
        raise SystemExit(1)

    try:
        if args.daemon:
            print(
                f"[EVENING] Daemon · objetivo {_safe_evening_int('EVENING_LOCAL_HOUR', 21)}:"
                f"{_safe_evening_int('EVENING_LOCAL_MINUTE', 0):02d} "
                f"{os.environ.get('EVENING_TZ', 'America/Argentina/Buenos_Aires')}"
            )
            while True:
                try:
                    if not args.now:
                        wait = _seconds_until_evening()
                        print(f"[EVENING] Esperando {wait / 3600:.2f} h…")
                        time.sleep(wait)
                    send_evening()
                except Exception as e:
                    print(f"[EVENING] Error: {e}", file=sys.stderr)
                if args.now:
                    break
                time.sleep(120)
        else:
            send_evening()
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
