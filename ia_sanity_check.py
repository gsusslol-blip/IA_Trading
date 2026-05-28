"""
Diagnóstico de dependencias y latencia MT5 antes de desplegar en VPS.

Uso:
  python ia_sanity_check.py

Variables:
  MT5_PATH, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER  — igual que el bot
  IA_SANITY_MAX_MT5_MS=50   — latencia máxima aceptable en initialize+account_info
  ENV_FILE=config/.env
"""

from __future__ import annotations

import os
import sys
import time


def _max_mt5_latency_ms() -> float:
    try:
        return max(10.0, float(os.environ.get("IA_SANITY_MAX_MT5_MS", "50").strip() or "50"))
    except ValueError:
        return 50.0


def ejecutar_sanity_check() -> int:
    """
    Devuelve 0 si el entorno es apto para producción; >0 si hay errores.
    """
    from local_env import load_env_file

    load_env_file()

    print("===================================================")
    print("IA_TRADING - DIAGNOSTICO DEL ENTORNO")
    print("===================================================\n")

    errores = 0
    advertencias = 0

    py_ver = sys.version.split()[0]
    print(f"Python: {py_ver}", end=" ")
    if sys.version_info >= (3, 8):
        print("(compatible)")
    else:
        print("(se requiere Python 3.8+)")
        errores += 1

    librerias: list[tuple[str, str]] = [
        ("MetaTrader5", "MetaTrader5"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("optuna", "optuna"),
        ("sklearn", "sklearn"),
        ("joblib", "joblib"),
        ("requests", "requests"),
        ("pytz", "pytz"),
    ]

    opcionales: list[tuple[str, str]] = [
        ("optuna_dashboard", "optuna-dashboard (panel web)"),
    ]

    print()
    for nombre_import, etiqueta in librerias:
        try:
            modulo = __import__(nombre_import)
            version = getattr(modulo, "__version__", "detectada")
            print(f"  {etiqueta}: {version} OK")
        except ImportError:
            print(f"  {etiqueta}: NO ENCONTRADO")
            errores += 1

    try:
        import pandas as pd
        import numpy as np

        _ = pd.DataFrame({"x": [1, 2]})
        _ = np.array([1.0, 2.0])
        print("  pandas/numpy: operaciones basicas OK")
    except Exception as e:
        print(f"  pandas/numpy: fallo de compatibilidad ({e})")
        errores += 1

    print("\nEnlace MetaTrader 5...")
    max_ms = _max_mt5_latency_ms()
    try:
        import MetaTrader5 as mt5

        from ia_mt5_connection import _mt5_initialize

        t0 = time.perf_counter()
        if not _mt5_initialize():
            code, msg = mt5.last_error()
            print(
                f"  FALLO: no se pudo inicializar MT5 ({code}) {msg}. "
                "Terminal abierta y MT5_PATH correcto en .env?"
            )
            errores += 1
        else:
            cuenta = mt5.account_info()
            terminal = mt5.terminal_info()
            latencia_ms = (time.perf_counter() - t0) * 1000.0

            if latencia_ms <= max_ms:
                print(f"  Latencia API: {latencia_ms:.2f} ms (limite {max_ms:.0f} ms) OK")
            else:
                print(
                    f"  Latencia API: {latencia_ms:.2f} ms > {max_ms:.0f} ms "
                    "(lento; revisar VPS o terminal)"
                )
                advertencias += 1

            if cuenta is not None:
                print(f"  Cuenta: {getattr(cuenta, 'login', '?')} | {getattr(cuenta, 'company', '?')}")
                print(f"  Equity: {getattr(cuenta, 'equity', 0.0)}")
            else:
                print("  Cuenta: sin datos (terminal sin login activo)")
                advertencias += 1

            if terminal is not None:
                trade_ok = bool(getattr(terminal, "trade_allowed", False))
                if trade_ok:
                    print("  Trading algoritmico: permitido en terminal OK")
                else:
                    print("  Trading algoritmico: BLOQUEADO en MT5 (activar AutoTrading)")
                    advertencias += 1
                if not bool(getattr(terminal, "connected", False)):
                    print("  Terminal: sin conexion al servidor del broker")
                    errores += 1
            else:
                print("  terminal_info: no disponible")
                advertencias += 1

            mt5.shutdown()
    except Exception as e:
        print(f"  Error MT5: {e}")
        errores += 1

    print("\nOpcionales:")
    for nombre_import, etiqueta in opcionales:
        try:
            __import__(nombre_import)
            print(f"  {etiqueta} OK")
        except ImportError:
            print(f"  {etiqueta} no instalado (pip install optuna-dashboard)")

    print("\nModulos del proyecto (import rapido)...")
    modulos_proyecto = [
        "ia_auto_trade_loop",
        "ia_scanner_loop",
        "ia_memory_gc",
        "ia_order_async",
        "ia_walkforward_validate",
    ]
    for mod in modulos_proyecto:
        try:
            __import__(mod)
            print(f"  {mod} OK")
        except Exception as e:
            print(f"  {mod}: {e}")
            errores += 1

    print("\n===================================================")
    if errores == 0 and advertencias == 0:
        print("DIAGNOSTICO EXITOSO: entorno estable para produccion.")
        print("Siguiente paso: ia_watchdog.bat en el VPS.")
        print("===================================================")
        return 0
    if errores == 0:
        print(f"DIAGNOSTICO OK con {advertencias} advertencia(s). Revisar antes de operar en vivo.")
        print("===================================================")
        return 0
    print(f"DIAGNOSTICO FALLIDO: {errores} error(es), {advertencias} advertencia(s).")
    print("Corrija dependencias (.env / pip install -r requirements.txt) antes del VPS.")
    print("===================================================")
    return min(errores, 255)


def main() -> None:
    raise SystemExit(ejecutar_sanity_check())


if __name__ == "__main__":
    main()
