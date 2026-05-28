"""
Recolector de memoria entre ciclos del bucle infinito (VPS 24/7).

Libera DataFrames temporales, invalida cachés opcionales y fuerza ``gc.collect()``.

Variables:
  IA_MEM_GC_ENABLE=1
  IA_MEM_GC_CLEAR_RATES_EVERY=0     — 0 = no vaciar caché MT5 cada ciclo (mejor latencia)
  IA_MEM_GC_CLEAR_RATES_ROUNDS=96 — si EVERY=1, cada N rondas limpia rates + D1
"""

from __future__ import annotations

import gc
import os
import sys

_ROUND = 0


def mem_gc_enabled() -> bool:
    return os.environ.get("IA_MEM_GC_ENABLE", "1").strip().lower() in ("1", "true", "yes")


def _clear_rates_every_n_rounds() -> int:
    try:
        flag = int(os.environ.get("IA_MEM_GC_CLEAR_RATES_EVERY", "0").strip() or "0")
    except ValueError:
        flag = 0
    if flag <= 0:
        return 0
    try:
        return max(1, int(os.environ.get("IA_MEM_GC_CLEAR_RATES_ROUNDS", "96").strip() or "96"))
    except ValueError:
        return 96


def _default_frame_names() -> tuple[str, ...]:
    return ("df_hoy", "df_m15", "df_h4", "df_h1", "df", "rates", "df_rates")


def liberar_memoria_ciclo(
    *,
    local_vars: dict[str, object] | None = None,
    extra_names: tuple[str, ...] | None = None,
) -> None:
    """
    Llamar al final de cada iteración del ``while True`` principal.
    """
    global _ROUND
    if not mem_gc_enabled():
        return

    _ROUND += 1
    names = _default_frame_names()
    if extra_names:
        names = names + tuple(extra_names)

    if local_vars is not None:
        for name in names:
            if name in local_vars:
                try:
                    del local_vars[name]
                except Exception:
                    pass

    every = _clear_rates_every_n_rounds()
    if every > 0 and (_ROUND % every == 0):
        try:
            from mt5_price_engine import get_price_engine

            get_price_engine().clear_cache()
        except Exception:
            pass
        try:
            from ia_d1_levels import invalidate_d1_levels

            invalidate_d1_levels()
        except Exception:
            pass

    collected = gc.collect()
    if os.environ.get("IA_MEM_GC_VERBOSE", "0").strip().lower() in ("1", "true", "yes"):
        print(f"[mem_gc] ronda={_ROUND} objetos={collected}", file=sys.stderr, flush=True)
