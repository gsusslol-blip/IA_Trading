"""Wellness sandbox isolation + Safe-Disclaimer."""

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

from jarvis.brain_parser import parse_and_execute
from jarvis.wellness_manager import (
    DISCLAIMER_SALUD,
    ensure_disclaimer,
    obtener_resumen_bienestar,
    registrar_evento_ciclo_o_sintoma,
    wellness_profile_path,
)


class WellnessTests(unittest.TestCase):
    def test_profiles_isolated_per_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.wellness_manager.DATA_DIR", root):
                registrar_evento_ciclo_o_sintoma("alice", "menstruacion", "día 1")
                registrar_evento_ciclo_o_sintoma("bob", "entrenamiento", "piernas")
                alice = json.loads((root / "users" / "alice" / "workspace" / "wellness_profile.json").read_text(encoding="utf-8"))
                bob = json.loads((root / "users" / "bob" / "workspace" / "wellness_profile.json").read_text(encoding="utf-8"))
                self.assertEqual(alice["historial_eventos"][0]["tipo"], "menstruacion")
                self.assertEqual(bob["historial_eventos"][0]["tipo"], "entrenamiento")
                self.assertNotEqual(alice["historial_eventos"], bob["historial_eventos"])

    def test_disclaimer_on_register_speech(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("jarvis.wellness_manager.DATA_DIR", Path(tmp)):
                raw = json.loads(registrar_evento_ciclo_o_sintoma("gsuss", "embarazo", "semana 12"))
            self.assertEqual(raw["status"], "success")
            self.assertIn("No reemplaza", raw.get("speech", ""))

    def test_parser_registrar(self) -> None:
        raw = (
            '{"tool":"wellness_action","params":{"action":"registrar",'
            '"tipo_tema":"menstruacion","notas_registro":"Primer día del ciclo"}}'
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("jarvis.brain_parser.DATA_DIR", Path(tmp)), patch(
                "jarvis.wellness_manager.DATA_DIR", Path(tmp)
            ):
                result = parse_and_execute(raw, client_info="offline_test", current_user="gsuss")
                path = wellness_profile_path("gsuss")
            self.assertEqual(result.get("status"), "success")
            self.assertTrue(path.is_file())
            print("[TEST OK] Tubería de bienestar cotidiana verificada con éxito de forma offline.")

    def test_ensure_disclaimer_idempotent(self) -> None:
        once = ensure_disclaimer("Hola")
        twice = ensure_disclaimer(once)
        self.assertEqual(once.count("No reemplaza"), 1)
        self.assertEqual(twice.count("No reemplaza"), 1)
        self.assertIn(DISCLAIMER_SALUD.strip()[:20], once)

    def test_smartwatch_demo_and_parser(self) -> None:
        from jarvis.smartwatch_processor import escribir_metricas_demo, procesar_datos_smartwatch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("jarvis.smartwatch_processor.DATA_DIR", root), patch(
                "jarvis.brain_parser.DATA_DIR", root
            ):
                escribir_metricas_demo("gsuss", pasos=9000, sueno=7.5, hrv=65)
                report = json.loads(procesar_datos_smartwatch("gsuss"))
                self.assertEqual(report["status"], "success")
                self.assertIn("Óptima", report["nivel_energia_estimado"])
                raw = (
                    '{"tool":"wellness_action","params":{"action":"leer_reloj",'
                    '"tipo_tema":"smartwatch"}}'
                )
                result = parse_and_execute(raw, client_info="offline_test", current_user="gsuss")
                self.assertEqual(result.get("status"), "success")
                self.assertEqual(result.get("pasos_hoy"), 9000)


if __name__ == "__main__":
    unittest.main()
