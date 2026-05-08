"""Helpers MT5 con mocks (sin terminal)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def _ensure_project_root() -> None:
    root = Path(__file__).resolve().parent.parent
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)


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
