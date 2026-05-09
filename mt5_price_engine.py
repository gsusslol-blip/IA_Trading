"""
Motor único de precios OHLCV (MT5) con política de caché centralizada.

Objetivos:
  - Una sola API para scanners/bot/backtests que lean velas sin repetir llamadas dispersas.
  - Reaprovecha ``get_rates_optimized`` / ``mt5_copy_rates_from_pos_cached`` (TTL por vela).

Regla para señales en live:
  ``iloc[-1]`` suele ser la vela **en formación** (repinta); el gatillo robusto debe basarse en
  ``iloc[-2]`` y ``iloc[-3]`` como contexto previo siempre que el DataFrame incluya la barra abierta.

Uso:
  from mt5_price_engine import get_price_engine

  df = get_price_engine().get_data(sym, mt5.TIMEFRAME_M15, 120)

Normalización unix para replay: ``mt5_prices.ensure_unix_time`` (= ``rates_df_time_as_unix_seconds`` aquí).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from mt5_prices import ensure_unix_time, get_rates_optimized, mt5_rates_cache_clear

rates_df_time_as_unix_seconds = ensure_unix_time


class PriceEngine:
    """
    Fachada delgada sobre la caché global de rates; permitís invalidar o extender sin tocar cada script.
    """

    def __init__(self) -> None:
        self._opts: dict[str, Any] = {}

    def clear_cache(self) -> None:
        """Invalida la caché de rates (p. ej. tras cambiar de cuenta o símbolo master)."""
        mt5_rates_cache_clear()

    def get_data(self, symbol: str, timeframe: int, n_bars: int = 100) -> pd.DataFrame:
        """
        Devuelve OHLCV con columna ``time`` como datetime (UTC naive al estilo pandas desde epoch MT5).
        Si no hay datos → DataFrame vacío (no ``None``), coherente con pipelines que hacen ``.empty``.
        """
        n = max(1, int(n_bars))
        df = get_rates_optimized(symbol, timeframe, n)
        if df is None or len(df) == 0:
            return pd.DataFrame()
        out = df.copy()
        out["time"] = pd.to_datetime(out["time"], unit="s")
        return out

    def set_options(self, **kwargs: Any) -> None:
        """Hook reservado (p. ej. overrides de backtest); sin efecto por defecto."""
        self._opts.update(kwargs)


_engine: PriceEngine | None = None


def get_price_engine() -> PriceEngine:
    """Instancia de proceso (single-threaded bot)."""
    global _engine
    if _engine is None:
        _engine = PriceEngine()
    return _engine


def reset_price_engine() -> None:
    """Tests o reinicio explícito."""
    global _engine
    _engine = None


def m15_closed_trigger_rows(df: pd.DataFrame) -> tuple[pd.Series, pd.Series] | None:
    """
    Última vela **cerrada** y la anterior: ``.iloc[-2]``, ``.iloc[-3]``.
    None si no hay al menos 3 filas (se suele querer ``>= 4`` para volumen vs previo).
    """
    if df is None or df.empty or len(df) < 3:
        return None
    return df.iloc[-2], df.iloc[-3]
