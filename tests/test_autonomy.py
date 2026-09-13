"""Autonomy policy and local RAG — no live Ollama."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.autonomy import _last_fire, decide
from jarvis.memory import Memory
from jarvis.rag import format_for_prompt, retrieve
from jarvis.tts import child_speech_pacing


class AutonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        _last_fire.clear()
        import jarvis.autonomy as auto

        auto._heavy_since = None
    def test_member_never_acts(self) -> None:
        self.assertIsNone(
            decide({"is_owner": False, "ram_pct": 99, "status": "Steam", "ha": ""}, who="Luis")
        )

    def test_hot_ram_owner(self) -> None:
        hit = decide(
            {"is_owner": True, "ram_pct": 90, "status": "Steam", "ha": ""},
            who="pá",
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.kind, "hot_pc")
        self.assertIn("RAM", hit.line)

    def test_no_light_without_occupancy(self) -> None:
        hit = decide(
            {
                "is_owner": True,
                "ram_pct": 20,
                "status": "",
                "ha": "light.living: off",
            },
            who="pá",
        )
        self.assertIsNone(hit)


class RagTests(unittest.TestCase):
    def test_retrieves_note(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            mem = Memory(folder / "memory.json")
            mem.add_note("comprar leche para el desayuno")
            (folder / "workspace").mkdir()
            (folder / "workspace" / "lista.txt").write_text("leche y pan", encoding="utf-8")
            hits = retrieve("leche", mem, folder / "workspace", k=3)
            self.assertTrue(hits)
            blob = format_for_prompt(hits)
            self.assertIn("leche", blob.lower())


class TtsPacingTests(unittest.TestCase):
    def test_hola_pa_pause(self) -> None:
        out = child_speech_pacing("Hola pá qué hacemos hoy")
        self.assertIn("...", out)


if __name__ == "__main__":
    unittest.main()
