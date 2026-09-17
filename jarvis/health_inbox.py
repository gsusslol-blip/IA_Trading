"""Friendly Health Importer — drop exports into workspace/inbox/.

Watches each user sandbox:
  data/users/<user>/workspace/inbox/
Accepted: .json .csv (Garmin/Fitbit/Apple-style dumps normalized locally).
Writes:  data/users/<user>/workspace/smartwatch_metrics.json
Moves processed files to inbox/processed/.

No cloud APIs. Polling thread from runtime (no Node, no extra daemon).
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.config import DATA_DIR, Settings, load_settings
from jarvis.smartwatch_processor import (
    append_metric_history,
    estimar_energia,
    metrics_path,
    importar_csv_basico,
    importar_gpx_basico,
)

_WATCH_EXTS = {".json", ".csv", ".gpx"}
_lock = threading.Lock()
_started = False


def inbox_dir(usuario: str) -> Path:
    user = (usuario or "guest").strip().lower() or "guest"
    path = DATA_DIR / "users" / user / "workspace" / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    (path / "processed").mkdir(parents=True, exist_ok=True)
    (path / "failed").mkdir(parents=True, exist_ok=True)
    return path


def ensure_inbox_readme(usuario: str) -> Path:
    """Drop a short how-to next to the inbox (once)."""
    folder = inbox_dir(usuario)
    readme = folder / "README.txt"
    if readme.is_file():
        return readme
    readme.write_text(
        "ILARIA — Health Inbox\n"
        "=====================\n"
        "Arrastrá acá exports de Garmin / Fitbit / Apple Health (CSV, JSON o GPX).\n"
        "Ilaria los convierte a smartwatch_metrics.json en este workspace.\n"
        "Archivos procesados → inbox/processed/\n"
        "\n"
        "CSV sugerido (última fila): pasos,sueño,hr,hrv  (headers flexibles).\n"
        "JSON sugerido: {\"steps\":8000,\"sleep_hours\":7.0,\"avg_hr\":68,\"hrv\":55}\n"
        "GPX: track points con HR en extensiones Garmin (avg HR + distancia).\n"
        "FIT binario: exportá a CSV/JSON primero (sin parser FIT nativo).\n",
        encoding="utf-8",
    )
    return readme


def list_user_sandboxes() -> list[str]:
    root = DATA_DIR / "users"
    if not root.is_dir():
        return []
    names: list[str] = []
    for path in root.iterdir():
        if path.is_dir() and not path.name.startswith("."):
            names.append(path.name.lower())
    env_user = os.getenv("TELEGRAM_REMOTE_USER", "").strip().lower()
    if env_user and env_user not in names:
        names.append(env_user)
    return sorted(set(names)) or ["gsuss"]


def _normalize_json_payload(data: dict[str, Any]) -> dict[str, Any]:
    def pick(*keys: str, default: Any = 0) -> Any:
        for key in keys:
            if key in data and data[key] is not None and str(data[key]).strip() != "":
                return data[key]
            # nested common exports
            daily = data.get("daily") or data.get("summary") or {}
            if isinstance(daily, dict) and key in daily:
                return daily[key]
        return default

    try:
        pasos = int(float(str(pick("pasos_hoy", "steps", "step_count", "Steps", default=0)).replace(",", ".")))
    except (TypeError, ValueError):
        pasos = 0
    try:
        sueno = float(str(pick("horas_sueno_anoche", "sleep_hours", "sleep", "SleepHours", default=0)).replace(",", "."))
    except (TypeError, ValueError):
        sueno = 0.0
    try:
        hr = float(
            str(
                pick(
                    "hr_promedio_bpm",
                    "avg_hr",
                    "hr_avg",
                    "resting_hr",
                    "heart_rate",
                    "HR",
                    default=70,
                )
            ).replace(",", ".")
        )
    except (TypeError, ValueError):
        hr = 70.0
    try:
        hrv = float(str(pick("hrv_ms", "hrv", "HRV", default=55)).replace(",", "."))
    except (TypeError, ValueError):
        hrv = 55.0
    return {
        "pasos_hoy": pasos,
        "horas_sueno_anoche": sueno,
        "hr_promedio_bpm": hr,
        "hrv_ms": hrv,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "nivel_energia_estimado": estimar_energia(sueno, hrv),
        "source": "health_inbox",
        "imported_at": time.time(),
    }


def importar_json_inbox(usuario: str, json_path: Path) -> Path:
    raw = json.loads(json_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("JSON debe ser un objeto {pasos, sueño, hr, hrv}")
    payload = _normalize_json_payload(raw)
    payload["source_file"] = json_path.name
    out = metrics_path(usuario)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    append_metric_history(usuario, payload)
    return out


def procesar_archivo_inbox(usuario: str, path: Path) -> dict[str, Any]:
    """Import one dropped file; move to processed/ on success, failed/ on error."""
    path = Path(path)
    if not path.is_file():
        return {"status": "error", "message": "Archivo inexistente"}
    suffix = path.suffix.lower()
    if suffix not in _WATCH_EXTS:
        return {
            "status": "skipped",
            "message": f"Extensión no soportada aún ({suffix}). Usá .json o .csv.",
            "file": path.name,
        }
    source_name = path.name
    try:
        if suffix == ".fit":
            raise ValueError(
                "FIT binario no soportado nativo. Exportá a CSV/JSON/GPX desde Garmin/Fitbit."
            )
        if suffix == ".csv":
            dest = importar_csv_basico(usuario, path)
        elif suffix == ".gpx":
            dest = importar_gpx_basico(usuario, path)
        else:
            dest = importar_json_inbox(usuario, path)
        processed = inbox_dir(usuario) / "processed" / f"{int(time.time())}_{source_name}"
        shutil.move(str(path), str(processed))
        print(f"[INBOX] {usuario}: {source_name} -> {dest.name}")
        return {
            "status": "success",
            "user": usuario,
            "metrics_file": str(dest),
            "archived": str(processed),
            "source_file": source_name,
        }
    except Exception as exc:  # noqa: BLE001
        fail_dir = inbox_dir(usuario) / "failed"
        fail_dir.mkdir(parents=True, exist_ok=True)
        fail = fail_dir / f"{int(time.time())}_{source_name}"
        try:
            shutil.move(str(path), str(fail))
        except OSError:
            pass
        print(f"[INBOX] Error {usuario}/{source_name}: {exc}")
        return {"status": "error", "message": str(exc), "file": source_name, "failed": str(fail)}


def escanear_inbox_usuario(usuario: str) -> list[dict[str, Any]]:
    folder = inbox_dir(usuario)
    results: list[dict[str, Any]] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if path.name.upper().startswith("README"):
            continue
        if path.suffix.lower() not in _WATCH_EXTS:
            continue
        results.append(procesar_archivo_inbox(usuario, path))
    return results


def escanear_todas_las_inboxes() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for user in list_user_sandboxes():
        ensure_inbox_readme(user)
        out.extend(escanear_inbox_usuario(user))
    return out


def start_health_inbox_watcher(settings: Settings | None = None) -> None:
    """Background poll of all user inboxes (default every 8s)."""
    global _started
    cfg = settings or load_settings()
    with _lock:
        if _started:
            return
        _started = True

    try:
        interval = float(os.getenv("HEALTH_INBOX_POLL_SEC", "8") or 8)
    except ValueError:
        interval = 8.0
    interval = max(3.0, min(120.0, interval))

    # Seed default remote user inbox so drop target exists on first boot.
    seed = os.getenv("TELEGRAM_REMOTE_USER", "").strip() or (cfg.user_name or "gsuss")
    seed = "".join(ch for ch in seed.lower() if ch.isalnum() or ch in "-_") or "gsuss"
    ensure_inbox_readme(seed)

    def _run() -> None:
        print(f"[INBOX] Vigilando exports de salud cada {interval:.0f}s → workspace/inbox/")
        while True:
            try:
                escanear_todas_las_inboxes()
            except Exception as exc:  # noqa: BLE001
                print(f"[INBOX] ciclo: {exc}")
            time.sleep(interval)

    threading.Thread(target=_run, name="ilaria-health-inbox", daemon=True).start()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scan health inbox once or write a sample drop")
    parser.add_argument("--user", default="gsuss")
    parser.add_argument("--scan", action="store_true", help="Process pending inbox files once")
    parser.add_argument("--sample", action="store_true", help="Drop a sample JSON into inbox/")
    args = parser.parse_args()
    ensure_inbox_readme(args.user)
    if args.sample:
        sample = inbox_dir(args.user) / f"sample_health_{int(time.time())}.json"
        sample.write_text(
            json.dumps(
                {
                    "pasos_hoy": 10234,
                    "horas_sueno_anoche": 6.8,
                    "hr_promedio_bpm": 71,
                    "hrv_ms": 48,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"[INBOX] Sample dropeado: {sample}")
    if args.scan or args.sample:
        for item in escanear_inbox_usuario(args.user):
            print(json.dumps(item, ensure_ascii=False))
    else:
        parser.print_help()
