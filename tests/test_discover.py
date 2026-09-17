"""LAN UDP discovery payload."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.discover import ACK_SIMPLE, MAGIC, build_reply, parse_reply


class DiscoverTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        raw = build_reply("http://192.168.1.11:8787", "1.4.2")
        self.assertTrue(raw.startswith(MAGIC))
        self.assertEqual(parse_reply(raw), "http://192.168.1.11:8787")

    def test_rejects_noise(self) -> None:
        self.assertIsNone(parse_reply(b"hello"))
        self.assertIsNone(parse_reply(MAGIC + b"{bad"))

    def test_simple_ack_constant(self) -> None:
        self.assertEqual(ACK_SIMPLE, b"ILARIA_SERVER_ACK")
        from jarvis.discover import ACK_IOS, PROBE_IOS

        self.assertEqual(ACK_IOS, b"ILARIA_IOS_SERVER_ACK")
        self.assertEqual(PROBE_IOS, b"ILARIA_IOS_DISCOVER")

if __name__ == "__main__":
    unittest.main()
