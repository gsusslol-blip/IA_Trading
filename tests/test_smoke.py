"""Smoke: sintaxis, imports del proyecto y helpers sin terminal MT5."""

from __future__ import annotations

import ast
import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _project_py_files() -> list[Path]:
    skip = {"venv", ".venv", "__pycache__"}
    out: list[Path] = []
    for p in ROOT.rglob("*.py"):
        if any(part in skip for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


class TestSyntax(unittest.TestCase):
    def test_all_project_python_parses(self) -> None:
        failures: list[str] = []
        for path in _project_py_files():
            try:
                src = path.read_text(encoding="utf-8")
                ast.parse(src, filename=str(path))
            except SyntaxError as e:
                failures.append(f"{path.relative_to(ROOT)}: {e}")
        self.assertFalse(failures, "\n" + "\n".join(failures))


class TestImports(unittest.TestCase):
    def setUp(self) -> None:
        root_str = str(ROOT)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

    def test_import_core_modules(self) -> None:
        for name in (
            "local_env",
            "telegram_utils",
            "signal_analysis",
            "mt5_prices",
            "ia_replay",
            "m15_ma_scan",
            "m15_engulfing_scan",
            "ia_scanner_loop",
            "ia_backtester",
            "ia_fast_backtest",
            "ia_report_performance",
            "ia_auto_trade_loop",
            "ia_news_alert_loop",
            "evening_signal",
            "signal_now",
            "bot_pnl_report",
            "mt5_status",
            "close_all_positions",
            "preview_tg_messages",
            "send_tg_preview",
            "telegram_hola",
            "daily_report_loop",
            "sentiment_news",
            "sentiment_m15_loop",
            "market_regime",
        ):
            with self.subTest(module=name):
                importlib.import_module(name)


class TestPureHelpers(unittest.TestCase):
    def setUp(self) -> None:
        root_str = str(ROOT)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

    def test_closed_trade_winrate_stats(self) -> None:
        from mt5_prices import closed_trade_winrate_stats

        wr, w, l, z = closed_trade_winrate_stats([1.0, -2.0, 0.0, 3.0])
        self.assertAlmostEqual(wr, 0.5)
        self.assertEqual(w, 2)
        self.assertEqual(l, 1)
        self.assertEqual(z, 1)

        wr2, _, _, _ = closed_trade_winrate_stats([])
        self.assertEqual(wr2, 0.0)

    def test_env_winrate_target_parsing(self) -> None:
        import os

        from mt5_prices import _env_winrate_target

        old = dict(os.environ)
        try:
            os.environ.pop("WINRATE_TARGET", None)
            self.assertEqual(_env_winrate_target(), 0.0)
            os.environ["WINRATE_TARGET"] = "85"
            self.assertAlmostEqual(_env_winrate_target(), 0.85)
            os.environ["WINRATE_TARGET"] = "0.75"
            self.assertAlmostEqual(_env_winrate_target(), 0.75)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_process_alive_current_pid(self) -> None:
        from ia_auto_trade_loop import _process_alive

        import os as _os

        self.assertTrue(_process_alive(_os.getpid()))
        self.assertFalse(_process_alive(9_876_543_210))


if __name__ == "__main__":
    unittest.main()
