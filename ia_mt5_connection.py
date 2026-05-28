"""
Salud y reconexión de la API MetaTrader 5 (resiliencia de red / terminal).
"""

from __future__ import annotations

import os
import time

import MetaTrader5 as mt5

from mt5_prices import mt5_rates_cache_clear


def _mt5_initialize() -> bool:
    path = os.environ.get("MT5_PATH", "").strip()
    login = os.environ.get("MT5_LOGIN", "").strip()
    password = os.environ.get("MT5_PASSWORD", "").strip()
    server = os.environ.get("MT5_SERVER", "").strip()
    kwargs: dict = {}
    if path:
        kwargs["path"] = path
    if login:
        try:
            kwargs["login"] = int(login)
        except ValueError:
            pass
    if password:
        kwargs["password"] = password
    if server:
        kwargs["server"] = server
    if kwargs:
        return bool(mt5.initialize(**kwargs))
    return bool(mt5.initialize(path=path) if path else mt5.initialize())


def mt5_conexion_saludable() -> bool:
    """True si terminal conectada al bróker y la API responde con datos de cuenta."""
    ti = mt5.terminal_info()
    if ti is None or not bool(getattr(ti, "connected", False)):
        return False
    acct = mt5.account_info()
    return acct is not None


def asegurar_conexion_mt5(
    *,
    max_intentos: int | None = None,
    espera_segundos: float | None = None,
    raise_on_failure: bool | None = None,
) -> bool:
    """
    Verifica enlace MT5 ↔ bróker; si falla, ``shutdown`` + ``initialize`` progresivo.

    Returns:
        True si la conexión está operativa.

    Raises:
        ConnectionError: si agota reintentos y ``IA_MT5_RECONNECT_RAISE=1`` (o ``raise_on_failure``).
    """
    if os.environ.get("IA_MT5_RECONNECT_ENABLE", "1").strip().lower() in ("0", "false", "no"):
        return mt5_conexion_saludable()

    if mt5_conexion_saludable():
        return True

    try:
        n_try = int(
            os.environ.get("IA_MT5_RECONNECT_ATTEMPTS", str(max_intentos or 5)).strip()
            or str(max_intentos or 5)
        )
    except ValueError:
        n_try = max_intentos or 5
    n_try = max(1, min(20, n_try))

    try:
        wait_s = float(
            os.environ.get("IA_MT5_RECONNECT_WAIT_S", str(espera_segundos or 10)).strip()
            or str(espera_segundos or 10)
        )
    except ValueError:
        wait_s = float(espera_segundos or 10)
    wait_s = max(1.0, wait_s)

    try:
        sync_s = float(os.environ.get("IA_MT5_RECONNECT_SYNC_S", "3").strip() or "3")
    except ValueError:
        sync_s = 3.0

    print("[MT5] Conexión perdida o inestable. Protocolo de reconexión...", flush=True)

    for intento in range(1, n_try + 1):
        print(f"[MT5] Reintento {intento}/{n_try}...", flush=True)
        try:
            mt5.shutdown()
        except Exception:
            pass
        time.sleep(2.0)
        mt5_rates_cache_clear()

        if _mt5_initialize():
            time.sleep(max(0.5, sync_s))
            if mt5_conexion_saludable():
                print("[MT5] Conexión restaurada.", flush=True)
                try:
                    from ia_autonomy_notify import notify_mt5_reconnected

                    notify_mt5_reconnected()
                except Exception as e:
                    print(f"[TG] reconexión: {e}", flush=True)
                return True

        if intento < n_try:
            time.sleep(wait_s)

    msg = (
        "IA_Trading: no se pudo reconectar a MT5 tras varios intentos. "
        "Revisá terminal / red / AutoTrading."
    )
    print(f"[MT5] {msg}", flush=True)
    try:
        from ia_autonomy_notify import notify_mt5_connection_failed

        notify_mt5_connection_failed(n_try)
    except Exception as e:
        print(f"[TG] fallo MT5: {e}", flush=True)

    do_raise = raise_on_failure
    if do_raise is None:
        do_raise = os.environ.get("IA_MT5_RECONNECT_RAISE", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        )
    if do_raise:
        raise ConnectionError(msg)
    return False
