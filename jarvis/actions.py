"""Real PC-side actions JARVIS can execute."""

from __future__ import annotations

import ast
import operator
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import shutil
import smtplib
import subprocess
import sys
import time
import webbrowser
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx

from jarvis.bank_apps import is_banking
from jarvis.bus import EventBus
from jarvis.config import DATA_DIR, Settings
from jarvis.security import safe_under

WORKSPACE = DATA_DIR / "workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)

_VK = {
    "mute": 0xAD,
    "vol_down": 0xAE,
    "vol_up": 0xAF,
    "next": 0xB0,
    "prev": 0xB1,
    "stop": 0xB2,
    "play_pause": 0xB3,
}

_APPS: dict[str, list[str]] = {
    "notepad": ["notepad.exe"],
    "bloc de notas": ["notepad.exe"],
    "calculadora": ["calc.exe"],
    "calculator": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "explorer": ["explorer.exe"],
    "archivos": ["explorer.exe"],
    "edge": [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],
    "chrome": [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ],
    "firefox": [r"%ProgramFiles%\Mozilla Firefox\firefox.exe"],
    "spotify": [
        r"%AppData%\Spotify\Spotify.exe",
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe",
    ],
    "discord": [r"%LocalAppData%\Discord\Update.exe"],
    "whatsapp": [r"%LocalAppData%\WhatsApp\WhatsApp.exe"],
    "telegram": [r"%AppData%\Telegram Desktop\Telegram.exe"],
    "cursor": [r"%LocalAppData%\Programs\cursor\Cursor.exe"],
    "vscode": [r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe"],
    "code": [r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe"],
    "word": [r"%ProgramFiles%\Microsoft Office\root\Office16\WINWORD.EXE"],
    "excel": [r"%ProgramFiles%\Microsoft Office\root\Office16\EXCEL.EXE"],
    "steam": [r"%ProgramFiles(x86)%\Steam\steam.exe"],
    "taskmgr": ["taskmgr.exe"],
    "administrador de tareas": ["taskmgr.exe"],
    "tareas": ["taskmgr.exe"],
    "cmd": ["cmd.exe"],
    "terminal": ["wt.exe", "cmd.exe"],
    "powershell": ["powershell.exe"],
    "snip": ["SnippingTool.exe"],
    "recortes": ["SnippingTool.exe"],
    "configuracion": ["ms-settings:"],
    "configuración": ["ms-settings:"],
    "settings": ["ms-settings:"],
    "wifi": ["ms-settings:network-wifi"],
    "bluetooth": ["ms-settings:bluetooth"],
    "sonido": ["ms-settings:sound"],
    "actualizaciones": ["ms-settings:windowsupdate"],
}

_FOLDERS: dict[str, list[Path]] = {
    "desktop": [
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
        Path.home() / "OneDrive" / "Escritorio",
    ],
    "escritorio": [
        Path.home() / "OneDrive" / "Escritorio",
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
    ],
    "downloads": [Path.home() / "Downloads", Path.home() / "Descargas"],
    "descargas": [Path.home() / "Downloads", Path.home() / "Descargas"],
    "documents": [Path.home() / "Documents", Path.home() / "Documentos"],
    "documentos": [Path.home() / "Documents", Path.home() / "Documentos"],
    "workspace": [WORKSPACE],
}

_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


class Actions:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        workspace: Path | None = None,
        is_owner: bool = False,
    ) -> None:
        self.settings = settings
        self.bus = bus
        self.is_owner = is_owner
        self.workspace = workspace or (DATA_DIR / "workspace")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._folders = dict(_FOLDERS)
        self._folders["workspace"] = [self.workspace]
        self.client_surface = "hud"
        self.device_note = ""
        self.android_upgrade_hint = ""
        self.phone_queue: list[dict[str, Any]] = []
        self._undo: dict[str, Any] | None = None
        self.last_action_label = ""

    def push_undo(self, kind: str, **payload: Any) -> None:
        self._undo = {"kind": kind, **payload, "ts": time.time()}

    def undo_last(self) -> str:
        item = self._undo
        self._undo = None
        if not item or (time.time() - float(item.get("ts") or 0)) > 30:
            return "No hay nada reciente para deshacer."
        kind = str(item.get("kind") or "")
        if kind == "volume":
            prev = item.get("previous")
            if prev is None:
                return "No guardé el volumen anterior."
            return self.set_volume(int(prev), track_undo=False)
        if kind == "clipboard":
            prev = str(item.get("previous") or "")
            return self.set_clipboard(prev, track_undo=False)
        return "Esa acción no se puede deshacer."

    def capabilities(self) -> str:
        smtp = "ready" if self.settings.has_smtp else "needs SMTP_* in .env"
        ha = "ready" if self.settings.has_ha else "needs HA_URL + HA_TOKEN in .env"
        apps = ", ".join(sorted(set(_APPS)))
        return (
            "Hands that work on this PC:\n"
            f"- Internet: search, read page, weather, wikipedia\n"
            f"- Memory: facts, notes, reminders, timers (HUD beeps at due time)\n"
            f"- Daily journal: append to workspace/diario_YYYY-MM-DD.txt\n"
            f"- Browser: open URL, Google search, maps, WhatsApp draft (user taps send)\n"
            f"- Music: play_music on YouTube (search URL) or Spotify (app + search URL; "
            f"optional SPOTIFY_UI_CONTROL=1 + pyautogui)\n"
            f"- Apps: {apps}\n"
            f"- Folders: desktop, downloads, documents, workspace\n"
            f"- Files: read/write/list inside this user's workspace only\n"
            f"- Screenshot, clipboard, master volume 0-100, media keys, key-app status\n"
            f"- Power (owner): schedule shutdown /s /t 30, restart /r /t 10, or abort /a\n"
            f"- Email: {smtp}\n"
            f"- Home Assistant lights/plugs: {ha}\n"
            "Will not: bank logins, card payments, silent WhatsApp/SMS send, "
            "reading the SMS inbox, root, or hardware you do not own.\n"
            "Stack diagnose: get_system_health / check_lan_status; "
            "owner remediación allowlisted: relaunch_service (ollama|piper|ha_ping).\n"
            "On the Ilaria Android/iOS app: phone_hands (dialer, SMS draft, WhatsApp draft, maps, "
            "apps, torch, camera, gallery, volume, alarm/timer, settings, share)."
        )

    def calculate(self, expression: str) -> str:
        try:
            tree = ast.parse(expression.strip(), mode="eval")
            value = _eval_math(tree)
        except Exception as exc:  # noqa: BLE001
            return f"Math failed: {exc}"
        return str(value)

    def wikipedia(self, topic: str) -> str:
        title = quote(topic.strip().replace(" ", "_"))
        url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{title}"
        headers = {"User-Agent": "Ilaria/1.3.5 personal-assistant"}
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
                response = client.get(url)
                if response.status_code == 404:
                    url_en = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
                    response = client.get(url_en)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            return f"Wikipedia failed: {exc}"
        extract = payload.get("extract") or ""
        page = (payload.get("content_urls") or {}).get("desktop", {}).get("page", "")
        return f"{payload.get('title', topic)}\n{extract}\n{page}".strip()

    def open_browser(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "Invalid URL. Need http(s)."
        webbrowser.open(url)
        return f"Opened browser: {url}"

    def play_music(self, query: str, platform: str = "youtube") -> str:
        """Play a track: YouTube search URL, or Spotify app + optional UI control."""
        q = " ".join((query or "").split())
        if not q:
            return "Decime qué canción, artista o playlist querés escuchar."
        plat = (platform or "youtube").strip().lower()
        if "spotify" in plat:
            opened = _open_spotify_app()
            if _spotify_ui_enabled():
                if _spotify_ui_search(q):
                    return f"Reproduciendo {q} en Spotify, pá."
            try:
                os.startfile("spotify:search:" + quote(q))  # type: ignore[attr-defined]
            except OSError:
                url = "https://open.spotify.com/search/" + quote(q)
                webbrowser.open(url)
            if opened:
                return (
                    f"Abrí Spotify con la búsqueda de {q}. "
                    "Tocá el tema en la app para que suene."
                )
            return (
                f"Abrí la búsqueda de {q} en Spotify. "
                "Si la app está instalada, debería abrir sola."
            )
        url = "https://www.youtube.com/results?search_query=" + quote(q)
        webbrowser.open(url)
        return f"Reproduciendo {q} en YouTube, pá. Abrí la búsqueda en el navegador."

    def google(self, query: str) -> str:
        url = "https://www.google.com/search?q=" + quote(query.strip())
        webbrowser.open(url)
        return f"Opened Google for: {query.strip()}"

    def open_maps(self, destination: str, origin: str = "") -> str:
        params = {"api": "1", "destination": destination.strip()}
        if origin.strip():
            params["origin"] = origin.strip()
        url = "https://www.google.com/maps/dir/?" + urlencode(params)
        webbrowser.open(url)
        return f"Opened maps: {destination.strip()}"

    def compose_whatsapp(self, phone: str, text: str) -> str:
        digits = _phone_digits(phone)
        if len(digits) < 8:
            return "Need a valid phone number with country code (e.g. 54911...)."
        url = f"https://wa.me/{digits}?text={quote(text)}"
        webbrowser.open(url)
        return (
            f"Opened WhatsApp draft to {digits}. "
            "You still have to tap send — there is no silent send."
        )

    def open_app(self, name: str) -> str:
        key = name.strip().lower()
        if is_banking(key) or is_banking(name):
            return "No abro apps bancarias."
        paths = _APPS.get(key)
        if paths:
            for item in paths:
                expanded = os.path.expandvars(item)
                if os.path.isabs(expanded) and Path(expanded).exists():
                    return _start(expanded, key)
                found = shutil.which(item) or shutil.which(Path(expanded).name)
                if found:
                    return _start(found, key)
            if sys.platform == "win32" and key == "spotify":
                try:
                    os.startfile("spotify:")  # type: ignore[attr-defined]
                    return "Opened spotify."
                except OSError:
                    pass
            if sys.platform == "win32" and not os.path.isabs(paths[0]):
                return _start(os.path.expandvars(paths[0]), key)
        shortcut = _start_menu_app(key)
        if shortcut is not None:
            return _start(str(shortcut), key)
        exe = shutil.which(key) or shutil.which(key + ".exe")
        if exe and not is_banking(exe):
            return _start(exe, key)
        if paths:
            return f"Could not find {name} installed."
        return f"No encuentro la app '{name}' en el menu de inicio."

    def open_folder(self, name: str) -> str:
        key = name.strip().lower()
        paths = self._folders.get(key)
        if not paths:
            return f"Unknown folder '{name}'. Allowed: {', '.join(sorted(self._folders))}"
        for path in paths:
            if path.exists():
                return _start(str(path), key)
        paths[0].mkdir(parents=True, exist_ok=True)
        return _start(str(paths[0]), key)

    def list_files(self, relative: str = "") -> str:
        try:
            folder = self._safe_rel(relative or ".")
        except ValueError as exc:
            return str(exc)
        if not folder.exists():
            return "Folder does not exist yet."
        if folder.is_file():
            return f"That path is a file: {folder.name}"
        names = sorted(p.name + ("/" if p.is_dir() else "") for p in folder.iterdir())
        return "\n".join(names[:80]) or "(empty workspace)"

    def read_file(self, relative: str) -> str:
        try:
            path = self._safe_rel(relative)
        except ValueError as exc:
            return str(exc)
        if not path.is_file():
            return "File not found in workspace."
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:8000]

    def write_file(self, relative: str, content: str, append: bool = False) -> str:
        try:
            path = self._safe_rel(relative)
        except ValueError as exc:
            return str(exc)
        path.parent.mkdir(parents=True, exist_ok=True)
        if append and path.exists():
            with path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            path.write_text(content, encoding="utf-8")
        return f"Wrote {path.name} ({path.stat().st_size} bytes) in workspace."

    def screenshot(self) -> str:
        try:
            from PIL import ImageGrab
        except ImportError:
            return "Pillow is not installed. Run: pip install pillow"
        path = self.workspace / "screenshot.png"
        image = ImageGrab.grab()
        image.save(path)
        return f"Screenshot saved to {path}"

    def set_clipboard(self, text: str, track_undo: bool = True) -> str:
        if sys.platform != "win32":
            return "Clipboard only wired on Windows."
        if track_undo:
            try:
                prev = self.get_clipboard()
                if not str(prev).startswith("Clipboard only") and not str(prev).startswith("ERROR"):
                    self.push_undo("clipboard", previous=prev if prev != "(empty clipboard)" else "")
            except Exception:
                pass
        quoted = text.replace("'", "''")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{quoted}'"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if completed.returncode != 0:
            return f"Clipboard failed: {completed.stderr.strip() or completed.returncode}"
        self.last_action_label = "portapapeles"
        return "Copied to clipboard. Decí deshacer si te arrepentís."

    def set_volume(self, level: int, track_undo: bool = True) -> str:
        if sys.platform != "win32":
            return "Volume only wired on Windows."
        try:
            value = max(0, min(100, int(level)))
        except (TypeError, ValueError):
            return "Nivel de volumen: un numero de 0 a 100."
        try:
            from ctypes import POINTER, cast
            import ctypes

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        except ImportError:
            return "Falta pycaw. Instala: pip install pycaw comtypes"
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
        try:
            speakers = AudioUtilities.GetSpeakers()
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            if track_undo:
                try:
                    prev = int(round(float(volume.GetMasterVolumeLevelScalar()) * 100))
                    self.push_undo("volume", previous=prev)
                except Exception:
                    pass
            volume.SetMasterVolumeLevelScalar(value / 100.0, None)
        except Exception as exc:  # noqa: BLE001
            return f"No pude cambiar el volumen: {exc}"
        self.last_action_label = f"volumen {value}%"
        return f"Volumen al {value}%. Decí deshacer si te arrepentís."

    def get_clipboard(self) -> str:
        """Read Windows clipboard; PowerShell first, ctypes CF_UNICODETEXT as fallback."""
        if sys.platform != "win32":
            return "Clipboard only wired on Windows."
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                text=True,
                timeout=12,
            )
            if completed.returncode == 0:
                value = (completed.stdout or "").rstrip("\r\n")
                if value.strip():
                    return value
        except Exception:
            pass
        native = _clipboard_unicode_text()
        if native is None:
            return "(empty clipboard)"
        if native.startswith("ERROR:"):
            return native[6:].strip()
        return native or "(empty clipboard)"

    def power_control(self, action: str) -> str:
        """Schedule Windows shutdown/restart or abort. No shell=True. Owner-only in code."""
        if not self.is_owner:
            return "Permiso denegado: apagar/reiniciar la PC es solo del dueño."
        if sys.platform != "win32":
            return "Power control is wired for Windows only."
        key = (action or "").strip().lower()
        try:
            if key in {"shutdown", "apagar", "off", "poweroff"}:
                completed = subprocess.run(
                    ["shutdown", "/s", "/t", "30"],
                    capture_output=True,
                    text=True,
                    timeout=12,
                    creationflags=_CREATE_NO_WINDOW,
                )
                if completed.returncode not in {0, 1190}:
                    err = (completed.stderr or completed.stdout or "").strip()
                    return f"Shutdown failed: {err or completed.returncode}"
                return "Apagado programado en 30 segundos. Decí abortar si te arrepentís."
            if key in {"restart", "reboot", "reiniciar"}:
                completed = subprocess.run(
                    ["shutdown", "/r", "/t", "10"],
                    capture_output=True,
                    text=True,
                    timeout=12,
                    creationflags=_CREATE_NO_WINDOW,
                )
                if completed.returncode not in {0, 1190}:
                    err = (completed.stderr or completed.stdout or "").strip()
                    return f"Restart failed: {err or completed.returncode}"
                return "Reinicio programado en 10 segundos. Decí abortar si te arrepentís."
            if key in {"abort", "cancel", "cancelar", "a"}:
                completed = subprocess.run(
                    ["shutdown", "/a"],
                    capture_output=True,
                    text=True,
                    timeout=12,
                    creationflags=_CREATE_NO_WINDOW,
                )
                if completed.returncode != 0:
                    if completed.returncode == 1116:
                        return "No hay apagado ni reinicio pendiente."
                    err = (completed.stderr or completed.stdout or "").strip()
                    return f"Abort failed: {err or completed.returncode}"
                return "Apagado/reinicio cancelado."
            if key in {"lock", "bloquear", "lockscreen"}:
                completed = subprocess.run(
                    ["rundll32.exe", "user32.dll,LockWorkStation"],
                    capture_output=True,
                    text=True,
                    timeout=12,
                    creationflags=_CREATE_NO_WINDOW,
                )
                if completed.returncode != 0:
                    err = (completed.stderr or completed.stdout or "").strip()
                    return f"Lock failed: {err or completed.returncode}"
                return "Pantalla bloqueada."
            return "Acción inválida. Usá: shutdown, restart, abort o lock."
        except Exception as exc:  # noqa: BLE001
            return f"Power control failed: {exc}"

    def media(self, action: str) -> str:
        if sys.platform != "win32":
            return "Media keys only wired on Windows."
        vk = _VK.get(action.strip().lower())
        if vk is None:
            return f"Unknown media action. Use: {', '.join(_VK)}"
        _press_vk(vk)
        return f"Media: {action}"

    def system_status(self) -> str:
        from jarvis.packs import format_local_when

        when = format_local_when(self.settings.timezone)
        apps = _running_watchlist()
        found = ", ".join(apps) if apps else "ninguna de las clave (Chrome, Cursor, Discord, Excel)"
        return f"{when}\nAplicaciones clave: {found}."

    def daily_journal(self, content: str) -> str:
        text = content.strip()
        if not text:
            return "Nada que anotar."
        now = datetime.now(ZoneInfo(self.settings.timezone))
        stamp = now.strftime("%H:%M")
        day = now.strftime("%Y-%m-%d")
        path = self.workspace / f"diario_{day}.txt"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {text}\n")
        return f"Asentado en {path.name}."

    def read_daily_journal(self) -> str:
        day = datetime.now(ZoneInfo(self.settings.timezone)).strftime("%Y-%m-%d")
        path = self.workspace / f"diario_{day}.txt"
        if not path.exists():
            return "Hoy todavia no hay minuta."
        return path.read_text(encoding="utf-8").strip() or "Hoy todavia no hay minuta."

    def journal_context(self, today_lines: int = 24, yesterday_lines: int = 8) -> str:
        """Last journal lines for system-prompt short-term memory."""
        from datetime import timedelta

        now = datetime.now(ZoneInfo(self.settings.timezone))
        today = self.workspace / f"diario_{now.strftime('%Y-%m-%d')}.txt"
        yday = self.workspace / f"diario_{(now - timedelta(days=1)).strftime('%Y-%m-%d')}.txt"
        chunks: list[str] = []
        if yday.exists():
            rows = [line for line in yday.read_text(encoding="utf-8").splitlines() if line.strip()]
            if rows:
                chunks.append("--- Bitácora de ayer (últimas líneas) ---")
                chunks.extend(rows[-max(1, yesterday_lines) :])
        if today.exists():
            rows = [line for line in today.read_text(encoding="utf-8").splitlines() if line.strip()]
            if rows:
                chunks.append("--- Bitácora de hoy ---")
                chunks.extend(rows[-max(1, today_lines) :])
        if not chunks:
            return "(Sin entradas recientes en la bitácora diaria.)"
        return "\n".join(chunks)

    def send_email(self, to: str, subject: str, body: str) -> str:
        if not self.settings.has_smtp:
            return "Email not configured. Add SMTP_HOST, SMTP_USER, SMTP_PASSWORD to .env"
        to_addr = to.strip()
        if "@" not in to_addr:
            return "Invalid recipient email."
        message = EmailMessage()
        message["From"] = self.settings.smtp_from or self.settings.smtp_user
        message["To"] = to_addr
        message["Subject"] = subject.strip() or "(no subject)"
        message.set_content(body)
        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
                smtp.send_message(message)
        except Exception as exc:  # noqa: BLE001
            return f"Email failed: {exc}"
        return f"Email sent to {to_addr}."

    def home_assistant(
        self,
        domain: str,
        service: str,
        entity_id: str = "",
        temperature: float | None = None,
    ) -> str:
        if not self.settings.has_ha:
            return "Home Assistant not configured. Add HA_URL and HA_TOKEN to .env"
        from jarvis.ha_guard import HaDenied, authorize_ha_call

        try:
            spec = authorize_ha_call(
                domain=domain,
                service=service,
                entity_id=entity_id,
                is_owner=self.is_owner,
                temperature=temperature,
            )
        except HaDenied as exc:
            return str(exc)
        url = self.settings.ha_url.rstrip("/") + f"/api/services/{spec['domain']}/{spec['service']}"
        headers = {
            "Authorization": f"Bearer {self.settings.ha_token}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, headers=headers, json=spec["payload"] or None)
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return f"Home Assistant failed: {exc}"
        extra = spec["payload"].get("entity_id", "")
        return f"Home Assistant: {spec['domain']}.{spec['service']} {extra}".strip()

    def control_device(self, entity_id: str, action: str, temperature: float | None = None) -> str:
        entity = (entity_id or "").strip().lower()
        if "." not in entity:
            return "Pasame el entity_id de HA (ej. light.living)."
        domain = entity.split(".", 1)[0]
        return self.home_assistant(domain, action, entity, temperature)

    def home_states(self, domain: str = "") -> str:
        if not self.settings.has_ha:
            return "Home Assistant not configured. Add HA_URL and HA_TOKEN to .env"
        from jarvis.ha_guard import MEMBER_DOMAINS, OWNER_DOMAINS

        allowed = set(MEMBER_DOMAINS)
        if self.is_owner:
            allowed |= set(OWNER_DOMAINS)
        want = (domain or "").strip().lower()
        headers = {"Authorization": f"Bearer {self.settings.ha_token}"}
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(self.settings.ha_url.rstrip("/") + "/api/states", headers=headers)
                response.raise_for_status()
                rows = response.json()
        except Exception as exc:  # noqa: BLE001
            return f"Home Assistant failed: {exc}"
        lines: list[str] = []
        if not isinstance(rows, list):
            return "HA no devolvió estados."
        for item in rows:
            if not isinstance(item, dict):
                continue
            eid = str(item.get("entity_id") or "")
            prefix = eid.split(".", 1)[0]
            if prefix not in allowed:
                continue
            if want and prefix != want:
                continue
            state = item.get("state", "?")
            lines.append(f"{eid}: {state}")
            if len(lines) >= 80:
                break
        return "\n".join(lines) if lines else "(sin entidades visibles)"

    def notify(self, text: str) -> str:
        self.bus.push(text)
        return "Alert posted to HUD."

    def _safe_rel(self, relative: str) -> Path:
        return safe_under(self.workspace, relative)


_CREATE_NO_WINDOW = 0x08000000

_WATCH_PROCS = {
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "brave.exe": "Brave",
    "firefox.exe": "Firefox",
    "cursor.exe": "Cursor",
    "code.exe": "VS Code",
    "discord.exe": "Discord",
    "spotify.exe": "Spotify",
    "excel.exe": "Excel",
    "winword.exe": "Word",
    "steam.exe": "Steam",
    "telegram.exe": "Telegram",
    "whatsapp.exe": "WhatsApp",
    "slack.exe": "Slack",
}


def _running_watchlist() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    images: set[str] = set()
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        image = line.split(",", 1)[0].strip().strip('"').lower()
        images.add(image)
    found: list[str] = []
    for exe, label in _WATCH_PROCS.items():
        if exe in images and label not in found:
            found.append(label)
    return found


def _start_menu_app(name: str) -> Path | None:
    """Resolve a Start Menu shortcut by display name. Skips banking titles."""
    if sys.platform != "win32":
        return None
    want = re.sub(r"[^a-z0-9]+", "", name.lower())
    if len(want) < 2:
        return None
    roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    exact: Path | None = None
    partial: Path | None = None
    partial_len = 10_000
    for root in roots:
        if not root.is_dir():
            continue
        for lnk in root.rglob("*.lnk"):
            stem = lnk.stem
            if is_banking(stem) or is_banking(str(lnk)):
                continue
            packed = re.sub(r"[^a-z0-9]+", "", stem.lower())
            if packed == want:
                exact = lnk
                break
            if want in packed and len(packed) < partial_len:
                partial = lnk
                partial_len = len(packed)
        if exact is not None:
            break
    return exact or partial


def _start(target: str, label: str) -> str:
    if sys.platform != "win32":
        return "App launch is wired for Windows."
    try:
        os.startfile(target)  # type: ignore[attr-defined]
    except OSError as exc:
        return f"Could not open {label}: {exc}"
    return f"Opened {label}."


def _clipboard_unicode_text() -> str | None:
    """Native CF_UNICODETEXT read via Win32. Returns None if empty; ERROR:… on hard failure."""
    if sys.platform != "win32":
        return None
    import ctypes

    cf_unicode = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        if not user32.IsClipboardFormatAvailable(cf_unicode):
            return None
        if not user32.OpenClipboard(None):
            return "ERROR: No pude abrir el portapapeles (otro proceso lo tiene bloqueado)."
        try:
            handle = user32.GetClipboardData(cf_unicode)
            if not handle:
                return None
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                text = ctypes.c_wchar_p(pointer).value
            finally:
                kernel32.GlobalUnlock(handle)
            return text if text is not None else None
        finally:
            user32.CloseClipboard()
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: Excepción al leer el portapapeles: {exc}"


def _press_vk(vk: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 1, 0)
    user32.keybd_event(vk, 0, 3, 0)


def _key_combo(*vks: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)


def _type_text(text: str) -> None:
    """Unicode keystrokes via SendInput (Windows)."""
    import ctypes
    from ctypes import wintypes

    extra = ctypes.c_ulong
    ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else extra

    class KeyBdInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ulong_ptr),
        ]

    class InputUnion(ctypes.Union):
        _fields_ = [("ki", KeyBdInput)]

    class Input(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]

    user32 = ctypes.windll.user32
    keyeventf_unicode = 0x0004
    keyeventf_keyup = 0x0002
    for ch in text[:80]:
        scan = ord(ch)
        down = Input(type=1, union=InputUnion(ki=KeyBdInput(0, scan, keyeventf_unicode, 0, 0)))
        up = Input(
            type=1,
            union=InputUnion(ki=KeyBdInput(0, scan, keyeventf_unicode | keyeventf_keyup, 0, 0)),
        )
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(down))
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(up))
        time.sleep(0.02)


def _focus_spotify() -> bool:
    if sys.platform != "win32":
        return False
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(New-Object -ComObject WScript.Shell).AppActivate('Spotify')",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=_CREATE_NO_WINDOW,
        )
        return completed.returncode == 0
    except Exception:
        return False


def _spotify_ui_enabled() -> bool:
    raw = os.getenv("SPOTIFY_UI_CONTROL", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _open_spotify_app() -> bool:
    """Launch Spotify desktop if installed. No shell=True, no URL interpolation."""
    if sys.platform != "win32":
        return False
    for item in _APPS.get("spotify", []):
        expanded = os.path.expandvars(item)
        if os.path.isabs(expanded) and Path(expanded).exists():
            _start(expanded, "spotify")
            return True
        exe = shutil.which("spotify") or shutil.which("Spotify.exe")
        if exe:
            _start(exe, "spotify")
            return True
    return _focus_spotify()


def _spotify_ui_search(query: str) -> bool:
    """
    Optional flaky desktop search: pyautogui Ctrl+L / type / Enter.
    Only when SPOTIFY_UI_CONTROL=1. Never types into a shell.
    """
    if not _spotify_ui_enabled() or sys.platform != "win32":
        return False
    safe = " ".join((query or "").split())[:80]
    if not safe:
        return False
    if not _open_spotify_app() and not _focus_spotify():
        return False
    time.sleep(1.6)
    if not _focus_spotify():
        time.sleep(1.2)
        if not _focus_spotify():
            return False
    try:
        import pyautogui
    except ImportError:
        print("[-] Spotify UI: falta pyautogui (pip install pyautogui).")
        return False
    try:
        pyautogui.FAILSAFE = True
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.35)
        pyautogui.typewrite(safe, interval=0.02)
        time.sleep(0.25)
        pyautogui.press("enter")
        time.sleep(1.1)
        pyautogui.press("space")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[-] Spotify UI control failed: {exc}")
        return False


def _phone_digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("11"):
        digits = "54" + digits
    return digits


def _eval_math(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _eval_math(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_math(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_math(node.left), _eval_math(node.right))
    raise ValueError("only + - * / // % ** and numbers are allowed")
