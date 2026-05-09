"""
Backtest incremental en vela M15 cerrada usando ``analizar_ia`` con datos externos.

Cada paso construye ventanas ``df_m15`` / ``df_h4`` sin futuro en esas tablas y delega el
relleno H1/M5 + bid/ask a ``replay_from_m15_h4_windows`` dentro de ``analizar_ia``.

  python ia_fast_backtest.py

.env:
  IA_FAST_BT_SYMBOL — default primer IA_SCAN_SYMBOLS
  IA_FAST_BT_BARS_M15 — barras histórico M15 a cargar (default 2500)
  IA_FAST_BT_WARMUP — primer índice de barra a evaluar (default 120)
"""

from __future__ import annotations

import os
import sys

import MetaTrader5 as mt5

from ia_scanner_loop import analizar_ia
from local_env import apply_optuna_overrides, load_env_file
from m15_ma_scan import _resolve_scan_symbol
from mt5_prices import get_rates_optimized


def main() -> int:
    load_env_file()
    apply_optuna_overrides()

    raw_sym = (
        os.environ.get("IA_FAST_BT_SYMBOL", "").strip()
        or os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").split(",")[0].strip()
        or "XAUUSD"
    )
    try:
        nb = int(os.environ.get("IA_FAST_BT_BARS_M15", "2500").strip() or "2500")
    except ValueError:
        nb = 2500
    try:
        warm = int(os.environ.get("IA_FAST_BT_WARMUP", "120").strip() or "120")
    except ValueError:
        warm = 120

    nb = max(250, min(50_000, nb))
    warm = max(100, min(nb - 2, warm))

    path = os.environ.get("MT5_PATH")
    if not (mt5.initialize(path=path) if path else mt5.initialize()):
        print(f"No MT5: {mt5.last_error()}", file=sys.stderr)
        return 1
    try:
        sym = _resolve_scan_symbol(raw_sym)
        if not sym:
            print(f"Símbolo inválido: {raw_sym}", file=sys.stderr)
            return 1
        mt5.symbol_select(sym, True)

        df15 = get_rates_optimized(sym, mt5.TIMEFRAME_M15, nb)
        df4 = get_rates_optimized(sym, mt5.TIMEFRAME_H4, max(400, nb // 8))
        if df15 is None or df4 is None:
            print("Sin datos históricos suficientes.", file=sys.stderr)
            return 1

        hits: list[tuple[int, str]] = []
        for i in range(warm, len(df15)):
            m15_win = df15.iloc[: i + 1].copy()
            tc = int(m15_win.iloc[-1]["time"])
            h4_win = df4[df4["time"] <= tc].copy()
            if len(h4_win) < 20:
                continue
            msg = analizar_ia(sym, df_m15_override=m15_win, df_h4_override=h4_win)
            if "CONFIRMADA" in msg:
                hits.append((tc, msg))

        print(f"[fast-bt] {sym} barras={len(df15)} eval={len(df15) - warm} hits={len(hits)}")
        for tc, msg in hits[:80]:
            print(f"  t={tc} | {msg}")
        if len(hits) > 80:
            print(f"  ... +{len(hits) - 80} más")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
