"""
Envío de alertas a Telegram (API oficial de bots).

Usa TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID (o TELEGRAM_TOKEN como alias del token).
URL correcta: https://api.telegram.org/bot<token>/sendMessage  (no telegram.org sin api.)

Sin dependencia obligatoria de requests: usa urllib (mismo criterio que mt5_prices).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def _resolve_credentials(
    token: str | None,
    chat_id: str | None,
) -> tuple[str, str]:
    tok = (token or os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN", "")).strip()
    cid = (chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    return tok, cid


def enviar_alerta_telegram(
    mensaje: str,
    token: str | None = None,
    chat_id: str | None = None,
    *,
    parse_mode: str | None = None,
) -> bool:
    """
    Envía texto al chat. Devuelve True si la API respondió ok.

    parse_mode: si None, usa TELEGRAM_PARSE_MODE del entorno; si vacío, sin formato (evita errores).
    """
    tok, cid = _resolve_credentials(token, chat_id)
    if not tok or not cid:
        return False

    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    if parse_mode is None:
        parse_mode = os.environ.get("TELEGRAM_PARSE_MODE", "HTML").strip() or ""

    body: dict[str, str | bool] = {
        "chat_id": cid,
        "text": mensaje[:4090],
        "disable_web_page_preview": True,
    }
    if parse_mode:
        body["parse_mode"] = parse_mode

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        timeout = float(os.environ.get("TELEGRAM_TIMEOUT_S", "15").strip() or "15")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.status != 200:
                print(f"[TG] HTTP {resp.status}: {raw[:200]!r}")
                return False
            out = json.loads(raw.decode("utf-8"))
            if not out.get("ok"):
                print(f"[TG] API ok=false: {out!r}")
                return False
            return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"[TG] HTTPError {e.code}: {err_body[:400]}")
        return False
    except Exception as e:
        print(f"[TG] Error enviando a Telegram: {e}")
        return False


def format_operacion_alert_html(
    symbol: str,
    *,
    side_label: str,
    score: int | None,
    volume: float,
    sl: float,
    tp: float,
    trailing_tp: bool,
    rr: float,
    dxy_line: str,
    session_line: str,
) -> str:
    """HTML compatible con parse_mode HTML de Telegram."""
    sc = f"{score}" if score is not None else "N/D"
    tp_txt = "Trailing ATR (sin TP fijo)" if trailing_tp else f"{tp:.5f} (RR ~{rr:g}:1 vs SL)"
    return (
        f"<b>NUEVA OPERACION {symbol}</b>\n\n"
        f"Lado: <b>{side_label}</b>\n"
        f"Score IA: <code>{sc}</code>\n"
        f"Lotes: <code>{volume:g}</code>\n"
        f"SL (precio): <code>{sl:.5f}</code>\n"
        f"TP: <code>{tp_txt}</code>\n\n"
        f"Contexto DXY: {dxy_line}\n"
        f"Sesion: {session_line}"
    )
