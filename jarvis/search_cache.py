"""Semantic search cache — skip Bing/DDG when a near-identical query was answered recently.

100% Python: token + char-ngram cosine (no embedding model / no VRAM).
Store lives in the user sandbox: data/users/<user>/workspace/search_cache.json
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"[a-záéíóúüñ0-9]{2,}", re.I)
_CACHE_NAME = "search_cache.json"
_DEFAULT_TTL_S = 24 * 3600
_MAX_ENTRIES = 120
_ACCENT = str.maketrans("áéíóúüñ", "aeiouun")


def cache_path(workspace: Path) -> Path:
    folder = Path(workspace)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / _CACHE_NAME


def _normalize_query(text: str) -> str:
    raw = " ".join((text or "").lower().split()).translate(_ACCENT)
    raw = re.sub(
        r"\b(por favor|please|decime|contame|buscar?|busca|google(?:a[rd]?)?|"
        r"hoy|ahora|como se hace|como hacer|receta de|receta)\b",
        " ",
        raw,
    )
    return " ".join(raw.split())


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(_normalize_query(text))


def _char_ngrams(text: str, n: int = 3) -> list[str]:
    s = re.sub(r"\s+", " ", _normalize_query(text))
    if len(s) < n:
        return [s] if s else []
    return [s[i : i + n] for i in range(len(s) - n + 1)]


def _tf(features: list[str]) -> dict[str, float]:
    bag: dict[str, float] = {}
    for item in features:
        bag[item] = bag.get(item, 0.0) + 1.0
    return bag


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return dot / (na * nb)


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def similarity(query_a: str, query_b: str) -> float:
    """Blend Jaccard tokens (55%) + char-trigram cosine (45%)."""
    ta = _tokens(query_a)
    tb = _tokens(query_b)
    jac = _jaccard(ta, tb)
    char = _cosine(_tf(_char_ngrams(query_a)), _tf(_char_ngrams(query_b)))
    score = 0.55 * jac + 0.45 * char
    # Exact normalized equality / containment boost for near-paraphrases
    na, nb = _normalize_query(query_a), _normalize_query(query_b)
    if na and nb and (na == nb or na in nb or nb in na):
        score = max(score, 0.96)
    return score


def _threshold() -> float:
    try:
        return float(os.getenv("SEARCH_CACHE_THRESHOLD", "0.85") or 0.85)
    except ValueError:
        return 0.85


def _ttl_seconds(kind: str = "web") -> float:
    env_key = "SEARCH_CACHE_TTL_WIKI_SEC" if kind == "wiki" else "SEARCH_CACHE_TTL_SEC"
    default = str(7 * 24 * 3600 if kind == "wiki" else _DEFAULT_TTL_S)
    try:
        return float(os.getenv(env_key, default) or default)
    except ValueError:
        return float(default)


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _save(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows[-_MAX_ENTRIES:], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def lookup(
    query: str,
    workspace: Path | None,
    *,
    kind: str = "web",
) -> dict[str, Any] | None:
    """Return best cache hit above threshold, or None."""
    if os.getenv("SEARCH_CACHE_ENABLED", "1").strip().lower() in {"0", "false", "off", "no"}:
        return None
    if workspace is None:
        return None
    q = _normalize_query(query)
    if len(q) < 4:
        return None
    path = cache_path(workspace)
    now = time.time()
    ttl = _ttl_seconds(kind)
    thr = _threshold()
    best: dict[str, Any] | None = None
    best_score = 0.0
    alive: list[dict[str, Any]] = []
    changed = False
    for row in _load(path):
        if row.get("kind", "web") != kind:
            alive.append(row)
            continue
        ts = float(row.get("ts") or 0)
        if ts and (now - ts) > ttl:
            changed = True
            continue
        alive.append(row)
        score = similarity(q, str(row.get("query") or ""))
        if score > best_score:
            best_score = score
            best = row
    if changed:
        _save(path, alive)
    if best is None or best_score < thr:
        return None
    answer = str(best.get("answer") or "").strip()
    if not answer:
        return None
    return {
        "query": best.get("query"),
        "answer": answer,
        "score": round(best_score, 4),
        "age_sec": int(now - float(best.get("ts") or now)),
        "kind": kind,
        "cached": True,
    }


def store(
    query: str,
    answer: str,
    workspace: Path | None,
    *,
    kind: str = "web",
) -> None:
    if workspace is None:
        return
    if os.getenv("SEARCH_CACHE_ENABLED", "1").strip().lower() in {"0", "false", "off", "no"}:
        return
    q = _normalize_query(query)
    body = (answer or "").strip()
    if len(q) < 4 or len(body) < 8:
        return
    if body.startswith("No results") or body.startswith("Empty query"):
        return
    path = cache_path(workspace)
    rows = _load(path)
    # Replace near-duplicates of the same question
    thr = _threshold()
    kept: list[dict[str, Any]] = []
    for row in rows:
        if row.get("kind", "web") == kind and similarity(q, str(row.get("query") or "")) >= thr:
            continue
        kept.append(row)
    kept.append(
        {
            "query": q,
            "answer": body[:12000],
            "kind": kind,
            "ts": time.time(),
        }
    )
    _save(path, kept)


def format_hit(hit: dict[str, Any]) -> str:
    score = hit.get("score", 0)
    age = hit.get("age_sec", 0)
    header = f"[SEARCH_CACHE hit score={score} age={age}s]\n"
    return header + str(hit.get("answer") or "")
