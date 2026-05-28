"""Tests ia_optuna_storage (sin Optuna run)."""

from __future__ import annotations

import os
import unittest


class TestOptunaStorage(unittest.TestCase):
    def test_study_name(self) -> None:
        from ia_optuna_storage import study_name_for_symbol

        os.environ["IA_OPTUNA_STUDY_PREFIX"] = "optimizacion_sharpe"
        self.assertEqual(study_name_for_symbol("XAUUSD"), "optimizacion_sharpe_xauusd")

    def test_storage_url_when_enabled(self) -> None:
        from ia_optuna_storage import optuna_storage_url

        os.environ["IA_OPTUNA_STORAGE_ENABLE"] = "1"
        os.environ.pop("IA_OPTUNA_STORAGE_URL", None)
        url = optuna_storage_url()
        self.assertIsNotNone(url)
        self.assertTrue(url.startswith("sqlite:///"))


if __name__ == "__main__":
    unittest.main()
