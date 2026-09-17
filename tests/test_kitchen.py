"""Kitchen offline index + parser bifurcation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.brain_parser import parse_and_execute
from jarvis.kitchen_manager import (
    RECETAS_LOCALES,
    buscar_receta_core,
    listar_recetas_locales,
)


class KitchenTests(unittest.TestCase):
    def test_static_index_has_core_plates(self) -> None:
        for key in ("milanesa", "tortilla", "fideos_caruso", "guiso_lentejas"):
            self.assertIn(key, RECETAS_LOCALES)

    def test_listar_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from unittest.mock import patch

            with patch("jarvis.kitchen_manager.DATA_DIR", root):
                payload = json.loads(listar_recetas_locales("gsuss"))
            self.assertEqual(payload["status"], "success")
            self.assertGreaterEqual(payload.get("count") or payload.get("total") or 0, 4)

    def test_buscar_caruso_zero_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch

            with patch("jarvis.kitchen_manager.DATA_DIR", Path(tmp)):
                payload = json.loads(buscar_receta_core("caruso", "gsuss"))
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload.get("found_in") or payload.get("source"), "local_db")
            self.assertIn("Caruso", payload["datos"]["nombre"])

    def test_parser_listar(self) -> None:
        raw = '{"tool":"kitchen_action","params":{"action":"listar"}}'
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch

            user_ws = Path(tmp) / "users" / "gsuss" / "workspace"
            user_ws.mkdir(parents=True)
            with patch("jarvis.brain_parser.DATA_DIR", Path(tmp)):
                result = parse_and_execute(raw, client_info="offline_test", current_user="gsuss")
            self.assertEqual(result.get("status"), "success")
            self.assertGreaterEqual(int(result.get("count") or result.get("total") or 0), 4)
            print(f"[TEST OK] Atajo de cocina 'listar' verificado. Encontradas {result.get('count') or result.get('total')} recetas.")

    def test_parser_missing_triggers_fallback(self) -> None:
        raw = '{"tool":"kitchen_action","params":{"action":"buscar","comida":"sushi espacial"}}'
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch

            (Path(tmp) / "users" / "gsuss" / "workspace").mkdir(parents=True)
            with patch("jarvis.brain_parser.DATA_DIR", Path(tmp)):
                result = parse_and_execute(raw, client_info="offline_test", current_user="gsuss")
            self.assertEqual(result.get("status"), "trigger_llm_fallback")


if __name__ == "__main__":
    unittest.main()
