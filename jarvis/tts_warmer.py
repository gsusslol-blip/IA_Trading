"""TTS phrase-cache warm-up for zero-latency common acks and HUD telemetry."""

from __future__ import annotations

import threading
from typing import Any

from jarvis.config import DATA_DIR
from jarvis.tts import phrase_cache_count, phrase_cache_dir, warm_phrase_cache

_warm_lock = threading.Lock()
_warm_started = False
_frases_precargadas_count = 0
_last_report: dict[str, Any] = {
    "status": "idle",
    "cached_phrases_count": 0,
    "ready": False,
}


def scan_phrase_cache() -> dict[str, Any]:
    """Count existing WAV/MP3 in phrase + hash caches (no Piper synthesis)."""
    global _frases_precargadas_count, _last_report
    total = phrase_cache_count()
    hash_dir = DATA_DIR / "tts-cache"
    if hash_dir.is_dir():
        try:
            total += sum(
                1
                for p in hash_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".wav", ".mp3"}
            )
        except OSError:
            pass
    report = {
        "status": "warmed" if total > 0 else "empty",
        "cached_phrases_count": int(total),
        "ready": total > 0,
        "phrase_cache_dir": str(phrase_cache_dir()),
    }
    with _warm_lock:
        _frases_precargadas_count = int(total)
        _last_report = dict(report)
    return report


def inicializar_warm_cache() -> int:
    """Scan disk once at boot — keeps /api/stack-health off the disk path after warm."""
    report = scan_phrase_cache()
    count = int(report.get("cached_phrases_count") or 0)
    print(f"[ARRANQUE] warm_phrase_cache: {count} frases listas (latencia 0ms si Piper ya las generó).")
    return count


def obtener_metricas_tts_actuales() -> int:
    with _warm_lock:
        return int(_frases_precargadas_count)


def incrementar_contador_tts(n: int = 1) -> None:
    """Call when Piper writes a new short phrase into the cache."""
    global _frases_precargadas_count
    with _warm_lock:
        _frases_precargadas_count = max(0, int(_frases_precargadas_count) + max(0, int(n)))
        _last_report["cached_phrases_count"] = _frases_precargadas_count
        _last_report["status"] = "warmed" if _frases_precargadas_count > 0 else "empty"
        _last_report["ready"] = _frases_precargadas_count > 0


def cache_snapshot() -> dict[str, Any]:
    with _warm_lock:
        snap = dict(_last_report)
        count = int(_frases_precargadas_count)
    if snap.get("status") == "idle":
        return scan_phrase_cache()
    snap["cached_phrases_count"] = count
    return snap


def start_tts_warm(settings: Any, *, limit: int = 16) -> None:
    """Background: scan now, then synthesize missing common phrases (once per process)."""
    global _warm_started
    with _warm_lock:
        if _warm_started:
            return
        _warm_started = True

    inicializar_warm_cache()

    def _run() -> None:
        try:
            import asyncio

            before = phrase_cache_count()
            generated = asyncio.run(warm_phrase_cache(settings, limit=limit))
            after = scan_phrase_cache()
            print(
                f"[WARM_UP] Caché TTS: {after.get('cached_phrases_count', 0)} frases "
                f"(había {before}, generó {generated})."
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[WARM_UP] No se pudo precargar TTS: {exc}")
            scan_phrase_cache()

    threading.Thread(target=_run, name="ilaria-tts-warm", daemon=True).start()
