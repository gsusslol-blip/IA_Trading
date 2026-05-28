"""
Entrena el clasificador ML desde trade_audit_ml.csv (preferido) o memoria legacy.

  python train_ml_filter.py
  python ia_trainer.py
"""

from __future__ import annotations

from local_env import load_env_file
from ia_trainer import auto_entrenar_modelo_ia
from ia_intelligence_layer import train_breakout_filter_from_memory
from ia_audit_logger import audit_csv_path


def main() -> int:
    load_env_file()
    if audit_csv_path().is_file():
        return 0 if auto_entrenar_modelo_ia() else 1
    return 0 if train_breakout_filter_from_memory() else 1


if __name__ == "__main__":
    raise SystemExit(main())
