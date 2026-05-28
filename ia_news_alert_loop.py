"""
Bucle de trading con avisos y filtro de noticias (intento compatible con calendario MT5).

La distribución habitual del paquete Python **MetaTrader5 no expone** `calendar_get` ni
`message_send`: no hay push nativo al móvil desde este script. Las alertas van por
**Telegram** si configuraste TELEGRAM_* en .env (llegan al celular con la app Telegram).

El filtro de noticias (`IA_NEWS_FILTER=1`) intenta usar funciones `calendar_*` si tu build
las añade; si no existen, muestra un aviso una vez y **no bloquea** operaciones.

  python ia_news_alert_loop.py

Requiere: IA_NEWS_ALERT_ENABLE=1
Recomendado: misma cuenta DEMO y variables que ia_auto_trade_loop.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from ia_auto_trade_loop import _demo_only_or_exit, enviar_orden
from ia_scanner_loop import analizar_ia, es_horario_seguro
from local_env import load_env_file
from m15_ma_scan import _resolve_scan_symbol
from mt5_prices import _position_side_for_bot

_CALENDAR_UNAVAILABLE_WARNED = False


def enviar_alerta_movil(mensaje: str) -> None:
    """Telegram si está configurado; siempre log (no hay message_send en la API estándar)."""
    try:
        from mt5_prices import _telegram_configured, _telegram_send

        if _telegram_configured():
            _telegram_send(mensaje)
    except Exception as e:
        print(f"Alerta Telegram falló: {e}", file=sys.stderr)
    print(f"Alerta: {mensaje}")


def hay_noticias_fuertes(simbolo: str) -> bool:
    """
    True = pausar por noticia de alto impacto en ventana próxima (UTC).
    Sin calendar_* en el binding Python → False y aviso único (no bloquea).
    """
    global _CALENDAR_UNAVAILABLE_WARNED
    if os.environ.get("IA_NEWS_FILTER", "0").strip().lower() not in ("1", "true", "yes"):
        return False

    desde = datetime.now(timezone.utc)
    hasta = desde + timedelta(minutes=int(os.environ.get("IA_NEWS_WINDOW_MIN", "30")))

    for fname in (
        "calendar_by_event",
        "calendar_event_by_currency",
        "calendar_by_country",
        "calendar_get",
    ):
        fn = getattr(mt5, fname, None)
        if not callable(fn):
            continue
        try:
            events = fn(time_from=desde, time_to=hasta)
        except TypeError:
            try:
                events = fn(desde, hasta)
            except Exception:
                continue
        except Exception:
            continue

        if not events:
            continue
        if isinstance(events, dict):
            continue
        try:
            rows = list(events) if not isinstance(events, (list, tuple)) else events
        except TypeError:
            continue
        for n in rows:
            try:
                imp = getattr(n, "importance", getattr(n, "impact", None))
                if imp == 3 or imp == "high":
                    print(
                        f"{simbolo}: noticia alto impacto próxima: "
                        f"{getattr(n, 'name', getattr(n, 'event_name', '?'))}",
                        file=sys.stderr,
                    )
                    return True
            except Exception:
                continue
        # Hubo calendario pero sin eventos de alto impacto en la ventana.
        return False

    if not _CALENDAR_UNAVAILABLE_WARNED:
        print(
            "IA_NEWS_FILTER activo pero este MetaTrader5 Python no expone calendario "
            "(calendar_*). Actualizá terminal/paquete o pon IA_NEWS_FILTER=0.",
            file=sys.stderr,
        )
        _CALENDAR_UNAVAILABLE_WARNED = True
    return False


def main() -> None:
    load_env_file()
    enable = os.environ.get("IA_NEWS_ALERT_ENABLE", "").strip().lower() in ("1", "true", "yes")
    if not enable:
        print(
            "Definí IA_NEWS_ALERT_ENABLE=1 en .env para confirmar este modo.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    os.environ.setdefault("IA_SCAN_QUIET", "1")

    raw = os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD")
    requested_list = [a.strip() for a in raw.split(",") if a.strip()]
    interval = float(os.environ.get("IA_NEWS_LOOP_INTERVAL_S", os.environ.get("IA_SCAN_INTERVAL_S", "60")))
    cooldown = float(os.environ.get("IA_AUTO_COOLDOWN_S", "900"))
    use_hours = os.environ.get("IA_AUTO_USE_HOURS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        print(f"No se pudo inicializar MT5. ({code}) {msg}", file=sys.stderr)
        raise SystemExit(1)

    try:
        ti = mt5.terminal_info()
        if ti is not None and not bool(getattr(ti, "trade_allowed", False)):
            print(
                "trade_allowed=False: activá Algo Trading en MT5.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        _demo_only_or_exit()

        resolved_map: list[tuple[str, str]] = []
        for req in requested_list:
            r = _resolve_scan_symbol(req)
            if not r:
                print(f"{req}: símbolo no operable.", file=sys.stderr)
                continue
            resolved_map.append((req, r))
        if not resolved_map:
            print("No hay símbolos válidos.", file=sys.stderr)
            raise SystemExit(1)

        print(
            f"IA noticias+alertas · DEMO · símbolos={len(resolved_map)} · "
            f"intervalo={interval}s · Ctrl+C salir"
        )

        while True:
            if use_hours and not es_horario_seguro():
                time.sleep(interval)
                continue

            traded = False
            for requested, sym in resolved_map:
                if hay_noticias_fuertes(sym):
                    continue
                if _position_side_for_bot(sym) is not None:
                    continue

                sig = analizar_ia(sym)
                if "COMPRA CONFIRMADA" in sig:
                    sent = enviar_orden(sym, buy=True)
                    if sent:
                        msg = (
                            f"IA: COMPRA límite colocada {requested} ({sym})"
                            if sent == "pending"
                            else f"IA: COMPRA ejecutada {requested} ({sym})"
                        )
                        enviar_alerta_movil(msg)
                        traded = True
                        time.sleep(cooldown)
                        break
                elif "VENTA CONFIRMADA" in sig:
                    sent = enviar_orden(sym, buy=False)
                    if sent:
                        msg = (
                            f"IA: VENTA límite colocada {requested} ({sym})"
                            if sent == "pending"
                            else f"IA: VENTA ejecutada {requested} ({sym})"
                        )
                        enviar_alerta_movil(msg)
                        traded = True
                        time.sleep(cooldown)
                        break

            if not traded:
                print(f"{datetime.now().strftime('%H:%M:%S')} escaneando...")
            time.sleep(interval)

    except KeyboardInterrupt:
        print("Detenido.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
