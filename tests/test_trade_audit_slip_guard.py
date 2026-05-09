"""Guard de slippage (CSV) sin MT5."""

from __future__ import annotations

import csv
import os
import sys
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestSlippageGuard(unittest.TestCase):
    def setUp(self) -> None:
        r = str(_root())
        if r not in sys.path:
            sys.path.insert(0, r)

    def tearDown(self) -> None:
        pass

    def _write_csv(self, rows: list[list[str]]) -> Path:
        tf = NamedTemporaryFile(mode="w", encoding="utf-8", newline="", delete=False, suffix=".csv")
        try:
            w = csv.writer(tf)
            for row in rows:
                w.writerow(row)
            tf.close()
            return Path(tf.name)
        except Exception:
            tf.close()
            raise

    def test_fail_open_missing_file(self) -> None:
        import trade_audit as ta

        p = Path(__file__).resolve().parent / "nonexistent_exec_quality_xyz.csv"
        with patch.dict(os.environ, {"IA_EXEC_SLIP_GUARD_ENABLE": "1", "IA_EXEC_SLIP_GUARD_MAX_AVG_PTS": "5"}):
            with patch.object(ta, "_exec_quality_path", return_value=p):
                ok, _ = ta.slippage_guard_allows_order("XAUUSD")
        self.assertTrue(ok)

    def test_check_slippage_safety_none_symbol_tail(self) -> None:
        import trade_audit as ta

        hdr = [
            "time_utc",
            "symbol",
            "side",
            "volume",
            "price_requested",
            "price_executed",
            "slippage_abs",
            "slippage_points",
            "spread_points",
            "retcode",
            "deal",
        ]
        hi = [
            "2026-01-01T00:00:00",
            "EURUSD",
            "COMPRA",
            "0.01",
            "1",
            "1",
            "0",
            "150",
            "1",
            "0",
            "0",
        ]
        row_lo = [
            "2026-01-02T00:00:00",
            "XAUUSD",
            "COMPRA",
            "0.01",
            "1",
            "1",
            "0",
            "200",
            "2",
            "0",
            "0",
        ]
        path = self._write_csv([hdr, hi, row_lo])
        try:
            ok, _why = ta.check_slippage_safety(
                path, symbol=None, window=3, max_avg_points=80.0, min_samples=2
            )
            self.assertFalse(ok)
        finally:
            path.unlink(missing_ok=True)

    def test_blocks_when_recent_avg_exceeds(self) -> None:
        import trade_audit as ta

        hdr = [
            "time_utc",
            "symbol",
            "side",
            "volume",
            "price_requested",
            "price_executed",
            "slippage_abs",
            "slippage_points",
            "spread_points",
            "retcode",
            "deal",
        ]
        rows: list[list[str]] = [hdr]
        for _ in range(3):
            rows.append(
                [
                    "2026-01-01T00:00:00",
                    "XAUUSD",
                    "COMPRA",
                    "0.01",
                    "2600",
                    "2600.5",
                    "0.5",
                    "50",
                    "3",
                    "0",
                    "0",
                ]
            )
        path = self._write_csv(rows)
        try:
            with patch.dict(
                os.environ,
                {
                    "IA_EXEC_SLIP_GUARD_ENABLE": "1",
                    "IA_EXEC_SLIP_GUARD_WINDOW": "3",
                    "IA_EXEC_SLIP_GUARD_MAX_AVG_PTS": "40",
                    "IA_EXEC_SLIP_GUARD_MIN_SAMPLES": "3",
                },
                clear=False,
            ):
                with patch.object(ta, "_exec_quality_path", return_value=path):
                    ok, why = ta.slippage_guard_allows_order("XAUUSD")
            self.assertFalse(ok)
            self.assertIn("slippage_avg", why)
        finally:
            path.unlink(missing_ok=True)

    def test_allows_when_below_limit(self) -> None:
        import trade_audit as ta

        hdr = [
            "time_utc",
            "symbol",
            "side",
            "volume",
            "price_requested",
            "price_executed",
            "slippage_abs",
            "slippage_points",
            "spread_points",
            "retcode",
            "deal",
        ]
        row = [
            "2026-01-01T00:00:00",
            "XAUUSD",
            "COMPRA",
            "0.01",
            "2600",
            "2600.01",
            "0.01",
            "2",
            "3",
            "0",
            "0",
        ]
        rows: list[list[str]] = [hdr, row, row, row]
        path = self._write_csv(rows)
        try:
            with patch.dict(
                os.environ,
                {
                    "IA_EXEC_SLIP_GUARD_ENABLE": "1",
                    "IA_EXEC_SLIP_GUARD_WINDOW": "3",
                    "IA_EXEC_SLIP_GUARD_MAX_AVG_PTS": "100",
                    "IA_EXEC_SLIP_GUARD_MIN_SAMPLES": "2",
                },
                clear=False,
            ):
                with patch.object(ta, "_exec_quality_path", return_value=path):
                    ok, _ = ta.slippage_guard_allows_order("XAUUSD")
            self.assertTrue(ok)
        finally:
            path.unlink(missing_ok=True)

    def test_alias_ia_max_slippage_avg_when_primary_empty(self) -> None:
        import trade_audit as ta

        hdr = [
            "time_utc",
            "symbol",
            "side",
            "volume",
            "price_requested",
            "price_executed",
            "slippage_abs",
            "slippage_points",
            "spread_points",
            "retcode",
            "deal",
        ]
        rows: list[list[str]] = [hdr]
        for _ in range(3):
            rows.append(
                [
                    "2026-01-01T00:00:00",
                    "XAUUSD",
                    "COMPRA",
                    "0.01",
                    "2600",
                    "2600.5",
                    "0.5",
                    "50",
                    "3",
                    "0",
                    "0",
                ]
            )
        path = self._write_csv(rows)
        try:
            with patch.dict(
                os.environ,
                {
                    "IA_EXEC_SLIP_GUARD_ENABLE": "1",
                    "IA_EXEC_SLIP_GUARD_MAX_AVG_PTS": "",
                    "IA_MAX_SLIPPAGE_AVG": "40",
                    "IA_EXEC_SLIP_GUARD_WINDOW": "3",
                    "IA_EXEC_SLIP_GUARD_MIN_SAMPLES": "3",
                },
                clear=False,
            ):
                with patch.object(ta, "_exec_quality_path", return_value=path):
                    ok, why = ta.slippage_guard_allows_order("XAUUSD")
            self.assertFalse(ok)
            self.assertIn("slippage_avg", why)
        finally:
            path.unlink(missing_ok=True)

    def test_primary_max_avg_pts_overrides_alias(self) -> None:
        import trade_audit as ta

        hdr = [
            "time_utc",
            "symbol",
            "side",
            "volume",
            "price_requested",
            "price_executed",
            "slippage_abs",
            "slippage_points",
            "spread_points",
            "retcode",
            "deal",
        ]
        rows: list[list[str]] = [hdr]
        for _ in range(3):
            rows.append(
                [
                    "2026-01-01T00:00:00",
                    "XAUUSD",
                    "COMPRA",
                    "0.01",
                    "2600",
                    "2600.5",
                    "0.5",
                    "50",
                    "3",
                    "0",
                    "0",
                ]
            )
        path = self._write_csv(rows)
        try:
            with patch.dict(
                os.environ,
                {
                    "IA_EXEC_SLIP_GUARD_ENABLE": "1",
                    "IA_EXEC_SLIP_GUARD_MAX_AVG_PTS": "100",
                    "IA_MAX_SLIPPAGE_AVG": "40",
                    "IA_EXEC_SLIP_GUARD_WINDOW": "3",
                    "IA_EXEC_SLIP_GUARD_MIN_SAMPLES": "3",
                },
                clear=False,
            ):
                with patch.object(ta, "_exec_quality_path", return_value=path):
                    ok, _ = ta.slippage_guard_allows_order("XAUUSD")
            self.assertTrue(ok)
        finally:
            path.unlink(missing_ok=True)

    def test_is_market_safe_to_trade_ignores_slip_guard_enable(self) -> None:
        import trade_audit as ta

        hdr = [
            "time_utc",
            "symbol",
            "side",
            "volume",
            "price_requested",
            "price_executed",
            "slippage_abs",
            "slippage_points",
            "spread_points",
            "retcode",
            "deal",
        ]
        rows: list[list[str]] = [hdr]
        for _ in range(3):
            rows.append(
                [
                    "2026-01-01T00:00:00",
                    "XAUUSD",
                    "COMPRA",
                    "0.01",
                    "2600",
                    "2600.5",
                    "0.5",
                    "50",
                    "3",
                    "0",
                    "0",
                ]
            )
        path = self._write_csv(rows)
        try:
            with patch.dict(
                os.environ,
                {
                    "IA_EXEC_SLIP_GUARD_ENABLE": "0",
                    "IA_MAX_SLIPPAGE_AVG": "40",
                    "IA_SLIPPAGE_WINDOW": "3",
                    "IA_EXEC_SLIP_GUARD_MIN_SAMPLES": "3",
                },
                clear=False,
            ):
                safe = ta.is_market_safe_to_trade(path, symbol="XAUUSD")
            self.assertFalse(safe)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
