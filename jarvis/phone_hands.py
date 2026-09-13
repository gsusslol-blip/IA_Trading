"""Queue Android intents for the phone app. PC never executes them."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from jarvis.bank_apps import is_banking

ALLOWED = frozenset(
    {
        "call",
        "sms",
        "whatsapp",
        "maps",
        "navigate",
        "browser",
        "search",
        "open_app",
        "torch",
        "camera",
        "gallery",
        "settings",
        "wifi",
        "bluetooth",
        "volume",
        "share",
        "clipboard",
        "alarm",
        "timer",
        "calendar",
        "contacts",
        "email",
        "music",
        "youtube",
    }
)

_APPS = {
    "whatsapp": "com.whatsapp",
    "telegram": "org.telegram.messenger",
    "instagram": "com.instagram.android",
    "youtube": "com.google.android.youtube",
    "spotify": "com.spotify.music",
    "maps": "com.google.android.apps.maps",
    "gmail": "com.google.android.gm",
    "chrome": "com.android.chrome",
    "fotos": "com.google.android.apps.photos",
    "photos": "com.google.android.apps.photos",
    "telefono": "com.android.dialer",
    "mensajes": "com.google.android.apps.messaging",
    "reloj": "com.google.android.deskclock",
    "camara": "com.android.camera",
    "camera": "com.android.camera",
}

_PHONE = re.compile(r"[^\d+]+")


def queue_action(queue: list[dict[str, Any]], raw: dict[str, Any]) -> str:
    action = str(raw.get("action") or "").strip().lower()
    if action not in ALLOWED:
        return f"Accion de celular no permitida: {action or '(vacia)'}."
    item: dict[str, Any] = {"action": action}
    target = str(raw.get("target") or "").strip()
    text = str(raw.get("text") or "").strip()[:2000]
    if action in {"call", "sms", "whatsapp"}:
        phone = _PHONE.sub("", target)[:20]
        if len(re.sub(r"[^\d]", "", phone)) < 6:
            return "Falta un numero de telefono valido."
        item["target"] = phone
        if text:
            item["text"] = text
    elif action in {"maps", "navigate", "browser", "search", "share", "clipboard", "email", "music", "youtube"}:
        if not target and not text:
            return "Falta destino o texto."
        if action == "browser":
            url = target or text
            if not url.startswith(("http://", "https://")):
                url = "https://" + url.lstrip("/")
            if not url.startswith(("http://", "https://")):
                return "URL invalida."
            item["target"] = url[:2000]
        else:
            item["target"] = (target or text)[:500]
            if text and action != "browser":
                item["text"] = text
    elif action == "open_app":
        key = (target or text).strip()
        if not key or len(key) > 80 or "/" in key or "\\" in key or ".." in key:
            return "Nombre de app invalido."
        if is_banking(key):
            return "No abro apps bancarias."
        pkg = _APPS.get(key.lower(), "")
        if not pkg and key.count(".") >= 1 and re.fullmatch(r"[a-zA-Z0-9._]+", key):
            if is_banking(key):
                return "No abro apps bancarias."
            pkg = key
        if pkg and is_banking(pkg):
            return "No abro apps bancarias."
        item["target"] = pkg or key
        item["text"] = key.lower()
    elif action == "torch":
        item["target"] = "on" if (target or text).strip().lower() in {"", "on", "1", "true", "prender", "encender"} else "off"
    elif action == "volume":
        item["target"] = (target or text or "up").strip().lower()[:16]
    elif action in {"alarm", "timer"}:
        item["target"] = (target or "1").strip()[:16]
        if text:
            item["text"] = text[:80]
    queue.append(item)
    return "OK: el celular va a ejecutar " + json.dumps(item, ensure_ascii=False)
