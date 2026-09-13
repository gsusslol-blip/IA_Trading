"""Detect LAN IPv4 addresses so phones can reach this PC."""

from __future__ import annotations

import socket


def lan_ipv4() -> list[str]:
    found: list[str] = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        primary = probe.getsockname()[0]
        probe.close()
        if _usable(primary):
            found.append(primary)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _usable(ip) and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def _usable(ip: str) -> bool:
    if not ip or ip.startswith("127."):
        return False
    if ip.startswith("169.254."):
        return False
    return True


def phone_base_urls(port: int) -> list[str]:
    return [f"http://{ip}:{port}" for ip in lan_ipv4()]
