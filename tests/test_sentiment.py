"""Tests de sentiment_news (sin red si no hay NEWS_API_KEY)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestSentimentNews(unittest.TestCase):
    def setUp(self) -> None:
        r = str(_root())
        if r not in sys.path:
            sys.path.insert(0, r)

    def test_veredicto_neutral_sin_textblob_o_fallback(self) -> None:
        import sentiment_news as sn

        # Polaridad acotada
        p = sn.analizar_sentimiento_noticias("XAUUSD-ECN")
        self.assertGreaterEqual(p, -1.0)
        self.assertLessEqual(p, 1.0)

        v = sn.obtener_veredicto_final("XAUUSD", verbose=False)
        self.assertIn(v, ("SOLO_COMPRAS", "SOLO_VENTAS", "NEUTRAL"))

    def test_sentiment_allows_hold(self) -> None:
        import sentiment_news as sn

        self.assertTrue(sn.sentiment_allows_trade("X", "Sin señal clara"))

    def test_analizar_sentimiento_basico_valores(self) -> None:
        import sentiment_news as sn

        v = sn.analizar_sentimiento_basico("XAUUSD")
        self.assertIn(v, ("ALCISTA", "BAJISTA"))


if __name__ == "__main__":
    unittest.main()
