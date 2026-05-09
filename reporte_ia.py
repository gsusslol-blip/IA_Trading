#!/usr/bin/env python3
"""
Reporte al cierre del día — rendimiento por magic + slippage medio (CSV de ejecución).

  python reporte_ia.py
  python reporte_ia.py --days 14

.env: ``BOT_MAGIC``, ``REPORTE_IA_DAYS`` (default 7), ``IA_EXEC_QUALITY_CSV``.
Ver también ``check_health.py`` (ventana por defecto más larga).
"""

from __future__ import annotations

import argparse
import os
import sys

import MetaTrader5 as mt5

from check_health import run_health_report
from local_env import load_env_file
from mt5_prices import BOT_MAGIC


def main() -> int:
    load_env_file()
    ap = argparse.ArgumentParser(description="Reporte IA_Trading (PnL + slippage desde CSV)")
    ap.add_argument("--days", type=int, default=0, help="Ventana en días (default REPORTE_IA_DAYS o 7)")
    args = ap.parse_args()
    try:
        days = (
            int(args.days)
            if args.days
            else int(os.environ.get("REPORTE_IA_DAYS", "7").strip() or "7")
        )
    except ValueError:
        days = 7
    days = max(1, min(3660, days))
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
        run_health_report(
            magic=magic,
            days=days,
            title=f"=== REPORTE IA_TRADING · últimos {days} d · magic {magic} ===",
        )
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
