"""Tests ia_audit_logger (sin MT5)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class TestAuditLogger(unittest.TestCase):
    def test_inicializar_csv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "trade_audit_ml.csv"
            os.environ["IA_ML_AUDIT_CSV"] = str(p)
            from ia_audit_logger import inicializar_csv_auditoria

            out = inicializar_csv_auditoria()
            self.assertTrue(out.is_file())
            head = out.read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("spread_pts", head)
            self.assertIn("resultado", head)


if __name__ == "__main__":
    unittest.main()
