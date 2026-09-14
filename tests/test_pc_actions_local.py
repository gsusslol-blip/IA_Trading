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
        self.assertIsNotNone(out, msg=f"no local hit for: {text!r}")
        return captured

    def test_open_chrome(self) -> None:
        captured = self._run("abrí chrome")
        self.assertEqual(captured[0][0], "open_app")
        self.assertEqual(captured[0][1]["name"], "chrome")

    def test_bare_app_name(self) -> None:
        captured = self._run("calculadora")
        self.assertEqual(captured[0][0], "open_app")

    def test_youtube_opens_browser(self) -> None:
        captured = self._run("abrí youtube")
        self.assertEqual(captured[0][0], "open_browser")
        self.assertIn("youtube.com", captured[0][1]["url"])

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

    def test_volume_up_down(self) -> None:
        up = self._run("subi el volumen")
        self.assertEqual(up[0], ("media", {"action": "vol_up"}))
        down = self._run("baja el volumen")
        self.assertEqual(down[0], ("media", {"action": "vol_down"}))

    def test_media_next_uses_vk_name(self) -> None:
        captured = self._run("siguiente cancion")
        self.assertEqual(captured[0], ("media", {"action": "next"}))
        pause = self._run("pausa")
        self.assertEqual(pause[0], ("media", {"action": "play_pause"}))

    def test_clipboard_set_and_get(self) -> None:
        set_c = self._run("copia hola mundo")
        self.assertEqual(set_c[0][0], "set_clipboard")
        self.assertEqual(set_c[0][1]["text"], "hola mundo")
        get_c = self._run("que hay en el portapapeles")
        self.assertEqual(get_c[0][0], "get_clipboard")

    def test_whatsapp_draft(self) -> None:
        captured = self._run("whatsapp a 5491112345678: llegue")
        self.assertEqual(captured[0][0], "compose_whatsapp")
        self.assertEqual(captured[0][1]["phone"], "5491112345678")
        self.assertIn("llegue", captured[0][1]["text"])

    def test_lock_pc(self) -> None:
        captured = self._run("bloquea la pc")
        self.assertEqual(captured[0], ("power_control", {"action": "lock"}))

    def test_translate(self) -> None:
        captured = self._run("traduci hello world")
        self.assertEqual(captured[0][0], "open_browser")
        self.assertIn("translate.google.com", captured[0][1]["url"])

    def test_youtube_search(self) -> None:
        captured = self._run("busca en youtube cerati")
        self.assertEqual(captured[0][0], "play_music")
        self.assertEqual(captured[0][1]["platform"], "youtube")

    def test_timer_recordame(self) -> None:
        captured = self._run("recordame en 5 minutos de sacar la pizza")
        self.assertEqual(captured[0][0], "set_timer")
        self.assertEqual(captured[0][1]["minutes"], 5.0)

    def test_workspace_list(self) -> None:
        captured = self._run("lista los archivos")
        self.assertEqual(captured[0][0], "list_files")

    def test_raw_url(self) -> None:
        captured = self._run("https://example.com/x")
        self.assertEqual(captured[0][0], "open_browser")

    def test_restart_needs_pc_word(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        out = try_local_command(
            "reinicia el flujo",
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

    def test_auto_prefers_groq_over_small_ollama_when_key_exists(self) -> None:
        settings = _settings(llm_model="")
        with patch("jarvis.llm._ollama_reachable", return_value=True):
            ep = resolve_llm(settings)
        self.assertEqual(ep.label, "groq")

    def test_auto_uses_ollama_when_llm_model_is_local_tag(self) -> None:
        settings = _settings(llm_model="gemma2:2b", groq_api_key="gsk_test")
        with patch("jarvis.llm._ollama_reachable", return_value=True):
            ep = resolve_llm(settings)
        self.assertEqual(ep.label, "ollama")
        self.assertEqual(ep.model, "gemma2:2b")

    def test_phone_volume_uses_phone_hands(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        out = try_local_command(
            "volumen al 40",
            execute,
            Memory(),
            _settings(),
            surface="android",
        )
        self.assertIsNotNone(out)
        self.assertEqual(captured[0][0], "phone_hands")
        self.assertEqual(captured[0][1]["action"], "volume")
        self.assertEqual(captured[0][1]["target"], "40")

    def test_ios_surface_same_as_android(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        out = try_local_command(
            "abrí spotify",
            execute,
            Memory(),
            _settings(),
            surface="ios",
        )
        self.assertIsNotNone(out)
        self.assertEqual(captured[0][0], "phone_hands")



if __name__ == "__main__":
    unittest.main()
