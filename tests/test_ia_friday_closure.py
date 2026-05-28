"""Tests ia_friday_closure (sin MT5)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone


class TestFridayClosure(unittest.TestCase):
    def test_friday_window_1930_utc(self) -> None:
        from ia_friday_closure import en_ventana_cierre_viernes_utc

        os.environ["IA_FRIDAY_CLOSE_UTC_HOUR"] = "19"
        os.environ["IA_FRIDAY_CLOSE_UTC_MINUTE"] = "30"
        dt_ok = datetime(2025, 5, 16, 19, 45, tzinfo=timezone.utc)
        dt_early = datetime(2025, 5, 16, 18, 0, tzinfo=timezone.utc)
        self.assertTrue(en_ventana_cierre_viernes_utc(dt_ok))
        self.assertFalse(en_ventana_cierre_viernes_utc(dt_early))


if __name__ == "__main__":
    unittest.main()
