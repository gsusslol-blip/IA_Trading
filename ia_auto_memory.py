"""
Memoria de operaciones IA_AUTO: recopila cierres del BOT_MAGIC en CSV para análisis (buenas / malas).

  IA_AUTO_MEMORY_ENABLE=1 (default)
  IA_AUTO_MEMORY_CSV — archivo CSV (default ia_auto_trade_memory.csv)
  IA_AUTO_MEMORY_STATE — watermark JSON (default ia_auto_memory_state.json)

No modifica la estrategia de entrada; solo persiste historial para que puedas mejorar el algoritmo.

  python ia_auto_memory.py   — imprime resumen desde el CSV y sincroniza MT5 una vez
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

from local_env import load_env_file


def _label(pnl: float) -> str:
    if pnl > 0:
        return "good"
    if pnl < 0:
        return "bad"
    return "flat"


def closed_positions_detail_by_magic(
    magic: int,
    utc_from: datetime,
    utc_to: datetime,
    *,
    history_lookback_days: int = 14,
) -> list[dict[str, Any]]:
    """
    Una fila por position_id cerrado en [utc_from, utc_to] UTC con PnL neto (profit+commission+swap).
    """
    uf = utc_from if utc_from.tzinfo else utc_from.replace(tzinfo=timezone.utc)
    ut = utc_to if utc_to.tzinfo else utc_to.replace(tzinfo=timezone.utc)
    uf_wide = uf - timedelta(days=max(0, int(history_lookback_days)))
    try:
        mt5.history_select(uf_wide, ut)
    except Exception:
        pass
    deals = mt5.history_deals_get(uf_wide, ut)
    if not deals:
        return []
    agg: dict[int, float] = {}
    times: dict[int, int] = {}
    symbols: dict[int, str] = {}
    for d in deals:
        if int(getattr(d, "magic", -1) or -1) != int(magic):
            continue
        pid = int(getattr(d, "position_id", 0) or 0)
        if pid <= 0:
            continue
        agg[pid] = agg.get(pid, 0.0) + float(getattr(d, "profit", 0.0) or 0.0)
        agg[pid] += float(getattr(d, "commission", 0.0) or 0.0)
        agg[pid] += float(getattr(d, "swap", 0.0) or 0.0)
        t = int(getattr(d, "time", 0) or 0)
        if t >= times.get(pid, 0):
            times[pid] = t
            symbols[pid] = str(getattr(d, "symbol", "") or "")
    ts_lo = int(uf.timestamp())
    ts_hi = int(ut.timestamp())
    out: list[dict[str, Any]] = []
    for pid in agg:
        tc = times.get(pid, 0)
        if ts_lo <= tc <= ts_hi:
            pnl = float(agg[pid])
            out.append(
                {
                    "position_id": pid,
                    "symbol": symbols.get(pid, ""),
                    "pnl_net": pnl,
                    "close_ts": tc,
                    "time_close_utc": datetime.fromtimestamp(tc, tz=timezone.utc).isoformat(),
                    "label": _label(pnl),
                }
            )
    out.sort(key=lambda x: x["close_ts"])
    return out


def _paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parent
    csv_name = os.environ.get("IA_AUTO_MEMORY_CSV", "ia_auto_trade_memory.csv").strip() or "ia_auto_trade_memory.csv"
    state_name = os.environ.get("IA_AUTO_MEMORY_STATE", "ia_auto_memory_state.json").strip() or "ia_auto_memory_state.json"
    return root / csv_name, root / state_name


def _load_watermark(state_path: Path) -> int:
    if not state_path.is_file():
        return 0
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return int(data.get("watermark_close_ts", 0) or 0)
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def _save_watermark(state_path: Path, ts: int) -> None:
    state_path.write_text(
        json.dumps({"watermark_close_ts": ts, "updated_utc": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8",
    )


def sync_memory_from_mt5(magic: int) -> int:
    """
    Añade al CSV los cierres nuevos desde el último watermark. Devuelve cantidad de filas nuevas.
    MT5 debe estar inicializado.
    """
    if os.environ.get("IA_AUTO_MEMORY_ENABLE", "1").strip().lower() in ("0", "false", "no"):
        return 0

    csv_path, state_path = _paths()
    wm = _load_watermark(state_path)
    utc_to = datetime.now(timezone.utc)
    if wm <= 0:
        try:
            days = int(os.environ.get("IA_AUTO_MEMORY_INITIAL_DAYS", "90").strip() or "90")
        except ValueError:
            days = 90
        days = max(1, min(days, 3650))
        utc_from = utc_to - timedelta(days=days)
    else:
        utc_from = datetime.fromtimestamp(max(0, wm - 120), tz=timezone.utc)

    rows = closed_positions_detail_by_magic(magic, utc_from, utc_to)
    new_rows = [r for r in rows if int(r["close_ts"]) > wm]
    if not new_rows:
        return 0

    write_header = not csv_path.is_file()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["time_close_utc", "position_id", "symbol", "pnl_net", "label"])
        max_ts = wm
        for r in new_rows:
            w.writerow(
                [
                    r["time_close_utc"],
                    r["position_id"],
                    r["symbol"],
                    f"{r['pnl_net']:.6f}",
                    r["label"],
                ]
            )
            max_ts = max(max_ts, int(r["close_ts"]))
        f.flush()
    _save_watermark(state_path, max_ts)
    return len(new_rows)


def _parse_csv_time_close(row: dict[str, str]) -> datetime | None:
    raw = (row.get("time_close_utc") or "").strip()
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def obtener_ultimo_cierre_por_simbolo(symbol: str) -> dict[str, Any] | None:
    """
    Última fila del CSV de memoria para el símbolo (más reciente por time_close_utc).
    Claves: time_close_utc, position_id, symbol, pnl_net, label, timestamp (datetime UTC).
    """
    csv_path, _ = _paths()
    if not csv_path.is_file():
        return None
    sym = symbol.strip()
    best: dict[str, Any] | None = None
    best_ts: float = -1.0
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("symbol") or "").strip() != sym:
                continue
            dt = _parse_csv_time_close(row)
            if dt is None:
                continue
            ts = dt.timestamp()
            if ts > best_ts:
                best_ts = ts
                pnl_s = row.get("pnl_net", "") or "0"
                try:
                    pnl = float(pnl_s)
                except ValueError:
                    pnl = 0.0
                best = {
                    "time_close_utc": row.get("time_close_utc", ""),
                    "position_id": row.get("position_id", ""),
                    "symbol": sym,
                    "pnl_net": pnl,
                    "label": (row.get("label") or "").strip(),
                    "timestamp": dt,
                }
    return best


def puede_reentrar_por_memoria_csv(symbol: str, max_age_sec: float | None = None) -> bool:
    """
    True si el último cierre registrado fue pérdida ('bad') y ocurrió hace menos de max_age_sec.

    Por defecto ~45 min (2700 s), alineado a ~3 velas M15 tras un shakeout.
    """
    if max_age_sec is None:
        try:
            max_age_sec = float(os.environ.get("IA_SHAKEOUT_CSV_MAX_AGE_S", "2700").strip() or "2700")
        except ValueError:
            max_age_sec = 2700.0
    row = obtener_ultimo_cierre_por_simbolo(symbol)
    if row is None or row.get("label") != "bad":
        return False
    ts = row["timestamp"]
    if not isinstance(ts, datetime):
        return False
    age = time.time() - ts.timestamp()
    return 0 <= age <= max_age_sec


def memory_csv_recent_bad_within(symbol: str, max_age_sec: float) -> bool:
    """Hay un cierre 'bad' para symbol en el CSV con antigüedad <= max_age_segundos."""
    if max_age_sec <= 0:
        return False
    row = obtener_ultimo_cierre_por_simbolo(symbol)
    if row is None or row.get("label") != "bad":
        return False
    ts = row["timestamp"]
    if not isinstance(ts, datetime):
        return False
    age = time.time() - ts.timestamp()
    return 0 <= age <= max_age_sec


def summary_from_csv() -> str:
    csv_path, _ = _paths()
    if not csv_path.is_file():
        return "Sin archivo de memoria todavía (operaciones cerradas se van guardando)."

    pnls: list[float] = []
    labels: dict[str, int] = {"good": 0, "bad": 0, "flat": 0}
    with csv_path.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                p = float(row.get("pnl_net", 0) or 0)
            except ValueError:
                continue
            pnls.append(p)
            lab = row.get("label", "").strip()
            if lab in labels:
                labels[lab] += 1

    n = len(pnls)
    if n == 0:
        return "CSV vacío de datos."
    net = sum(pnls)
    wins = labels["good"]
    wr = wins / n if n else 0.0
    return (
        f"Memoria IA_AUTO: {n} cierres | neto {net:+.2f} | "
        f"buenas {labels['good']} / malas {labels['bad']} / flat {labels['flat']} | "
        f"win rate ~{wr * 100:.1f}%"
    )


def main() -> None:
    load_env_file()
    from mt5_prices import BOT_MAGIC

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        print(f"No se pudo inicializar MT5. ({code}) {msg}", file=sys.stderr)
        raise SystemExit(1)
    try:
        n = sync_memory_from_mt5(BOT_MAGIC)
        print(f"Sincronizado: {n} cierre(s) nuevo(s).")
        print(summary_from_csv())
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
