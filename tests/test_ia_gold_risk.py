"""Tests núcleo matemático de ia_gold_risk (sin MT5)."""

from __future__ import annotations

import os
import unittest


class TestGoldRiskCore(unittest.TestCase):
    def test_lot_from_risk_and_contract(self) -> None:
        from ia_gold_risk_core import lotaje_oro_desde_parametros

        os.environ["IA_GOLD_MARGIN_HALVE_ENABLE"] = "0"
        vol = lotaje_oro_desde_parametros(
            equity=10_000.0,
            margin_free=8_000.0,
            leverage=100,
            contract_size=100.0,
            precio_entrada=2650.0,
            precio_sl=2640.0,
            porcentaje_riesgo=1.0,
            volume_step=0.01,
            volume_min=0.01,
            volume_max=10.0,
        )
        # riesgo $100, dist 10, contract 100 -> 100/(10*100)=0.10
        self.assertAlmostEqual(vol, 0.10, places=4)

    def test_halve_when_margin_tight(self) -> None:
        from ia_gold_risk_core import lotaje_oro_desde_parametros

        os.environ["IA_GOLD_MARGIN_HALVE_ENABLE"] = "1"
        os.environ["IA_GOLD_MARGIN_MAX_FREE_RATIO"] = "0.50"
        vol = lotaje_oro_desde_parametros(
            equity=10_000.0,
            margin_free=50.0,
            leverage=10,
            contract_size=100.0,
            precio_entrada=2650.0,
            precio_sl=2640.0,
            porcentaje_riesgo=1.0,
            volume_step=0.01,
            volume_min=0.01,
            volume_max=10.0,
        )
        self.assertLessEqual(vol, 0.10)


if __name__ == "__main__":
    unittest.main()
