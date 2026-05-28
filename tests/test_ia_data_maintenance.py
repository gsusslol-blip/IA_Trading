"""Tests ia_data_maintenance (sin MT5)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone


class TestDataMaintenance(unittest.TestCase):
    def test_not_saturday_hour(self) -> None:
        from ia_data_maintenance import debe_ejecutar_mantenimiento_sabado

        os.environ["IA_DATA_MAINTENANCE_ENABLE"] = "1"
        mon = datetime(2025, 5, 19, 1, 0, tzinfo=timezone.utc)
        self.assertFalse(debe_ejecutar_mantenimiento_sabado(mon))


if __name__ == "__main__":
    unittest.main()
