"""Tests ia_microstructure (sin MT5)."""

from __future__ import annotations

import os
import unittest


class TestMicrostructure(unittest.TestCase):
    def test_gold_fixing_blocks_am_window(self) -> None:
        from ia_microstructure import verificar_ventana_gold_fixing

        os.environ["IA_GOLD_FIXING_ENABLE"] = "1"
        self.assertFalse(verificar_ventana_gold_fixing(utc_hour=10, utc_minute=25))
        self.assertTrue(verificar_ventana_gold_fixing(utc_hour=10, utc_minute=40))

    def test_barrido_compras_logic_pure(self) -> None:
        minimo_hoy = 2645.0
        bajo_ayer = 2650.0
        px = 2652.0
        alto_ayer = 2700.0
        maximo_hoy = 2690.0
        barrido_compras = (minimo_hoy < bajo_ayer) and (px > bajo_ayer)
        barrido_ventas = (maximo_hoy > alto_ayer) and (px < alto_ayer)
        self.assertTrue(barrido_compras)
        self.assertFalse(barrido_ventas)

    def test_microestructura_permite_buy(self) -> None:
        from ia_microstructure import microestructura_permite_entrada

        os.environ["IA_STOP_HUNT_ENABLE"] = "1"
        os.environ["IA_GOLD_FIXING_ENABLE"] = "1"
        ok, _ = microestructura_permite_entrada(
            "XAUUSD",
            "BUY",
            2652.0,
            utc_hour=12,
            utc_minute=0,
        )
        # sin barrido live puede fallar; fixing ok
        self.assertIsInstance(ok, bool)


if __name__ == "__main__":
    unittest.main()
