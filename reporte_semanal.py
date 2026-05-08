"""
Reporte semanal de desempeño del BOT (MT5) para revisar en Telegram.

  IA_REPORTE_SEMANAL_ENABLE=1     — en ia_auto_trade_loop: envío automático sábados a la hora configurada.
  IA_REPORTE_SEMANAL_DOW=5        — weekday 0=Lun … 5=Sáb (default 5).
  IA_REPORTE_SEMANAL_HOUR=10      — inicio ventana horaria local (default 10 inclusive).
  IA_REPORTE_SEMANAL_HOUR_END=11  — fin exclusivo (default HOUR+1; si el bucle duerme >1h, mantené el rango ancho).
  IA_REPORTE_SEMANAL_STATE       — JSON con última ISO-semana enviada (default ia_reporte_semanal_state.json).

Usa el mismo agregado por position_id que ia_auto_memory (magic BOT_MAGIC, PnL neto por cierre).

  python reporte_semanal.py   — genera y envía ahora (Telegram si hay credenciales).

Usa el código con precaución.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

from ia_auto_memory import closed_positions_detail_by_magic
from local_env import load_env_file
from mt5_prices import BOT_MAGIC


def _state_path() -> Path:
    raw = os.environ.get("IA_REPORTE_SEMANAL_STATE", "").strip()
    root = Path(__file__).resolve().parent
    if not raw:
        return root / "ia_reporte_semanal_state.json"
    p = Path(raw)
    return p if p.is_absolute() else (root / p)


def _iso_week_key(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def rango_semana_local_hasta_ahora() -> tuple[datetime, datetime]:
    """
    Lunes 00:00 local (reloj del proceso) → ahora, ambos con tzinfo para pasar a UTC.
    """
    now_loc = datetime.now().astimezone()
    monday = (now_loc - timedelta(days=int(now_loc.weekday()))).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday, now_loc


def _metricas_desde_cierres(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(r["pnl_net"]) for r in rows]
    wins = [x for x in pnls if x > 0]
    losses = [-x for x in pnls if x < 0]
    n = len(pnls)
    net = sum(pnls)
    wr = (len(wins) / n * 100.0) if n else 0.0
    pf = (sum(wins) / sum(losses)) if losses else (999.0 if wins else 0.0)
    return {
        "n": n,
        "net": net,
        "wins": len(wins),
        "losses": len(losses),
        "wr": wr,
        "pf": pf,
    }


def generar_reporte_semanal(*, magic: int | None = None) -> str:
    """
    Texto HTML simple (compatible con TELEGRAM_PARSE_MODE=HTML por defecto).
    Requiere MT5 inicializado.
    """
    mag = int(magic if magic is not None else BOT_MAGIC)
    utc_from, utc_to = rango_semana_local_hasta_ahora()
    utc_from_utc = utc_from.astimezone(timezone.utc)
    utc_to_utc = utc_to.astimezone(timezone.utc)

    rows = closed_positions_detail_by_magic(
        mag,
        utc_from_utc,
        utc_to_utc,
        history_lookback_days=14,
    )
    if not rows:
        mon_s = utc_from.strftime("%d/%m")
        to_s = utc_to.strftime("%d/%m %H:%M")
        return (
            f"📉 <b>Reporte semanal IA_AUTO</b>\n"
            f"Magic <code>{mag}</code>\n"
            f"Sin cierres del bot en <code>{mon_s}</code> → <code>{to_s}</code> (hora local)."
        )

    m = _metricas_desde_cierres(rows)
    estado = "🚀 SEMANA VERDE" if m["net"] > 0 else "🔴 SEMANA ROJA"
    mon_s = utc_from.strftime("%d/%m")
    to_s = utc_to.strftime("%d/%m %H:%M")

    ai = mt5.account_info()
    bal = float(getattr(ai, "balance", 0.0) or 0.0) if ai else 0.0
    eq = float(getattr(ai, "equity", 0.0) or 0.0) if ai else 0.0
    cur = str(getattr(ai, "currency", "") or "USD") if ai else "USD"
    pf_s = f"{m['pf']:.2f}" if m["pf"] < 500 else "∞"

    sym_line = os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").strip() or "XAUUSD"

    return (
        f"📊 <b>REPORTE SEMANAL</b> <i>{sym_line}</i>\n"
        f"<b>{estado}</b>\n\n"
        f"💰 <b>PnL neto (BOT):</b> <code>{m['net']:+.2f}</code> {cur}\n"
        f"📈 <b>Win rate:</b> <code>{m['wr']:.1f}%</code>\n"
        f"📐 <b>Profit factor:</b> <code>{pf_s}</code>\n"
        f"🔄 <b>Cierres:</b> <code>{m['n']}</code> "
        f"(✅ {m['wins']} | ❌ {m['losses']})\n\n"
        f"🏦 <b>Balance</b> <code>{bal:.2f}</code> {cur}\n"
        f"⚖️ <b>Equity</b> <code>{eq:.2f}</code> {cur}\n\n"
        f"📅 <b>Periodo (local)</b>: {mon_s} → {to_s}\n"
        f"<code>MAGIC={mag}</code>"
    )


def _ultimo_envio_iso_week() -> str | None:
    p = _state_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return str(data.get("last_iso_week", "") or "").strip() or None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _guardar_iso_week(key: str) -> None:
    p = _state_path()
    p.write_text(
        json.dumps({"last_iso_week": key, "saved_utc": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8",
    )


def enviar_reporte_semanal_telegram(texto: str) -> bool:
    try:
        from telegram_utils import enviar_alerta_telegram
    except ImportError:
        print("[reporte-semanal] telegram_utils no disponible.", file=sys.stderr)
        return False
    return enviar_alerta_telegram(texto)


def intentar_enviar_reporte_semanal_si_toca() -> bool:
    """
    Si coincide día/hora (local) y no se envió esta ISO-week, envía Telegram y guarda estado.
    Devuelve True si esta llamada ejecutó envío OK.
    """
    if os.environ.get("IA_REPORTE_SEMANAL_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return False

    try:
        dow = int(os.environ.get("IA_REPORTE_SEMANAL_DOW", "5").strip() or "5")
    except ValueError:
        dow = 5
    try:
        hour_t0 = int(os.environ.get("IA_REPORTE_SEMANAL_HOUR", "10").strip() or "10")
    except ValueError:
        hour_t0 = 10
    try:
        hour_t1_raw = os.environ.get("IA_REPORTE_SEMANAL_HOUR_END", "").strip()
        hour_t1 = int(hour_t1_raw) if hour_t1_raw else hour_t0 + 1
    except ValueError:
        hour_t1 = hour_t0 + 1
    if hour_t1 <= hour_t0:
        hour_t1 = hour_t0 + 1

    now_loc = datetime.now().astimezone()
    h = int(now_loc.hour)
    if int(now_loc.weekday()) != dow or not (hour_t0 <= h < max(hour_t0 + 1, hour_t1)):
        return False

    wk = _iso_week_key(now_loc)
    if _ultimo_envio_iso_week() == wk:
        return False

    body = generar_reporte_semanal()
    if not enviar_reporte_semanal_telegram(body):
        print("[reporte-semanal] Falló envío Telegram (no guardo marca de semana).", file=sys.stderr)
        return False
    _guardar_iso_week(wk)
    print(f"[reporte-semanal] Enviado para ISO week {wk}.")
    return True


def main() -> int:
    load_env_file()
    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        print(f"❌ MT5 init: {mt5.last_error()}", file=sys.stderr)
        return 1
    try:
        msg = generar_reporte_semanal()
        print(msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", ""))
        if enviar_reporte_semanal_telegram(msg):
            print("Telegram OK.")
        else:
            print("Telegram no enviado (sin credenciales o error).")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
