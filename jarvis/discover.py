"""UDP LAN beacon so the phone finds this PC without typing an IP."""

from __future__ import annotations

import json
import socket
import threading

from jarvis import __version__
from jarvis.config import Settings
from jarvis.lan import lan_ipv4

PROBE = b"ILARIA?"
MAGIC = b"ILARIA1"
DISCOVER_PORT = 8788


def hud_base_url(port: int) -> str:
    ips = lan_ipv4()
    host = ips[0] if ips else "127.0.0.1"
    return f"http://{host}:{port}"


def build_reply(base_url: str, version: str = __version__) -> bytes:
    body = json.dumps(
        {"app": "Ilaria", "url": base_url, "v": version},
        separators=(",", ":"),
    )
    return MAGIC + body.encode("utf-8")


def parse_reply(raw: bytes) -> str | None:
    if not raw.startswith(MAGIC):
        return None
    try:
        payload = json.loads(raw[len(MAGIC) :].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if payload.get("app") != "Ilaria":
        return None
    url = str(payload.get("url") or "").strip().rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        return None
    return url


def start_discover(settings: Settings) -> None:
    if settings.hud_host not in {"0.0.0.0", "::"}:
        return

    def _run() -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind(("0.0.0.0", DISCOVER_PORT))
        except OSError as exc:
            print(f"[!] Descubrimiento LAN no pudo abrir UDP {DISCOVER_PORT}: {exc}")
            return
        print(f"[+] Celular: buscar en Wi-Fi (UDP {DISCOVER_PORT}) → {hud_base_url(settings.hud_port)}")
        while True:
            try:
                data, addr = sock.recvfrom(256)
            except OSError:
                return
            if data.strip() != PROBE:
                continue
            reply = build_reply(hud_base_url(settings.hud_port))
            try:
                sock.sendto(reply, addr)
            except OSError:
                continue

    threading.Thread(target=_run, name="ilaria-discover", daemon=True).start()
