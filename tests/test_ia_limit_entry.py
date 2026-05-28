"""Tests ia_limit_entry (sin MT5)."""

from __future__ import annotations

import unittest


class TestLimitEntry(unittest.TestCase):
    def test_discount_buy_below_close(self) -> None:
        from ia_limit_entry import _atr_discount

        disc = _atr_discount()
        px = 2650.0 - 10.0 * disc
        self.assertLess(px, 2650.0)
        self.assertAlmostEqual(px, 2650.0 - 1.5, places=1)


if __name__ == "__main__":
    unittest.main()
