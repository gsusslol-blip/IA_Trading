"""Tests ia_indicators (sin MT5)."""

from __future__ import annotations

import unittest


class TestIaIndicators(unittest.TestCase):
    def test_obtener_metricas_returns_tuple(self) -> None:
        # Sin MT5: fetch_rates devuelve None → escape 0.0
        from ia_indicators import obtener_metricas_ia

        adx, dist = obtener_metricas_ia("XAUUSD", buy=True)
        self.assertIsInstance(adx, float)
        self.assertIsInstance(dist, float)


if __name__ == "__main__":
    unittest.main()
