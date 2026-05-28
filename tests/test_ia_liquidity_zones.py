"""Tests ia_liquidity_zones (sin MT5)."""

from __future__ import annotations

import os
import unittest


class TestLiquidityZones(unittest.TestCase):
    def test_near_yesterday_high(self) -> None:
        from ia_liquidity_zones import verificar_proximidad_liquidez_diaria

        os.environ["IA_D1_LIQUIDITY_ENABLE"] = "1"
        ok, _ = verificar_proximidad_liquidez_diaria(
            "XAUUSD",
            2650.0,
            5.0,
            high_ayer=2651.0,
            bajo_ayer=2600.0,
        )
        self.assertTrue(ok)

    def test_mid_range_blocked(self) -> None:
        from ia_liquidity_zones import verificar_proximidad_liquidez_diaria

        os.environ["IA_D1_LIQUIDITY_ENABLE"] = "1"
        ok, why = verificar_proximidad_liquidez_diaria(
            "XAUUSD",
            2625.0,
            2.0,
            high_ayer=2700.0,
            bajo_ayer=2600.0,
        )
        self.assertFalse(ok)
        self.assertIn("lejos", why)


if __name__ == "__main__":
    unittest.main()
