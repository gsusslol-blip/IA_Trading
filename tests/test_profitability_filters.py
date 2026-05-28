"""Tests ia_profitability_filters (sin MT5)."""

from __future__ import annotations

import os
import unittest


class TestProfitabilityFilters(unittest.TestCase):
    def test_london_window(self) -> None:
        from ia_profitability_filters import sesion_utc_alta_rentabilidad

        self.assertTrue(sesion_utc_alta_rentabilidad(8))
        self.assertTrue(sesion_utc_alta_rentabilidad(14))
        self.assertFalse(sesion_utc_alta_rentabilidad(3))
        self.assertFalse(sesion_utc_alta_rentabilidad(22))

    def test_disabled_passes(self) -> None:
        from ia_profitability_filters import validar_ventana_alta_rentabilidad

        os.environ["IA_PROFIT_SESSION_ENABLE"] = "0"
        try:
            ok, _ = validar_ventana_alta_rentabilidad("XAUUSD", utc_hour=3)
            self.assertTrue(ok)
        finally:
            os.environ.pop("IA_PROFIT_SESSION_ENABLE", None)


if __name__ == "__main__":
    unittest.main()
