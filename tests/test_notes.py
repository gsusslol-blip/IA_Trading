"""Notes sync payload — JSON on PC, REST for Android later."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.memory import Memory


class NotesSyncTests(unittest.TestCase):
    def test_legacy_strings_become_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "memory.json"
            path.write_text('{"facts": {}, "reminders": [], "notes": ["leche"]}', encoding="utf-8")
            mem = Memory(path)
            export = mem.notes_export()
            self.assertEqual(export["notes"], ["leche"])
            self.assertEqual(export["items"][0]["text"], "leche")
            self.assertTrue(export["items"][0]["id"])

    def test_merge_last_write_wins(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            mem = Memory(Path(raw) / "memory.json")
            mem.add_note("vieja")
            nid = mem.notes_records()[0]["id"]
            mem.merge_notes(
                [{"id": nid, "text": "nueva", "updated": 9_999_999_999}],
                client_rev=0,
            )
            self.assertEqual(mem.notes_items(), ["nueva"])
            self.assertGreater(mem.notes_rev(), 0)

    def test_merge_facts_from_phone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            mem = Memory(Path(raw) / "memory.json")
            mem.remember("ciudad", "Córdoba")
            merged = mem.merge_facts({"mascota": "Luna"})
            self.assertEqual(merged["ciudad"], "Córdoba")
            self.assertEqual(merged["mascota"], "Luna")


if __name__ == "__main__":
    unittest.main()
