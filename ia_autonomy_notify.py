"""
Alertas Telegram de autonomía (cortacircuitos, cambio de régimen).

Reutiliza ``telegram_utils.enviar_alerta_telegram`` (urllib, sin requests).
"""

from __future__ import annotations

import os
import time

from telegram_utils import enviar_alerta_telegram

_LAST_SENT_MONO: dict[str, float] = {}


def _autonomy_tg_enabled() -> bool:
    return os.environ.get("IA_AUTONOMY_TG_ENABLE", "1").strip().lower() in ("1", "true", "yes")


def _cooldown_s() -> float:
    try:
        return float(os.environ.get("IA_AUTONOMY_TG_COOLDOWN_S", "900").strip() or "900")
    except ValueError:
        return 900.0


def _should_send(dedupe_key: str) -> bool:
    if not _autonomy_tg_enabled():
        return False
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and not os.environ.get(
        "TELEGRAM_TOKEN", ""
    ).strip():
        return False
    if not os.environ.get("TELEGRAM_CHAT_ID", "").strip():
        return False
    cd = max(60.0, _cooldown_s())
    now = time.monotonic()
    last = _LAST_SENT_MONO.get(dedupe_key, 0.0)
    if now - last < cd:
        return False
    _LAST_SENT_MONO[dedupe_key] = now
    return True


def notify_circuit_breaker(
    symbol: str,
    *,
    streak: int,
    limit: int,
    per_symbol: bool = False,
    halt_hours: float = 0.0,
) -> bool:
    """Aviso de cortacircuitos por racha de pérdidas."""
    key = f"circuit:{symbol if per_symbol else 'global'}"
    if not _should_send(key):
        return False
    scope = f"símbolo <b>{symbol}</b>" if per_symbol else "cuenta (BOT_MAGIC)"
    halt_line = (
        f"\nPausa programada: <b>{halt_hours:g} h</b> (IA_STREAK_HALT_HOURS)."
        if halt_hours > 0
        else ""
    )
    msg = (
        "<b>IA_Trading — CORTACIRCUITOS</b>\n\n"
        f"Racha de <b>{streak}</b> pérdidas consecutivas ({scope}; límite {limit}).\n"
        "Nuevas entradas bloqueadas para proteger capital."
        f"{halt_line}"
    )
    ok = enviar_alerta_telegram(msg)
    if not ok:
        print("[TG] No se pudo enviar alerta de cortacircuitos.", flush=True)
    return ok


def notify_circuit_halt_global(reason: str) -> bool:
    """Pausa total del ciclo por halt temporal de racha."""
    if not _should_send("circuit:halt_global"):
        return False
    msg = (
        "<b>IA_Trading — CICLO EN PAUSA</b>\n\n"
        f"{reason}\n"
        "<i>Solo gestión de posiciones abiertas hasta que expire el halt.</i>"
    )
    return enviar_alerta_telegram(msg)


def notify_mt5_reconnected() -> bool:
    if not _should_send("mt5:reconnected"):
        return False
    msg = (
        "<b>IA_Trading — CONEXIÓN RESTAURADA</b>\n\n"
        "El bot recuperó el enlace con el servidor del bróker (MT5)."
    )
    return enviar_alerta_telegram(msg)


def notify_mt5_connection_failed(attempts: int) -> bool:
    if not _should_send("mt5:failed"):
        return False
    msg = (
        "<b>IA_Trading — ERROR DE CONEXIÓN MT5</b>\n\n"
        f"No se pudo reconectar tras <b>{attempts}</b> intentos.\n"
        "<i>Ciclo en pausa; revisá terminal, red y AutoTrading.</i>"
    )
    return enviar_alerta_telegram(msg)


def notify_margin_blocked(symbol: str, volume: float, reason: str) -> bool:
    if not _should_send(f"margin:{symbol}"):
        return False
    msg = (
        "<b>IA_Trading — ALERTA DE MARGEN</b>\n\n"
        f"Orden bloqueada: <b>{symbol}</b> vol=<code>{volume:g}</code>\n"
        f"Motivo: {reason}"
    )
    return enviar_alerta_telegram(msg)


def notify_news_shield_active(detail: str = "") -> bool:
    if not _should_send("news:shield_on"):
        return False
    extra = f"\nPróximo/evento: <code>{detail}</code>" if detail else ""
    msg = (
        "<b>IA_Trading — ESCUDO DE NOTICIAS</b>\n\n"
        "Noticia de <b>alto impacto (USD)</b> en ventana de riesgo.\n"
        "Scanner pausado; gestión de posiciones abiertas (SL/TP/BE) sigue activa."
        f"{extra}"
    )
    return enviar_alerta_telegram(msg)


def notify_news_shield_cleared() -> bool:
    if not _should_send("news:shield_off"):
        return False
    msg = (
        "<b>IA_Trading — MERCADO LIBRE DE NOTICIAS</b>\n\n"
        "Finalizó la ventana de alta volatilidad macro. El scanner vuelve en línea."
    )
    return enviar_alerta_telegram(msg)


def notify_spread_autotune(avg_slip_pts: float, strict_pctl: float) -> bool:
    if not _should_send("autotune:spread"):
        return False
    msg = (
        "<b>IA_Trading — AUTO-TUNE SPREAD</b>\n\n"
        f"Slippage medio reciente: <b>{avg_slip_pts:.1f}</b> pts\n"
        f"Percentil dinámico endurecido a <b>{strict_pctl:g}</b>."
    )
    return enviar_alerta_telegram(msg)


def notify_regime_change(symbol: str, regimen: str, rr_dinamico: float) -> bool:
    """Aviso cuando el régimen autónomo cambia respecto al ciclo anterior."""
    key = f"regime:{symbol}:{regimen}"
    if not _should_send(key):
        return False
    msg = (
        "<b>IA_Trading — CAMBIO DE RÉGIMEN</b>\n\n"
        f"Activo: <b>{symbol}</b>\n"
        f"Estado: <code>{regimen}</code>\n"
        f"R:R objetivo: <b>1:{rr_dinamico:g}</b>\n"
        "<i>Parámetros del scanner ajustados en memoria.</i>"
    )
    ok = enviar_alerta_telegram(msg)
    if not ok:
        print("[TG] No se pudo enviar alerta de régimen.", flush=True)
    return ok
