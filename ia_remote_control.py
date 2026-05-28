"""
Control remoto: botón de pánico Telegram (/PANIC, /DETENER, /INICIAR).

Polling liviano de getUpdates (urllib, sin requests). Ver variables ``IA_TELEGRAM_PANIC_*``.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _offset_file() -> Path:
    raw = os.environ.get("IA_TELEGRAM_PANIC_OFFSET_FILE", "").strip()
    root = Path(__file__).resolve().parent
    if not raw:
        return root / "ia_telegram_panic_offset.json"
    p = Path(raw)
    return p if p.is_absolute() else root / p


def _load_offset() -> int | None:
    p = _offset_file()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        n = data.get("offset")
        return int(n) if n is not None else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _save_offset(offset: int) -> None:
    p = _offset_file()
    p.write_text(
        json.dumps({"offset": offset, "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ")}, indent=2),
        encoding="utf-8",
    )


def _token_bot() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN", "") or "").strip()


def _chat_autorizado() -> str:
    return (os.environ.get("TELEGRAM_CHAT_ID", "") or "").strip()


def _get_updates(tok: str, offset: int | None) -> tuple[list[dict[str, Any]], list[int]]:
    q: dict[str, str | int] = {"timeout": 0}
    if offset is not None:
        q["offset"] = int(offset)
    qs = urllib.parse.urlencode(q)
    url = f"https://api.telegram.org/bot{tok}/getUpdates?{qs}"
    req = urllib.request.Request(url, method="GET")
    tout = float(os.environ.get("TELEGRAM_TIMEOUT_S", "15").strip() or "15")
    try:
        with urllib.request.urlopen(req, timeout=tout) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        print(f"[panic] getUpdates: {e}", file=sys.stderr)
        return [], []
    if not isinstance(data, dict) or not data.get("ok"):
        return [], []
    res = data.get("result") or []
    ids: list[int] = []
    if isinstance(res, list):
        for u in res:
            if isinstance(u, dict) and "update_id" in u:
                try:
                    ids.append(int(u["update_id"]))
                except (TypeError, ValueError):
                    pass
        return res, ids  # type: ignore[return-value]
    return [], []


def _parse_chat_and_text(upd: dict[str, Any]) -> tuple[str | None, str | None]:
    msg = upd.get("message")
    if isinstance(msg, dict):
        cid = msg.get("chat", {}).get("id") if isinstance(msg.get("chat"), dict) else None
        text = msg.get("text") if isinstance(msg.get("text"), str) else None
        try:
            cids = str(int(cid)) if cid is not None else None
        except (TypeError, ValueError):
            cids = str(cid).strip() if cid is not None else None
        return cids, text
    return None, None


def _comando_del_texto(raw: str) -> str | None:
    parts = raw.strip().split()
    if not parts:
        return None
    tok0 = parts[0].split("@", 1)[0]
    if not tok0.startswith("/"):
        return None
    cmd = tok0[1:].upper()
    if cmd in ("DETENER", "STOP", "PANIC"):
        return "STOP"
    if cmd in ("INICIAR", "RESUME", "GO"):
        return "RESUME"
    if cmd in ("STATUS", "STATE"):
        return "STATUS"
    if cmd in ("BITACORA", "BITÁCORA", "JOURNAL"):
        return "BITACORA"
    if cmd == "START" and os.environ.get(
        "IA_TELEGRAM_PANIC_TRUST_RESUME_START", "0"
    ).strip().lower() in ("1", "true", "yes"):
        return "RESUME"
    return None


_PRIMERA_VUELTA: bool = True


def poll_telegram_panic_commands() -> str | None:
    """Devuelve ``STOP``, ``RESUME``, ``STATUS``, ``BITACORA`` o ``None``."""
    global _PRIMERA_VUELTA

    if os.environ.get("IA_TELEGRAM_PANIC_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return None

    tok = _token_bot()
    want_chat = _chat_autorizado()
    if not tok or not want_chat:
        return None

    siguiente_off = _load_offset()
    updates, ids = _get_updates(tok, siguiente_off)

    consume_backlog = os.environ.get("IA_TELEGRAM_PANIC_CONSUME_BACKLOG", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    if not ids:
        _PRIMERA_VUELTA = False
        return None

    max_id = max(ids)
    siguiente = max_id + 1
    outcome: str | None = None

    if _PRIMERA_VUELTA and not consume_backlog:
        _PRIMERA_VUELTA = False
        try:
            _save_offset(siguiente)
        except OSError:
            print("[panic] No se pudo guardar offset de Telegram.", file=sys.stderr)
        return None

    _PRIMERA_VUELTA = False
    cmd_last: str | None = None
    for upd in sorted(updates, key=lambda u: int((u.get("update_id") or 0) if isinstance(u, dict) else 0)):
        if not isinstance(upd, dict):
            continue
        cht, txt = _parse_chat_and_text(upd)
        if txt is None or not cht or cht != want_chat.strip():
            continue
        parsed = _comando_del_texto(txt)
        if parsed is not None:
            cmd_last = parsed
    outcome = cmd_last

    try:
        _save_offset(siguiente)
    except OSError:
        print("[panic] No se pudo guardar offset de Telegram.", file=sys.stderr)

    return outcome


def cerrar_posiciones_panico_ia_auto(*, deviation: int | None = None) -> tuple[int, int]:
    """Cierra todas las posiciones con ``BOT_MAGIC``. (ok, fallos)."""
    try:
        import MetaTrader5 as mt5

        from mt5_prices import BOT_MAGIC, _close_position_ticket
    except ImportError:
        print("[panic] MT5/mt5_prices no disponible.", file=sys.stderr)
        return 0, 1

    dev = deviation
    if dev is None:
        try:
            dev = int(os.environ.get("DEVIATION", "20").strip() or "20")
        except ValueError:
            dev = 20

    ok_ct = fa_ct = 0
    tickets: list[int] = []
    for p in mt5.positions_get() or []:
        try:
            if int(getattr(p, "magic", -999) or -999) != BOT_MAGIC:
                continue
            t = int(getattr(p, "ticket", 0) or 0)
            if t > 0:
                tickets.append(t)
        except (TypeError, ValueError):
            continue

    for t in sorted(set(tickets)):
        if _close_position_ticket(t, dev):
            ok_ct += 1
        else:
            fa_ct += 1
        time.sleep(0.18)
    return ok_ct, fa_ct


def cancelar_ordenes_pendientes_bot_panico() -> int:
    if os.environ.get("IA_TELEGRAM_PANIC_CANCEL_PENDING", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return 0
    try:
        import MetaTrader5 as mt5

        from mt5_prices import BOT_MAGIC
    except ImportError:
        return 0

    orders = mt5.orders_get()
    if not orders:
        return 0
    done_rc = int(getattr(mt5, "TRADE_RETCODE_DONE", 10009))
    n = 0
    for o in orders:
        try:
            if int(getattr(o, "magic", -999) or -999) != BOT_MAGIC:
                continue
            oid = int(getattr(o, "ticket", 0) or 0)
        except (TypeError, ValueError):
            continue
        if oid <= 0:
            continue
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": oid})
        if r is not None and int(getattr(r, "retcode", -1)) == done_rc:
            n += 1
        time.sleep(0.08)
    return n
