"""Tests ia_paths."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class TestIaPaths(unittest.TestCase):
    def test_default_under_logs(self) -> None:
        from ia_paths import resolve_data_path

        p = resolve_data_path("IA_TEST_UNUSED_KEY_XYZ", "logs/foo.csv")
        self.assertIn("logs", p.parts)
        self.assertEqual(p.name, "foo.csv")

    def test_env_override(self) -> None:
        from ia_paths import resolve_data_path

        with tempfile.TemporaryDirectory() as td:
            custom = Path(td) / "custom.csv"
            os.environ["IA_ML_AUDIT_CSV"] = str(custom)
            try:
                p = resolve_data_path("IA_ML_AUDIT_CSV", "logs/trade_audit_ml.csv")
                self.assertEqual(p, custom)
            finally:
                os.environ.pop("IA_ML_AUDIT_CSV", None)


if __name__ == "__main__":
    unittest.main()
