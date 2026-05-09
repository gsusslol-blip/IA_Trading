"""Rotación de CSV de auditoría por tamaño (ia_utils)."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class TestLogRotation(unittest.TestCase):
    def test_missing_file_noop(self) -> None:
        from ia_utils import rotar_log_por_tamaño

        self.assertFalse(rotar_log_por_tamaño(Path("/nonexistent/__ia__/log.csv"), max_mb=5))

    def test_max_mb_zero_skips(self) -> None:
        from ia_utils import rotar_log_por_tamaño

        with TemporaryDirectory() as d:
            p = Path(d) / "log.csv"
            p.write_text("x", encoding="utf-8")
            self.assertFalse(rotar_log_por_tamaño(p, max_mb=0))
            self.assertTrue(p.is_file())

    def test_rotates_when_over_limit(self) -> None:
        from ia_utils import rotar_log_por_tamaño

        with TemporaryDirectory() as d:
            p = Path(d) / "log.csv"
            p.write_text("hello\n", encoding="utf-8")
            self.assertTrue(rotar_log_por_tamaño(p, max_mb=1e-12))
            self.assertFalse(p.is_file())
            self.assertTrue((Path(d) / "log.csv.old").is_file())

    def test_replaces_previous_old(self) -> None:
        from ia_utils import rotar_log_por_tamaño

        with TemporaryDirectory() as d:
            p = Path(d) / "log.csv"
            old = Path(d) / "log.csv.old"
            old.write_text("stale", encoding="utf-8")
            p.write_text("newdata\n" * 100, encoding="utf-8")
            self.assertTrue(rotar_log_por_tamaño(p, max_mb=1e-12))
            self.assertFalse(p.is_file())
            self.assertIn("newdata", old.read_text(encoding="utf-8"))
            self.assertNotIn("stale", old.read_text(encoding="utf-8"))

    def test_execution_quality_max_mb_from_env(self) -> None:
        from ia_utils import execution_quality_max_mb_from_env

        with patch.dict(os.environ, {"IA_LOG_MAX_MB": "0"}, clear=False):
            self.assertEqual(execution_quality_max_mb_from_env(), 0.0)
        with patch.dict(os.environ, {"IA_LOG_MAX_MB": "", "IA_EXEC_LOG_MAX_MB": "2.5"}, clear=False):
            self.assertEqual(execution_quality_max_mb_from_env(), 2.5)


if __name__ == "__main__":
    unittest.main()
