"""
Backtest bar-by-bar sin duplicar reglas de ia_scanner_loop.analizar_ia.

  python ia_backtester.py

Requiere MT5 inicializado (descarga historia una vez por símbolo). En cada índice de vela M15
cerrada, recorta todas las temporalidades con time <= cierre de esa vela y llama analizar_ia(..., replay=...).

Variables .env:
  IA_BACKTEST_SYMBOL       — símbolo resuelto (default: primer IA_SCAN_SYMBOLS o XAUUSD)
  IA_BACKTEST_BARS_M15    — máx velas M15 a cargar (default 2000)
  IA_BACKTEST_WARMUP_M15 — primer índice de barra a evaluar (default 80)
  IA_BACKTEST_SYNTH_SPREAD_POINTS — spread sintético en puntos sobre mid (opcional)

Carga opcionalmente .env / params igual que otros scripts del proyecto (local_env + optuna si aplica).
"""

from __future__ import annotations

import os
import sys

import MetaTrader5 as mt5

from ia_replay import fetch_history_for_backtest, slices_upto_m15_time
from ia_scanner_loop import analizar_ia
from local_env import apply_optuna_overrides, load_env_file
from m15_ma_scan import _resolve_scan_symbol


def main() -> int:
    load_env_file()
    apply_optuna_overrides()

    raw_sym = (
        os.environ.get("IA_BACKTEST_SYMBOL", "").strip()
        or os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").split(",")[0].strip()
        or "XAUUSD"
    )
    try:
        m15_n = int(os.environ.get("IA_BACKTEST_BARS_M15", "2000").strip() or "2000")
    except ValueError:
        m15_n = 2000
    try:
        warm = int(os.environ.get("IA_BACKTEST_WARMUP_M15", "80").strip() or "80")
    except ValueError:
        warm = 80
    m15_n = max(200, min(50_000, m15_n))
    warm = max(60, min(m15_n - 5, warm))

    path = os.environ.get("MT5_PATH")
    if not (mt5.initialize(path=path) if path else mt5.initialize()):
        print(f"No MT5: {mt5.last_error()}", file=sys.stderr)
        return 1
    try:
        sym = _resolve_scan_symbol(raw_sym)
        if not sym:
            print(f"Símbolo no operable: {raw_sym}", file=sys.stderr)
            return 1
        mt5.symbol_select(sym, True)

        c5 = max(5000, m15_n * 16)
        c1 = max(2500, m15_n // 8 + 400)
        c4 = max(600, m15_n // (15 * 4) + 100)
        df5, df15, dfh, df4 = fetch_history_for_backtest(sym, (c5, m15_n, c1, c4))

        n = len(df15)
        confirmations = []
        for i in range(warm, n):
            tc = int(df15.iloc[i]["time"])
            rep = slices_upto_m15_time(
                t_close=tc,
                df_m15=df15,
                df_m5=df5,
                df_h1=dfh,
                df_h4=df4,
            )
            if rep is None:
                continue
            msg = analizar_ia(sym, replay=rep)
            if "CONFIRMADA" in msg:
                confirmations.append((tc, msg))

        from datetime import datetime, timezone

        print(f"Símbolo {sym} | barras M15={n} | evaluadas {n - warm}")
        print(f"Señales confirmadas: {len(confirmations)}")
        for tc, msg in confirmations[:50]:
            dt = datetime.fromtimestamp(tc, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            print(f"  {dt} | {msg}")
        if len(confirmations) > 50:
            print(f"  ... y {len(confirmations) - 50} más")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
