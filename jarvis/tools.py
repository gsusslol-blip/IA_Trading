"""Internet, memory, and PC tools JARVIS can call."""

from __future__ import annotations

import json
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import httpx
from ddgs import DDGS

from jarvis.actions import Actions
from jarvis.config import Settings
from jarvis.memory import Memory


def _fn(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _fn(
        "list_capabilities",
        "List what you can actually do right now (configured vs not).",
        {},
    ),
    _fn(
        "web_search",
        "Search the live internet for news, facts, prices, people, how-to.",
        {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 5},
        },
        ["query"],
    ),
    _fn(
        "read_page",
        "Fetch and read a web page (does not open a browser window).",
        {"url": {"type": "string"}},
        ["url"],
    ),
    _fn("weather", "Current weather and short forecast.", {"city": {"type": "string"}}, ["city"]),
    _fn("wikipedia", "Wikipedia summary in Spanish, English fallback.", {"topic": {"type": "string"}}, ["topic"]),
    _fn(
        "now",
        "Current date, time, and timezone. Prefer system_status if the user also wants which apps are open.",
        {},
    ),
    _fn(
        "system_status",
        "Local clock plus whether key apps are running (Chrome, Cursor, Discord, Excel, etc). Use this instead of web_search for PC/day status.",
        {},
    ),
    _fn(
        "daily_journal",
        "Append a thought, reminder, market note, or task to today's local journal file. Use when the user says tomá nota, anotá en el diario, bitácora, or wants a daily log.",
        {"content": {"type": "string"}},
        ["content"],
    ),
    _fn(
        "read_daily_journal",
        "Read today's local journal. Use for 'en qué me quedé', 'qué anoté', 'bitácora de hoy', or before answering about recent PC work.",
        {},
    ),
    _fn(
        "set_volume",
        "Set Windows master volume to an exact percent from 0 to 100. Use this instead of media vol_up/vol_down when a number is given.",
        {"level": {"type": "integer"}},
        ["level"],
    ),
    _fn(
        "undo_last",
        "Undo the last reversible PC action within ~30s (volume or clipboard). Use when the user says deshacer/undo.",
        {},
    ),
    _fn("calculate", "Exact arithmetic. Expression like 12.5 * 1.21", {"expression": {"type": "string"}}, ["expression"]),
    _fn(
        "remember",
        "Store a durable fact about the user.",
        {"key": {"type": "string"}, "value": {"type": "string"}},
        ["key", "value"],
    ),
    _fn("recall", "Read stored facts. Omit key to list all.", {"key": {"type": "string"}}),
    _fn("forget", "Delete a stored fact by key.", {"key": {"type": "string"}}, ["key"]),
    _fn("note", "Save a short note, or list notes if text is empty.", {"text": {"type": "string"}}),
    _fn(
        "set_reminder",
        "Set a reminder at local ISO-8601 datetime. HUD will beep at that time.",
        {
            "when_iso": {"type": "string", "description": "e.g. 2026-08-20T18:30:00"},
            "text": {"type": "string"},
        },
        ["when_iso", "text"],
    ),
    _fn(
        "set_timer",
        "Timer from now, in minutes. HUD beeps when it fires.",
        {"minutes": {"type": "number"}, "text": {"type": "string"}},
        ["minutes", "text"],
    ),
    _fn("list_reminders", "List pending reminders and timers.", {}),
    _fn("cancel_reminder", "Cancel pending reminder(s) matching text.", {"query": {"type": "string"}}, ["query"]),
    _fn(
        "open_browser",
        "Open a URL in the user's default browser on this PC.",
        {"url": {"type": "string"}},
        ["url"],
    ),
    _fn("google", "Open a Google search in the browser.", {"query": {"type": "string"}}, ["query"]),
    _fn(
        "open_maps",
        "Open Google Maps directions in the browser.",
        {"destination": {"type": "string"}, "origin": {"type": "string"}},
        ["destination"],
    ),
    _fn(
        "compose_whatsapp",
        "Open WhatsApp with a draft message. User must tap send. Phone with country code.",
        {"phone": {"type": "string"}, "text": {"type": "string"}},
        ["phone", "text"],
    ),
    _fn(
        "open_app",
        "Open a PC app: chrome, edge, firefox, notepad, calculadora, paint, explorer, "
        "spotify, discord, whatsapp, telegram, cursor, vscode, word, excel, steam, "
        "taskmgr, terminal, powershell, snip/recortes, configuracion, wifi, bluetooth, sonido. "
        "Also resolves Start Menu shortcuts by name.",
        {"name": {"type": "string"}},
        ["name"],
    ),
    _fn(
        "open_folder",
        "Open desktop, downloads, documents, or workspace in Explorer.",
        {"name": {"type": "string"}},
        ["name"],
    ),
    _fn(
        "list_files",
        "List files in THIS user's workspace (data/users/<username>/workspace). "
        "Optional relative subfolder. Prefer for 'qué hay en el workspace / archivos'.",
        {"relative": {"type": "string"}},
    ),
    _fn(
        "read_file",
        "Read a UTF-8 file from THIS user's workspace only (relative path). "
        "Use for notes, diario_YYYY-MM-DD.txt, or files they mention in their sandbox.",
        {"relative": {"type": "string"}},
        ["relative"],
    ),
    _fn(
        "write_file",
        "Write a UTF-8 file inside THIS user's workspace only.",
        {
            "relative": {"type": "string"},
            "content": {"type": "string"},
            "append": {"type": "boolean", "default": False},
        },
        ["relative", "content"],
    ),
    _fn("screenshot", "Capture the PC screen into workspace/screenshot.png.", {}),
    _fn("set_clipboard", "Copy text to the Windows clipboard.", {"text": {"type": "string"}}, ["text"]),
    _fn(
        "get_clipboard",
        "Read the Windows clipboard text. Use when the user asks to review, summarize, "
        "fix, or look at what they just copied (Ctrl+C / portapapeles / 'lo que copié').",
        {},
    ),
    _fn(
        "power_control",
        "OWNER power on this Windows PC: action=shutdown (/s /t 30), restart (/r /t 10), "
        "abort (/a), or lock (LockWorkStation). Only when the user clearly orders "
        "apagar/reiniciar/cancelar apagado/bloquear pantalla.",
        {"action": {"type": "string", "description": "shutdown | restart | abort | lock"}},
        ["action"],
    ),
    _fn(
        "media",
        "Media/volume keys: play_pause, next, prev, stop, vol_up, vol_down, mute.",
        {"action": {"type": "string"}},
        ["action"],
    ),
    _fn(
        "play_music",
        "Play or search a song/artist/playlist. YouTube search URL, or Spotify app + search URL. "
        "Use when the user asks to hear music (poneme, reproducí, Spotify, YouTube, Cerati, etc.).",
        {
            "query": {
                "type": "string",
                "description": "Song, artist, album, or playlist name.",
            },
            "platform": {
                "type": "string",
                "description": "youtube (default) or spotify",
            },
        },
        ["query"],
    ),
    _fn(
        "send_email",
        "Send email via SMTP if configured in .env.",
        {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
        ["to", "subject", "body"],
    ),
    _fn(
        "home_assistant",
        "Call a Home Assistant service if HA_URL and HA_TOKEN are set. "
        "Lights/switches: turn_on/off. Climate temperature is hard-capped 18–26 C in Python. "
        "Locks/covers/alarm: owner only. Never shell_command.",
        {
            "domain": {"type": "string"},
            "service": {"type": "string"},
            "entity_id": {"type": "string"},
            "temperature": {"type": "number"},
        },
        ["domain", "service"],
    ),
    _fn(
        "control_device",
        "Turn a Home Assistant light/switch/fan on or off by entity_id "
        "(e.g. light.living, action=on|off|toggle). Owner may also set climate 18–26 C.",
        {
            "entity_id": {"type": "string"},
            "action": {"type": "string"},
            "temperature": {"type": "number"},
        },
        ["entity_id", "action"],
    ),
    _fn(
        "home_states",
        "List Home Assistant entity states (lights/switches; owner also climate/locks).",
        {"domain": {"type": "string"}},
    ),
    _fn(
        "phone_hands",
        "Control the user's phone when they are talking from the Ilaria Android or iOS app. "
        "action: call, sms, whatsapp, maps, navigate, browser, search, youtube, music, "
        "open_app, torch, camera, gallery, settings, wifi, bluetooth, volume, share, "
        "clipboard, alarm, timer, calendar, contacts, email, "
        "open_wifi_settings, open_app_settings, clear_http, refresh_device_snap. "
        "target: phone number, place, URL, or any installed app name except banking apps, "
        "torch on/off, volume up/down/mute/0-100, alarm HH:MM, timer minutes. "
        "text: SMS/WhatsApp/share body. Never open bank/wallet banking apps. "
        "Opens the system UI so the user confirms calls and messages. Never silent SMS.",
        {
            "action": {"type": "string"},
            "target": {"type": "string"},
            "text": {"type": "string"},
        },
        ["action"],
    ),
    _fn(
        "queue_phone_fix",
        "Enqueue Android maintenance for the CURRENT phone session only "
        "(open_wifi_settings, open_app_settings, clear_http, refresh_device_snap). "
        "Uses the same phone_actions SSE queue. Android client surface required.",
        {
            "action": {
                "type": "string",
                "description": "open_wifi_settings | open_app_settings | clear_http | refresh_device_snap",
            },
        },
        ["action"],
    ),
    _fn(
        "get_system_health",
        "Diagnose ILARIA local stack: HUD /health, Ollama API, Piper voice files, "
        "Home Assistant (if configured), UDP discover 8788, RAM. "
        "Use for 'diagnostica', 'qué está caído', stack health — not for open apps list "
        "(that is system_status).",
        {},
    ),
    _fn(
        "relaunch_service",
        "One-step allowlisted remediación of ILARIA stack only. "
        "service: ollama | piper | ha_ping. No arbitrary shell. Owner-oriented.",
        {
            "service": {
                "type": "string",
                "description": "ollama, piper, or ha_ping",
            },
        },
        ["service"],
    ),
    _fn(
        "check_lan_status",
        "LAN IP(s), whether internet probe works, HUD URLs for the phone, "
        "and whether UDP discover port 8788 is bound.",
        {},
    ),
]


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if text:
            self.parts.append(text)


def _search(query: str, max_results: int = 5) -> str:
    limit = max(1, min(int(max_results or 5), 8))
    rows: list[dict[str, Any]] = []
    try:
        found = DDGS().text(query, max_results=limit)
        rows.extend(list(found or []))
    except Exception as exc:  # noqa: BLE001
        return f"Search failed: {exc}"
    if not rows:
        return "No results."
    lines = []
    for item in rows:
        title = item.get("title") or ""
        href = item.get("href") or ""
        body = item.get("body") or ""
        lines.append(f"- {title}\n  {href}\n  {body}")
    return "\n".join(lines)


def _read_page(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Invalid URL."
    headers = {"User-Agent": "Ilaria/1.3 personal-assistant"}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return f"Fetch failed: {exc}"
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and not url.endswith((".html", ".htm")):
        text = response.text[:6000]
        return text or f"Non-HTML response ({content_type})."
    parser = _VisibleText()
    try:
        parser.feed(response.text)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", response.text)
        return re.sub(r"\s+", " ", text)[:8000]
    joined = " ".join(parser.parts)
    return joined[:8000] or "Empty page."


def _weather(city: str) -> str:
    q = city.strip() or "Buenos Aires"
    url = f"https://wttr.in/{quote(q)}"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params={"format": "j1"})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return f"Weather failed: {exc}"
    current = payload.get("current_condition", [{}])[0]
    nearest = payload.get("nearest_area", [{}])[0]
    area = (nearest.get("areaName") or [{}])[0].get("value", q)
    country = (nearest.get("country") or [{}])[0].get("value", "")
    desc = (current.get("weatherDesc") or [{}])[0].get("value", "")
    temp = current.get("temp_C", "?")
    feels = current.get("FeelsLikeC", "?")
    humidity = current.get("humidity", "?")
    wind = current.get("windspeedKmph", "?")
    days = payload.get("weather", [])[:2]
    forecast = []
    for day in days:
        forecast.append(f"{day.get('date')}: {day.get('mintempC')}–{day.get('maxtempC')} C")
    return (
        f"{area}, {country}: {desc}, {temp} C (feels {feels} C), "
        f"humidity {humidity}%, wind {wind} km/h. "
        + " | ".join(forecast)
    )


def weather_now(city: str) -> str:
    return _weather(city)


def make_executor(
    settings: Settings,
    memory: Memory,
    actions: Actions,
) -> Callable[[str, str], str]:
    def execute(name: str, arguments_json: str) -> str:
        try:
            args = json.loads(arguments_json or "{}")
        except json.JSONDecodeError:
            return (
                "ERROR: tool arguments must be a JSON object. "
                "Retry the same tool with valid JSON."
            )
        if not isinstance(args, dict):
            args = {}

        if name == "list_capabilities":
            return actions.capabilities()
        if name == "web_search":
            return _search(str(args.get("query", "")), int(args.get("max_results") or 5))
        if name in {"read_page", "open_url"}:
            return _read_page(str(args.get("url", "")))
        if name == "weather":
            return _weather(str(args.get("city", "")))
        if name == "wikipedia":
            return actions.wikipedia(str(args.get("topic", "")))
        if name == "now":
            stamp = datetime.now(ZoneInfo(settings.timezone))
            return stamp.strftime("%Y-%m-%d %H:%M:%S %Z")
        if name == "system_status":
            return actions.system_status()
        if name == "daily_journal":
            return actions.daily_journal(str(args.get("content", "")))
        if name == "read_daily_journal":
            return actions.read_daily_journal()
        if name == "set_volume":
            try:
                level = int(float(args.get("level") or 0))
            except (TypeError, ValueError):
                return "Nivel de volumen: un numero de 0 a 100."
            return actions.set_volume(level)
        if name == "undo_last":
            return actions.undo_last()
        if name == "calculate":
            return actions.calculate(str(args.get("expression", "")))
        if name == "remember":
            return memory.remember(str(args.get("key", "")), str(args.get("value", "")))
        if name == "recall":
            key = args.get("key")
            return memory.recall(str(key) if key else None)
        if name == "forget":
            return memory.forget(str(args.get("key", "")))
        if name == "note":
            text = str(args.get("text", "")).strip()
            return memory.add_note(text) if text else memory.list_notes()
        if name == "set_reminder":
            return memory.add_reminder(str(args.get("when_iso", "")), str(args.get("text", "")))
        if name == "set_timer":
            return memory.add_timer(float(args.get("minutes") or 0), str(args.get("text", "")), settings.timezone)
        if name == "list_reminders":
            return memory.pending_reminders()
        if name == "cancel_reminder":
            return memory.cancel_reminder(str(args.get("query", "")))
        if name == "open_browser":
            return actions.open_browser(str(args.get("url", "")))
        if name == "google":
            return actions.google(str(args.get("query", "")))
        if name == "open_maps":
            return actions.open_maps(str(args.get("destination", "")), str(args.get("origin", "")))
        if name == "compose_whatsapp":
            return actions.compose_whatsapp(str(args.get("phone", "")), str(args.get("text", "")))
        if name == "open_app":
            return actions.open_app(str(args.get("name", "")))
        if name == "open_folder":
            return actions.open_folder(str(args.get("name", "")))
        if name == "list_files":
            return actions.list_files(str(args.get("relative", "") or ""))
        if name == "read_file":
            return actions.read_file(str(args.get("relative", "")))
        if name == "write_file":
            return actions.write_file(
                str(args.get("relative", "")),
                str(args.get("content", "")),
                bool(args.get("append")),
            )
        if name == "screenshot":
            return actions.screenshot()
        if name == "set_clipboard":
            return actions.set_clipboard(str(args.get("text", "")))
        if name == "get_clipboard":
            return actions.get_clipboard()
        if name == "power_control":
            return actions.power_control(str(args.get("action", "")))
        if name == "media":
            return actions.media(str(args.get("action", "")))
        if name == "play_music":
            return actions.play_music(
                str(args.get("query", "")),
                str(args.get("platform", "youtube") or "youtube"),
            )
        if name == "send_email":
            return actions.send_email(
                str(args.get("to", "")),
                str(args.get("subject", "")),
                str(args.get("body", "")),
            )
        if name == "home_assistant":
            temp = args.get("temperature")
            try:
                temperature = float(temp) if temp is not None and str(temp) != "" else None
            except (TypeError, ValueError):
                return "Temperatura inválida."
            return actions.home_assistant(
                str(args.get("domain", "")),
                str(args.get("service", "")),
                str(args.get("entity_id", "")),
                temperature,
            )
        if name == "control_device":
            temp = args.get("temperature")
            try:
                temperature = float(temp) if temp is not None and str(temp) != "" else None
            except (TypeError, ValueError):
                return "Temperatura inválida."
            return actions.control_device(
                str(args.get("entity_id", "")),
                str(args.get("action", "")),
                temperature,
            )
        if name == "home_states":
            return actions.home_states(str(args.get("domain", "") or ""))
        if name == "phone_hands":
            if getattr(actions, "client_surface", "hud") not in {"android", "ios"}:
                return "Eso se hace en el celular. Pedilo desde la app Ilaria (Wi-Fi)."
            from jarvis.phone_hands import queue_action

            return queue_action(actions.phone_queue, args)
        if name == "queue_phone_fix":
            if getattr(actions, "client_surface", "hud") not in {"android", "ios"}:
                return "Eso se hace en el celular. Pedilo desde la app Ilaria (Wi-Fi)."
            from jarvis.phone_hands import queue_phone_fix

            return json.dumps(
                queue_phone_fix(actions.phone_queue, str(args.get("action", ""))),
                ensure_ascii=False,
            )
        if name == "get_system_health":
            from jarvis.self_healing import health_report_text

            return health_report_text(settings)
        if name == "relaunch_service":
            from jarvis.self_healing import relaunch_service

            result = relaunch_service(settings, str(args.get("service", "")))
            return json.dumps(result, ensure_ascii=False)
        if name == "check_lan_status":
            from jarvis.self_healing import check_lan_status

            return json.dumps(check_lan_status(settings), ensure_ascii=False)
        return f"Unknown tool: {name}"

    return execute


def _tool_name(schema: dict[str, Any]) -> str:
    return str(schema["function"]["name"])


ALL_TOOL_NAMES = {_tool_name(item) for item in TOOL_SCHEMAS}
# Owner-only even when members_pc_hands is enabled.
OWNER_ONLY_TOOLS = {"power_control", "relaunch_service"}
PC_TOOLS = {
    "open_app",
    "open_folder",
    "screenshot",
    "media",
    "play_music",
    "set_volume",
    "undo_last",
    "send_email",
    "home_assistant",
    "compose_whatsapp",
    "write_file",
    "set_clipboard",
    "get_clipboard",
    "power_control",
    "relaunch_service",
}
# webbrowser / PC shell openers — never expose these on phone surfaces
PHONE_BLOCKED_TOOLS = PC_TOOLS | {
    "open_browser",
    "google",
    "open_maps",
    "system_status",
    "list_files",
    "read_file",
    "control_device",
    "get_system_health",
    "check_lan_status",
}
MEMBER_TOOLS = ALL_TOOL_NAMES - PC_TOOLS


def schemas_for(allowed: set[str]) -> list[dict[str, Any]]:
    return [item for item in TOOL_SCHEMAS if _tool_name(item) in allowed]


def tools_for_surface(allowed: set[str] | None, surface: str) -> list[dict[str, Any]]:
    """Filter tool schemas so phone sessions cannot trigger PC-side openers."""
    base = set(ALL_TOOL_NAMES) if allowed is None else set(allowed)
    if (surface or "hud").strip().lower() in {"android", "ios", "iphone", "ipad"}:
        base -= PHONE_BLOCKED_TOOLS
    return schemas_for(base)
