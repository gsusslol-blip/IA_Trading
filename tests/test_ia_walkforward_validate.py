"""Tests ia_walkforward_validate (sin MT5)."""

from __future__ import annotations

import os
import unittest


class TestWalkForwardValidate(unittest.TestCase):
    def test_train_fraction_bounds(self) -> None:
        from ia_walkforward_validate import _train_fraction

        os.environ["IA_OPTUNA_WF_SPLIT_TRAIN"] = "0.70"
        self.assertAlmostEqual(_train_fraction(), 0.70)

    def test_oos_rejects_low_sharpe(self) -> None:
        from ia_walkforward_validate import oos_params_aprobados

        os.environ["IA_OPTUNA_OOS_MIN_SHARPE"] = "0.1"
        ok, why = oos_params_aprobados({"net": 10.0, "n": 20}, sharpe_oos=0.0)
        self.assertFalse(ok)
        self.assertIn("Sharpe", why)


if __name__ == "__main__":
    unittest.main()
