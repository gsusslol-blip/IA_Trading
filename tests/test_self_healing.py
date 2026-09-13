"""Self-healing diagnose helpers — no live Ollama required."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.config import load_settings
from jarvis.self_healing import check_lan_status, get_system_health, relaunch_service
from jarvis.tools import ALL_TOOL_NAMES, OWNER_ONLY_TOOLS


class SelfHealingToolsTests(unittest.TestCase):
    def test_tools_registered(self) -> None:
        self.assertIn("get_system_health", ALL_TOOL_NAMES)
        self.assertIn("relaunch_service", ALL_TOOL_NAMES)
        self.assertIn("check_lan_status", ALL_TOOL_NAMES)
        self.assertIn("relaunch_service", OWNER_ONLY_TOOLS)

    def test_health_shape(self) -> None:
        settings = load_settings()
        report = get_system_health(settings)
        self.assertIn("ollama_alive", report)
        self.assertIn("piper_ready", report)
        self.assertIn("udp_discover_bound", report)
        self.assertIn("resource_usage", report)
        self.assertIsInstance(report["recent_logs"], list)

    def test_lan_shape(self) -> None:
        settings = load_settings()
        lan = check_lan_status(settings)
        self.assertIn("local_ip", lan)
        self.assertIn("udp_discover_bound", lan)
        self.assertEqual(lan["udp_port"], 8788)

    def test_relaunch_rejects_unknown(self) -> None:
        settings = load_settings()
        out = relaunch_service(settings, "cmd.exe")
        self.assertFalse(out["ok"])

    def test_relaunch_piper_uses_reset(self) -> None:
        settings = load_settings()
        with mock.patch("jarvis.piper_tts.reset_piper_session") as reset:
            with mock.patch("jarvis.piper_tts.piper_available", return_value=True):
                out = relaunch_service(settings, "piper")
        reset.assert_called_once()
        self.assertTrue(out["ok"])
        self.assertEqual(out["service"], "piper")

    def test_health_json_roundtrip(self) -> None:
        settings = load_settings()
        raw = json.dumps(get_system_health(settings))
        self.assertTrue(json.loads(raw))


if __name__ == "__main__":
    unittest.main()
