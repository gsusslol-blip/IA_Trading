"""Tactical undo queue — last reversible PC action within ~30 seconds."""

from __future__ import annotations

import threading
import time
from typing import Any


class UndoQueue:
    """In-memory single-slot undo with hard TTL (default 30s)."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = float(ttl_seconds)
        self._lock = threading.Lock()
        self._item: dict[str, Any] | None = None
        self._timer: threading.Timer | None = None

    def push(self, kind: str, **payload: Any) -> None:
        with self._lock:
            self._cancel_timer_unlocked()
            self._item = {"kind": kind, **payload, "ts": time.time()}
            self._timer = threading.Timer(self._ttl, self.clear)
            self._timer.daemon = True
            self._timer.start()

    def pop(self) -> dict[str, Any] | None:
        with self._lock:
            item = self._item
            self._item = None
            self._cancel_timer_unlocked()
            if not item:
                return None
            if (time.time() - float(item.get("ts") or 0)) > self._ttl:
                return None
            return item

    def peek(self) -> dict[str, Any] | None:
        with self._lock:
            item = self._item
            if not item:
                return None
            if (time.time() - float(item.get("ts") or 0)) > self._ttl:
                return None
            return dict(item)

    def clear(self) -> None:
        with self._lock:
            self._item = None
            self._cancel_timer_unlocked()

    def _cancel_timer_unlocked(self) -> None:
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None
