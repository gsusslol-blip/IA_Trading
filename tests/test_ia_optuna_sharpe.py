"""Tests ia_optuna_sharpe."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class _T:
    entry: float
    sl: float
    pnl_points: float


class TestOptunaSharpe(unittest.TestCase):
    def test_sharpe_penalizes_few_trades(self) -> None:
        from ia_optuna_sharpe import calcular_sharpe_ratio_estrategia

        self.assertEqual(calcular_sharpe_ratio_estrategia(trades=[]), -1.0)

    def test_sharpe_positive_on_consistent_wins(self) -> None:
        from ia_optuna_sharpe import calcular_sharpe_ratio_estrategia

        trades = [
            _T(100.0, 99.0, 1.0),
            _T(100.0, 99.0, 1.2),
            _T(100.0, 99.0, 0.9),
            _T(100.0, 99.0, 1.1),
            _T(100.0, 99.0, 1.0),
            _T(100.0, 99.0, 0.8),
            _T(100.0, 99.0, 1.3),
            _T(100.0, 99.0, 1.0),
            _T(100.0, 99.0, 1.1),
            _T(100.0, 99.0, 0.95),
        ]
        sh = calcular_sharpe_ratio_estrategia(trades=trades)
        self.assertGreater(sh, 0.0)


if __name__ == "__main__":
    unittest.main()
