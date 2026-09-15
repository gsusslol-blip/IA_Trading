"""Local command routing for Android hands."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.config import load_settings
from jarvis.local import try_local_command
from jarvis.memory import Memory


class LocalPhoneTests(unittest.TestCase):
    def test_open_spotify_on_android_queues_phone_hands(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        try_local_command(
            "abrí spotify",
            execute,
            Memory(),
            load_settings(),
            surface="android",
        )
        self.assertEqual(captured[0][0], "phone_hands")
        self.assertEqual(captured[0][1]["action"], "open_app")
        self.assertEqual(captured[0][1]["target"], "spotify")

    def test_open_spotify_on_pc_uses_open_app(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        try_local_command(
            "abrí spotify",
            execute,
            Memory(),
            load_settings(),
            surface="hud",
        )
        self.assertEqual(captured[0][0], "open_app")
        self.assertEqual(captured[0][1]["name"], "spotify")

    def test_open_any_app_on_android(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        try_local_command(
            "abrí tiktok",
            execute,
            Memory(),
            load_settings(),
            surface="android",
        )
        self.assertEqual(captured[0][0], "phone_hands")
        self.assertEqual(captured[0][1]["target"], "tiktok")

    def test_refuses_bank_on_android(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        out = try_local_command(
            "abrí mercado pago",
            execute,
            Memory(),
            load_settings(),
            surface="android",
        )
        self.assertIn("bancarias", out or "")
        self.assertEqual(captured, [])

    def test_play_song_on_android_uses_music(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        try_local_command(
            "reproducí cerati",
            execute,
            Memory(),
            load_settings(),
            surface="android",
        )
        self.assertEqual(captured[0][0], "phone_hands")
        self.assertEqual(captured[0][1]["action"], "music")
        self.assertEqual(captured[0][1]["target"], "cerati")

    def test_poneme_song_not_open_app(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        try_local_command(
            "poneme bohemian rhapsody",
            execute,
            Memory(),
            load_settings(),
            surface="android",
        )
        self.assertEqual(captured[0][1]["action"], "music")
        self.assertIn("bohemian", captured[0][1]["target"])

    def test_play_on_youtube_android(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        try_local_command(
            "poneme cerati en youtube",
            execute,
            Memory(),
            load_settings(),
            surface="android",
        )
        self.assertEqual(captured[0][1]["action"], "youtube")
        self.assertEqual(captured[0][1]["target"], "cerati")

    def test_maps_on_ios_uses_phone_hands(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        try_local_command(
            "cómo llego a Palermo",
            execute,
            Memory(),
            load_settings(),
            surface="ios",
        )
        self.assertEqual(captured[0][0], "phone_hands")
        self.assertEqual(captured[0][1]["action"], "maps")
        self.assertIn("Palermo", captured[0][1]["target"])

    def test_https_on_phone_opens_browser_action(self) -> None:
        captured: list[tuple[str, dict]] = []

        def execute(name: str, arguments_json: str) -> str:
            captured.append((name, json.loads(arguments_json)))
            return "OK"

        try_local_command(
            "https://example.com",
            execute,
            Memory(),
            load_settings(),
            surface="android",
        )
        self.assertEqual(captured[0][0], "phone_hands")
        self.assertEqual(captured[0][1]["action"], "browser")


if __name__ == "__main__":
    unittest.main()
