"""
Validación walk-forward 70% in-sample / 30% out-of-sample antes de guardar params.

Variables:
  IA_OPTUNA_WF_SPLIT_TRAIN=0.70
  IA_OPTUNA_OOS_MIN_SHARPE=0.0
  IA_OPTUNA_OOS_REQUIRE_POSITIVE_NET=1
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from ia_optuna_sharpe import calcular_sharpe_ratio_estrategia, optuna_objective_mode


def _month_floor_utc(dt: datetime) -> datetime:
    d = dt.astimezone(timezone.utc)
    return datetime(d.year, d.month, 1, tzinfo=timezone.utc)


def _add_months(dt: datetime, months: int) -> datetime:
    y, m = dt.year, dt.month
    m2 = m - 1 + months
    y2 = y + m2 // 12
    m3 = (m2 % 12) + 1
    return datetime(y2, m3, 1, tzinfo=timezone.utc)


def _train_fraction() -> float:
    try:
        return max(0.50, min(0.85, float(os.environ.get("IA_OPTUNA_WF_SPLIT_TRAIN", "0.70").strip() or "0.70")))
    except ValueError:
        return 0.70


def _oos_min_sharpe() -> float:
    try:
        return float(os.environ.get("IA_OPTUNA_OOS_MIN_SHARPE", "0.0").strip() or "0.0")
    except ValueError:
        return 0.0


def _oos_require_positive_net() -> bool:
    return os.environ.get("IA_OPTUNA_OOS_REQUIRE_POSITIVE_NET", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def ventanas_is_oos(months_total: int) -> tuple[datetime, datetime, datetime, datetime]:
    """
    (train_from, train_to, test_from, test_to) con split temporal 70/30 sobre ``months_total``.
    """
    end = _month_floor_utc(datetime.now(timezone.utc))
    start = _add_months(end, -int(months_total))
    span_s = (end - start).total_seconds()
    if span_s <= 0:
        raise ValueError("Rango histórico inválido para walk-forward")
    train_to_dt = start + timedelta(seconds=span_s * _train_fraction())
    return start, train_to_dt, train_to_dt, end


def evaluar_params_oos(
    symbol: str,
    params: dict[str, Any],
    test_from: datetime,
    test_to: datetime,
) -> tuple[dict[str, float], list[Any], float]:
    from backtest_walkforward import metrics_ext, run_backtest

    trades = run_backtest(symbol, test_from, test_to, params)
    m = metrics_ext(trades)
    if optuna_objective_mode() == "sharpe":
        score = calcular_sharpe_ratio_estrategia(trades=trades)
    else:
        score = float(m.get("sharpe", 0.0) or 0.0)
    return m, trades, float(score)


def oos_params_aprobados(
    metrics: dict[str, float],
    *,
    sharpe_oos: float,
) -> tuple[bool, str]:
    min_sh = _oos_min_sharpe()
    net = float(metrics.get("net", 0.0) or 0.0)
    n = int(metrics.get("n", 0) or 0)

    if n < 3:
        return False, f"pocos trades OOS (n={n})"
    if sharpe_oos < min_sh:
        return False, f"Sharpe OOS {sharpe_oos:.3f} < mínimo {min_sh:.3f}"
    if _oos_require_positive_net() and net <= 0:
        return False, f"net OOS {net:.2f} <= 0"
    return True, "OK"
