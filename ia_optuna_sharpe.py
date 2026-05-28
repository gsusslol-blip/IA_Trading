"""
Objetivo Optuna basado en Sharpe Ratio (consistencia vs beneficio bruto).

Usado por ``optuna_walkforward.objective_train_fold`` cuando ``IA_OPTUNA_OBJECTIVE=sharpe``.

Variables:
  IA_OPTUNA_MIN_TRADES_SHARPE=10
  IA_OPTUNA_SHARPE_DD_PENALTY=0.15   — resta λ × max_dd (puntos) al score
"""

from __future__ import annotations

import math
import os
import statistics
from typing import Any


def _min_trades_sharpe() -> int:
    try:
        return max(5, int(os.environ.get("IA_OPTUNA_MIN_TRADES_SHARPE", "10").strip() or "10"))
    except ValueError:
        return 10


def _dd_penalty_coef() -> float:
    try:
        return max(0.0, float(os.environ.get("IA_OPTUNA_SHARPE_DD_PENALTY", "0.15").strip() or "0.15"))
    except ValueError:
        return 0.15


def rendimientos_por_trade(trades: list[Any]) -> list[float]:
    """Retorno % sobre riesgo inicial (distancia entry→SL) por operación cerrada."""
    out: list[float] = []
    for t in trades:
        try:
            entry = float(getattr(t, "entry", 0) or 0)
            sl = float(getattr(t, "sl", 0) or 0)
            pnl = float(getattr(t, "pnl_points", 0) or 0)
        except (TypeError, ValueError):
            continue
        risk = abs(entry - sl)
        if risk <= 1e-12:
            continue
        out.append((pnl / risk) * 100.0)
    return out


def calcular_sharpe_ratio_estrategia(
    trades: list[Any] | None = None,
    *,
    df_trades: Any | None = None,
) -> float:
    """
    Sharpe simplificado sobre retornos por trade × factor √(n) de consistencia.

    Acepta lista de ``Trade`` del backtest o DataFrame con columna ``profit_percent``.
    """
    if df_trades is not None:
        try:
            import pandas as pd

            if isinstance(df_trades, pd.DataFrame) and "profit_percent" in df_trades.columns:
                rendimientos = [float(x) for x in df_trades["profit_percent"].tolist()]
            else:
                return -1.0
        except Exception:
            return -1.0
    elif trades is not None:
        rendimientos = rendimientos_por_trade(trades)
    else:
        return -1.0

    n = len(rendimientos)
    if n < _min_trades_sharpe():
        return -1.0

    rendimiento_promedio = statistics.mean(rendimientos)
    desviacion = statistics.stdev(rendimientos) if n > 1 else 0.0
    if desviacion <= 1e-12:
        return 0.0

    sharpe = rendimiento_promedio / desviacion
    factor_consistencia = math.sqrt(n) / 10.0
    return float(sharpe * factor_consistencia)


def objetivo_sharpe_desde_metricas(
    trades: list[Any],
    metrics: dict[str, float],
) -> float:
    """
    Score final para Optuna: Sharpe − penalización por drawdown (puntos).
    """
    sh = calcular_sharpe_ratio_estrategia(trades=trades)
    if sh <= -0.99:
        return float(os.environ.get("OPTUNA_LOW_SAMPLE_SCORE", "-1000"))
    dd = float(metrics.get("max_dd", 0.0) or 0.0)
    net = float(metrics.get("net", 0.0) or 0.0)
    if net < 0:
        sh -= 0.5
    return sh - _dd_penalty_coef() * dd


def optuna_objective_mode() -> str:
    """``sharpe`` | ``composite`` (default composite)."""
    return os.environ.get("IA_OPTUNA_OBJECTIVE", "composite").strip().lower()
