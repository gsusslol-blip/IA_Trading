"""PriceEngine sin terminal MT5."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestPriceEngine(unittest.TestCase):
    def setUp(self) -> None:
        r = str(_root())
        if r not in sys.path:
            sys.path.insert(0, r)

    def tearDown(self) -> None:
        import mt5_price_engine as pe

        pe.reset_price_engine()

    def test_get_data_returns_empty_when_no_rates(self) -> None:
        import mt5_price_engine as pe

        with patch("mt5_price_engine.get_rates_optimized", return_value=None):
            df = pe.get_price_engine().get_data("X", 15, 10)
            self.assertTrue(df.empty)

    def test_m15_closed_trigger_rows_requires_length(self) -> None:
        import pandas as pd

        import mt5_price_engine as pe

        self.assertIsNone(pe.m15_closed_trigger_rows(pd.DataFrame()))
        self.assertIsNone(pe.m15_closed_trigger_rows(pd.DataFrame({"close": [1, 2]})))
        df = pd.DataFrame({"close": [1, 2, 3, 4]})
        row = pe.m15_closed_trigger_rows(df)
        self.assertIsNotNone(row)
        assert row is not None
        a, b = row
        self.assertEqual(int(a["close"]), 3)
        self.assertEqual(int(b["close"]), 2)


if __name__ == "__main__":
    unittest.main()
