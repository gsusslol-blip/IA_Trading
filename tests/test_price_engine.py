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

    def test_rates_df_time_as_unix_seconds_idempotent_int(self) -> None:
        import pandas as pd

        import mt5_price_engine as pe

        df = pd.DataFrame({"time": [100, 101], "close": [1.0, 2.0]})
        u = pe.rates_df_time_as_unix_seconds(df)
        self.assertIsNotNone(u)
        assert u is not None
        self.assertListEqual(list(u["time"]), [100, 101])

    def test_ensure_unix_time_from_mt5_prices_matches_engine_helper(self) -> None:
        import pandas as pd

        import mt5_price_engine as pe
        import mt5_prices as mp

        df = pd.DataFrame(
            {
                "time": pd.to_datetime(
                    ["2020-06-01T12:00:00+00:00"],
                    utc=True,
                ),
                "close": [1.5],
            }
        )
        u1 = mp.ensure_unix_time(df)
        u2 = pe.rates_df_time_as_unix_seconds(df)
        self.assertEqual(int(u1["time"].iloc[0]), int(u2["time"].iloc[0]))

    def test_ensure_unix_time_datetime_index(self) -> None:
        import pandas as pd

        import mt5_prices as mp

        idx = pd.DatetimeIndex(
            pd.to_datetime(["2020-01-01T00:00:00+00:00", "2020-01-01T01:00:00+00:00"]), tz="UTC"
        )
        df = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
        u = mp.ensure_unix_time(df)
        self.assertListEqual(["time", "close"], list(u.columns)[:2])
        self.assertEqual(int(u["time"].iloc[0]), 1_577_836_800)
        self.assertEqual(int(u["time"].iloc[1]), 1_577_840_400)

    def test_rates_df_time_as_unix_seconds_from_datetime(self) -> None:
        import pandas as pd

        import mt5_price_engine as pe

        df = pd.DataFrame(
            {
                "time": pd.to_datetime(
                    ["2020-01-01T00:00:00+00:00", "2020-01-01T00:15:00+00:00"],
                    utc=True,
                ),
                "close": [1.0, 2.0],
            }
        )
        u = pe.rates_df_time_as_unix_seconds(df)
        self.assertIsNotNone(u)
        assert u is not None
        self.assertEqual(int(u["time"].iloc[0]), 1_577_836_800)
        self.assertEqual(int(u["time"].iloc[1]), 1_577_837_700)


if __name__ == "__main__":
    unittest.main()
