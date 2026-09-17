"""UDP LAN beacon so the phone finds this PC without typing an IP.

Primary protocol (Android Kotlin LanFind): probe ``ILARIA?`` → ``ILARIA1`` + JSON url.
Legacy/simple ping (sample Java clients): ``ILARIA_CLIENT_PING`` → ``ILARIA_SERVER_ACK``
(+ also the JSON reply so modern apps still get the full HUD URL).

UDP listens on DISCOVER_PORT (8788), never on the HTTP HUD port (8787).
"""

from __future__ import annotations

import json
import socket
import threading

from jarvis import __version__
from jarvis.config import Settings
from jarvis.lan import lan_ipv4

PROBE = b"ILARIA?"
PROBE_PING = b"ILARIA_CLIENT_PING"
MAGIC = b"ILARIA1"
ACK_SIMPLE = b"ILARIA_SERVER_ACK"
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


def _normalize_probe(data: bytes) -> str:
    return data.strip().decode("utf-8", errors="ignore").strip()


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
            probe = _normalize_probe(data)
            if probe not in {"ILARIA?", "ILARIA_CLIENT_PING"}:
                continue
            base = hud_base_url(settings.hud_port)
            try:
                if probe == "ILARIA_CLIENT_PING":
                    # Simple ACK for Java-style clients (they use rinfo.address as PC IP).
                    sock.sendto(ACK_SIMPLE, addr)
                # Always send JSON URL reply (Kotlin LanFind + any client that parses MAGIC).
                sock.sendto(build_reply(base), addr)
            except OSError:
                continue

    threading.Thread(target=_run, name="ilaria-discover", daemon=True).start()
