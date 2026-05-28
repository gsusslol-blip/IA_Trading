"""Tests ia_filesystem (sin MT5)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TestIaFilesystem(unittest.TestCase):
    def test_ensure_csv_creates_once(self) -> None:
        from ia_filesystem import _EXEC_QUALITY_HEADERS, _ensure_csv

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "execution_quality.csv"
            self.assertTrue(_ensure_csv(p, _EXEC_QUALITY_HEADERS))
            self.assertTrue(p.is_file())
            self.assertFalse(_ensure_csv(p, _EXEC_QUALITY_HEADERS))


if __name__ == "__main__":
    unittest.main()
