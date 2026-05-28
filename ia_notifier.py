"""
Alertas Telegram ligeras (facade sobre ``telegram_utils``).

Uso recomendado en el proyecto:
  ``from ia_notifier import enviar_alerta_telegram``
"""

from __future__ import annotations

import MetaTrader5 as mt5

from telegram_utils import (
    enviar_alerta_telegram,
    enviar_documento_telegram,
    format_operacion_alert_html,
)

__all__ = [
    "enviar_alerta_telegram",
    "enviar_documento_telegram",
    "format_operacion_alert_html",
    "notify_mt5_trade_retcode_if_critical",
]


def _critical_trade_retcodes() -> set[int]:
    return {
        10016,
        10019,
        int(getattr(mt5, "TRADE_RETCODE_INVALID_STOPS", 10016)),
        int(getattr(mt5, "TRADE_RETCODE_NO_MONEY", 10019)),
    }


def notify_mt5_trade_retcode_if_critical(
    symbol: str,
    retcode: int,
    comment: str = "",
) -> bool:
    """
    Notifica por Telegram si MT5 devuelve 10016 (stops inválidos) o 10019 (sin margen).
    """
    rc = int(retcode)
    if rc not in _critical_trade_retcodes():
        return False
    label = "INVALID STOPS (10016)" if rc in (10016, int(getattr(mt5, "TRADE_RETCODE_INVALID_STOPS", 10016))) else "NO MONEY (10019)"
    extra = f"\nComentario: <code>{comment}</code>" if comment else ""
    msg = (
        f"<b>IA_Trading — ERROR MT5</b>\n\n"
        f"Símbolo: <b>{symbol}</b>\n"
        f"Código: <b>{label}</b>{extra}"
    )
    ok = enviar_alerta_telegram(msg)
    if not ok:
        print(f"[TG] No se pudo enviar alerta retcode={rc}", flush=True)
    return ok
