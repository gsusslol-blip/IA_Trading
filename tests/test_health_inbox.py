"""Health inbox drop → smartwatch_metrics.json."""

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

from jarvis.health_inbox import (
    ensure_inbox_readme,
    escanear_inbox_usuario,
    inbox_dir,
    procesar_archivo_inbox,
)
from jarvis.smartwatch_processor import metrics_path, procesar_datos_smartwatch


class HealthInboxTests(unittest.TestCase):
    def test_json_drop_imports_and_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.health_inbox.DATA_DIR", root), patch(
                "jarvis.smartwatch_processor.DATA_DIR", root
            ):
                ensure_inbox_readme("gsuss")
                drop = inbox_dir("gsuss") / "export.json"
                drop.write_text(
                    json.dumps(
                        {
                            "pasos_hoy": 5555,
                            "horas_sueno_anoche": 7.1,
                            "hr_promedio_bpm": 66,
                            "hrv_ms": 61,
                        }
                    ),
                    encoding="utf-8",
                )
                result = procesar_archivo_inbox("gsuss", drop)
                self.assertEqual(result["status"], "success")
                self.assertFalse(drop.exists())
                report = json.loads(procesar_datos_smartwatch("gsuss"))
                self.assertEqual(report["status"], "success")
                self.assertEqual(report["pasos_hoy"], 5555)
                self.assertIn("Óptima", report["nivel_energia_estimado"])
                archived = list((inbox_dir("gsuss") / "processed").glob("*export.json"))
                self.assertTrue(archived)

    def test_csv_drop_via_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.health_inbox.DATA_DIR", root), patch(
                "jarvis.smartwatch_processor.DATA_DIR", root
            ):
                folder = inbox_dir("alice")
                csv_path = folder / "day.csv"
                csv_path.write_text("steps,sleep,hr,hrv\n1200,5.5,80,35\n", encoding="utf-8")
                results = escanear_inbox_usuario("alice")
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["status"], "success")
                data = json.loads(metrics_path("alice").read_text(encoding="utf-8"))
                self.assertEqual(data["pasos_hoy"], 1200)
                self.assertEqual(data.get("source_file"), "day.csv")
                self.assertIn("Baja", data["nivel_energia_estimado"])
                self.assertFalse(csv_path.exists())

    def test_english_keys_avg_hr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.health_inbox.DATA_DIR", root), patch(
                "jarvis.smartwatch_processor.DATA_DIR", root
            ):
                drop = inbox_dir("gsuss") / "test_watch.json"
                drop.write_text(
                    json.dumps(
                        {
                            "steps": 9450,
                            "sleep_hours": 7.5,
                            "avg_hr": 64,
                            "hrv": 68,
                        }
                    ),
                    encoding="utf-8",
                )
                result = procesar_archivo_inbox("gsuss", drop)
                self.assertEqual(result["status"], "success")
                report = json.loads(procesar_datos_smartwatch("gsuss"))
                self.assertEqual(report["pasos_hoy"], 9450)
                self.assertEqual(report["horas_sueno_anoche"], 7.5)
                self.assertEqual(report["hr_promedio_bpm"], 64)
                self.assertEqual(report["hrv_ms"], 68)
                self.assertIn("Óptima", report["nivel_energia_estimado"])
                self.assertGreaterEqual(len(report.get("history") or []), 1)

    def test_gpx_drop_avg_hr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.health_inbox.DATA_DIR", root), patch(
                "jarvis.smartwatch_processor.DATA_DIR", root
            ):
                gpx = (
                    '<?xml version="1.0"?>'
                    '<gpx><trk><trkseg>'
                    '<trkpt lat="-34.60" lon="-58.38"><extensions><hr>60</hr></extensions></trkpt>'
                    '<trkpt lat="-34.601" lon="-58.381"><extensions><hr>80</hr></extensions></trkpt>'
                    "</trkseg></trk></gpx>"
                )
                drop = inbox_dir("gsuss") / "run.gpx"
                drop.write_text(gpx, encoding="utf-8")
                result = procesar_archivo_inbox("gsuss", drop)
                self.assertEqual(result["status"], "success")
                report = json.loads(procesar_datos_smartwatch("gsuss"))
                self.assertEqual(report["hr_promedio_bpm"], 70.0)
                self.assertGreater(report["pasos_hoy"], 0)


if __name__ == "__main__":
    unittest.main()
