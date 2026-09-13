"""Isolation + allowlist for Android maintenance queue."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.phone_hands import queue_phone_fix


class PhoneHealingTests(unittest.TestCase):
    def test_queue_phone_fix_success_and_isolation(self) -> None:
        queue_a: list = []
        queue_b: list = []
        res = queue_phone_fix(queue_a, "clear_http")
        self.assertEqual(res["status"], "QUEUED")
        self.assertEqual(res["action"], "clear_http")
        self.assertEqual(queue_a[0]["action"], "clear_http")
        self.assertEqual(queue_b, [])

    def test_queue_phone_fix_denied_action(self) -> None:
        queue: list = []
        res = queue_phone_fix(queue, "rm_rf_system")
        self.assertEqual(res["status"], "ERROR")
        self.assertEqual(queue, [])

    def test_wifi_and_settings_allowed(self) -> None:
        queue: list = []
        for action in (
            "open_wifi_settings",
            "open_app_settings",
            "refresh_device_snap",
        ):
            res = queue_phone_fix(queue, action)
            self.assertEqual(res["status"], "QUEUED", action)
        self.assertEqual(len(queue), 3)


if __name__ == "__main__":
    unittest.main()
