"""Tests ia_welcome (sin MT5)."""

from __future__ import annotations

import os
import unittest


class TestIaWelcome(unittest.TestCase):
    def test_welcome_enabled_default(self) -> None:
        from ia_welcome import welcome_enabled

        os.environ.pop("IA_WELCOME_ENABLE", None)
        self.assertTrue(welcome_enabled())

    def test_fmt_money(self) -> None:
        from ia_welcome import _fmt_money

        self.assertIn("10,000.00", _fmt_money(10000, "USD"))


if __name__ == "__main__":
    unittest.main()
