"""
Watchdog del bot IA_AUTO (Windows Task Scheduler friendly).

Objetivo:
  - Chequear si ia_auto_trade_loop.py está corriendo.
  - Si NO está corriendo, intentar arrancarlo y notificar por Telegram.
  - Chequear conectividad MT5 (initialize) y notificar si falla.

Config (opcional .env):
  IA_WATCHDOG_ENABLE=0                 (default 0; poné 1 para reactivar)
  IA_WATCHDOG_LOG=watchdog.log         (default watchdog.log)
  IA_WATCHDOG_BOT_LOG=ia_auto_trade_loop_runtime.log  (stdout/err del bot)
  IA_WATCHDOG_PYTHON=...               (ruta explícita a python.exe; si vacío usa sys.executable)
  IA_WATCHDOG_NOTIFY=1                 (default 1) enviar Telegram en eventos
  IA_WATCHDOG_CHECK_MT5=1              (default 1)
  IA_WATCHDOG_MIN_UPTIME_S=20          (default 20) si muere antes, reintentar en siguiente tick

Uso manual:
  python watchdog_bot.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_env() -> None:
    try:
        from local_env import load_env_file

        load_env_file()
    except Exception:
        pass


def _env_on(key: str, default: str = "1") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")


def _root() -> Path:
    return Path(__file__).resolve().parent


def _log_path() -> Path:
    name = os.environ.get("IA_WATCHDOG_LOG", "").strip() or "watchdog.log"
    p = Path(name)
    return p if p.is_absolute() else (_root() / p)


def _bot_log_path() -> Path:
    name = os.environ.get("IA_WATCHDOG_BOT_LOG", "").strip() or "ia_auto_trade_loop_runtime.log"
    p = Path(name)
    return p if p.is_absolute() else (_root() / p)


def _append_log(line: str) -> None:
    try:
        p = _log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        return


def _notify(msg: str) -> None:
    if not _env_on("IA_WATCHDOG_NOTIFY", "1"):
        return
    try:
        from telegram_utils import enviar_alerta_telegram

        enviar_alerta_telegram(msg)
    except Exception:
        return


def _python_cmd() -> str:
    p = os.environ.get("IA_WATCHDOG_PYTHON", "").strip()
    if p:
        return p
    return sys.executable


def _is_bot_running() -> tuple[bool, int | None]:
    """
    Returns (running, pid).
    Best-effort: uses tasklist and command line via CIM.
    """
    try:
        import win32com.client  # type: ignore

        # If pywin32 exists, great; but we don't depend on it.
        del win32com.client
    except Exception:
        pass
    try:
        # Works without extra deps.
        import wmi  # type: ignore

        c = wmi.WMI()
        for p in c.Win32_Process(name="python.exe"):
            cmd = str(getattr(p, "CommandLine", "") or "")
            if "ia_auto_trade_loop.py" in cmd:
                return True, int(getattr(p, "ProcessId", 0) or 0) or None
        return False, None
    except Exception:
        # Fallback: use CIM via powershell
        try:
            ps = [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'ia_auto_trade_loop\\.py' } | "
                "Select-Object -First 1 -ExpandProperty ProcessId",
            ]
            out = subprocess.check_output(ps, stderr=subprocess.DEVNULL, text=True).strip()
            if out:
                return True, int(out)
        except Exception:
            pass
        return False, None


def _check_mt5() -> bool:
    if not _env_on("IA_WATCHDOG_CHECK_MT5", "1"):
        return True
    try:
        import MetaTrader5 as mt5

        mt5_path = os.environ.get("MT5_PATH")
        ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
        last = mt5.last_error()
        mt5.shutdown()
        if not ok:
            _append_log(f"{_now()} [MT5] init fail {last}")
            _notify(f"⚠️ <b>IA_WATCHDOG</b>: MT5 init fail <code>{last}</code>")
            return False
        return True
    except Exception as e:
        _append_log(f"{_now()} [MT5] exception {e}")
        return False


def _start_bot() -> bool:
    py = _python_cmd()
    bot = _root() / "ia_auto_trade_loop.py"
    if not bot.is_file():
        _append_log(f"{_now()} [BOT] missing file {bot}")
        return False

    outp = _bot_log_path()
    outp.parent.mkdir(parents=True, exist_ok=True)
    f = outp.open("a", encoding="utf-8", newline="")
    try:
        # Detached/background
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        subprocess.Popen(
            [py, "-u", str(bot)],
            cwd=str(_root()),
            stdout=f,
            stderr=f,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
        _append_log(f"{_now()} [BOT] started via {py}")
        _notify("🟢 <b>IA_WATCHDOG</b>: bot reiniciado (ia_auto_trade_loop.py).")
        return True
    except Exception as e:
        _append_log(f"{_now()} [BOT] start fail {e}")
        _notify(f"🔴 <b>IA_WATCHDOG</b>: no pude reiniciar bot. <code>{e}</code>")
        return False
    finally:
        try:
            f.flush()
        except Exception:
            pass
        try:
            f.close()
        except Exception:
            pass


def main() -> int:
    _load_env()
    if not _env_on("IA_WATCHDOG_ENABLE", "0"):
        return 0

    running, pid = _is_bot_running()
    _append_log(f"{_now()} [CHECK] running={running} pid={pid or ''}")

    _check_mt5()

    if running:
        return 0

    # Bot no está vivo: intentar levantar.
    started = _start_bot()
    return 0 if started else 2


if __name__ == "__main__":
    raise SystemExit(main())

