"""Tests ia_fee_detector (sin MT5)."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace


class TestFeeDetector(unittest.TestCase):
    def test_delta_precio_formula(self) -> None:
        os.environ["IA_FEE_BE_ENABLE"] = "1"
        os.environ["IA_FEE_DEFAULT_PER_LOT"] = "7.0"
        from ia_fee_detector import _CACHE, delta_precio_breakeven_comision

        _CACHE.clear()
        info = SimpleNamespace(trade_contract_size=100.0)
        delta = delta_precio_breakeven_comision("XAUUSD", 0.10, info=info)
        # 7 * 0.1 / (100 * 0.1) = 0.07
        self.assertAlmostEqual(delta, 0.07, places=4)

    def test_precio_be_buy(self) -> None:
        os.environ["IA_FEE_BE_ENABLE"] = "1"
        os.environ["IA_FEE_DEFAULT_PER_LOT"] = "7.0"
        from ia_fee_detector import _CACHE, precio_breakeven_ajustado

        _CACHE.clear()
        info = SimpleNamespace(trade_contract_size=100.0)
        px = precio_breakeven_ajustado(
            "XAUUSD",
            buy=True,
            entry_price=2650.0,
            volume=0.10,
            buffer_price=0.05,
            info=info,
        )
        self.assertGreater(px, 2650.05)


if __name__ == "__main__":
    unittest.main()
