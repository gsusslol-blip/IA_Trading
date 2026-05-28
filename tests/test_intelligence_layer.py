"""Tests ia_intelligence_layer (sin MT5)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd


class TestIntelligenceLayer(unittest.TestCase):
    def test_filtro_fail_open_sin_modelo(self) -> None:
        os.environ["IA_ML_FILTER_ENABLE"] = "1"
        from ia_intelligence_layer import filtro_inteligencia_artificial

        self.assertTrue(filtro_inteligencia_artificial([1.0, 12.0, 25.0, 0.1, 40.0]))

    def test_autotune_strict_on_high_slip(self) -> None:
        os.environ["IA_EXEC_AUTOTUNE_ENABLE"] = "1"
        os.environ["IA_EXEC_AUTOTUNE_SLIP_PTS"] = "5"
        os.environ.pop("IA_EXEC_AUTOTUNE_ACTIVE", None)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "execution_quality.csv"
            df = pd.DataFrame({"slippage_points": [30.0] * 10})
            df.to_csv(p, index=False)
            os.environ["IA_EXEC_QUALITY_CSV"] = str(p)
            from ia_intelligence_layer import auto_ajuste_spread_por_auditoria

            self.assertTrue(auto_ajuste_spread_por_auditoria())
            self.assertEqual(os.environ.get("IA_EXEC_AUTOTUNE_ACTIVE"), "1")


if __name__ == "__main__":
    unittest.main()
