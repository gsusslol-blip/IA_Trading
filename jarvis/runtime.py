"""Process entry: local HUD window (not Brave) + optional Telegram."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from jarvis.accounts import AccountStore
from jarvis.brain import Brain
from jarvis.bus import EventBus
from jarvis.bootstrap import ensure_owner, should_lock_owner
from jarvis.config import DATA_DIR, Settings, load_settings
from jarvis.hud import create_hud
from jarvis.discover import start_discover
from jarvis.lan import phone_base_urls
from jarvis.memory import Memory
from jarvis.scheduler import reminder_loop
from jarvis.state import AppState
from jarvis.vision import start_vision
from jarvis.wake import start_wake_listener


def public_url(port: int, path: str = "/") -> str:
    # Brave "Always use HTTPS" breaks http://127.0.0.1 — localhost is exempt.
    # Open / so a valid jarvis_sid cookie skips the login screen.
    return f"http://localhost:{port}{path}"


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.8) as response:
            return getattr(response, "status", 200) == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _lan_health_ok(port: int) -> bool:
    for base in phone_base_urls(port):
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=0.8) as response:
                if getattr(response, "status", 200) == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def _alert(message: str) -> None:
    if not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "Ilaria", 0x10)
    except Exception:
        pass


def wait_health(port: int, timeout: float = 40.0) -> None:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout
    last_error = "sin respuesta"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if getattr(response, "status", 200) == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    message = (
        f"Ilaria no levanto el HUD en el puerto {port} ({last_error}). "
        "Cerra otra instancia o cambia HUD_PORT en .env"
    )
    _alert(message)
    raise SystemExit(message)


async def run_backend(settings: Settings, state: AppState) -> None:
    hud = create_hud(state)
    config = uvicorn.Config(
        hud,
        host=settings.hud_host,
        port=settings.hud_port,
        log_level="warning" if getattr(sys, "frozen", False) else "info",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = False

    telegram_send = None
    telegram = None
    # Street channel: polling inside this process (no second python in run.bat).
    if settings.has_telegram:
        from jarvis.remote_bridge import remote_workspace
        from jarvis.telegram_bot import build_telegram_app

        host_brain = Brain(settings, Memory(DATA_DIR / "host_memory.json"), EventBus())
        host_brain.actions.client_surface = "telegram"
        host_brain.actions.workspace = remote_workspace(settings=settings)
        telegram = build_telegram_app(settings, host_brain)
        await telegram.initialize()
        await telegram.start()
        if telegram.updater is None:
            raise SystemExit("Telegram updater failed to start.")
        await telegram.updater.start_polling(drop_pending_updates=True)
        print("[REMOTO] Canal Telegram (polling) activo — atajos de calle + cerebro.")
        app = telegram

        async def telegram_send(text: str) -> None:
            chat_id = host_brain.bus.telegram_chat_id or settings.telegram_user_id
            if chat_id is None:
                return
            await app.bot.send_message(chat_id=chat_id, text=text)

    pump = asyncio.create_task(reminder_loop(state, telegram_send))
    try:
        await server.serve()
    finally:
        pump.cancel()
        if telegram is not None and telegram.updater is not None:
            await telegram.updater.stop()
            await telegram.stop()
            await telegram.shutdown()


_MIC_HOOKS: list[object] = []


def open_ui(url: str, title: str = "Ilaria") -> None:
    try:
        import webview

        window = webview.create_window(
            title,
            url,
            width=1180,
            height=760,
            min_size=(900, 600),
            background_color="#070709",
        )

        def _allow_mic() -> None:
            try:
                from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState

                form = getattr(window, "native", None)
                if form is None:
                    return
                controls = getattr(form, "Controls", None)
                if controls is None:
                    return
                for ctrl in controls:
                    core = getattr(ctrl, "CoreWebView2", None)
                    if core is None:
                        continue

                    def on_perm(_sender, args) -> None:
                        args.Handled = True
                        args.State = CoreWebView2PermissionState.Allow

                    core.PermissionRequested += on_perm
                    _MIC_HOOKS.append(on_perm)
                    return
            except Exception as exc:
                print(f"Permiso de microfono no se pudo auto-aceptar ({exc}).")

        window.events.shown += _allow_mic
        webview.start()
        return
    except Exception as exc:
        print(f"Ventana propia no disponible ({exc}). Abro el navegador.")
    webbrowser.open(url)
    print()
    print("Si Brave no entra:")
    print("  1) Usa exactamente:", url)
    print("  2) brave://settings/security -> desactiva 'Siempre usar HTTPS'")
    print("  3) O ejecuta abrir-brave.bat")
    print("No uses https:// ni 127.0.0.1 - Brave los bloquea o los 'mejora' a HTTPS.")
    print()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return


def main() -> None:
    settings: Settings = load_settings()
    accounts = AccountStore()
    if should_lock_owner():
        print(ensure_owner(accounts))
    state = AppState(settings, accounts)
    url = public_url(settings.hud_port)
    from jarvis import __version__
    from jarvis.piper_tts import piper_available, piper_model

    print(f"Ilaria v{__version__} lista.")
    print(f"HUD: {url}")
    if piper_available():
        print(f"TTS: Piper CPU — {piper_model()}")
    else:
        print("TTS: Piper ausente (run.bat lo descarga; sin red la voz queda muda).")
    from jarvis.llm import resolve_llm

    try:
        ep = resolve_llm(settings)
        print(f"LLM: {ep.label} — {ep.model}")
    except Exception as exc:  # noqa: BLE001
        print(f"LLM: sin cerebro ({exc})")
    print("No abras https:// ni 127.0.0.1: Brave los rompe. La app abre su propia ventana.")
    if settings.hud_host in {"0.0.0.0", "::"}:
        phones = phone_base_urls(settings.hud_port)
        if phones:
            print("Celular (mismo Wi-Fi):")
            for base in phones:
                print(f"  {base}/welcome")
            print("En Android: misma Wi-Fi (no 4G). La app busca la PC sola.")
            print("Firewall una vez: firewall-ilaria.bat como Administrador (TCP 8787 + UDP 8788).")
        else:
            print("LAN activo (0.0.0.0) pero no detecté IP local. Revisá ipconfig.")
    else:
        print(f"Solo local ({settings.hud_host}). Para el celular: HUD_HOST=0.0.0.0 en .env")

    if already_running(settings.hud_port):
        print("Ya habia una instancia. Abro esa.")
        if settings.hud_host in {"0.0.0.0", "::"} and not _lan_health_ok(settings.hud_port):
            print("CUIDADO: esa instancia solo escucha en esta PC (127.0.0.1).")
            print("El celular no entra. Cerra Ilaria por completo y volve a abrir run.bat.")
        if os.getenv("JARVIS_OPEN_BROWSER", "1") != "0":
            open_ui(url, settings.assistant_name)
        return

    worker = threading.Thread(
        target=lambda: asyncio.run(run_backend(settings, state)),
        name="jarvis-backend",
        daemon=True,
    )
    worker.start()
    wait_health(settings.hud_port)
    start_discover(settings)
    try:
        from jarvis.tunnel_manager import start_tunnel_background

        start_tunnel_background(settings)
    except Exception as exc:  # noqa: BLE001
        print(f"[TUNNEL] skip: {exc}")
    try:
        from jarvis.tts_warmer import start_tts_warm

        start_tts_warm(settings, limit=16)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARM_UP] skip: {exc}")
    try:
        from jarvis.health_inbox import start_health_inbox_watcher

        start_health_inbox_watcher(settings)
    except Exception as exc:  # noqa: BLE001
        print(f"[INBOX] skip: {exc}")
    start_wake_listener(state)
    start_vision(state)
    if os.getenv("JARVIS_OPEN_BROWSER", "1") == "0":
        worker.join()
        return
    open_ui(url, settings.assistant_name)


if __name__ == "__main__":
    main()
