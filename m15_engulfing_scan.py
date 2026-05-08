"""
M15: patrón tipo envolvente entre vela anterior [1] y actual [2] + confirmación por volumen (tick_volume).

  python m15_engulfing_scan.py

Variables opcionales en .env:
  ENGULFING_SCAN_SYMBOLS — lista separada por comas (default: XAUUSD)
  ENGULFING_H4_FILTER — si 1 (default), muestra también la lectura M15 filtrada por tendencia H4 (SMA20).
"""

from __future__ import annotations

import os
import sys

import MetaTrader5 as mt5
import pandas as pd

from local_env import load_env_file
from m15_ma_scan import _resolve_scan_symbol


def obtener_analisis_pro(simbolo: str, *, verbose: bool = True) -> str:
    velas = mt5.copy_rates_from_pos(simbolo, mt5.TIMEFRAME_M15, 0, 3)
    if velas is None or len(velas) < 3:
        return "Sin datos"

    df = pd.DataFrame(velas)
    v_ant = df.iloc[1]
    v_act = df.iloc[2]

    volumen_confirmado = int(v_act["tick_volume"]) > int(v_ant["tick_volume"])

    # Condiciones del snippet original (no envolvente clásica textbook)
    alcista = float(v_act["close"]) > float(v_ant["open"]) and float(v_act["open"]) < float(
        v_ant["close"]
    )
    bajista = float(v_act["close"]) < float(v_ant["open"]) and float(v_act["open"]) > float(
        v_ant["close"]
    )

    close_act = float(v_act["close"])
    if verbose:
        print(f"{simbolo} | Vol {'OK' if volumen_confirmado else 'no'} | Precio: {close_act}")

    if alcista and volumen_confirmado:
        return "COMPRA FUERTE (patrón + volumen)"
    if bajista and volumen_confirmado:
        return "VENTA FUERTE (patrón + volumen)"
    return "Buscando confirmación..."


def analizar_con_filtro_h4(simbolo: str, resultado_m15: str | None = None) -> str:
    """
    Filtro de mayor plazo: precio vs SMA(20) en H4.
    Solo eleva a alta probabilidad si M15 y H4 coinciden en dirección.
    """
    velas_h4 = mt5.copy_rates_from_pos(simbolo, mt5.TIMEFRAME_H4, 0, 60)
    if velas_h4 is None or len(velas_h4) < 20:
        return "Sin datos H4"

    df_h4 = pd.DataFrame(velas_h4)
    sma_20_h4 = df_h4["close"].rolling(window=20).mean().iloc[-1]
    precio_h4 = float(df_h4["close"].iloc[-1])
    if pd.isna(sma_20_h4):
        return "Sin datos H4"

    sma_f = float(sma_20_h4)
    tendencia_mayor = "ALCISTA" if precio_h4 > sma_f else "BAJISTA"

    if resultado_m15 is None:
        resultado_m15 = obtener_analisis_pro(simbolo, verbose=False)

    if "COMPRA" in resultado_m15 and tendencia_mayor == "ALCISTA":
        return "COMPRA DE ALTA PROBABILIDAD (coincide con H4)"
    if "VENTA" in resultado_m15 and tendencia_mayor == "BAJISTA":
        return "VENTA DE ALTA PROBABILIDAD (coincide con H4)"
    return "Señal débil (en contra de tendencia mayor). Esperando..."


def main() -> None:
    load_env_file()
    raw = os.environ.get("ENGULFING_SCAN_SYMBOLS", "XAUUSD")
    activos = [a.strip() for a in raw.split(",") if a.strip()]
    use_h4 = os.environ.get("ENGULFING_H4_FILTER", "1").strip().lower() not in ("0", "false", "no")

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
                print(f"{requested}: símbolo no operable en este terminal", file=sys.stderr)
                continue
            mt5.symbol_select(resolved, True)
            tag = requested if resolved == requested else f"{requested} → {resolved}"
            resultado = obtener_analisis_pro(resolved, verbose=True)
            print(f"M15 {tag}: {resultado}")
            if use_h4:
                filtro = analizar_con_filtro_h4(resolved, resultado_m15=resultado)
                print(f"H4+Filtro {tag}: {filtro}")
            print()
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
