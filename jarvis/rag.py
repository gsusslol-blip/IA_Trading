"""Tiny local retrieval — keyword overlap, no extra embedding model / VRAM."""

from __future__ import annotations

import re
from pathlib import Path

from jarvis.memory import Memory

_TOKEN = re.compile(r"[a-záéíóúüñ0-9]{3,}", re.I)
_SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".mp3", ".wav", ".webm", ".mp4", ".exe", ".zip"}


def retrieve(
    query: str,
    memory: Memory,
    workspace: Path,
    *,
    k: int = 3,
) -> list[str]:
    """Return up to k short snippets for the compact prompt."""
    needle = (query or "").strip()
    if len(needle) < 3:
        return []
    q_tokens = set(_TOKEN.findall(needle.lower()))
    if not q_tokens:
        return []
    scored: list[tuple[int, str]] = []
    for chunk in _chunks(memory, workspace):
        score = _score(q_tokens, chunk.lower())
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for _, chunk in scored:
        key = chunk[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(chunk[:280])
        if len(out) >= k:
            break
    return out


def format_for_prompt(snippets: list[str]) -> str:
    if not snippets:
        return ""
    lines = "\n".join(f"- {item}" for item in snippets)
    return f"Datos locales relevantes:\n{lines}"


def _score(q_tokens: set[str], hay: str) -> int:
    hits = 0
    for token in q_tokens:
        if token in hay:
            hits += 1
    return hits


def _chunks(memory: Memory, workspace: Path) -> list[str]:
    items: list[str] = []
    facts = memory.recall()
    if facts and not facts.startswith("No stored"):
        items.append(facts[:800])
    for note in memory.notes_items()[-20:]:
        items.append(f"nota: {note}")
    root = workspace
    if not root.is_dir():
        return items
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in _SKIP_SUFFIX:
            continue
        if path.stat().st_size > 80_000:
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        body = " ".join(text.split())[:500]
        if body:
            items.append(f"{rel}: {body}")
        if len(items) > 80:
            break
    return items
