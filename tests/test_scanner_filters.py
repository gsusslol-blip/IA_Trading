"""Tests para filtros EMA H4 y momentum M15 (ia_scanner_loop, sin MT5)."""

from __future__ import annotations

import unittest

import pandas as pd

from ia_scanner_loop import (
    _filtro_h4_ema_alineado,
    _filtro_m15_momentum_vela,
    _h4_ema_last,
)


class TestH4Ema(unittest.TestCase):
    def test_ema_last(self) -> None:
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0, 104.0] * 10})
        ema = _h4_ema_last(df, 5)
        self.assertIsNotNone(ema)

    def test_align_buy(self) -> None:
        self.assertTrue(_filtro_h4_ema_alineado("BUY", 105.0, 100.0, min_dist_pct=0.0))
        self.assertFalse(_filtro_h4_ema_alineado("BUY", 99.0, 100.0, min_dist_pct=0.0))

    def test_align_sell(self) -> None:
        self.assertTrue(_filtro_h4_ema_alineado("SELL", 95.0, 100.0, min_dist_pct=0.0))
        self.assertFalse(_filtro_h4_ema_alineado("SELL", 101.0, 100.0, min_dist_pct=0.0))

    def test_min_dist(self) -> None:
        # (102-100)/100*100 = 2%
        self.assertTrue(_filtro_h4_ema_alineado("BUY", 102.0, 100.0, min_dist_pct=1.5))
        self.assertFalse(_filtro_h4_ema_alineado("BUY", 101.0, 100.0, min_dist_pct=1.5))


class TestM15Momentum(unittest.TestCase):
    def test_body_ratio(self) -> None:
        row = pd.Series({"open": 100.0, "high": 110.0, "low": 90.0, "close": 108.0})
        ok, _ = _filtro_m15_momentum_vela("BUY", row, min_body_ratio=0.4, close_in_third=False)
        self.assertTrue(ok)

    def test_close_third_buy(self) -> None:
        # range 20, close 109 -> pos = 19/20 = 0.95 > 2/3
        row = pd.Series({"open": 100.0, "high": 110.0, "low": 90.0, "close": 109.0})
        ok, _ = _filtro_m15_momentum_vela("BUY", row, min_body_ratio=0.1, close_in_third=True)
        self.assertTrue(ok)

    def test_close_third_sell(self) -> None:
        row = pd.Series({"open": 100.0, "high": 110.0, "low": 90.0, "close": 91.0})
        ok, _ = _filtro_m15_momentum_vela("SELL", row, min_body_ratio=0.1, close_in_third=True)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
