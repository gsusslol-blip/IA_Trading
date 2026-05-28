"""Tests de ia_news_filter (sin red)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ia_news_filter import (
    _parse_event_datetime,
    _parse_forexfactory_weekly_xml,
    verificar_bloqueo_por_noticias,
)


class TestNewsFilter(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["IA_NEWS_FILTER_ENABLE"] = "1"

    def test_parse_ff_datetime(self) -> None:
        tz = ZoneInfo("America/New_York")
        dt = _parse_event_datetime("05-20-2026", "8:30am", tz)
        self.assertIsNotNone(dt)
        assert dt is not None
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_ff_xml_high_usd(self) -> None:
        xml = b"""<?xml version="1.0"?>
<weeklyevents>
  <event>
    <title>NFP</title>
    <country>USD</country>
    <date>05-20-2026</date>
    <time>8:30am</time>
    <impact>High</impact>
  </event>
  <event>
    <title>Low EU</title>
    <country>EUR</country>
    <date>05-20-2026</date>
    <time>9:00am</time>
    <impact>Low</impact>
  </event>
</weeklyevents>"""
        tz = ZoneInfo("America/New_York")
        evs = _parse_forexfactory_weekly_xml(xml, tz)
        self.assertEqual(len(evs), 1)

    def test_verificar_bloqueo_en_ventana(self) -> None:
        now = datetime.now(timezone.utc)
        ev = now + timedelta(minutes=5)
        self.assertTrue(verificar_bloqueo_por_noticias([ev], ventana_minutos=15))

    def test_verificar_bloqueo_fuera_ventana(self) -> None:
        now = datetime.now(timezone.utc)
        ev = now + timedelta(hours=3)
        self.assertFalse(verificar_bloqueo_por_noticias([ev], ventana_minutos=15))


if __name__ == "__main__":
    unittest.main()
