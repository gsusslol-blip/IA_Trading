"""Persistent user facts and reminders."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from jarvis.config import DATA_DIR


def _note_id() -> str:
    from uuid import uuid4

    return uuid4().hex[:12]


class Memory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (DATA_DIR / "memory.json")
        self._lock = Lock()
        self._data: dict[str, Any] = {"facts": {}, "reminders": [], "notes": []}
        self.recovered = False
        self._load()

    def _load(self) -> None:
        bak = self.path.with_suffix(self.path.suffix + ".bak")
        loaded = _read_json_dict(self.path)
        if loaded is None and bak.is_file():
            loaded = _read_json_dict(bak)
            if loaded is not None:
                self.recovered = True
                try:
                    self.path.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")
                except OSError:
                    pass
        if loaded is None and (self.path.exists() or bak.exists()):
            self.recovered = True
            loaded = {}
        if loaded:
            self._data.update(loaded)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)
        bak = self.path.with_suffix(self.path.suffix + ".bak")
        try:
            bak.write_text(payload, encoding="utf-8")
        except OSError:
            pass
        _daily_backup(self.path)

    def remember(self, key: str, value: str) -> str:
        key = key.strip().lower()
        with self._lock:
            self._data.setdefault("facts", {})[key] = value.strip()
            self._save()
        return f"Saved: {key} = {value.strip()}"

    def forget(self, key: str) -> str:
        key = key.strip().lower()
        with self._lock:
            facts: dict[str, str] = self._data.setdefault("facts", {})
            if key not in facts:
                return f"No fact named '{key}'."
            del facts[key]
            self._save()
        return f"Forgot: {key}"

    def recall(self, key: str | None = None) -> str:
        facts: dict[str, str] = self._data.get("facts", {})
        if key:
            key = key.strip().lower()
            return facts.get(key, f"No fact named '{key}'.")
        if not facts:
            return "No stored facts yet."
        return "\n".join(f"- {k}: {v}" for k, v in facts.items())

    def facts_map(self) -> dict[str, str]:
        facts = self._data.get("facts", {})
        if not isinstance(facts, dict):
            return {}
        out: dict[str, str] = {}
        for key, value in facts.items():
            k = str(key).strip().lower()
            v = str(value).strip()
            if k and v:
                out[k] = v
        return out

    def merge_facts(self, incoming: dict[str, str]) -> dict[str, str]:
        with self._lock:
            facts: dict[str, Any] = self._data.setdefault("facts", {})
            if not isinstance(facts, dict):
                facts = {}
                self._data["facts"] = facts
            for key, value in incoming.items():
                k = str(key).strip().lower()
                v = str(value).strip()
                if k and v:
                    facts[k] = v
            self._save()
        return self.facts_map()

    def add_note(self, text: str) -> str:
        body = text.strip()
        if not body:
            return "Empty note."
        with self._lock:
            records = self._note_records_locked()
            records.append(
                {
                    "id": _note_id(),
                    "text": body,
                    "updated": datetime.now().timestamp(),
                }
            )
            records[:] = records[-50:]
            self._data["notes"] = records
            self._bump_rev_locked()
            self._save()
        return "Note stored."

    def list_notes(self) -> str:
        items = self.notes_items()
        if not items:
            return "No notes."
        return "\n".join(f"{i}. {n}" for i, n in enumerate(items, 1))

    def notes_items(self) -> list[str]:
        return [item["text"] for item in self.notes_records() if item.get("text")]

    def notes_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._note_records_locked()]

    def notes_rev(self) -> int:
        with self._lock:
            try:
                return int(self._data.get("notes_rev") or 0)
            except (TypeError, ValueError):
                return 0

    def notes_export(self) -> dict[str, Any]:
        records = self.notes_records()
        return {
            "ok": True,
            "rev": self.notes_rev(),
            "items": records,
            "notes": [item["text"] for item in records],
        }

    def merge_notes(self, incoming: list[dict[str, Any]], client_rev: int = 0) -> dict[str, Any]:
        """Last-write-wins by id + updated. PC is source of truth if timestamps tie."""
        with self._lock:
            current = {item["id"]: dict(item) for item in self._note_records_locked()}
            for raw in incoming:
                if not isinstance(raw, dict):
                    continue
                text = str(raw.get("text") or "").strip()
                nid = str(raw.get("id") or "").strip() or _note_id()
                if raw.get("deleted"):
                    current.pop(nid, None)
                    continue
                if not text:
                    continue
                try:
                    updated = float(raw.get("updated") or 0)
                except (TypeError, ValueError):
                    updated = 0.0
                prev = current.get(nid)
                if prev is None or updated >= float(prev.get("updated") or 0):
                    current[nid] = {"id": nid, "text": text, "updated": updated or datetime.now().timestamp()}
            records = sorted(current.values(), key=lambda item: float(item.get("updated") or 0))[-50:]
            self._data["notes"] = records
            server_rev = 0
            try:
                server_rev = int(self._data.get("notes_rev") or 0)
            except (TypeError, ValueError):
                server_rev = 0
            self._data["notes_rev"] = max(server_rev, int(client_rev or 0)) + 1
            self._save()
            out = [dict(item) for item in records]
        return {
            "ok": True,
            "rev": self.notes_rev(),
            "items": out,
            "notes": [item["text"] for item in out],
        }

    def delete_note(self, note_id: str) -> bool:
        nid = (note_id or "").strip()
        with self._lock:
            records = self._note_records_locked()
            kept = [item for item in records if item.get("id") != nid]
            if len(kept) == len(records):
                return False
            self._data["notes"] = kept
            self._bump_rev_locked()
            self._save()
        return True

    def _bump_rev_locked(self) -> None:
        try:
            current = int(self._data.get("notes_rev") or 0)
        except (TypeError, ValueError):
            current = 0
        self._data["notes_rev"] = current + 1

    def _note_records_locked(self) -> list[dict[str, Any]]:
        raw = self._data.get("notes", [])
        records: list[dict[str, Any]] = []
        migrated = False
        for index, item in enumerate(raw):
            if isinstance(item, str) and item.strip():
                records.append(
                    {
                        "id": f"legacy-{index}",
                        "text": item.strip(),
                        "updated": 0.0,
                    }
                )
                migrated = True
            elif isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                nid = str(item.get("id") or "").strip() or f"legacy-{index}"
                try:
                    updated = float(item.get("updated") or 0)
                except (TypeError, ValueError):
                    updated = 0.0
                records.append({"id": nid, "text": text, "updated": updated})
        if migrated:
            self._data["notes"] = records
            self._save()
        return records

    def add_reminder(self, when_iso: str, text: str) -> str:
        with self._lock:
            reminders: list[dict[str, str]] = self._data.setdefault("reminders", [])
            reminders.append({"when": when_iso, "text": text.strip(), "done": "0"})
            self._save()
        return f"Reminder set for {when_iso}: {text.strip()}"

    def add_timer(self, minutes: float, text: str, timezone: str) -> str:
        from zoneinfo import ZoneInfo

        when = datetime.now(ZoneInfo(timezone)) + timedelta(minutes=float(minutes))
        stamp = when.isoformat(timespec="seconds")
        return self.add_reminder(stamp, text)

    def cancel_reminder(self, query: str) -> str:
        needle = query.strip().lower()
        with self._lock:
            reminders: list[dict[str, str]] = self._data.setdefault("reminders", [])
            hits = [
                item
                for item in reminders
                if item.get("done") != "1"
                and needle in f"{item.get('text', '')} {item.get('when', '')}".lower()
            ]
            if not hits:
                return f"No pending reminder matching '{query}'."
            for item in hits:
                item["done"] = "1"
            self._save()
        return f"Cancelled {len(hits)} reminder(s)."

    def due_reminders(self, now: datetime) -> list[str]:
        due: list[str] = []
        with self._lock:
            changed = False
            for item in self._data.get("reminders", []):
                if item.get("done") == "1":
                    continue
                try:
                    when = datetime.fromisoformat(item["when"])
                except (KeyError, ValueError):
                    continue
                if when.tzinfo is None:
                    when = when.replace(tzinfo=now.tzinfo)
                if when <= now:
                    due.append(item.get("text", ""))
                    item["done"] = "1"
                    changed = True
            if changed:
                self._save()
        return [text for text in due if text]

    def pending_reminders(self) -> str:
        pending = [
            f"- {r.get('when')}: {r.get('text')}"
            for r in self._data.get("reminders", [])
            if r.get("done") != "1"
        ]
        return "\n".join(pending) if pending else "No pending reminders."

    def as_prompt(self) -> str:
        facts: dict[str, str] = self._data.get("facts", {})
        if not facts:
            return "(none yet)"
        return "\n".join(f"- {k}: {v}" for k, v in facts.items())


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _daily_backup(path: Path) -> None:
    try:
        if not path.is_file():
            return
        folder = DATA_DIR / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = folder / f"{path.stem}-{datetime.now().strftime('%Y-%m-%d')}.json"
        if stamp.is_file():
            return
        shutil.copy2(path, stamp)
        kept = sorted(folder.glob(f"{path.stem}-*.json"))
        for old in kept[:-14]:
            old.unlink(missing_ok=True)
    except OSError:
        pass
