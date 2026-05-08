"""
Prueba rápida: envía "hola" por Telegram.

La API de bots NO usa números de teléfono; necesitás:
  TELEGRAM_BOT_TOKEN — de @BotFather
  TELEGRAM_CHAT_ID — lo sacás de getUpdates después de escribirle al bot

PowerShell:
  $env:TELEGRAM_BOT_TOKEN="..."
  $env:TELEGRAM_CHAT_ID="..."
  python telegram_hola.py
"""

from __future__ import annotations

import json
import os
import sys

from local_env import load_env_file
import urllib.error
import urllib.parse
import urllib.request


def main() -> None:
    load_env_file()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    text = os.environ.get("TELEGRAM_MSG", "hola")

    if not token or not chat_id:
        print(
            "Definí TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.\n"
            "El número +54... no sirve para bots: Telegram usa chat_id.\n"
            "Pasos: creá el bot con @BotFather, abrilo en Telegram y tocá Iniciar;\n"
            "luego abrí https://api.telegram.org/bot<TOKEN>/getUpdates y copiá chat.id",
            file=sys.stderr,
        )
        raise SystemExit(1)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            body = json.loads(raw.decode("utf-8"))
            if body.get("ok"):
                print("OK — mensaje enviado.")
                return
            print(f"Error API: {body}", file=sys.stderr)
            raise SystemExit(1)
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
