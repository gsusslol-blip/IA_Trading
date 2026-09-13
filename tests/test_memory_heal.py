"""Atomic memory.json recover."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.memory import Memory


class MemoryHealTests(unittest.TestCase):
    def test_recovers_from_bak(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "memory.json"
            bak = Path(raw) / "memory.json.bak"
            bak.write_text('{"facts": {"ciudad": "Córdoba"}, "notes": [], "reminders": []}', encoding="utf-8")
            path.write_text("{not-json", encoding="utf-8")
            mem = Memory(path)
            self.assertTrue(mem.recovered)
            self.assertIn("Córdoba", mem.recall("ciudad"))

    def test_atomic_save_writes_bak(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "memory.json"
            mem = Memory(path)
            mem.remember("mascota", "lola")
            bak = Path(raw) / "memory.json.bak"
            self.assertTrue(bak.is_file())
            self.assertIn("lola", bak.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
