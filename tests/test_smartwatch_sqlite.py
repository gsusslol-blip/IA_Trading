"""SQLite smartwatch history tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.smartwatch_processor import (
    append_metric_history,
    history_db_path,
    history_path,
    load_metric_history,
    escribir_metricas_demo,
    procesar_datos_smartwatch,
)


class SmartwatchSqliteTests(unittest.TestCase):
    def test_append_and_load_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.smartwatch_processor.DATA_DIR", root):
                append_metric_history(
                    "gsuss",
                    {
                        "pasos_hoy": 1000,
                        "hr_promedio_bpm": 70,
                        "hrv_ms": 50,
                        "horas_sueno_anoche": 7,
                        "timestamp": "2026-01-01 10:00",
                    },
                )
                append_metric_history(
                    "gsuss",
                    {
                        "pasos_hoy": 2000,
                        "hr_promedio_bpm": 65,
                        "hrv_ms": 60,
                        "horas_sueno_anoche": 7.5,
                        "timestamp": "2026-01-02 10:00",
                    },
                )
                rows = load_metric_history("gsuss", limit=10)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[-1]["pasos"], 2000)
                self.assertTrue(history_db_path("gsuss").is_file())

    def test_migrate_json_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.smartwatch_processor.DATA_DIR", root):
                legacy = history_path("alice")
                legacy.parent.mkdir(parents=True, exist_ok=True)
                legacy.write_text(
                    json.dumps(
                        [
                            {"t": "a", "pasos": 1, "hr": 60, "hrv": 40, "sueno": 6, "ts": 1},
                            {"t": "b", "pasos": 2, "hr": 70, "hrv": 50, "sueno": 7, "ts": 2},
                        ]
                    ),
                    encoding="utf-8",
                )
                rows = load_metric_history("alice", limit=10)
                self.assertEqual(len(rows), 2)
                self.assertTrue(history_db_path("alice").is_file())
                self.assertTrue(legacy.with_suffix(".json.bak").is_file() or not legacy.is_file())

    def test_processor_includes_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.smartwatch_processor.DATA_DIR", root):
                escribir_metricas_demo("bob", pasos=3000, sueno=7.2, hr=68, hrv=62)
                report = json.loads(procesar_datos_smartwatch("bob"))
                self.assertEqual(report["status"], "success")
                self.assertGreaterEqual(len(report.get("history") or []), 1)


if __name__ == "__main__":
    unittest.main()
