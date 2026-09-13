"""Local process/data heal — Python only, no LLM, no arbitrary shell."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from jarvis.config import DATA_DIR, Settings
from jarvis.discover import DISCOVER_PORT
from jarvis.lan import lan_ipv4

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_last_ollama_launch = 0.0
_ha_was_down = False

_ALLOWED_RELAUNCH = frozenset({"ollama", "piper", "ha_ping"})


def heal_stack(settings: Settings) -> str | None:
    if os.getenv("SELF_HEAL", "1").strip().lower() in {"0", "false", "no"}:
        return None
    notice = ensure_ollama(settings)
    ping_home_assistant(settings)
    return notice


def ensure_ollama(settings: Settings) -> str | None:
    global _last_ollama_launch
    base = settings.ollama_base_url or "http://127.0.0.1:11434/v1"
    if _ping_ollama(base):
        return None
    now = time.monotonic()
    if now - _last_ollama_launch < 90:
        return None
    exe = _ollama_exe()
    if not exe:
        return None
    try:
        kwargs: dict[str, object] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = _CREATE_NO_WINDOW
        subprocess.Popen([str(exe), "serve"], **kwargs)
        _last_ollama_launch = now
        print("[self-heal] ollama serve launched")
        return "Ollama estaba caído. Lo volví a levantar."
    except OSError as exc:
        print(f"[self-heal] could not start Ollama: {exc}")
        return None


def ping_home_assistant(settings: Settings) -> bool:
    global _ha_was_down
    if not settings.has_ha:
        return False
    url = settings.ha_url.rstrip("/") + "/api/"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {settings.ha_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            ok = getattr(resp, "status", 200) < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        ok = False
    if ok:
        _ha_was_down = False
        return True
    if not _ha_was_down:
        print("[self-heal] Home Assistant not reachable on LAN")
    _ha_was_down = True
    return False


def get_system_health(settings: Settings) -> dict[str, Any]:
    """Flat health JSON for the LLM diagnose step. No shell, no port steal."""
    ollama_base = settings.ollama_base_url or "http://127.0.0.1:11434/v1"
    ollama_api = _ping_ollama(ollama_base)
    ollama_proc = _process_running("ollama.exe") if os.name == "nt" else _process_running("ollama")
    from jarvis.piper_tts import piper_available

    piper_ok = piper_available()
    ha_status: str | bool
    if not settings.has_ha:
        ha_status = "NOT_CONFIGURED"
    else:
        ha_status = "SUCCESS" if ping_home_assistant(settings) else "UNREACHABLE"

    hud = _http_ok(f"http://127.0.0.1:{int(settings.hud_port)}/health", timeout=1.2)
    udp = _udp_port_in_use(DISCOVER_PORT)
    ram = _ram_snapshot()
    return {
        "hud_health": "OK" if hud else "DOWN",
        "hud_port": int(settings.hud_port),
        "ollama_api": bool(ollama_api),
        "ollama_process": bool(ollama_proc),
        "ollama_alive": bool(ollama_api),
        "piper_ready": bool(piper_ok),
        "piper_running": bool(piper_ok),
        "home_assistant": ha_status,
        "udp_discover_bound": bool(udp),
        "udp_port": DISCOVER_PORT,
        "resource_usage": ram,
        "recent_logs": _tail_logs(12),
    }


def relaunch_service(settings: Settings, service: str) -> dict[str, Any]:
    """One-step allowlisted remediations only."""
    key = (service or "").strip().lower()
    if key not in _ALLOWED_RELAUNCH:
        return {
            "ok": False,
            "service": key,
            "detail": f"Servicio no permitido. Usá: {', '.join(sorted(_ALLOWED_RELAUNCH))}.",
        }
    if key == "ollama":
        notice = ensure_ollama(settings)
        alive = _ping_ollama(settings.ollama_base_url or "http://127.0.0.1:11434/v1")
        return {
            "ok": bool(alive),
            "service": "ollama",
            "detail": notice or ("Ollama responde." if alive else "No pude levantar Ollama."),
        }
    if key == "piper":
        from jarvis.piper_tts import piper_available, reset_piper_session

        reset_piper_session()
        ready = piper_available()
        return {
            "ok": ready,
            "service": "piper",
            "detail": "Piper reiniciado." if ready else "Falta binario Piper o modelo en data/tts.",
        }
    # ha_ping
    if not settings.has_ha:
        return {"ok": False, "service": "ha_ping", "detail": "HA no está configurado en .env."}
    ok = ping_home_assistant(settings)
    return {
        "ok": ok,
        "service": "ha_ping",
        "detail": "Home Assistant responde." if ok else "Home Assistant no alcanzable en la LAN.",
    }


def check_lan_status(settings: Settings) -> dict[str, Any]:
    ips = lan_ipv4()
    primary = ips[0] if ips else "127.0.0.1"
    internet = False
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(1.0)
        probe.connect(("8.8.8.8", 80))
        internet = True
        probe.close()
    except OSError:
        internet = False
    return {
        "local_ip": primary,
        "lan_ips": ips,
        "has_internet": internet,
        "hud_urls": [f"http://{ip}:{int(settings.hud_port)}" for ip in ips],
        "udp_discover_bound": _udp_port_in_use(DISCOVER_PORT),
        "udp_port": DISCOVER_PORT,
        "hud_host_bind": settings.hud_host,
    }


def _ping_ollama(base_url: str, timeout: float = 1.2) -> bool:
    raw = (base_url or "http://127.0.0.1:11434/v1").rstrip("/")
    root = raw[:-3] if raw.endswith("/v1") else raw
    for url in (f"{root}/api/tags", f"{raw}/models"):
        if _http_ok(url, timeout=timeout):
            return True
    return False


def _http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return getattr(resp, "status", 200) < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _ollama_exe() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if local.is_file():
        return local
    return None


def _process_running(image: str) -> bool:
    name = (image or "").strip().lower()
    if not name:
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        blob = (completed.stdout or "").lower()
        return name in blob and "no tasks" not in blob and "no hay tareas" not in blob
    try:
        completed = subprocess.run(
            ["pgrep", "-x", name.replace(".exe", "")],
            capture_output=True,
            timeout=5,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _udp_port_in_use(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", int(port)))
        return False
    except OSError:
        return True
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _ram_snapshot() -> dict[str, Any]:
    if os.name != "nt":
        return {"ram_load_pct": 0, "ram_available_gb": 0}
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return {"ram_load_pct": 0, "ram_available_gb": 0}
        return {
            "ram_load_pct": int(stat.dwMemoryLoad),
            "ram_available_gb": round(float(stat.ullAvailPhys) / (1024**3), 2),
        }
    except Exception:
        return {"ram_load_pct": 0, "ram_available_gb": 0}


def _tail_logs(n: int = 12) -> list[str]:
    candidates = [
        DATA_DIR / "jarvis.log",
        DATA_DIR / "runtime.log",
        Path.cwd() / "logs" / "jarvis.log",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return [line[:240] for line in lines[-max(1, n) :]]
        except OSError:
            continue
    return []


def health_report_text(settings: Settings) -> str:
    return json.dumps(get_system_health(settings), ensure_ascii=False, indent=2)
