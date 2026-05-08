"""
Precierre antes del fin de semana (gap risk en XAUUSD y similares).

  IA_WEEKEND_CLOSE_ENABLE=1          — activar (default 0, seguro).
  IA_WEEKEND_TZ                       — zona IANA opcional (ej. Europe/Athens); vacío = reloj local del PC.
  IA_WEEKEND_CLOSE_WEEKDAY=4          — día 0=Lun … 4=Vier (default viernes).
  IA_WEEKEND_CLOSE_HOUR>=20          — hora exacta desde la que aplicar precierre (hora en IA_WEEKEND_TZ o local).
  IA_WEEKEND_RESUME_WEEKDAY=0        — día de reanudación (default Lunes).
  IA_WEEKEND_RESUME_HOUR=2           — desde esta hora se vuelve a operar ese día.

  Solo cierra posiciones con BOT_MAGIC salvo IA_WEEKEND_CLOSE_ALL_MAGIC=1 (cuenta entera).

  IA_WEEKEND_BLOCK_SAT_SUN=1 — sáb/dom no opera (útil si reiniciás el bot en fin de semana; no cierra solo).

  Órdenes pendientes LIMIT/STOP del mismo magic se cancelan (TRADE_ACTION_REMOVE).

  Telegram: mismo esquema que mt5_prices (_telegram_send) una vez por ventana dormida.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

import MetaTrader5 as mt5

from local_env import load_env_file
from mt5_prices import BOT_MAGIC, _close_position_ticket

_dormente: bool = False
_tele_precierre_emitido: bool = False


def _now_weekend_clock() -> datetime:
    tz = os.environ.get("IA_WEEKEND_TZ", "").strip()
    if tz:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(tz))
        except Exception:
            pass
    return datetime.now()


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)).strip() or str(default))
    except ValueError:
        return default


def _dentro_precierre_fin_sem(now: datetime) -> bool:
    wd_close = _env_int("IA_WEEKEND_CLOSE_WEEKDAY", 4)
    h_close = _env_int("IA_WEEKEND_CLOSE_HOUR", 20)
    return int(now.weekday()) == wd_close and int(now.hour) >= h_close


def _hora_reanudar(now: datetime) -> bool:
    wd_resume = _env_int("IA_WEEKEND_RESUME_WEEKDAY", 0)
    h_resume = _env_int("IA_WEEKEND_RESUME_HOUR", 2)
    return int(now.weekday()) == wd_resume and int(now.hour) >= h_resume


def _cerrar_precierre_habilitado() -> bool:
    return os.environ.get("IA_WEEKEND_CLOSE_ENABLE", "0").strip().lower() in ("1", "true", "yes")


def _incluye_magic_posicion(magic: int) -> bool:
    if os.environ.get("IA_WEEKEND_CLOSE_ALL_MAGIC", "0").strip().lower() in ("1", "true", "yes"):
        return True
    return magic == BOT_MAGIC


def _tickets_precierre() -> list[int]:
    pos = mt5.positions_get()
    if not pos:
        return []
    out: list[int] = []
    for p in pos:
        try:
            mg = int(getattr(p, "magic", -999) or -999)
        except (TypeError, ValueError):
            continue
        if not _incluye_magic_posicion(mg):
            continue
        t = int(getattr(p, "ticket", 0) or 0)
        if t > 0:
            out.append(t)
    return out


def cerrar_posiciones_precierre_weekend(deviation: int | None = None) -> tuple[int, int]:
    """
    Cierra todas las posiciones objetivo por ticket de mercado. (ok_count, fail_count).
    """
    dev = deviation
    if dev is None:
        dev = _env_int("DEVIATION", 20)
    ok = fa = 0
    seen = 0
    while seen < 48:
        tix = _tickets_precierre()
        if not tix:
            break
        tk = tix[0]
        seen += 1
        if _close_position_ticket(tk, dev):
            ok += 1
        else:
            fa += 1
        time.sleep(0.2)
    return ok, fa


def cancelar_ordenes_pendientes_bot() -> int:
    """Elimina órdenes pendientes del magic del bot (o todas si IA_WEEKEND_CANCEL_ALL_MAGICS)."""
    ordlist = mt5.orders_get()
    if not ordlist:
        return 0
    cancel_all = os.environ.get("IA_WEEKEND_CANCEL_ALL_MAGICS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    n = 0
    for o in ordlist:
        try:
            mg = int(getattr(o, "magic", -999) or -999)
            oid = int(getattr(o, "ticket", 0) or 0)
        except (TypeError, ValueError):
            continue
        if oid <= 0:
            continue
        if not cancel_all and mg != BOT_MAGIC:
            continue
        req = {"action": mt5.TRADE_ACTION_REMOVE, "order": oid}
        try:
            r = mt5.order_send(req)
        except Exception as e:
            print(f"[WEEKEND] cancel pending order fail {oid}: {e}", file=sys.stderr)
            continue
        rc = int(getattr(r, "retcode", -1)) if r is not None else -1
        done_rc = int(getattr(mt5, "TRADE_RETCODE_DONE", 10009))
        if r is not None and rc == done_rc:
            n += 1
            print(f"[WEEKEND] orden pendiente eliminada {oid}")
        elif r is not None and rc not in (done_rc, 10004):  # 10004 algunos rechazos inofensivos
            print(f"[WEEKEND] remove order {oid} retcode={rc} {getattr(r, 'comment', '')}", file=sys.stderr)
        time.sleep(0.08)
    return n


def _telegram_precierre_weekend(extra: str) -> None:
    try:
        from mt5_prices import _telegram_configured, _telegram_send

        if not _telegram_configured():
            return
        msg = (
            "IA_AUTO · Precierre fin de semana\n"
            "Bot en pausa (sin nuevas entradas) hasta ventana configurada.\n"
            + extra
        )
        if not _telegram_send(msg):
            print("[TG] No se envió aviso precierre weekend.", file=sys.stderr)
    except Exception as e:
        print(f"[TG] Precierre weekend: {e}", file=sys.stderr)


def gestionar_precierre_fin_de_semana() -> bool:
    """
    Llamada al inicio de cada vuelta del bucle IA_AUTO.

    Devuelve True si el bot NO debe enviar órdenes ni escaneos agresivos (dormición fin de semana).
    Cierra mercado BOT al entrar en la ventana de viernes tardío (primera vez o reintento hasta flat).
    """
    global _dormente, _tele_precierre_emitido

    if not _cerrar_precierre_habilitado():
        return False

    now = _now_weekend_clock()

    if os.environ.get("IA_WEEKEND_BLOCK_SAT_SUN", "0").strip().lower() in ("1", "true", "yes"):
        if int(now.weekday()) in (5, 6):
            return True

    if _dormente:
        if _hora_reanudar(now):
            print("[WEEKEND] Reanudación (día/hora configurados). Operativa normal.")
            _dormente = False
            _tele_precierre_emitido = False
            return False
        if os.environ.get("IA_WEEKEND_RETRY_CLOSE", "1").strip().lower() in ("1", "true", "yes"):
            if _tickets_precierre():
                print("[WEEKEND] Quedaban posiciones: reintentando cierre...")
                cerrar_posiciones_precierre_weekend()
            cancelar_ordenes_pendientes_bot()
        return True

    if not _dentro_precierre_fin_sem(now):
        return False

    print("[WEEKEND] Ventana precierre fin de semana: cerrando posiciones y ordenes pendientes del bot...")
    ok, fa = cerrar_posiciones_precierre_weekend()
    nop = cancelar_ordenes_pendientes_bot()

    resume_wd = _env_int("IA_WEEKEND_RESUME_WEEKDAY", 0)
    resume_h = _env_int("IA_WEEKEND_RESUME_HOUR", 2)
    extra = (
        f"Posiciones cerradas OK={ok} fail={fa} | pendientes eliminadas≈{nop}\n"
        f"Siguiente operativa típica: weekday={resume_wd} desde h>={resume_h} ({os.environ.get('IA_WEEKEND_TZ', 'local')} si definido)."
    )
    print(f"[WEEKEND] Precierre ejecutado ({extra.replace(chr(10), ' ')})")

    if not _tele_precierre_emitido:
        _telegram_precierre_weekend(extra)
        _tele_precierre_emitido = True

    _dormente = True
    return True


def main() -> None:
    load_env_file()
    mt5_path = os.environ.get("MT5_PATH")
    ok_init = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok_init:
        print(f"MT5 init fail: {mt5.last_error()}", file=sys.stderr)
        raise SystemExit(1)
    try:
        os.environ.setdefault("IA_WEEKEND_CLOSE_ENABLE", "1")
        b = gestionar_precierre_fin_de_semana()
        print("dormición activa:", b)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
