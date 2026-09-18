"""Long-term memory condenser — deterministic diary → JSON."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.memory_condenser import (
    condense_day,
    extract_milestones,
    format_long_term_prompt,
    merge_facts,
    normalize_fact,
)
from jarvis.personality import split_system_prompt


class MemoryCondenserTests(unittest.TestCase):
    def test_extract_prefers_milestones(self) -> None:
        blob = (
            "[10:00] hola qué tal\n"
            "[11:00] Hoy empecé la dieta alta en proteína\n"
            "[12:00] ping\n"
            "[18:00] Compré la RAM de 32GB para la PC\n"
            "[19:00] Decidí no tocar Telegram por ahora\n"
            "[20:00] otra línea corta\n"
        )
        hits = extract_milestones(blob, limit=3)
        self.assertEqual(len(hits), 3)
        joined = " | ".join(hits).lower()
        self.assertIn("dieta", joined)
        self.assertIn("ram", joined)
        self.assertIn("telegram", joined)

    def test_dedupe_and_cap(self) -> None:
        existing = [
            {
                "text": "Compré la RAM de 32GB",
                "norm": normalize_fact("Compré la RAM de 32GB"),
                "source_day": "2026-01-01",
                "added_at": 1.0,
            }
        ]
        merged, added = merge_facts(
            existing,
            ["Compré la RAM de 32GB!!!", "Empecé yoga a la mañana"],
            source_day="2026-01-02",
            cap=5,
        )
        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)

    def test_condense_day_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "diario_2026-09-16.txt").write_text(
                "[09:00] Empecé el rodaje duro de Ilaria\n"
                "[15:00] Configuré NGROK_AUTHTOKEN en el .env\n"
                "[21:00] café\n",
                encoding="utf-8",
            )
            result = condense_day(ws, "2026-09-16")
            self.assertEqual(result["status"], "ok")
            self.assertGreaterEqual(result["added"], 1)
            store = json.loads((ws / "long_term_memory.json").read_text(encoding="utf-8"))
            self.assertTrue(store["facts"])
            prompt = format_long_term_prompt(ws)
            self.assertIn("Long-term milestones", prompt)
            # Second run same day still marks last_run; re-extract but dedupe → 0 added
            again = condense_day(ws, "2026-09-16")
            self.assertEqual(again["added"], 0)

    def test_static_prompt_includes_ltm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "long_term_memory.json").write_text(
                json.dumps(
                    {
                        "facts": [
                            {
                                "text": "Empecé dieta alta en proteína",
                                "norm": "empecé dieta alta en proteína",
                                "source_day": "2026-09-01",
                                "added_at": 1.0,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            settings = MagicMock()
            settings.timezone = "America/Argentina/Buenos_Aires"
            settings.assistant_name = "Ilaria"
            settings.user_name = "gsuss"
            memory = MagicMock()
            memory.as_prompt.return_value = "- ciudad: CABA"
            memory.recall.return_value = "No fact"
            actions = MagicMock()
            actions.workspace = ws
            actions.system_status.return_value = "ok"
            actions.journal_context.return_value = "nada"
            actions.capabilities.return_value = "tools..."
            static, _live = split_system_prompt(
                settings, memory, actions, is_owner=True, lean=True, user_message="hola"
            )
            self.assertIn("dieta", static.lower())


if __name__ == "__main__":
    unittest.main()
