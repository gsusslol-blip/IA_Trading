"""
Dataset de entrenamiento ML: foto de mercado en apertura + resultado en cierre.

Variables:
  IA_ML_AUDIT_ENABLE=1
  IA_ML_AUDIT_CSV=trade_audit_ml.csv
  IA_ML_AUDIT_PENDING=ia_audit_pending.json
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

from ia_indicators import obtener_snapshot_completo
from mt5_prices import BOT_MAGIC

_CSV_HEADERS = [
    "position_id",
    "symbol",
    "side",
    "volume",
    "precio_entrada",
    "precio_cierre",
    "profit_net",
    "spread_pts",
    "hora_utc",
    "adx_m15",
    "distancia_ema_h4",
    "atr_m15_pct",
    "time_open_utc",
    "time_close_utc",
    "resultado",
]


def audit_enabled() -> bool:
    return os.environ.get("IA_ML_AUDIT_ENABLE", "1").strip().lower() in ("1", "true", "yes")


def audit_csv_path() -> Path:
    from ia_paths import resolve_data_path

    return resolve_data_path("IA_ML_AUDIT_CSV", "logs/trade_audit_ml.csv")


def _pending_path() -> Path:
    from ia_paths import resolve_data_path

    return resolve_data_path("IA_ML_AUDIT_PENDING", "logs/ia_audit_pending.json")


def _written_state_path() -> Path:
    return _pending_path().with_suffix(".written.json")


def inicializar_csv_auditoria() -> Path:
    p = audit_csv_path()
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(_CSV_HEADERS)
    return p


def _load_pending() -> dict[str, Any]:
    p = _pending_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_pending(data: dict[str, Any]) -> None:
    p = _pending_path()
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_written_ids() -> set[str]:
    p = _written_state_path()
    if not p.is_file():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ids = data.get("position_ids", [])
        return {str(x) for x in ids}
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def _save_written_ids(ids: set[str]) -> None:
    p = _written_state_path()
    p.write_text(
        json.dumps(
            {
                "position_ids": sorted(ids)[-5000:],
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def capturar_metricas_mercado(symbol: str, *, buy: bool) -> dict[str, float]:
    """Foto de mercado vía ``ia_indicators.obtener_snapshot_completo``."""
    return obtener_snapshot_completo(symbol, buy=buy)


def _position_id_from_deal(deal_ticket: int) -> int | None:
    if deal_ticket <= 0:
        return None
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=3)
    try:
        mt5.history_select(start, now)
    except Exception:
        pass
    deals = mt5.history_deals_get(start, now)
    if not deals:
        return None
    for d in deals:
        if int(getattr(d, "ticket", 0) or 0) == deal_ticket:
            pid = int(getattr(d, "position_id", 0) or 0)
            if pid > 0:
                return pid
    return None


def registrar_apertura_trade(
    symbol: str,
    *,
    buy: bool,
    volume: float,
    entry_price: float,
    deal_ticket: int = 0,
    position_id: int | None = None,
) -> bool:
    """
    Guarda métricas de entrada en JSON pendiente hasta el cierre de la posición.
    """
    if not audit_enabled():
        return False
    pid = position_id
    if pid is None and deal_ticket > 0:
        pid = _position_id_from_deal(deal_ticket)
    if pid is None:
        for p in mt5.positions_get(symbol=symbol) or []:
            if int(getattr(p, "magic", -1) or -1) != BOT_MAGIC:
                continue
            pid = int(getattr(p, "ticket", 0) or 0)
            break
    if pid is None or pid <= 0:
        return False

    metrics = capturar_metricas_mercado(symbol, buy=buy)
    pending = _load_pending()
    pending[str(pid)] = {
        "position_id": pid,
        "symbol": symbol,
        "side": "BUY" if buy else "SELL",
        "volume": float(volume),
        "precio_entrada": float(entry_price),
        "time_open_utc": datetime.now(timezone.utc).isoformat(),
        "deal_open": int(deal_ticket),
        **metrics,
    }
    _save_pending(pending)
    inicializar_csv_auditoria()
    print(f"[audit] Apertura registrada position_id={pid} {symbol}", flush=True)
    return True


def registrar_apertura_desde_orden(
    symbol: str,
    *,
    buy: bool,
    volume: float,
    entry_price: float,
    order_result: Any,
) -> bool:
    deal = int(getattr(order_result, "deal", 0) or 0)
    return registrar_apertura_trade(
        symbol,
        buy=buy,
        volume=volume,
        entry_price=entry_price,
        deal_ticket=deal,
    )


def _pnl_for_position(position_id: int, magic: int) -> tuple[float, float, str]:
    """(profit_net, close_price_approx, time_close_iso)."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=14)
    try:
        mt5.history_select(start, now)
    except Exception:
        pass
    deals = mt5.history_deals_get(start, now)
    if not deals:
        return 0.0, 0.0, now.isoformat()
    total = 0.0
    last_price = 0.0
    last_t = 0
    for d in deals:
        if int(getattr(d, "magic", -1) or -1) != magic:
            continue
        if int(getattr(d, "position_id", 0) or 0) != position_id:
            continue
        total += float(getattr(d, "profit", 0.0) or 0.0)
        total += float(getattr(d, "commission", 0.0) or 0.0)
        total += float(getattr(d, "swap", 0.0) or 0.0)
        t = int(getattr(d, "time", 0) or 0)
        if t >= last_t:
            last_t = t
            last_price = float(getattr(d, "price", 0.0) or 0.0)
    close_iso = datetime.fromtimestamp(last_t, tz=timezone.utc).isoformat() if last_t else now.isoformat()
    return total, last_price, close_iso


def registrar_cierre_trade(position_id: int, *, magic: int | None = None) -> bool:
    """
    Escribe fila completa en ``trade_audit_ml.csv`` si hay snapshot de apertura pendiente.
    """
    if not audit_enabled():
        return False
    mag = int(magic if magic is not None else BOT_MAGIC)
    pid_s = str(position_id)
    written = _load_written_ids()
    if pid_s in written:
        return False

    pending = _load_pending()
    snap = pending.get(pid_s)
    if not snap:
        return False

    profit, px_close, t_close = _pnl_for_position(int(position_id), mag)
    resultado = 1 if profit > 1e-8 else 0

    inicializar_csv_auditoria()
    row = [
        int(position_id),
        snap.get("symbol", ""),
        snap.get("side", ""),
        snap.get("volume", 0.0),
        snap.get("precio_entrada", 0.0),
        px_close,
        profit,
        snap.get("spread_pts", 0.0),
        snap.get("hora_utc", 0.0),
        snap.get("adx_m15", 0.0),
        snap.get("distancia_ema_h4", 0.0),
        snap.get("atr_m15_pct", 0.0),
        snap.get("time_open_utc", ""),
        t_close,
        resultado,
    ]
    with audit_csv_path().open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)

    pending.pop(pid_s, None)
    _save_pending(pending)
    written.add(pid_s)
    _save_written_ids(written)
    print(
        f"[audit] Cierre position_id={position_id} resultado={resultado} profit={profit:.2f}",
        flush=True,
    )
    return True


def limpiar_pending_huerfanos(magic: int | None = None) -> int:
    """
    Elimina entradas de ``ia_audit_pending.json`` sin posición abierta ni cierre reciente.

    Variables: ``IA_AUDIT_PENDING_MAX_AGE_H`` (default 72).
    """
    if not audit_enabled():
        return 0
    try:
        max_h = float(os.environ.get("IA_AUDIT_PENDING_MAX_AGE_H", "72").strip() or "72")
    except ValueError:
        max_h = 72.0
    max_h = max(1.0, max_h)

    mag = int(magic if magic is not None else BOT_MAGIC)
    pending = _load_pending()
    if not pending:
        return 0

    open_ids: set[str] = set()
    for p in mt5.positions_get() or []:
        if int(getattr(p, "magic", -1) or -1) != mag:
            continue
        open_ids.add(str(int(getattr(p, "ticket", 0) or 0)))

    now = datetime.now(timezone.utc)
    removed = 0
    for pid_s, snap in list(pending.items()):
        if pid_s in open_ids:
            continue
        age_ok = False
        t_open = str(snap.get("time_open_utc", "") or "")
        if t_open:
            try:
                dt = datetime.fromisoformat(t_open.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_h = (now - dt).total_seconds() / 3600.0
                age_ok = age_h > max_h
            except (TypeError, ValueError):
                age_ok = True
        else:
            age_ok = True

        if not age_ok:
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            pending.pop(pid_s, None)
            removed += 1
            continue
        if registrar_cierre_trade(pid, magic=mag):
            removed += 1
        else:
            pending.pop(pid_s, None)
            removed += 1

    if removed:
        _save_pending(pending)
        print(f"[audit] Limpiados {removed} pending huérfano(s).", flush=True)
    return removed


def procesar_cierres_audit(magic: int | None = None) -> int:
    """
    Detecta posiciones cerradas (ya no en ``positions_get``) con snapshot pendiente
    y las persiste en el CSV de entrenamiento.
    """
    if not audit_enabled():
        return 0
    mag = int(magic if magic is not None else BOT_MAGIC)
    try:
        limpiar_pending_huerfanos(mag)
    except Exception:
        pass
    pending = _load_pending()
    if not pending:
        return 0

    open_ids: set[str] = set()
    for p in mt5.positions_get() or []:
        if int(getattr(p, "magic", -1) or -1) != mag:
            continue
        open_ids.add(str(int(getattr(p, "ticket", 0) or 0)))

    n = 0
    for pid_s in list(pending.keys()):
        if pid_s in open_ids:
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            pending.pop(pid_s, None)
            continue
        if registrar_cierre_trade(pid, magic=mag):
            n += 1
    return n
