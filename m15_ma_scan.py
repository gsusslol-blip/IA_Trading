"""
Escaneo rápido M15 con dos medias móviles (estilo cruce / confirmación de tendencia).

  python m15_ma_scan.py

Variables opcionales en .env:
  MA_SCAN_SYMBOLS — lista separada por comas (default: XAUUSD)
  MA_FAST / MA_SLOW — ventanas (default 10 / 30)
"""

from __future__ import annotations

import os
import sys

import MetaTrader5 as mt5
import pandas as pd

from local_env import load_env_file


def _resolve_scan_symbol(requested: str) -> str | None:
    """Igual que el bot pero sin abortar el proceso si el símbolo no existe."""
    from mt5_prices import _candidate_symbols, _find_symbol_fallback, _first_working_tick

    if mt5.symbol_info_tick(requested) is not None:
        return requested
    candidates = [requested]
    fb = _find_symbol_fallback(requested)
    if fb and fb not in candidates:
        candidates.append(fb)
    candidates.extend([c for c in _candidate_symbols(requested, limit=30) if c not in candidates])
    hit = _first_working_tick(candidates)
    return hit[0] if hit else None


def obtener_datos(simbolo: str, temporalidad: int, cantidad: int) -> pd.DataFrame | None:
    velas = mt5.copy_rates_from_pos(simbolo, temporalidad, 0, cantidad)
    if velas is None or len(velas) == 0:
        return None
    df = pd.DataFrame(velas)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def analizar_estrategia(simbolo: str, *, fast: int = 10, slow: int = 30) -> str:
    need = max(slow + 5, 50)
    df = obtener_datos(simbolo, mt5.TIMEFRAME_M15, max(100, need))
    if df is None or len(df) < slow:
        return "Sin datos suficientes"

    ma_rapida = df["close"].rolling(window=fast).mean().iloc[-1]
    ma_lenta = df["close"].rolling(window=slow).mean().iloc[-1]
    precio_actual = float(df["close"].iloc[-1])

    if pd.isna(ma_rapida) or pd.isna(ma_lenta):
        return "Indicadores sin valor (pocas velas)"

    ma_rapida = float(ma_rapida)
    ma_lenta = float(ma_lenta)

    print(f"Análisis {simbolo}: precio={precio_actual:.5f} MA{fast}={ma_rapida:.5f} MA{slow}={ma_lenta:.5f}")

    if precio_actual > ma_rapida and ma_rapida > ma_lenta:
        return "COMPRA - Tendencia alcista confirmada"
    if precio_actual < ma_rapida and ma_rapida < ma_lenta:
        return "VENTA - Tendencia bajista confirmada"
    return "ESPERAR - Mercado sin dirección clara"


def main() -> None:
    load_env_file()
    fast = int(os.environ.get("MA_FAST", "10"))
    slow = int(os.environ.get("MA_SLOW", "30"))
    raw = os.environ.get("MA_SCAN_SYMBOLS", "XAUUSD")
    activos = [a.strip() for a in raw.split(",") if a.strip()]

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        print(f"No se pudo inicializar MT5. ({code}) {msg}", file=sys.stderr)
        raise SystemExit(1)

    try:
        for requested in activos:
            resolved = _resolve_scan_symbol(requested)
            if not resolved:
                print(f"-> {requested}: símbolo no operable en este terminal", file=sys.stderr)
                continue
            mt5.symbol_select(resolved, True)
            tag = requested if resolved == requested else f"{requested} → {resolved}"
            resultado = analizar_estrategia(resolved, fast=fast, slow=slow)
            print(f"-> {tag}: {resultado}")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
