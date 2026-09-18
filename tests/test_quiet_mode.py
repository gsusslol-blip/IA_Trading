"""Quiet-Mode policy — deterministic, no Win32 required for unit tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.quiet_mode import evaluate_quiet, is_quiet, snapshot


class QuietModeTests(unittest.TestCase):
    def test_steam_focus_quiet(self) -> None:
        state = evaluate_quiet(process="Steam.exe", title="Steam", fullscreen=False)
        self.assertTrue(state.active)
        self.assertEqual(state.reason, "focus:steam.exe")

    def test_cursor_windowed_not_quiet(self) -> None:
        state = evaluate_quiet(process="Cursor.exe", title="Ilaria", fullscreen=False)
        self.assertFalse(state.active)

    def test_cursor_fullscreen_quiet(self) -> None:
        state = evaluate_quiet(process="cursor.exe", title="Ilaria", fullscreen=True)
        self.assertTrue(state.active)
        self.assertIn("fullscreen", state.reason)

    def test_game_fullscreen_quiet(self) -> None:
        state = evaluate_quiet(process="eldenring.exe", title="ELDEN RING", fullscreen=True)
        self.assertTrue(state.active)

    def test_force_env(self) -> None:
        with patch.dict(os.environ, {"QUIET_FORCE": "1", "QUIET_MODE_ENABLED": "1"}):
            state = evaluate_quiet(process="notepad.exe", force=None)
            self.assertTrue(state.active)
            self.assertEqual(state.reason, "force")

    def test_disabled(self) -> None:
        with patch.dict(os.environ, {"QUIET_MODE_ENABLED": "0"}, clear=False):
            state = evaluate_quiet(process="steam.exe", fullscreen=True)
            self.assertFalse(state.active)
            self.assertEqual(state.reason, "disabled")

    def test_extra_exes(self) -> None:
        with patch.dict(os.environ, {"QUIET_EXTRA_EXES": "obs64.exe"}, clear=False):
            state = evaluate_quiet(process="obs64.exe", fullscreen=False)
            self.assertTrue(state.active)

    def test_snapshot_force(self) -> None:
        with patch.dict(os.environ, {"QUIET_FORCE": "1", "QUIET_MODE_ENABLED": "1"}):
            with patch("jarvis.quiet_mode.probe_foreground", return_value=("", "", False)):
                from jarvis.quiet_mode import clear_cache

                clear_cache()
                self.assertTrue(is_quiet(bypass_cache=True))
                self.assertTrue(snapshot(bypass_cache=True).active)


if __name__ == "__main__":
    unittest.main()
