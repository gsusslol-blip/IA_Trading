"""PC local routing must fire without waiting for the LLM."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.config import Settings
from jarvis.llm import looks_like_cloud_model, resolve_llm
from jarvis.local import try_local_command
from jarvis.memory import Memory


def _settings(**kwargs: object) -> Settings:
    base = dict(
        groq_api_key="gsk_test",
        openai_api_key="",
        gemini_api_key="",
        llm_provider="auto",
        telegram_bot_token="",
        telegram_user_id=None,
        hud_host="127.0.0.1",
        hud_port=8787,
        assistant_name="Ilaria",
        user_name="gsuss",
        tts_voice="es-AR-ElenaNeural",
        timezone="America/Argentina/Buenos_Aires",
        llm_model="openai/gpt-oss-20b",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="",
        ha_url="",
        ha_token="",
        ollama_base_url="http://127.0.0.1:11434/v1",
        ollama_model="gemma2:2b",
    )
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


class PcActionsLocalTests(unittest.TestCase):
    def _run(self, text: str) -> list[tuple[str, dict]]:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        out = try_local_command(text, execute, Memory(), _settings(), surface="hud")
        self.assertIsNotNone(out)
        return captured

    def test_open_chrome(self) -> None:
        captured = self._run("abrí chrome")
        self.assertEqual(captured[0][0], "open_app")
        self.assertEqual(captured[0][1]["name"], "chrome")

    def test_quiero_que_abras(self) -> None:
        captured = self._run("quiero que abras notepad")
        self.assertEqual(captured[0][0], "open_app")

    def test_screenshot(self) -> None:
        captured = self._run("sacá una captura de pantalla")
        self.assertEqual(captured[0][0], "screenshot")

    def test_open_downloads(self) -> None:
        captured = self._run("abrí descargas")
        self.assertEqual(captured[0][0], "open_folder")
        self.assertEqual(captured[0][1]["name"], "descargas")

    def test_mute_without_volumen_word(self) -> None:
        captured = self._run("mute")
        self.assertEqual(captured[0][0], "media")
        self.assertEqual(captured[0][1]["action"], "mute")
        captured2 = self._run("silenciar")
        self.assertEqual(captured2[0][0], "media")

    def test_restart_needs_pc_word(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        out = try_local_command(
            "reiniciá el flujo",
            execute,
            Memory(),
            _settings(),
            surface="hud",
        )
        self.assertIsNone(out)
        self.assertEqual(captured, [])

    def test_cloud_model_detection(self) -> None:
        self.assertTrue(looks_like_cloud_model("openai/gpt-oss-20b"))
        self.assertFalse(looks_like_cloud_model("gemma2:2b"))

    def test_auto_prefers_groq_when_llm_model_is_cloud(self) -> None:
        settings = _settings()
        with patch("jarvis.llm._ollama_reachable", return_value=True):
            ep = resolve_llm(settings)
        self.assertEqual(ep.label, "groq")
        self.assertIn("gpt-oss", ep.model)


if __name__ == "__main__":
    unittest.main()
