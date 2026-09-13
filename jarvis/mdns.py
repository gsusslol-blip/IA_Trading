"""Optional LAN hostname via mDNS (ilaria.local). Needs zeroconf if MDNS=1."""

from __future__ import annotations

import socket
import threading
from typing import Any

from jarvis.config import Settings


def start_mdns(settings: Settings) -> None:
    if not settings.mdns_enabled:
        return

    def _run() -> None:
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            print("[!] MDNS=1 pero falta zeroconf. pip install zeroconf")
            return
        host = (settings.mdns_hostname or "ilaria").strip() or "ilaria"
        try:
            ip = socket.gethostbyname(socket.gethostname())
            packed = socket.inet_aton(ip)
        except OSError:
            packed = socket.inet_aton("127.0.0.1")
        info = ServiceInfo(
            "_http._tcp.local.",
            f"{host}._http._tcp.local.",
            addresses=[packed],
            port=settings.hud_port,
            properties={"path": "/", "app": "Ilaria"},
            server=f"{host}.local.",
        )
        zero: Any = Zeroconf()
        zero.register_service(info)
        print(f"[+] mDNS: http://{host}.local:{settings.hud_port}")

    threading.Thread(target=_run, name="ilaria-mdns", daemon=True).start()
