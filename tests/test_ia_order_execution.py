"""Tests ia_order_execution (sin MT5: solo parseo de preferencias)."""

from __future__ import annotations

import os
import unittest


class TestOrderExecution(unittest.TestCase):
    def test_parse_preference(self) -> None:
        from ia_order_execution import _parse_preference_list

        lst = _parse_preference_list("ioc,fok,return")
        self.assertEqual(len(lst), 3)


if __name__ == "__main__":
    unittest.main()
