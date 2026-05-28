"""
Entrena el clasificador de falsos rompimientos (memoria de trades del bot).

  python train_ml_filter.py

Requiere: ia_auto_trade_memory.csv con al menos ~30 cierres.
"""

from __future__ import annotations

from local_env import load_env_file
from ia_intelligence_layer import train_breakout_filter_from_memory


def main() -> int:
    load_env_file()
    return 0 if train_breakout_filter_from_memory() else 1


if __name__ == "__main__":
    raise SystemExit(main())
