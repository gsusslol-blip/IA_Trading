"""
Envío de reporte diario de operaciones cerradas (magic del bot) por Telegram a una hora local.

No usa mt5.message_send (no existe en la API Python estándar): usa TELEGRAM_* del .env.
El PnL agrupa por position_id como bot_pnl_report (profit+commission+swap).

  python daily_report_loop.py

Variables .env:
  DAILY_REPORT_ENABLE=1      — obligatorio para ejecutar el bucle
  REPORT_HOUR=17            — hora local (0–23) en REPORT_TZ
  REPORT_TZ=America/Argentina/Buenos_Aires
  REPORT_LOOP_SLEEP_S=30    — frecuencia del reloj (para no saltarse la hora objetivo)

Para trading automático en paralelo usá ia_auto_trade_loop.py u otro script; este archivo
solo gestiona el reporte programado.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

from local_env import load_env_file


def _fail(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _local_day_utc_bounds() -> tuple[datetime, datetime]:
    """Inicio del día local y ahora, ambos en UTC."""
    tz_name = os.environ.get("REPORT_TZ", "America/Argentina/Buenos_Aires").strip()
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
        now_local = datetime.now(tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_local.astimezone(timezone.utc), now_local.astimezone(timezone.utc)
    except Exception:
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now


def obtener_reporte_diario_texto() -> str:
    from mt5_prices import BOT_MAGIC, closed_positions_pnls_by_magic, closed_trade_winrate_stats

    utc_from, utc_to = _local_day_utc_bounds()
    try:
        lb = int(os.environ.get("REPORT_HISTORY_EXTRA_DAYS", "14"))
    except ValueError:
        lb = 14
    pnls = closed_positions_pnls_by_magic(
        BOT_MAGIC, utc_from, utc_to, history_lookback_days=max(0, lb)
    )
    if not pnls:
        return "Reporte diario: hoy no hay operaciones cerradas con el magic del bot."

    net = sum(pnls)
    wr, wins, losses, flat = closed_trade_winrate_stats(pnls)
    sign = "+" if net >= 0 else ""
    tz_label = os.environ.get("REPORT_TZ", "local")
    return (
        f"Reporte diario ({tz_label})\n"
        f"PnL neto: {sign}{net:.2f}\n"
        f"Operaciones cerradas: {len(pnls)} (ganadoras {wins}, perdedoras {losses}, BE {flat})\n"
        f"Aciertos: {wr * 100:.1f}%"
    )


def enviar_alerta_movil(mensaje: str) -> None:
    try:
        from mt5_prices import _telegram_configured, _telegram_send

        if _telegram_configured():
            _telegram_send(mensaje)
    except Exception as e:
        print(f"Telegram: {e}", file=sys.stderr)
    print(mensaje)


def main() -> None:
    load_env_file()
    if os.environ.get("DAILY_REPORT_ENABLE", "").strip().lower() not in ("1", "true", "yes"):
        _fail("Definí DAILY_REPORT_ENABLE=1 en .env para ejecutar el reporte programado.")

    try:
        report_hour = int(os.environ.get("REPORT_HOUR", "17"))
    except ValueError:
        report_hour = 17
    report_hour = max(0, min(23, report_hour))
    sleep_s = float(os.environ.get("REPORT_LOOP_SLEEP_S", "30"))

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        _fail(f"No se pudo inicializar MT5. ({code}) {msg}")

    try:
        print(
            f"Reporte diario activo · hora local {report_hour}:xx · "
            f"TZ={os.environ.get('REPORT_TZ', '?')} · Ctrl+C salir"
        )
        last_sent_date: str | None = None

        while True:
            tz_name = os.environ.get("REPORT_TZ", "America/Argentina/Buenos_Aires").strip()
            try:
                from zoneinfo import ZoneInfo

                now_local = datetime.now(ZoneInfo(tz_name))
            except Exception:
                now_local = datetime.now()

            today_str = now_local.strftime("%Y-%m-%d")
            if now_local.hour == report_hour and last_sent_date != today_str:
                body = obtener_reporte_diario_texto()
                enviar_alerta_movil(body)
                last_sent_date = today_str

            time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("Reporte diario detenido.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
