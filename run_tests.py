#!/usr/bin/env python3
"""Ejecutar la batería de tests desde la raíz del proyecto:

  python run_tests.py

Código de salida 0 si todo OK, 1 si hubo fallos.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    tests_dir = root / "tests"
    sys.path.insert(0, str(root))
    loader = unittest.TestLoader()
    suite = loader.discover(str(tests_dir), pattern="test*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
