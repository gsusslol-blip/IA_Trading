"""Tests unitarios para market_regime (sin MT5)."""

from __future__ import annotations

import os
import unittest

from market_regime import _adx_last


class TestAdx(unittest.TestCase):
    def test_trend_high_adx(self) -> None:
        n = 300
        h = [100.0 + i * 0.5 for i in range(n)]
        l = [99.0 + i * 0.5 for i in range(n)]
        c = [99.5 + i * 0.5 for i in range(n)]
        adx = _adx_last(h, l, c, 14)
        self.assertIsNotNone(adx)
        assert adx is not None
        self.assertGreater(adx, 50.0)

    def test_chop_low_adx(self) -> None:
        n = 300
        h = [100.0 + (i % 5) * 0.1 for i in range(n)]
        l = [99.9 + (i % 5) * 0.1 for i in range(n)]
        c = [99.95 + (i % 5) * 0.1 for i in range(n)]
        adx = _adx_last(h, l, c, 14)
        self.assertIsNotNone(adx)
        assert adx is not None
        self.assertLess(adx, 25.0)


class TestRegimeFromHlc(unittest.TestCase):
    def test_from_hlc_trending_high_adx(self) -> None:
        from market_regime import RegimeLabel, classify_regime_rules_from_hlc

        n = 300
        h = [100.0 + i * 0.5 for i in range(n)]
        l = [99.0 + i * 0.5 for i in range(n)]
        c = [99.5 + i * 0.5 for i in range(n)]
        os.environ["IA_REGIME_ADX_TREND_MIN"] = "25"
        os.environ["IA_REGIME_ADX_RANGE_MAX"] = "22"
        snap = classify_regime_rules_from_hlc(h, l, c)
        self.assertEqual(snap.label, RegimeLabel.TREND)


class TestRegimeRulesNoMt5(unittest.TestCase):
    def test_disabled_gate_allows(self) -> None:
        from market_regime import evaluate_regime_for_trend_module

        os.environ.pop("IA_REGIME_ENABLE", None)
        os.environ["IA_REGIME_ENABLE"] = "0"
        ok, snap = evaluate_regime_for_trend_module("XAUUSD")
        self.assertTrue(ok)
        self.assertEqual(snap.source, "off")


if __name__ == "__main__":
    unittest.main()
