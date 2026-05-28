"""
Alerta Telegram cuando el watchdog reinicia ``ia_auto_trade_loop.py``.

Uso (desde ia_watchdog.bat):
  python watchdog_notify.py --event stopped
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _cooldown_seconds() -> int:
    try:
        return max(60, int(os.environ.get("IA_WATCHDOG_ALERT_COOLDOWN_S", "300").strip() or "300"))
    except ValueError:
        return 300


def _state_path() -> Path:
    from ia_paths import logs_dir

    return logs_dir() / "watchdog_notify_state.json"


def _should_send() -> bool:
    if os.environ.get("IA_WATCHDOG_TELEGRAM", "1").strip().lower() in ("0", "false", "no"):
        return False
    p = _state_path()
    now = datetime.now(timezone.utc).timestamp()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            last = float(data.get("last_sent_ts", 0))
            if now - last < _cooldown_seconds():
                return False
        except Exception:
            pass
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last_sent_ts": now}), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--event",
        choices=("stopped", "started"),
        default="stopped",
        help="stopped = el bucle Python terminó; started = arranque del watchdog",
    )
    args = parser.parse_args()

    try:
        from local_env import load_env_file

        load_env_file()
    except Exception:
        pass

    if args.event == "started":
        if os.environ.get("IA_WATCHDOG_ALERT_ON_START", "0").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            return 0

    if args.event == "stopped" and not _should_send():
        print("[watchdog] Alerta omitida (cooldown).", flush=True)
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if args.event == "stopped":
        msg = (
            f"🚨 <b>IA_Trading Watchdog</b>\n"
            f"El bot se detuvo de forma inesperada.\n"
            f"<code>{ts}</code>\n"
            f"Reinicio automático en ~10 s."
        )
    else:
        msg = f"🛡️ <b>IA_Trading Watchdog</b> activo\n<code>{ts}</code>"

    try:
        from telegram_utils import enviar_alerta_telegram

        ok = enviar_alerta_telegram(msg)
        if not ok:
            print("[watchdog] Telegram no configurado o falló el envío.", file=sys.stderr)
            return 1
        print("[watchdog] Alerta enviada.", flush=True)
        return 0
    except Exception as e:
        print(f"[watchdog] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
