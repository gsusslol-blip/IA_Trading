"""Semantic search cache unit tests (offline)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.search_cache import format_hit, lookup, similarity, store


class SearchCacheTests(unittest.TestCase):
    def test_similar_queries_score_high(self) -> None:
        a = "como se hace la salsa caruso"
        b = "cómo se hace salsa caruso"
        self.assertGreaterEqual(similarity(a, b), 0.85)

    def test_unrelated_score_low(self) -> None:
        self.assertLess(similarity("dólar blue hoy", "receta de milanesas"), 0.5)

    def test_store_and_lookup_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            store("cómo se hace la salsa caruso", "Pasos: cebolla, crema, jamón…", ws, kind="web")
            hit = lookup("como se hace salsa caruso", ws, kind="web")
            self.assertIsNotNone(hit)
            assert hit is not None
            self.assertTrue(hit["cached"])
            self.assertIn("Pasos", format_hit(hit))

    def test_miss_when_different(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            store("clima en córdoba", "25 C soleado", ws, kind="web")
            self.assertIsNone(lookup("precio bitcoin", ws, kind="web"))


if __name__ == "__main__":
    unittest.main()
