#!/usr/bin/env python3
"""
Chequeo diario de salud del bot (post-trade + calidad de ejecución en CSV).

Ejecutar una vez al día con MT5 abierto y cuenta con historial cargado:

  python check_health.py
  python check_health.py --days 14

Variables .env:
  BOT_MAGIC — mismo magic que órdenes del bot (default al de mt5_prices)
  CHECK_HEALTH_DAYS — ventana de deals cerrados (default 30)
  IA_EXEC_QUALITY_CSV — ruta de execution_quality.csv (para resumen de slippage)

Limitación: el slippage agregado viene del CSV generado por ``log_execution_quality``
(precio pedido vs ejecutado); el historial MT5 solo no lleva “precio pedido” estándar.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5

from local_env import load_env_file
from mt5_prices import BOT_MAGIC, closed_positions_pnls_by_magic


def _exec_quality_csv_path() -> Path:
    root = Path(__file__).resolve().parent
    name = os.environ.get("IA_EXEC_QUALITY_CSV", "").strip() or "execution_quality.csv"
    p = Path(name)
    return p if p.is_absolute() else (root / p)


def _summarize_exec_csv(path: Path) -> None:
    if not path.is_file():
        print(f"Ejecución: no existe {path} (activá IA_EXEC_QUALITY_ENABLE si querés métricas).")
        return
    slips: list[float] = []
    spreads: list[float] = []
    try:
        with path.open(encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            if not r.fieldnames:
                print("Ejecución: CSV vacío o sin cabecera.")
                return
            for row in r:
                s = row.get("slippage_points", "").strip()
                if not s:
                    continue
                try:
                    slips.append(float(s))
                except ValueError:
                    continue
                sp = row.get("spread_points", "").strip()
                if sp:
                    try:
                        spreads.append(float(sp))
                    except ValueError:
                        pass
    except OSError as e:
        print(f"Ejecución: no se pudo leer {path}: {e}")
        return
    n = len(slips)
    if n == 0:
        print("Ejecución: sin filas con slippage_points en el CSV.")
        return
    med = statistics.median(slips)
    mx = max(slips)
    avg_spread = statistics.mean(spreads) if spreads else None
    print("--- Calidad de ejecución (CSV) ---")
    print(f"Muestras (órdenes con slip en pts): {n}")
    print(f"Slippage pts — mediana: {med:.4g} · máx: {mx:.4g}")
    if avg_spread is not None:
        print(f"Spread pts (media en mismas filas): {avg_spread:.4g}")


def run_health_report(*, magic: int, days: int, title: str | None = None) -> None:
    """
    Asume MT5 inicializado. Imprime PnL/win rate por posición cerrada + resumen slippage desde CSV.
    ``title``: línea banner opcional (ej. reporte fin de día).
    """
    if title:
        print(title)
        print()
    _pnl_report(magic, days)
    print()
    _summarize_exec_csv(_exec_quality_csv_path())


def _pnl_report(magic: int, days: int) -> None:
    utc_to = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(days=max(1, int(days)))
    pnls = closed_positions_pnls_by_magic(magic, utc_from, utc_to)
    print("--- Historial MT5 (posiciones cerradas, por magic) ---")
    print(f"Magic: {magic} · ventana: últimos {days} días (UTC)")
    if not pnls:
        print("Sin cierres en la ventana (o historial no cargado en MT5).")
        return
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    flat = len(pnls) - wins - losses
    total = sum(pnls)
    wr = wins / len(pnls) if pnls else 0.0
    print(f"Trades (posiciones): {len(pnls)}  (W / L / BE: {wins} / {losses} / {flat})")
    print(f"Win rate: {wr:.2%}")
    print(f"Profit neto (suma posiciones): {total:.2f}")
    profits = [p for p in pnls if p > 0]
    losses_only = [p for p in pnls if p < 0]
    if profits and losses_only:
        avg_w = sum(profits) / len(profits)
        avg_l = sum(losses_only) / len(losses_only)
        print(f"Avg win: {avg_w:.2f} · Avg loss: {avg_l:.2f} (bruto por trade)")


def main() -> int:
    load_env_file()
    ap = argparse.ArgumentParser(description="Reporte de salud IA_Trading (MT5 + CSV ejecución)")
    ap.add_argument("--days", type=int, default=0, help="Ventana en días (default: CHECK_HEALTH_DAYS o 30)")
    args = ap.parse_args()
    try:
        days = int(args.days) if args.days else int(os.environ.get("CHECK_HEALTH_DAYS", "30").strip() or "30")
    except ValueError:
        days = 30
    days = max(1, min(3650, days))
    try:
        magic = int(os.environ.get("BOT_MAGIC", str(BOT_MAGIC)).strip() or str(BOT_MAGIC))
    except ValueError:
        magic = BOT_MAGIC

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        print(f"No se pudo inicializar MT5. ({code}) {msg}", file=sys.stderr)
        return 1
    try:
        run_health_report(magic=magic, days=days, title="=== IA_Trading · check_health ===")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
