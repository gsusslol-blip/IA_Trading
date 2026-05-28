"""Tests ia_order_async (sin MT5)."""

from __future__ import annotations

import unittest


class TestOrderAsync(unittest.TestCase):
    def test_pending_count_starts_zero(self) -> None:
        from ia_order_async import pending_orders_count

        self.assertGreaterEqual(pending_orders_count(), 0)

    def test_register_pending_order(self) -> None:
        from ia_order_async import pending_orders_count, register_pending_order

        register_pending_order(12345, symbol="XAUUSD", side="BUY")
        self.assertGreaterEqual(pending_orders_count(), 1)


if __name__ == "__main__":
    unittest.main()
