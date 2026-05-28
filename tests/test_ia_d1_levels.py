"""Tests ia_d1_levels (caché sin MT5)."""

from __future__ import annotations

import os
import time
import unittest


class TestD1Levels(unittest.TestCase):
    def test_cache_hit_without_mt5(self) -> None:
        from ia_d1_levels import high_low_ayer_d1, invalidate_d1_levels

        invalidate_d1_levels()
        os.environ["IA_D1_LEVELS_CACHE_TTL_S"] = "300"
        import ia_d1_levels as mod

        mod._CACHE["XAUUSD"] = ((2650.0, 2600.0), time.time())
        hl = high_low_ayer_d1("XAUUSD")
        self.assertEqual(hl, (2650.0, 2600.0))
        invalidate_d1_levels("XAUUSD")


if __name__ == "__main__":
    unittest.main()
