"""
Escudo de fin de semana (viernes tarde UTC): cancela límites y cierra posiciones del bot.

Variables:
  IA_FRIDAY_CLOSE_ENABLE=1
  IA_FRIDAY_CLOSE_UTC_HOUR=19
  IA_FRIDAY_CLOSE_UTC_MINUTE=30
  IA_FRIDAY_RESUME_WEEKDAY=0      — 0=lunes
  IA_FRIDAY_RESUME_UTC_HOUR=2
  IA_FRIDAY_BLOCK_SAT_SUN=1
  IA_FRIDAY_LOOP_SLEEP_S=60
  IA_FRIDAY_TELEGRAM=1
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

def _bot_magic() -> int:
    try:
        return int(os.environ.get("BOT_MAGIC", "260505").strip() or "260505")
    except ValueError:
        return 260505


_DORMANT: bool = False
_EVACUATED_KEY: str | None = None


def friday_closure_enabled() -> bool:
    return os.environ.get("IA_FRIDAY_CLOSE_ENABLE", "1").strip().lower() in ("1", "true", "yes")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)).strip() or str(default))
    except ValueError:
        return default


def _state_path() -> Path:
    from ia_paths import resolve_data_path

    return resolve_data_path("IA_FRIDAY_STATE_FILE", "logs/ia_friday_closure_state.json")


def _load_state() -> dict:
    p = _state_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(**fields) -> None:
    data = _load_state()
    data.update(fields)
    data["updated_utc"] = _utc_now().isoformat()
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def en_ventana_cierre_viernes_utc(now: datetime | None = None) -> bool:
    """Viernes desde HH:MM UTC (default 19:30)."""
    now = now or _utc_now()
    if int(now.weekday()) != 4:
        return False
    h = _env_int("IA_FRIDAY_CLOSE_UTC_HOUR", 19)
    m = _env_int("IA_FRIDAY_CLOSE_UTC_MINUTE", 30)
    cur = now.hour * 60 + now.minute
    start = h * 60 + m
    return cur >= start


def en_pausa_fin_de_semana(now: datetime | None = None) -> bool:
    """True si el bot debe permanecer sin nuevas entradas (post-evacuación o sáb/dom)."""
    if not friday_closure_enabled():
        return False
    now = now or _utc_now()
    if _DORMANT:
        return not _hora_reanudacion(now)
    if os.environ.get("IA_FRIDAY_BLOCK_SAT_SUN", "1").strip().lower() in ("1", "true", "yes"):
        if int(now.weekday()) in (5, 6):
            return True
    return en_ventana_cierre_viernes_utc(now)


def _hora_reanudacion(now: datetime) -> bool:
    wd = _env_int("IA_FRIDAY_RESUME_WEEKDAY", 0)
    h = _env_int("IA_FRIDAY_RESUME_UTC_HOUR", 2)
    return int(now.weekday()) == wd and int(now.hour) >= h


def _cancelar_pendientes_magic(magic: int) -> int:
    from cierre_viernes import cancelar_ordenes_pendientes_bot

    return cancelar_ordenes_pendientes_bot()


def _cerrar_posiciones_magic(magic: int) -> tuple[int, int]:
    from cierre_viernes import cerrar_posiciones_precierre_weekend

    return cerrar_posiciones_precierre_weekend()


def _telegram_friday(msg: str) -> None:
    if os.environ.get("IA_FRIDAY_TELEGRAM", "1").strip().lower() not in ("1", "true", "yes"):
        return
    try:
        from mt5_prices import _telegram_configured, _telegram_send

        if _telegram_configured():
            _telegram_send(msg)
    except Exception as e:
        print(f"[TG] friday: {e}", file=sys.stderr)


def _ejecutar_evacuacion(magic: int) -> None:
    global _DORMANT, _EVACUATED_KEY
    print("[friday] Evacuacion fin de semana: cancelando limites y cerrando posiciones...", flush=True)
    nop = _cancelar_pendientes_magic(magic)
    ok, fail = _cerrar_posiciones_magic(magic)
    key = _utc_now().strftime("%Y-%m-%d")
    _EVACUATED_KEY = key
    _save_state(last_evacuation_utc=_utc_now().isoformat(), last_evacuation_key=key)
    _DORMANT = True
    msg = (
        "IA_AUTO · Cierre viernes (swap/gap)\n"
        f"Pendientes canceladas: {nop}\n"
        f"Posiciones cerradas OK={ok} fail={fail}"
    )
    print(f"[friday] {msg.replace(chr(10), ' | ')}", flush=True)
    _telegram_friday(msg)


def ejecutar_cierre_viernes_autonomo(magic_number: int | None = None) -> bool:
    """
    Si corresponde, liquida el bot y devuelve True (el bucle debe ``continue`` sin escanear).

    Llamar al inicio de cada vuelta del ``while True`` con MT5 ya conectado.
    """
    global _DORMANT

    if not friday_closure_enabled():
        return False

    mag = int(magic_number if magic_number is not None else _bot_magic())
    now = _utc_now()

    if _DORMANT:
        if _hora_reanudacion(now):
            print("[friday] Reanudacion operativa (lunes/hora UTC configurada).", flush=True)
            _DORMANT = False
            return False
        import MetaTrader5 as mt5

        pos_list = mt5.positions_get() or []
        if pos_list:
            tickets = [
                int(getattr(p, "ticket", 0) or 0)
                for p in pos_list
                if int(getattr(p, "magic", -1) or -1) == mag
            ]
            if tickets:
                _cerrar_posiciones_magic(mag)
        _cancelar_pendientes_magic(mag)
        return True

    if en_pausa_fin_de_semana(now) and not en_ventana_cierre_viernes_utc(now):
        return True

    if not en_ventana_cierre_viernes_utc(now):
        return False

    key = now.strftime("%Y-%m-%d")
    st = _load_state()
    if st.get("last_evacuation_key") == key:
        _DORMANT = True
        return True

    _ejecutar_evacuacion(mag)
    return True


def main() -> int:
    from local_env import load_env_file
    from ia_mt5_connection import asegurar_conexion_mt5

    load_env_file()
    if not asegurar_conexion_mt5():
        print("MT5 no disponible", file=sys.stderr)
        return 1
    os.environ["IA_FRIDAY_CLOSE_ENABLE"] = "1"
    active = ejecutar_cierre_viernes_autonomo(_bot_magic())
    print("pausa_fin_de_semana:", active)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
