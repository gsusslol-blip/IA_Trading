"""Home Assistant fatigue ↔ lights unit tests (no live HA)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.ha_fatigue import apply_fatigue_lights, classify_fatigue


class HaFatigueTests(unittest.TestCase):
    def test_classify(self) -> None:
        self.assertEqual(classify_fatigue("Baja / Estrés físico detectado."), "low")
        self.assertEqual(classify_fatigue("Óptima. Cuerpo recuperado."), "optimal")
        self.assertEqual(classify_fatigue("Moderada. Lista."), "moderate")

    def test_dry_run_low_energy(self) -> None:
        payload = {
            "status": "success",
            "nivel_energia_estimado": "Baja / Estrés físico detectado.",
            "pasos_hoy": 1000,
            "hrv_ms": 30,
        }
        with patch("jarvis.ha_fatigue.procesar_datos_smartwatch", return_value=__import__("json").dumps(payload)):
            with patch.dict(
                "os.environ",
                {"HA_FATIGUE_ON_ENTITIES": "light.living", "HA_FATIGUE_ENABLED": "1"},
                clear=False,
            ):
                # Reset idempotency
                import jarvis.ha_fatigue as mod

                mod._last_action = None
                result = apply_fatigue_lights(dry_run=True, username="gsuss")
                self.assertEqual(result["fatigue"], "low")
                self.assertEqual(result["desired"], "fatigue_on")
                self.assertTrue(any("light.living" in a for a in result["actions"]))


if __name__ == "__main__":
    unittest.main()
