"""In-process alerts for HUD and Telegram."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class Alert:
    id: int
    text: str
    created: float
    audio_url: str | None = None


class EventBus:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: list[Alert] = []
        self._next_id = 1
        self.telegram_chat_id: int | None = None

    def push(self, text: str, audio_url: str | None = None) -> Alert:
        clean = " ".join(text.split())
        with self._lock:
            alert = Alert(
                id=self._next_id,
                text=clean,
                created=time.time(),
                audio_url=audio_url,
            )
            self._next_id += 1
            self._items.append(alert)
            self._items[:] = self._items[-80:]
        _beep()
        return alert

    def since(self, after_id: int) -> list[Alert]:
        with self._lock:
            return [item for item in self._items if item.id > after_id]

    def set_telegram_chat(self, chat_id: int) -> None:
        with self._lock:
            self.telegram_chat_id = chat_id


def _beep() -> None:
    if sys.platform != "win32":
        return
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass
