"""Background reminder + light proactive desk-break pump."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.state import AppState
from jarvis.tts import audio_api_path, speak_to_file

TelegramSend = Callable[[str], Awaitable[None]]


async def reminder_loop(state: AppState, telegram_send: TelegramSend | None = None) -> None:
    """Poll due reminders and optional hourly care nudges; speak via HUD Piper."""
    last_hourly_key = ""
    while True:
        try:
            for brain in state.all_user_brains():
                who = (brain.settings.user_name or "señor").strip() or "señor"
                for text in brain.due_alerts():
                    spoken = f"Disculpe la interrupción, {who}. Recordatorio: {text}"
                    await _announce(brain, spoken, telegram_send)

                if brain.is_owner:
                    try:
                        from jarvis.autonomy import tick

                        nudge = tick(brain)
                    except Exception:
                        nudge = None
                    if nudge:
                        await _announce(brain, nudge, telegram_send)

                if _hourly_enabled() and not (brain.is_owner and _autonomy_on()):
                    key = _hourly_slot(brain.settings.timezone)
                    if key and key != last_hourly_key and key.endswith(":00"):
                        # Fire once per clock hour across the process.
                        last_hourly_key = key
                        status = ""
                        try:
                            status = brain.actions.system_status()
                        except Exception:
                            status = ""
                        if "Cursor" in status or "VS Code" in status or "Excel" in status:
                            spoken = (
                                f"Disculpe la interrupción, {who}. "
                                "Lleva un rato seguido en la estación. "
                                "Si quiere, estiro el monitoreo de recordatorios mientras usted toma un minuto."
                            )
                            await _announce(brain, spoken, telegram_send)
        except Exception:
            pass
        await asyncio.sleep(30)


def _hourly_enabled() -> bool:
    return os.getenv("PROACTIVE_HOURLY", "1").strip() not in {"0", "false", "False", "no"}


def _autonomy_on() -> bool:
    return os.getenv("AUTONOMY", "1").strip().lower() not in {"0", "false", "no"}


def _hourly_slot(timezone: str) -> str:
    now = datetime.now(ZoneInfo(timezone))
    # Only trigger in the first half-minute of the hour so we don't spam.
    if now.minute != 0 or now.second > 35:
        return ""
    return now.strftime("%Y-%m-%d %H:00")


async def _announce(brain, spoken: str, telegram_send: TelegramSend | None) -> None:
    audio_url = None
    try:
        path = await speak_to_file(
            brain.settings,
            spoken,
            f"tts-alerta-{time.time_ns()}.mp3",
        )
        audio_url = audio_api_path(path.name)
    except Exception:
        audio_url = None
    alert = brain.bus.push(spoken, audio_url=audio_url)
    if telegram_send is not None:
        await telegram_send(alert.text)
