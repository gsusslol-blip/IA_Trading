"""Condensed long-term memory from daily journals (deterministic, no LLM).

Nightly (or catch-up on boot): read diario_YYYY-MM-DD.txt, extract up to
``MEMORY_LTM_PER_NIGHT`` milestone lines, rigid-dedupe against
workspace/long_term_memory.json, hard-cap ``MEMORY_LTM_CAP`` facts.

The JSON is injected into the *static* system-prompt block so Ollama's KV
prefix stays stable across turns (clock/journal stay in LIVE).

Env:
  MEMORY_CONDENSER_ENABLED=1|0   (default 1)
  MEMORY_LTM_PER_NIGHT=3
  MEMORY_LTM_CAP=40
  MEMORY_CONDENSER_POLL_SEC=120
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jarvis.config import DATA_DIR, Settings, load_settings

_LOCK = threading.Lock()
_STARTED = False

_TS_PREFIX = re.compile(r"^\[\d{1,2}:\d{2}\]\s*")
_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^\w\sáéíóúüñ¿¡]+", re.I)

# Deterministic milestone cues (rioplatense / Spanish).
_MILESTONE = re.compile(
    r"\b("
    r"compr[eé]|compramos|empec[eé]|arranqu[eé]|termin[eé]|decid[ií]|"
    r"record[aá]|me\s+mud[eé]|nueva?\s+dieta|dieta\s+nueva|"
    r"instal[eé]|configur[eé]|cambi[eé]|aprend[ií]|logré|logre|"
    r"firm[eé]|acept[eé]|rechaz[eé]|viaj[eé]|llegu[eé]|"
    r"primer|primera\s+vez|hito|importante|hoy\s+empec"
    r")\b",
    re.I,
)

_SKIP = re.compile(
    r"^\s*(nota\s+remota|recordatorio:|timer|ping|test|hola|chau)\b",
    re.I,
)


def ltm_path(workspace: Path) -> Path:
    return Path(workspace) / "long_term_memory.json"


def per_night_limit() -> int:
    try:
        return max(1, min(5, int(os.getenv("MEMORY_LTM_PER_NIGHT", "3") or 3)))
    except ValueError:
        return 3


def hard_cap() -> int:
    try:
        return max(5, min(120, int(os.getenv("MEMORY_LTM_CAP", "40") or 40)))
    except ValueError:
        return 40


def condenser_enabled() -> bool:
    return os.getenv("MEMORY_CONDENSER_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def normalize_fact(text: str) -> str:
    raw = _TS_PREFIX.sub("", (text or "").strip())
    raw = _NON_ALNUM.sub(" ", raw.lower())
    return _WS.sub(" ", raw).strip()


def _load_store(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"facts": [], "last_run_day": "", "version": 1}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"facts": [], "last_run_day": "", "version": 1}
    if not isinstance(data, dict):
        return {"facts": [], "last_run_day": "", "version": 1}
    facts = data.get("facts")
    if not isinstance(facts, list):
        data["facts"] = []
    return data


def _save_store(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def extract_milestones(diario_text: str, *, limit: int | None = None) -> list[str]:
    """Pick up to ``limit`` milestone lines from a diary (deterministic)."""
    lim = per_night_limit() if limit is None else max(1, min(5, int(limit)))
    scored: list[tuple[int, int, str]] = []
    for idx, line in enumerate((diario_text or "").splitlines()):
        clean = _TS_PREFIX.sub("", line.strip())
        if len(clean) < 12 or len(clean) > 180:
            continue
        if _SKIP.match(clean):
            continue
        score = 0
        if _MILESTONE.search(clean):
            score += 10
        low = clean.lower()
        if any(k in low for k in ("porque", "decid", "desde hoy", "a partir")):
            score += 2
        if clean[:1].isupper() or clean.startswith(("Hoy", "Ayer", "Me ")):
            score += 1
        if score <= 0:
            continue
        scored.append((score, -idx, clean[:140]))
    scored.sort(reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for _, __, text in scored:
        norm = normalize_fact(text)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(text)
        if len(out) >= lim:
            break
    # Fallback: last non-trivial lines if nothing matched cues
    if not out:
        lines = [
            _TS_PREFIX.sub("", ln.strip())[:140]
            for ln in (diario_text or "").splitlines()
            if len(ln.strip()) >= 20 and not _SKIP.match(ln.strip())
        ]
        for text in lines[-lim:]:
            norm = normalize_fact(text)
            if norm and norm not in seen:
                seen.add(norm)
                out.append(text)
    return out[:lim]


def merge_facts(
    existing: list[dict[str, Any]],
    newcomers: list[str],
    *,
    source_day: str,
    cap: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Append newcomers with rigid dedupe; trim to hard cap (oldest dropped)."""
    limit = hard_cap() if cap is None else max(5, int(cap))
    norms = {
        str(item.get("norm") or normalize_fact(str(item.get("text") or "")))
        for item in existing
        if isinstance(item, dict)
    }
    norms.discard("")
    added = 0
    now_ts = time.time()
    merged = [item for item in existing if isinstance(item, dict)]
    for text in newcomers:
        body = (text or "").strip()
        norm = normalize_fact(body)
        if not body or not norm or norm in norms:
            continue
        norms.add(norm)
        merged.append(
            {
                "id": f"{source_day}-{added}-{int(now_ts) % 100000}",
                "text": body,
                "norm": norm,
                "source_day": source_day,
                "added_at": now_ts,
            }
        )
        added += 1
    if len(merged) > limit:
        merged = merged[-limit:]
    return merged, added


def condense_day(workspace: Path, day: str) -> dict[str, Any]:
    """Condense one ``diario_<day>.txt`` into long_term_memory.json."""
    workspace = Path(workspace)
    path = ltm_path(workspace)
    diario = workspace / f"diario_{day}.txt"
    with _LOCK:
        store = _load_store(path)
        if not diario.is_file():
            store["last_run_day"] = max(str(store.get("last_run_day") or ""), day)
            _save_store(path, store)
            return {
                "status": "no_diario",
                "day": day,
                "added": 0,
                "total": len(store.get("facts") or []),
            }
        text = diario.read_text(encoding="utf-8", errors="replace")
        milestones = extract_milestones(text)
        facts, added = merge_facts(
            list(store.get("facts") or []),
            milestones,
            source_day=day,
        )
        store["facts"] = facts
        store["last_run_day"] = day
        store["updated_at"] = time.time()
        _save_store(path, store)
        return {
            "status": "ok",
            "day": day,
            "added": added,
            "candidates": milestones,
            "total": len(facts),
            "path": str(path),
        }


def format_long_term_prompt(workspace: Path | None, *, max_lines: int = 12) -> str:
    """Stable text block for the static system prompt (empty → omit)."""
    if workspace is None:
        return ""
    path = ltm_path(Path(workspace))
    store = _load_store(path)
    facts = [f for f in (store.get("facts") or []) if isinstance(f, dict)]
    if not facts:
        return ""
    lines: list[str] = []
    for item in facts[-max(1, max_lines) :]:
        text = str(item.get("text") or "").strip()
        if text:
            lines.append(f"- {text}")
    if not lines:
        return ""
    return "Long-term milestones (condensed, durable):\n" + "\n".join(lines)


def list_user_workspaces() -> list[tuple[str, Path]]:
    root = DATA_DIR / "users"
    if not root.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for path in root.iterdir():
        if path.is_dir() and not path.name.startswith("."):
            ws = path / "workspace"
            ws.mkdir(parents=True, exist_ok=True)
            out.append((path.name.lower(), ws))
    return out


def catch_up_user(workspace: Path, *, timezone: str) -> list[dict[str, Any]]:
    """Condense yesterday if not yet processed (one day max per tick)."""
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    path = ltm_path(workspace)
    store = _load_store(path)
    last = str(store.get("last_run_day") or "")
    if last >= yesterday:
        return []
    return [condense_day(workspace, yesterday)]


def run_all_users(*, timezone: str | None = None) -> list[dict[str, Any]]:
    tz = timezone or "America/Argentina/Buenos_Aires"
    results: list[dict[str, Any]] = []
    for user, ws in list_user_workspaces():
        for item in catch_up_user(ws, timezone=tz):
            item["user"] = user
            results.append(item)
            print(
                f"[LTM] {user} day={item.get('day')} "
                f"+{item.get('added')} → total={item.get('total')} ({item.get('status')})"
            )
    return results


def start_memory_condenser_watcher(settings: Settings | None = None) -> None:
    """Background poll: after local midnight, condense yesterday's diary."""
    global _STARTED
    if not condenser_enabled():
        print("[LTM] off (set MEMORY_CONDENSER_ENABLED=1)")
        return
    cfg = settings or load_settings()
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    try:
        interval = float(os.getenv("MEMORY_CONDENSER_POLL_SEC", "120") or 120)
    except ValueError:
        interval = 120.0
    interval = max(60.0, min(900.0, interval))

    def _run() -> None:
        print(f"[LTM] condensador de memoria cada {interval:.0f}s (catch-up post-medianoche)")
        # Immediate catch-up if Ilaria was off at midnight.
        try:
            run_all_users(timezone=cfg.timezone)
        except Exception as exc:  # noqa: BLE001
            print(f"[LTM] boot catch-up: {exc}")
        while True:
            time.sleep(interval)
            try:
                run_all_users(timezone=cfg.timezone)
            except Exception as exc:  # noqa: BLE001
                print(f"[LTM] ciclo: {exc}")

    threading.Thread(target=_run, name="ilaria-memory-condenser", daemon=True).start()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Condense diario → long_term_memory.json")
    parser.add_argument("--user", default="gsuss")
    parser.add_argument("--day", default="", help="YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--catch-up", action="store_true")
    args = parser.parse_args()
    ws = DATA_DIR / "users" / args.user.strip().lower() / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    if args.catch_up:
        print(json.dumps(run_all_users(), ensure_ascii=False, indent=2))
    else:
        if args.day:
            day = args.day
        else:
            day = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        print(json.dumps(condense_day(ws, day), ensure_ascii=False, indent=2))
