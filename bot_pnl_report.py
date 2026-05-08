"""
Resumen de ganancias y pérdidas de las operaciones del bot (historial MT5 filtrado por BOT_MAGIC).

Usa el mismo criterio que el bot: deals con magic del bot, símbolo resuelto (TRADE_SYMBOL),
PnL neto por position_id (profit + commission + swap).

  python bot_pnl_report.py

Variables opcionales:
  BOT_PNL_DAYS   — ventana hacia atrás en días (default 3650)
"""

from __future__ import annotations

import os
import sys

import MetaTrader5 as mt5

from local_env import load_env_file


def main() -> None:
    load_env_file()
    try:
        days = int(os.environ.get("BOT_PNL_DAYS", "3650").strip() or "3650")
    except ValueError:
        days = 3650
    from mt5_prices import BOT_MAGIC, _resolve_trade_symbol, closed_bot_trade_pnls, closed_trade_winrate_stats

    requested = os.environ.get("TRADE_SYMBOL", "XAUUSD")
    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        print(f"No se pudo inicializar MT5. ({code}) {msg}", file=sys.stderr)
        raise SystemExit(1)
    try:
        symbol = _resolve_trade_symbol(requested)
        pnls = closed_bot_trade_pnls(symbol, BOT_MAGIC, days=days)
        cur = os.environ.get("ACCOUNT_CURRENCY") or ""
        ai = mt5.account_info()
        if ai is not None:
            cur = str(getattr(ai, "currency", "") or cur)
    finally:
        mt5.shutdown()

    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross_win = sum(wins)
    gross_loss = sum(losses)  # negative sum
    net = sum(pnls)
    wr, _, _, _ = closed_trade_winrate_stats(pnls)
    exp = net / len(pnls) if pnls else 0.0

    sym_disp = f"{requested} → {symbol}" if requested != symbol else symbol

    print(f"Símbolo: {sym_disp}")
    print(f"Magic BOT: {BOT_MAGIC}")
    print(f"Ventana: últimos {days} días (historial MT5 cargado en terminal)")
    print(f"Operaciones cerradas contadas: {len(pnls)}")
    print(f"  Ganadoras: {len(wins)} · Perdedoras: {len(losses)} · BE/cero: {len(pnls) - len(wins) - len(losses)}")
    print(f"  % aciertos (win rate): {wr * 100:.2f}%")
    print(f"  Expectativa media por trade: {exp:.2f} {cur}".strip())
    print(f"Suma de ganancias (solo trades > 0): +{gross_win:.2f} {cur}".strip())
    print(f"Suma de pérdidas (solo trades < 0): {gross_loss:.2f} {cur}".strip())
    print(f"Resultado neto: {net:.2f} {cur}".strip())


if __name__ == "__main__":
    main()
