"""
Métricas de rendimiento a partir del historial MT5 en la cuenta actual (magic del bot).

  python ia_report_performance.py [--days 30] [--magic 260505]

Usa agrupación por position_id (profit+commission+swap) como mt5_prices.closed_positions_pnls_by_magic.

.env: BOT_MAGIC si no pasás --magic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from local_env import load_env_file
from mt5_prices import BOT_MAGIC, closed_positions_pnls_by_magic


def max_drawdown_fraction(pnls_ordered: list[float]) -> float:
    """Máximo drawdown relativo al pico de equity acumulada (0 .. 1+)."""
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls_ordered:
        eq += p
        if eq > peak:
            peak = eq
        if peak > 1e-12:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def generar_reporte_ia(*, magic: int, days: int) -> dict[str, float | str | int]:
    utc_to = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(days=max(1, days))
    path = os.environ.get("MT5_PATH")
    if not (mt5.initialize(path=path) if path else mt5.initialize()):
        return {"error": str(mt5.last_error()), "magic": magic}

    try:
        pnls = closed_positions_pnls_by_magic(magic, utc_from, utc_to)
    finally:
        mt5.shutdown()

    if not pnls:
        return {"error": "no_trades", "magic": magic, "days": days}

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    if gross_loss > 1e-12:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 1e-12:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    net = sum(pnls)
    winrate_pct = len(wins) / len(pnls) * 100.0
    mdd = max_drawdown_fraction(pnls)

    return {
        "magic": magic,
        "days": days,
        "n_positions_closed": len(pnls),
        "net_profit": round(net, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "win_rate_pct": round(winrate_pct, 2),
        "max_drawdown_frac": round(mdd, 4),
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
    }


def main() -> int:
    load_env_file()
    ap = argparse.ArgumentParser(description="Reporte MT5 por magic (posiciones cerradas)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--magic", type=int, default=BOT_MAGIC)
    ap.add_argument("--json", action="store_true", help="Salida JSON")
    args = ap.parse_args()

    rep = generar_reporte_ia(magic=int(args.magic), days=int(args.days))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        if rep.get("error") == "no_trades":
            print(f"No hay cierres con magic={args.magic} en últimos {args.days} días.")
            return 2
        if "error" in rep:
            print(rep, file=sys.stderr)
            return 1
        for k, v in rep.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
