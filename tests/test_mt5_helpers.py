"""Helpers MT5 con mocks (sin terminal)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def _bar(time: int) -> dict:
    return {
        "time": time,
        "open": 1.0,
        "high": 1.0,
        "low": 1.0,
        "close": 1.0,
        "tick_volume": 1,
        "spread": 0,
        "real_volume": 0,
    }


def _ensure_project_root() -> None:
    root = Path(__file__).resolve().parent.parent
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)


class TestRatesCache(unittest.TestCase):
    def setUp(self) -> None:
        _ensure_project_root()

    def test_mt5_rates_cache_second_hit_only_polls_probe(self) -> None:
        import os

        import MetaTrader5 as mt5_import

        import mt5_prices as mp

        mp.mt5_rates_cache_clear()
        old = dict(os.environ)
        try:
            os.environ["IA_MT5_RATES_CACHE"] = "1"
            anchor = 424242
            probe = [_bar(anchor)]
            bulk = [_bar(anchor - 200), _bar(anchor - 100), _bar(anchor)]
            counts: list[int] = []

            def side(_sym, _tf, _pos, cnt):
                c = int(cnt)
                counts.append(c)
                return probe[:] if c == 1 else bulk[:]

            with patch.object(mp.mt5, "copy_rates_from_pos", side_effect=side):
                r1 = mp.mt5_copy_rates_from_pos_cached("S", mt5_import.TIMEFRAME_M15, 0, 3)
                r2 = mp.mt5_copy_rates_from_pos_cached("S", mt5_import.TIMEFRAME_M15, 0, 3)

            self.assertEqual(list(r1), list(bulk))
            self.assertIs(r2, r1)
            self.assertEqual(counts, [1, 3, 1])
        finally:
            os.environ.clear()
            os.environ.update(old)
            mp.mt5_rates_cache_clear()


class TestSpreadPoints(unittest.TestCase):
    def setUp(self) -> None:
        _ensure_project_root()

    def test_spread_points_from_tick_calculates_points(self) -> None:
        import mt5_prices as mp

        class Tick:
            bid = 2600.0
            ask = 2600.35

        class Info:
            point = 0.01

        with patch.object(mp.mt5, "symbol_info_tick", return_value=Tick()), patch.object(
            mp.mt5, "symbol_info", return_value=Info()
        ):
            self.assertEqual(mp.spread_points_from_tick("XAUUSD"), 35)

    def test_spread_points_none_when_tick_missing(self) -> None:
        import mt5_prices as mp

        with patch.object(mp.mt5, "symbol_info_tick", return_value=None), patch.object(
            mp.mt5, "symbol_info", return_value=None
        ):
            self.assertIsNone(mp.spread_points_from_tick("X"))

    def test_es_spread_valido_disabled_when_limit_zero(self) -> None:
        import mt5_prices as mp

        self.assertTrue(mp.es_spread_valido("ANY", 0))
        self.assertTrue(mp.es_spread_valido("ANY", -1))


class TestEveningEnv(unittest.TestCase):
    def setUp(self) -> None:
        _ensure_project_root()

    def test_safe_evening_int(self) -> None:
        import os

        import evening_signal as es

        old = dict(os.environ)
        try:
            os.environ["TEST_EVENING_H"] = "not_an_int"
            self.assertEqual(es._safe_evening_int("TEST_EVENING_H", 21), 21)
            os.environ["TEST_EVENING_H"] = "22"
            self.assertEqual(es._safe_evening_int("TEST_EVENING_H", 21), 22)
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
