"""Home Assistant Python guardrails — LLM cannot bypass these."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.ha_guard import HaDenied, authorize_ha_call


class HaGuardTests(unittest.TestCase):
    def test_light_on_ok(self) -> None:
        spec = authorize_ha_call(
            domain="light",
            service="on",
            entity_id="light.living",
            is_owner=False,
        )
        self.assertEqual(spec["service"], "turn_on")
        self.assertEqual(spec["payload"]["entity_id"], "light.living")

    def test_member_cannot_unlock(self) -> None:
        with self.assertRaises(HaDenied):
            authorize_ha_call(
                domain="lock",
                service="unlock",
                entity_id="lock.front",
                is_owner=False,
            )

    def test_owner_climate_capped(self) -> None:
        with self.assertRaises(HaDenied):
            authorize_ha_call(
                domain="climate",
                service="set_temperature",
                entity_id="climate.room",
                is_owner=True,
                temperature=100,
            )
        spec = authorize_ha_call(
            domain="climate",
            service="set_temperature",
            entity_id="climate.room",
            is_owner=True,
            temperature=22,
        )
        self.assertEqual(spec["payload"]["temperature"], 22.0)

    def test_shell_blocked(self) -> None:
        with self.assertRaises(HaDenied):
            authorize_ha_call(
                domain="shell_command",
                service="turn_on",
                is_owner=True,
            )

    def test_entity_must_match_domain(self) -> None:
        with self.assertRaises(HaDenied):
            authorize_ha_call(
                domain="light",
                service="turn_on",
                entity_id="switch.kitchen",
                is_owner=True,
            )


if __name__ == "__main__":
    unittest.main()
