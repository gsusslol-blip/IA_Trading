"""Scan / summarize / maintain the active user's workspace and TTS phrase cache."""

from __future__ import annotations

import json
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.config import DATA_DIR, ROOT
from jarvis.security import safe_under
from jarvis.tts import phrase_cache_dir


def analyze_workspace(workspace: Path, *, timezone: str = "America/Argentina/Buenos_Aires") -> str:
    """Telemetry for the LLM: counts, today's diario, sample filenames."""
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    files = sorted(p.name for p in root.iterdir() if p.is_file() or p.is_dir())
    txt = [f for f in files if f.lower().endswith(".txt")]
    mp3 = [f for f in files if f.lower().endswith(".mp3")]
    wav = [f for f in files if f.lower().endswith(".wav")]
    dirs = [p.name for p in root.iterdir() if p.is_dir()]
    try:
        day = datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")
    except Exception:
        day = datetime.now().strftime("%Y-%m-%d")
    diario_name = f"diario_{day}.txt"
    report: dict[str, Any] = {
        "status": "success",
        "workspace": str(root),
        "total_entries": len(files),
        "txt_count": len(txt),
        "mp3_count": len(mp3),
        "wav_count": len(wav),
        "dir_count": len(dirs),
        "latest_diario": diario_name in txt,
        "diario_name": diario_name,
        "files_list": files[:12],
    }
    return json.dumps(report, ensure_ascii=False, indent=2)


def write_to_workspace(workspace: Path, filename: str, content: str) -> str:
    """Write UTF-8 file with basename-only sandbox (no path traversal)."""
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        return json.dumps({"status": "error", "message": "Nombre de archivo inválido."})
    try:
        target = safe_under(workspace, safe_name)
    except ValueError as exc:
        return json.dumps({"status": "error", "message": str(exc)})
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return json.dumps(
        {"status": "success", "file_created": target.name, "bytes": target.stat().st_size},
        ensure_ascii=False,
    )


def purge_old_tts_cache(days_limit: int = 7) -> dict[str, Any]:
    """Delete phrase-cache WAV/MP3 older than ``days_limit`` days."""
    cache = phrase_cache_dir()
    # Also sweep legacy hash cache under data/tts-cache
    folders = [cache, DATA_DIR / "tts-cache"]
    cutoff = time.time() - (max(1, int(days_limit)) * 86400)
    purged = 0
    scanned = 0
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() not in {".wav", ".mp3"}:
                continue
            scanned += 1
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    purged += 1
            except OSError:
                continue
    return {
        "status": "success",
        "files_removed": purged,
        "files_scanned": scanned,
        "days_limit": int(days_limit),
        "cache_dir": str(cache.relative_to(ROOT) if cache.is_relative_to(ROOT) else cache),
    }


def backup_user_notes(
    *,
    workspace: Path,
    user_root: Path | None = None,
    memory_path: Path | None = None,
) -> dict[str, Any]:
    """Zip synced notes (memory.json notes + optional notes/ folder) into the workspace."""
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"backup_notes_{stamp}.zip"
    try:
        zip_path = safe_under(workspace, zip_name)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    sources: list[tuple[Path, str]] = []
    root = Path(user_root) if user_root else workspace.parent
    notes_dir = root / "notes"
    if notes_dir.is_dir():
        for path in notes_dir.rglob("*"):
            if path.is_file():
                sources.append((path, f"notes/{path.relative_to(notes_dir).as_posix()}"))

    mem = Path(memory_path) if memory_path else (root / "memory.json")
    if mem.is_file():
        try:
            payload = json.loads(mem.read_text(encoding="utf-8"))
            notes = payload.get("notes") if isinstance(payload, dict) else None
            if isinstance(notes, list) and notes:
                snap = workspace / f"_notes_snap_{stamp}.json"
                snap.write_text(
                    json.dumps({"notes": notes, "rev": payload.get("notes_rev", 0)}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                sources.append((snap, "memory_notes.json"))
        except (OSError, json.JSONDecodeError):
            pass

    if not sources:
        return {"status": "ignored", "reason": "No notes found to backup"}

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for full, arc in sources:
            try:
                zf.write(full, arcname=arc)
            except OSError:
                continue

    # Drop temporary snapshot if we created one
    for full, arc in sources:
        if arc == "memory_notes.json" and full.name.startswith("_notes_snap_"):
            try:
                full.unlink()
            except OSError:
                pass

    return {"status": "success", "backup_file": zip_name, "entries": len(sources)}
