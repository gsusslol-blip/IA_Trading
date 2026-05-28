"""
Reporte de bienvenida al arranque: diagnóstico MT5 + entorno y envío a Telegram (una vez por proceso).

Variables:
  IA_WELCOME_ENABLE=1
  IA_BOT_VERSION=2.0.0
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ia_paths import project_root, resolve_data_path


def welcome_enabled() -> bool:
    return os.environ.get("IA_WELCOME_ENABLE", "1").strip().lower() in ("1", "true", "yes")


def _bot_version() -> str:
    return (os.environ.get("IA_BOT_VERSION", "2.0.0").strip() or "2.0.0")


def _model_path() -> Path:
    return resolve_data_path("IA_ML_MODEL_PATH", "modelos/filtro_falsos_rompimientos.pkl")


def _fmt_money(value: float, currency: str) -> str:
    cur = (currency or "").strip() or "USD"
    try:
        return f"{float(value):,.2f} {cur}"
    except (TypeError, ValueError):
        return f"? {cur}"


def _account_kind(cuenta, broker: str) -> str:
    import MetaTrader5 as mt5

    srv = broker.upper()
    if "DEMO" in srv:
        return "DEMO"
    trade_mode = getattr(cuenta, "trade_mode", None)
    demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
    if demo_mode is not None and trade_mode == demo_mode:
        return "DEMO"
    return "REAL"


def _diagnostico_archivos(root: Path) -> list[str]:
    lines: list[str] = []
    checks = [
        ("Watchdog VPS", root / "ia_watchdog.bat"),
        (".env raíz", root / ".env"),
        ("config/.env", root / "config" / ".env"),
        ("Modelo ML", _model_path()),
        ("Auditoría ML", resolve_data_path("IA_ML_AUDIT_CSV", "logs/trade_audit_ml.csv")),
        ("Calidad ejecución", resolve_data_path("IA_EXEC_QUALITY_CSV", "logs/execution_quality.csv")),
        ("Carpeta logs/", root / "logs"),
        ("Carpeta modelos/", root / "modelos"),
    ]
    for label, path in checks:
        ok = path.is_file() or path.is_dir()
        mark = "OK" if ok else "—"
        rel = path.name if path.parent == root else str(path.relative_to(root))
        lines.append(f"• {label}: <code>{mark}</code> ({rel})")
    return lines


def _capas_seguridad_activas() -> str:
    parts: list[str] = []
    if os.environ.get("IA_NEWS_FILTER_ENABLE", "0").strip().lower() in ("1", "true", "yes"):
        parts.append("News Filter")
    if os.environ.get("IA_GOLD_RISK_ENABLE", "1").strip().lower() in ("1", "true", "yes"):
        parts.append("Risk Oro (contract_size)")
    if os.environ.get("IA_STREAK_ENABLE", "0").strip().lower() in ("1", "true", "yes"):
        parts.append("Loss-Streak breaker")
    if os.environ.get("IA_TELEGRAM_PANIC_ENABLE", "0").strip().lower() in ("1", "true", "yes"):
        parts.append("/PANIC remoto")
    if os.environ.get("IA_ML_FILTER_ENABLE", "0").strip().lower() in ("1", "true", "yes"):
        parts.append("Filtro ML")
    if os.environ.get("IA_MARGIN_CHECK_ENABLE", "1").strip().lower() in ("1", "true", "yes"):
        parts.append("Chequeo margen")
    return ", ".join(parts) if parts else "config por defecto (.env)"


def enviar_reporte_bienvenida(
    magic_number: int | None = None,
    *,
    version: str | None = None,
) -> bool:
    """
    Diagnóstico de cuenta y entorno; un mensaje a Telegram por arranque del proceso.
    """
    if not welcome_enabled():
        return False

    import MetaTrader5 as mt5

    cuenta = mt5.account_info()
    terminal = mt5.terminal_info()
    if cuenta is None or terminal is None:
        print("[welcome] No se pudo leer account_info o terminal_info.", file=sys.stderr)
        return False

    mag = int(magic_number if magic_number is not None else int(os.environ.get("BOT_MAGIC", "260505")))
    ver = version or _bot_version()
    root = project_root()

    broker = str(getattr(cuenta, "company", "") or getattr(cuenta, "server", "") or "?")
    login = int(getattr(cuenta, "login", 0) or 0)
    tipo = _account_kind(cuenta, broker)
    currency = str(getattr(cuenta, "currency", "USD") or "USD")

    balance = _fmt_money(float(getattr(cuenta, "balance", 0.0) or 0.0), currency)
    equity = _fmt_money(float(getattr(cuenta, "equity", 0.0) or 0.0), currency)
    margin_free = _fmt_money(float(getattr(cuenta, "margin_free", 0.0) or 0.0), currency)
    leverage = int(getattr(cuenta, "leverage", 0) or 0)

    hora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    term_name = str(getattr(terminal, "name", "") or "")
    vps = "SÍ" if "vps" in term_name.lower() or (root / "ia_watchdog.bat").is_file() else "NO"
    trade_ok = "SÍ" if bool(getattr(terminal, "trade_allowed", False)) else "NO"

    if _model_path().is_file():
        ia_estado = "LISTO (RandomForest)"
    else:
        ia_estado = "PENDIENTE (+30 trades en auditoría)"

    symbols = os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").strip() or "XAUUSD"
    archivos_html = "\n".join(_diagnostico_archivos(root))
    seguridad = _capas_seguridad_activas()

    mensaje = (
        f"🤖 <b>IA_Trading — SISTEMA INICIALIZADO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚀 <b>Estado:</b> EN LÍNEA (v<code>{ver}</code>)\n"
        f"🔒 <b>Magic:</b> <code>{mag}</code>\n"
        f"📊 <b>Filtro IA:</b> {ia_estado}\n"
        f"📌 <b>Símbolos:</b> <code>{symbols}</code>\n\n"
        f"🏦 <b>CUENTA</b>\n"
        f"• Bróker: <code>{broker}</code>\n"
        f"• Login: <code>{login}</code> (<b>{tipo}</b>)\n"
        f"• Balance: <code>{balance}</code>\n"
        f"• Equidad: <code>{equity}</code>\n"
        f"• Margen libre: <code>{margin_free}</code>\n"
        f"• Apalancamiento: <code>1:{leverage}</code>\n\n"
        f"🛠️ <b>ENTORNO</b>\n"
        f"• MT5: <code>{term_name or 'conectado'}</code>\n"
        f"• Algo trading: <code>{trade_ok}</code>\n"
        f"• Soporte VPS: <code>{vps}</code>\n"
        f"• Inicio: <code>{hora}</code>\n\n"
        f"📁 <b>ARCHIVOS CLAVE</b>\n"
        f"{archivos_html}\n\n"
        f"🛡️ <b>Capas:</b> {seguridad}\n\n"
        f"✨ <i>Scanner M15 activo — buscando configuraciones de alta probabilidad.</i>"
    )

    from telegram_utils import enviar_alerta_telegram

    ok = enviar_alerta_telegram(mensaje, parse_mode="HTML")
    if ok:
        print("[welcome] Informe de bienvenida enviado a Telegram.", flush=True)
    else:
        print(
            "[welcome] Telegram no configurado o falló el envío (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).",
            file=sys.stderr,
        )
    return bool(ok)
