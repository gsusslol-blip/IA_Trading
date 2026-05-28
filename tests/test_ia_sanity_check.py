"""Tests ia_sanity_check (sin MT5)."""

from __future__ import annotations

import unittest


class TestSanityCheck(unittest.TestCase):
    def test_max_latency_default(self) -> None:
        from ia_sanity_check import _max_mt5_latency_ms

        self.assertEqual(_max_mt5_latency_ms(), 50.0)

    def test_python_version_gate(self) -> None:
        import sys

        self.assertGreaterEqual(sys.version_info[:2], (3, 8))


if __name__ == "__main__":
    unittest.main()
