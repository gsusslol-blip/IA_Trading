"""Passive heal + Android compat tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.client_compat import android_upgrade_hint
from jarvis.passive_heal import classify_llm_fault, on_llm_exception, reset_for_tests
from jarvis.pc_updater import load_manifest


class PassiveHealTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_for_tests()

    def test_classify(self) -> None:
        self.assertEqual(classify_llm_fault(TimeoutError("timed out")), "timeout")
        self.assertEqual(classify_llm_fault(RuntimeError("HTTP 503")), "http_5xx")
        self.assertEqual(classify_llm_fault(ConnectionError("connection refused")), "connection")
        self.assertIsNone(classify_llm_fault(ValueError("bad json")))

    def test_on_llm_cooldown(self) -> None:
        class S:
            ollama_base_url = "http://127.0.0.1:11434/v1"

        with patch("jarvis.passive_heal.ensure_ollama", return_value="lanzado") as mocked:
            first = on_llm_exception(S(), TimeoutError("timeout"))  # type: ignore[arg-type]
            second = on_llm_exception(S(), TimeoutError("timeout"))  # type: ignore[arg-type]
        self.assertEqual(first["status"], "healed")
        self.assertEqual(second["status"], "cooldown")
        self.assertEqual(mocked.call_count, 1)


class CompatTests(unittest.TestCase):
    def test_upgrade_hint(self) -> None:
        with patch("jarvis.client_compat.min_required_android_client", return_value="1.5.4"):
            hint = android_upgrade_hint({"app_version": "1.4.0"})
            self.assertIn("Play Store", hint)
            self.assertEqual(android_upgrade_hint({"app_version": "1.5.4"}), "")

    def test_manifest_download_url(self) -> None:
        man = load_manifest(
            {
                "version": "1.5.1",
                "download_url": "https://example.com/x.zip",
                "sha256": "abc",
                "changelog": ["a", "b"],
                "min_required_android_client": "1.5.4",
            }
        )
        self.assertEqual(man.zip_url, "https://example.com/x.zip")
        self.assertEqual(man.changelog, ("a", "b"))
        self.assertEqual(man.min_required_android_client, "1.5.4")


if __name__ == "__main__":
    unittest.main()
