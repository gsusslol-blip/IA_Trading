"""
Bitácora Fase 1 (CSV): columnas alineadas a plantilla Excel — día, fecha, saldo inicial,
ganancia/pérdida, saldo final, ¿operó?, notas.

Se integra con ia_auto_trade_loop: un tick por vuelta de bucle actualiza snapshot de saldo;
al cambiar el día (TZ configurable) se escribe la fila del día cerrado. Opcional: alertas
Telegram al cruzar piso/techo de fase (reglas de graduación / retroceso).

Variables de entorno:
  IA_JOURNAL_ENABLE=1
  IA_JOURNAL_CSV=ia_phase1_journal.csv
  IA_JOURNAL_STATE=ia_trading_journal_state.json
  IA_JOURNAL_TZ=   — si vacío, usa IA_AUTO_DAILY_PNL_TZ o America/Argentina/Buenos_Aires
  IA_JOURNAL_USE_EQUITY=0 — 1 = usar equity en lugar de balance para saldos
  IA_JOURNAL_GRAD_USD=1250 — aviso "meta de fase" (saldo final del día)
  IA_JOURNAL_FLOOR_USD=900 — aviso "revisar parámetros" si saldo final < este valor
  IA_JOURNAL_ALERTS=1 — Telegram + print en cruces (default 1 si TELEGRAM_* y journal activo)
"""

from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_JOURNAL_NOTES: list[str] = []


def journal_enabled() -> bool:
    return os.environ.get("IA_JOURNAL_ENABLE", "0").strip().lower() in ("1", "true", "yes")


def journal_add_note(text: str) -> None:
    t = (text or "").strip()
    if not t or not journal_enabled():
        return
    _JOURNAL_NOTES.append(t)


def _journal_tz_name() -> str:
    z = os.environ.get("IA_JOURNAL_TZ", "").strip()
    if z:
        return z
    return os.environ.get("IA_AUTO_DAILY_PNL_TZ", "America/Argentina/Buenos_Aires").strip() or "America/Argentina/Buenos_Aires"


def _journal_local_today() -> date:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(_journal_tz_name())
        return datetime.now(tz).date()
    except Exception:
        return date.today()


def _root() -> Path:
    return Path(__file__).resolve().parent


def _csv_path() -> Path:
    raw = os.environ.get("IA_JOURNAL_CSV", "").strip() or "ia_phase1_journal.csv"
    p = Path(raw)
    return p if p.is_absolute() else (_root() / p)


def _state_path() -> Path:
    raw = os.environ.get("IA_JOURNAL_STATE", "").strip() or "ia_trading_journal_state.json"
    p = Path(raw)
    return p if p.is_absolute() else (_root() / p)


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)).replace(",", ".").strip() or str(default))
    except ValueError:
        return default


def _account_saldo() -> float | None:
    try:
        import MetaTrader5 as mt5

        ai = mt5.account_info()
        if ai is None:
            return None
        if os.environ.get("IA_JOURNAL_USE_EQUITY", "0").strip().lower() in ("1", "true", "yes"):
            return float(getattr(ai, "equity", 0.0) or 0.0)
        return float(getattr(ai, "balance", 0.0) or 0.0)
    except Exception:
        return None


def _load_state() -> dict[str, Any]:
    p = _state_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(data: dict[str, Any]) -> None:
    p = _state_path()
    try:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass


def _alerts_enabled() -> bool:
    raw = os.environ.get("IA_JOURNAL_ALERTS", "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    try:
        from telegram_utils import _telegram_configured

        return _telegram_configured()
    except Exception:
        return False


def _maybe_alert_phase(saldo_final: float, *, context: str) -> None:
    if not _alerts_enabled():
        return
    grad = _float_env("IA_JOURNAL_GRAD_USD", 1250.0)
    floor = _float_env("IA_JOURNAL_FLOOR_USD", 900.0)
    st = _load_state()
    tags: dict[str, str] = dict(st.get("alert_tags") or {})

    def _send(html: str, plain: str) -> None:
        print(plain)
        try:
            from telegram_utils import enviar_alerta_telegram

            enviar_alerta_telegram(html)
        except Exception:
            pass

    gkey = f"grad:{context}"
    if saldo_final >= grad and tags.get("graduated") != "1":
        tags["graduated"] = "1"
        _send(
            f"<b>Bitácora Fase 1</b>\nSaldo final del cierre ({context}) ≈ <code>{saldo_final:.2f}</code> "
            f"(meta de graduación ≥ {grad:.0f}). Revisá si subís fase / lotaje con disciplina.",
            f"[bitácora] Meta de graduación: saldo ≈ {saldo_final:.2f} (≥ {grad:.0f}). Contexto: {context}.",
        )
    elif saldo_final < floor:
        if tags.get(gkey) != "1":
            tags[gkey] = "1"
            _send(
                f"<b>Bitácora — regla de retroceso</b>\nSaldo final del cierre ({context}) ≈ "
                f"<code>{saldo_final:.2f}</code> (&lt; piso {floor:.0f}). "
                "Conviene detener, revisar IA_MIN_CONFIDENCE / SLOPE_FILTER y parámetros.",
                f"[bitácora] Piso {floor:.0f}: saldo ≈ {saldo_final:.2f}. Contexto: {context}. Revisar parámetros.",
            )
    st["alert_tags"] = tags
    _save_state(st)


def _append_csv_row(
    *,
    dia: int,
    fecha: date,
    saldo_inicial: float,
    ganancia_perdida: float,
    saldo_final: float,
    opero: str,
    notas: str,
) -> None:
    path = _csv_path()
    new_file = not path.is_file()
    row = {
        "dia": str(dia),
        "fecha": fecha.isoformat(),
        "saldo_inicial": f"{saldo_inicial:.2f}",
        "ganancia_perdida": f"{ganancia_perdida:.2f}",
        "saldo_final": f"{saldo_final:.2f}",
        "opero": opero,
        "notas": notas,
    }
    fieldnames = ["dia", "fecha", "saldo_inicial", "ganancia_perdida", "saldo_final", "opero", "notas"]
    try:
        with path.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            if new_file:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        print(f"[bitácora] no se pudo escribir CSV: {e}", flush=True)


@dataclass
class _OpenDay:
    day_index: int
    calendar: date
    saldo_inicial: float
    operated: bool
    last_snapshot: float


def _parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def _finalize_gap_days(
    start_d: date,
    end_exclusive: date,
    last_balance: float,
    start_day_index: int,
) -> int:
    """Escribe filas sintéticas para días sin tick de bot (saldo plano). Devuelve siguiente índice día."""
    d = start_d
    idx = start_day_index
    while d < end_exclusive:
        _append_csv_row(
            dia=idx,
            fecha=d,
            saldo_inicial=last_balance,
            ganancia_perdida=0.0,
            saldo_final=last_balance,
            opero="NO",
            notas="Sin datos del bot (días sin ejecución de ia_auto_trade_loop); saldo estimado plano.",
        )
        _maybe_alert_phase(last_balance, context=d.isoformat())
        idx += 1
        d += timedelta(days=1)
    return idx


def journal_mark_opened_today() -> None:
    """Llamar cuando el bot abrió una orden OK en la sesión actual."""
    if not journal_enabled():
        return
    st = _load_state()
    od = st.get("open_day")
    if isinstance(od, str) and od:
        st["open_operated"] = True
        _save_state(st)


def journal_tick() -> None:
    """
    Llamar una vez por vuelta del bucle principal (MT5 ya inicializado).
    Cierra filas al cambiar día local (TZ bitácora).
    """
    if not journal_enabled():
        return
    saldo = _account_saldo()
    if saldo is None:
        return

    today = _journal_local_today()
    st = _load_state()

    cur = _parse_date(str(st.get("open_day", "") or ""))
    day_index = int(st.get("day_index", 0) or 0)
    if day_index <= 0:
        day_index = 1

    notes_today = list(_JOURNAL_NOTES)
    _JOURNAL_NOTES.clear()

    if cur is None:
        st["open_day"] = today.isoformat()
        st["day_index"] = day_index
        st["saldo_inicial"] = saldo
        st["open_operated"] = False
        st["last_snapshot"] = saldo
        if notes_today:
            st["day_notes"] = "; ".join(notes_today)
        _save_state(st)
        return

    if today == cur:
        st["last_snapshot"] = saldo
        if st.get("open_operated"):
            pass
        if notes_today:
            prev = str(st.get("day_notes", "") or "").strip()
            extra = "; ".join(notes_today)
            st["day_notes"] = f"{prev}; {extra}".strip("; ").strip() if prev else extra
        _save_state(st)
        return

    # Cambio de día: cerrar `cur` y días intermedios sin datos
    try:
        saldo_inicial = float(st.get("saldo_inicial", saldo) or saldo)
    except (TypeError, ValueError):
        saldo_inicial = saldo
    last_snap = float(st.get("last_snapshot", saldo) or saldo)
    operated = bool(st.get("open_operated"))
    dn = str(st.get("day_notes", "") or "").strip()
    if notes_today:
        extra = "; ".join(notes_today)
        dn = f"{dn}; {extra}".strip("; ").strip() if dn else extra

    gan = last_snap - saldo_inicial
    opero_str = "SI" if operated else "NO"
    _append_csv_row(
        dia=day_index,
        fecha=cur,
        saldo_inicial=saldo_inicial,
        ganancia_perdida=gan,
        saldo_final=last_snap,
        opero=opero_str,
        notas=dn,
    )
    _maybe_alert_phase(last_snap, context=cur.isoformat())

    next_d = cur + timedelta(days=1)
    idx_next = day_index + 1
    if next_d < today:
        idx_next = _finalize_gap_days(next_d, today, last_snap, idx_next)

    st["open_day"] = today.isoformat()
    st["day_index"] = idx_next
    st["saldo_inicial"] = saldo
    st["open_operated"] = False
    st["last_snapshot"] = saldo
    st["day_notes"] = ""
    _save_state(st)


def journal_flush_shutdown(reason: str = "cierre de sesión del bot") -> None:
    """
    Persiste último saldo y opcionalmente una nota al salir (Ctrl+C / STOP_AT).
    No escribe fila CSV aquí: el cierre del día calendario lo hace journal_tick al volver a correr
    o al cruzar medianoche en TZ, para no duplicar filas del mismo día.
    """
    if not journal_enabled():
        return
    saldo = _account_saldo()
    st = _load_state()
    cur = _parse_date(str(st.get("open_day", "") or ""))
    if cur is None or saldo is None:
        return
    st["last_snapshot"] = saldo
    dn = str(st.get("day_notes", "") or "").strip()
    if reason:
        st["day_notes"] = f"{dn}; {reason}".strip("; ").strip() if dn else reason
    _save_state(st)
