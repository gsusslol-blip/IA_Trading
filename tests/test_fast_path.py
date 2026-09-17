"""Fast-path router — zero LLM for mechanical commands."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.brain_parser import match_fast_path, try_fast_path
from jarvis.fast_path import match_fast_path as match_fp
from jarvis.personality import split_system_prompt


class FastPathTests(unittest.TestCase):
    def test_volume_match(self) -> None:
        hit = match_fast_path("volumen al 30")
        self.assertIsNotNone(hit)
        assert hit is not None
        tool, params, rule = hit
        self.assertEqual(tool, "set_volume")
        self.assertEqual(params.get("level"), 30)
        self.assertEqual(rule, "volume_level")

    def test_volume_spoken_variants(self) -> None:
        for phrase in (
            "poné el volumen al 45",
            "volumen a 20%",
            "volumen al 50 por favor",
            "hey ilaria, volumen al 35!",
        ):
            hit = match_fp(phrase)
            self.assertIsNotNone(hit, phrase)
            assert hit is not None
            self.assertEqual(hit[0], "set_volume")
            self.assertIn(hit[1].get("level"), {20, 35, 45, 50})

    def test_mute_and_media(self) -> None:
        self.assertEqual(match_fp("silenciá")[0], "media")  # type: ignore[index]
        self.assertEqual(match_fp("siguiente")[0], "media")  # type: ignore[index]
        self.assertEqual(match_fp("pause")[0], "media")  # type: ignore[index]

    def test_wake_prefix_stripped(self) -> None:
        hit = match_fp("hey ilaria volumen al 40")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit[1].get("level"), 40)

    def test_kitchen_list(self) -> None:
        hit = match_fast_path("listá mis recetas")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit[0], "kitchen_recipe")
        self.assertEqual(hit[1].get("action"), "listar")

    def test_watch(self) -> None:
        hit = match_fast_path("leer el reloj")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit[0], "wellness_action")

    def test_ambiguous_falls_through(self) -> None:
        self.assertIsNone(match_fast_path("qué pensás del clima político"))

    def test_execute_under_50ms(self) -> None:
        calls: list[tuple[str, str]] = []

        def execute(tool: str, args: str) -> str:
            calls.append((tool, args))
            return "ok volumen"

        t0 = time.perf_counter()
        out = try_fast_path("volumen al 25", execute)
        ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(out, "ok volumen")
        self.assertEqual(calls[0][0], "set_volume")
        self.assertLess(ms, 50.0)

    def test_split_prompt_static_stable(self) -> None:
        settings = MagicMock()
        settings.timezone = "America/Argentina/Buenos_Aires"
        settings.assistant_name = "Ilaria"
        settings.user_name = "gsuss"
        memory = MagicMock()
        memory.as_prompt.return_value = "team=river"
        memory.recall.return_value = "No fact"
        actions = MagicMock()
        actions.system_status.return_value = "ok"
        actions.journal_context.return_value = "nada"
        actions.capabilities.return_value = "tools..."
        a, live_a = split_system_prompt(
            settings, memory, actions, is_owner=True, lean=True, user_message="hola"
        )
        b, live_b = split_system_prompt(
            settings, memory, actions, is_owner=True, lean=True, user_message="chau"
        )
        self.assertEqual(a, b)
        self.assertIn("Current local datetime", live_a)
        self.assertIn("Current local datetime", live_b)


if __name__ == "__main__":
    unittest.main()
