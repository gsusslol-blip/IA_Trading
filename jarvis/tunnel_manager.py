"""Optional WAN tunnel (ngrok) so phones can reach HUD :8787 off LAN.

Soft-depends on ``pyngrok``. Without NGROK_AUTHTOKEN, Ilaria stays LAN-only.
Invoked from runtime after the HUD is healthy — not as a second ``run.bat`` process.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from jarvis.config import Settings, load_settings
from jarvis.remote_bridge import remote_workspace

_lock = threading.Lock()
_public_url: str | None = None
_started = False


def sync_path(settings: Settings | None = None) -> Path:
    return remote_workspace(settings=settings) / "network_sync.json"


def read_sync_url(settings: Settings | None = None) -> str | None:
    path = sync_path(settings)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    url = str(data.get("remote_url") or "").strip().rstrip("/")
    if url.startswith("https://") or url.startswith("http://"):
        return url
    return None


def write_sync_url(public_url: str, settings: Settings | None = None) -> Path:
    path = sync_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    deep = f"ilaria://sync?url={public_url.rstrip('/')}"
    payload = {
        "remote_url": public_url.rstrip("/"),
        "deep_link": deep,
        "last_update": time.time(),
        "tunnel_active": True,
        "proto": "https" if public_url.startswith("https://") else "http",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def qr_svg_path() -> Path:
    from jarvis.config import DATA_DIR

    folder = DATA_DIR / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "sync_qr.svg"


def generar_qr_deep_link(public_url: str) -> Path | None:
    """Write SVG QR for ilaria://sync?url=… (phone camera / Profile scanner)."""
    deep_link = f"ilaria://sync?url={public_url.rstrip('/')}"
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        print("[TUNNEL] Falta qrcode. Instalá: pip install qrcode")
        return None
    try:
        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(deep_link, image_factory=factory, box_size=8, border=2)
        path = qr_svg_path()
        with path.open("wb") as handle:
            img.save(handle)
        print(f"[TUNNEL] Código QR de sincronización: {path}")
        return path
    except Exception as exc:  # noqa: BLE001
        print(f"[TUNNEL] No pude generar QR: {exc}")
        return None


def hud_network_state(settings: Settings | None = None) -> dict[str, Any]:
    """Lightweight LAN/WAN telemetry for /api/stack-health + HUD panel."""
    cfg = settings or load_settings()
    url = current_public_url() or read_sync_url(cfg)
    age = 0
    tunnel_flag = bool(current_public_url())
    path = sync_path(cfg)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            last = float(data.get("last_update") or 0)
            if last > 0:
                age = max(0, int(time.time() - last))
            if not url:
                url = str(data.get("remote_url") or "").strip().rstrip("/") or None
            tunnel_flag = tunnel_flag or bool(data.get("tunnel_active"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    mode = "lan"
    if url and age < 86400 and tunnel_flag:
        mode = "wan"
    elif url and age >= 86400:
        mode = "wan_stale"
    short = "N/A"
    if url:
        bare = url.replace("https://", "").replace("http://", "")
        short = (bare[:12] + "...") if len(bare) > 12 else bare
    alive = mode == "wan"
    return {
        "mode": mode,
        "network_mode": mode,
        "remote_url": url or "",
        "remote_url_short": short,
        "wan_url_display": short,
        "wan_tunnel_active": alive,
        "sync_file_age_seconds": age,
        "qr_ready": qr_svg_path().is_file(),
        "deep_link": f"ilaria://sync?url={url}" if url else "",
    }


def current_public_url() -> str | None:
    with _lock:
        return _public_url


def inicializar_tunel_remoto(
    settings: Settings | None = None,
    *,
    port: int | None = None,
) -> str | None:
    """Bring up ngrok HTTPS reverse tunnel to the HUD port; persist network_sync.json."""
    global _public_url, _started
    cfg = settings or load_settings()
    token = os.getenv("NGROK_AUTHTOKEN", "").strip()
    if not token:
        print("[TUNNEL] Sin NGROK_AUTHTOKEN. Sincronización limitada a LAN (UDP 8788).")
        return None

    hud_port = int(port if port is not None else cfg.hud_port)
    try:
        from pyngrok import ngrok
    except ImportError:
        print("[TUNNEL] Falta pyngrok. Instalá: pip install pyngrok")
        return None

    with _lock:
        if _started and _public_url:
            return _public_url
        _started = True

    try:
        ngrok.set_auth_token(token)
        # Prefer HTTPS public URL for iOS ATS / Android cleartext policy.
        tunnel = ngrok.connect(hud_port, bind_tls=True)
        public_url = str(getattr(tunnel, "public_url", "") or "").rstrip("/")
        if public_url.startswith("http://"):
            # Older pyngrok may still return http:// — upgrade scheme for clients.
            https_url = "https://" + public_url[len("http://") :]
            public_url = https_url
        if not public_url:
            print("[TUNNEL] Ngrok no devolvió public_url.")
            return None
        write_sync_url(public_url, cfg)
        generar_qr_deep_link(public_url)
        with _lock:
            _public_url = public_url
        print(f"[TUNNEL] Sincronización global activa vía WAN: {public_url}")
        print(f"[TUNNEL] Guardado en {sync_path(cfg)}")
        return public_url
    except Exception as exc:  # noqa: BLE001
        print(f"[TUNNEL] Error al inicializar puente seguro: {exc}")
        with _lock:
            _started = False
        return None


def start_tunnel_background(settings: Settings) -> None:
    """Non-blocking warm of the WAN tunnel after HUD bind."""

    def _run() -> None:
        inicializar_tunel_remoto(settings)

    threading.Thread(target=_run, name="ilaria-ngrok", daemon=True).start()


def wants_sync_request(text: str) -> bool:
    lower = (text or "").strip().lower()
    if not lower:
        return False
    # Exact / command forms from Telegram buttons and Profile deep-links.
    if lower in {
        "sincronizar",
        "/sincronizar",
        "ilaria_request_sync_url",
        "/ilaria_request_sync_url",
    }:
        return True
    keys = (
        "ilaria_request_sync_url",
        "sincronizar",
        "sync url",
        "url remota",
        "pedir url",
    )
    return any(k in lower for k in keys)


def sync_ack_message(settings: Settings | None = None) -> str:
    """Plain SYNC_ACK + ilaria:// deep link for Telegram → native apps."""
    cfg = settings or load_settings()
    url = current_public_url() or read_sync_url(cfg)
    if not url:
        return "SYNC_ERR: El túnel reverso aún no ha escrito credenciales de red."
    return (
        f"SYNC_ACK:{url}\n\n"
        f"Toque el siguiente enlace para actualizar la configuración de su app nativa:\n"
        f"ilaria://sync?url={url}"
    )



if __name__ == "__main__":
    inicializar_tunel_remoto()
