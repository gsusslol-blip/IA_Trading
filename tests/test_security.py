"""Sandbox paths and secret redaction."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.security import redact_secrets, safe_under


class SafeUnderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="ilaria-sandbox-")
        self.root = Path(self.tmp.name) / "workspace"
        self.root.mkdir()
        (self.root / "ok.txt").write_text("hi", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_inside_ok(self) -> None:
        path = safe_under(self.root, "ok.txt")
        self.assertEqual(path, (self.root / "ok.txt").resolve())

    def test_nested_ok(self) -> None:
        dest = safe_under(self.root, "sub/a.txt")
        self.assertTrue(str(dest).startswith(str(self.root.resolve())))

    def test_dotdot_blocked(self) -> None:
        with self.assertRaises(ValueError):
            safe_under(self.root, "../secret.txt")
        with self.assertRaises(ValueError):
            safe_under(self.root, "foo/../../etc/passwd")

    def test_absolute_blocked(self) -> None:
        with self.assertRaises(ValueError):
            safe_under(self.root, r"C:\Windows\win.ini")
        with self.assertRaises(ValueError):
            safe_under(self.root, "/etc/passwd")


class RedactTests(unittest.TestCase):
    def test_exact_and_patterns(self) -> None:
        token = "ha-secret-token-value-12345"
        text = f"token={token} cookie jarvis_sid=abc_DEF-99 Bearer abcdefghijklmnop gsk_{'a' * 32}"
        out = redact_secrets(text, extra=(token,))
        self.assertNotIn(token, out)
        self.assertNotIn("jarvis_sid=abc", out)
        self.assertIn("[SECRET_REDACTED]", out)
        self.assertNotIn("gsk_" + "a" * 8, out)


if __name__ == "__main__":
    unittest.main()
