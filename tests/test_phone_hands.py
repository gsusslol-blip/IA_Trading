"""Phone intent queue sanitizer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.bank_apps import is_banking
from jarvis.phone_hands import queue_action


class PhoneHandsTests(unittest.TestCase):
    def test_call_strips_junk(self) -> None:
        q: list = []
        msg = queue_action(q, {"action": "call", "target": "+54 9 11-5555-1234"})
        self.assertTrue(msg.startswith("OK:"))
        self.assertEqual(q[0]["target"], "+5491155551234")

    def test_rejects_shell(self) -> None:
        q: list = []
        msg = queue_action(q, {"action": "shell", "target": "su"})
        self.assertIn("no permitida", msg)
        self.assertEqual(q, [])

    def test_open_app_alias(self) -> None:
        q: list = []
        queue_action(q, {"action": "open_app", "target": "whatsapp"})
        self.assertEqual(q[0]["target"], "com.whatsapp")

    def test_open_any_installed_name(self) -> None:
        q: list = []
        msg = queue_action(q, {"action": "open_app", "target": "calculadora"})
        self.assertTrue(msg.startswith("OK:"))
        self.assertEqual(q[0]["target"], "calculadora")

    def test_rejects_banking_apps(self) -> None:
        q: list = []
        msg = queue_action(q, {"action": "open_app", "target": "Mercado Pago"})
        self.assertIn("bancarias", msg)
        self.assertEqual(q, [])
        msg = queue_action(q, {"action": "open_app", "target": "com.galicia.galicia"})
        self.assertIn("bancarias", msg)

    def test_banking_detector(self) -> None:
        self.assertTrue(is_banking("Banco Galicia"))
        self.assertTrue(is_banking("uala"))
        self.assertFalse(is_banking("spotify"))
        self.assertFalse(is_banking("chrome"))


if __name__ == "__main__":
    unittest.main()
