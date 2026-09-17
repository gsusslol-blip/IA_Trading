"""Local smartwatch metrics from sandbox dumps (no cloud APIs).

Expects data/users/<user>/workspace/smartwatch_metrics.json written by a
phone/PC export sync (Garmin/Fitbit/Apple Health CSV→JSON, etc.).
"""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.config import DATA_DIR
from jarvis.wellness_manager import DISCLAIMER_SALUD, ensure_disclaimer


def metrics_path(usuario: str) -> Path:
    user = (usuario or "guest").strip().lower() or "guest"
    folder = DATA_DIR / "users" / user / "workspace"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "smartwatch_metrics.json"


def history_path(usuario: str) -> Path:
    """Legacy JSON path (migrated once into SQLite)."""
    user = (usuario or "guest").strip().lower() or "guest"
    folder = DATA_DIR / "users" / user / "workspace"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "smartwatch_history.json"


def history_db_path(usuario: str) -> Path:
    user = (usuario or "guest").strip().lower() or "guest"
    folder = DATA_DIR / "users" / user / "workspace"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "smartwatch_history.sqlite3"


_HISTORY_MAX = 24  # default sparkline window (API can request more)
_HISTORY_HARD_CAP = 50_000


def _connect(usuario: str) -> Any:
    import sqlite3

    path = history_db_path(usuario)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            t_label TEXT,
            pasos INTEGER NOT NULL DEFAULT 0,
            hr REAL NOT NULL DEFAULT 0,
            hrv REAL NOT NULL DEFAULT 0,
            sueno REAL NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts)")
    conn.commit()
    return conn


def _migrate_json_if_needed(usuario: str) -> None:
    """One-shot import of smartwatch_history.json into SQLite."""
    json_path = history_path(usuario)
    if not json_path.is_file():
        return
    marker = history_db_path(usuario).with_suffix(".sqlite3.migrated")
    if marker.is_file():
        return
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        marker.write_text("empty-or-bad-json\n", encoding="utf-8")
        return
    if not isinstance(raw, list):
        marker.write_text("not-a-list\n", encoding="utf-8")
        return
    conn = _connect(usuario)
    try:
        for i, row in enumerate(raw):
            if not isinstance(row, dict):
                continue
            label = str(row.get("t") or "")
            conn.execute(
                "INSERT INTO metrics (ts, t_label, pasos, hr, hrv, sueno) VALUES (?,?,?,?,?,?)",
                (
                    float(row.get("ts") or (i + 1)),
                    label,
                    int(row.get("pasos") or 0),
                    float(row.get("hr") or 0),
                    float(row.get("hrv") or 0),
                    float(row.get("sueno") or 0),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    try:
        json_path.replace(json_path.with_suffix(".json.bak"))
    except OSError:
        pass
    marker.write_text(f"migrated {datetime.now().isoformat()}\n", encoding="utf-8")


def append_metric_history(usuario: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Append one snapshot to SQLite history; return recent window for callers."""
    _migrate_json_if_needed(usuario)
    point = {
        "t": payload.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pasos": int(payload.get("pasos_hoy") or 0),
        "hr": float(payload.get("hr_promedio_bpm") or 0),
        "hrv": float(payload.get("hrv_ms") or 0),
        "sueno": float(payload.get("horas_sueno_anoche") or 0),
        "ts": float(payload.get("imported_at") or time.time()),
    }
    conn = _connect(usuario)
    try:
        conn.execute(
            "INSERT INTO metrics (ts, t_label, pasos, hr, hrv, sueno) VALUES (?,?,?,?,?,?)",
            (point["ts"], point["t"], point["pasos"], point["hr"], point["hrv"], point["sueno"]),
        )
        # Soft prune extreme growth (years of data still fine under hard cap)
        count = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        if count > _HISTORY_HARD_CAP:
            cut = count - _HISTORY_HARD_CAP
            conn.execute(
                "DELETE FROM metrics WHERE id IN (SELECT id FROM metrics ORDER BY ts ASC LIMIT ?)",
                (cut,),
            )
        conn.commit()
    finally:
        conn.close()
    return load_metric_history(usuario, limit=_HISTORY_MAX)


def load_metric_history(usuario: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Load recent telemetry points (newest last) for HUD sparklines."""
    _migrate_json_if_needed(usuario)
    if not history_db_path(usuario).is_file() and not history_path(usuario).is_file():
        return []
    lim = _HISTORY_MAX if limit is None else max(1, min(int(limit), _HISTORY_HARD_CAP))
    conn = _connect(usuario)
    try:
        rows = conn.execute(
            "SELECT t_label, pasos, hr, hrv, sueno, ts FROM metrics ORDER BY ts DESC LIMIT ?",
            (lim,),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for label, pasos, hr, hrv, sueno, ts in reversed(rows):
        out.append(
            {
                "t": label or datetime.fromtimestamp(float(ts or time.time())).strftime("%Y-%m-%d %H:%M"),
                "pasos": int(pasos or 0),
                "hr": float(hr or 0),
                "hrv": float(hrv or 0),
                "sueno": float(sueno or 0),
            }
        )
    return out


def _default_payload() -> dict[str, Any]:
    return {
        "status": "no_data",
        "pasos_hoy": 0,
        "horas_sueno_anoche": 0.0,
        "hr_promedio_bpm": 70,
        "hrv_ms": 50,
        "nivel_energia_estimado": "Desconocido. Dejá un smartwatch_metrics.json en tu workspace.",
        "speech": ensure_disclaimer(
            "Todavía no hay métricas de reloj. Exportá Health/Garmin/Fitbit al workspace."
        ),
    }


def estimar_energia(sueno: float, hrv: float) -> str:
    if sueno >= 7.0 and hrv > 60:
        return "Óptima. Cuerpo totalmente recuperado."
    if sueno < 6.0 or hrv < 40:
        return "Baja / Estrés físico detectado. Se sugiere entrenamiento liviano."
    return "Moderada. Lista para el día a día."


def procesar_datos_smartwatch(usuario_activo: str) -> str:
    """Read sandbox dump and return daily energy / HR / steps / sleep JSON."""
    path = metrics_path(usuario_activo)
    if not path.is_file():
        return json.dumps(_default_payload(), ensure_ascii=False)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return json.dumps(
                {"status": "error", "message": "smartwatch_metrics.json inválido"},
                ensure_ascii=False,
            )
        sueno = float(data.get("horas_sueno_anoche") or data.get("sleep_hours") or 0.0)
        hrv = float(data.get("hrv_ms") or data.get("hrv") or 55)
        pasos = int(data.get("pasos_hoy") or data.get("steps") or 0)
        hr = float(data.get("hr_promedio_bpm") or data.get("hr_avg") or 72)
        energia = estimar_energia(sueno, hrv)
        last = str(data.get("timestamp") or data.get("last_sync") or "Hace poco")
        speak = (
            f"Hoy: {pasos} pasos, sueño {sueno:.1f} h, HR ~{hr:.0f} bpm, HRV {hrv:.0f} ms. "
            f"Energía: {energia}"
        )
        reporte = {
            "status": "success",
            "pasos_hoy": pasos,
            "horas_sueno_anoche": sueno,
            "hr_promedio_bpm": hr,
            "hrv_ms": hrv,
            "nivel_energia_estimado": energia,
            "last_sync": last,
            "history": load_metric_history(usuario_activo, limit=90),
            "speech": ensure_disclaimer(speak),
        }
        return json.dumps(reporte, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[SMARTWATCH] Error leyendo métricas: {exc}")
        return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)


def escribir_metricas_demo(
    usuario_activo: str,
    *,
    pasos: int = 8420,
    sueno: float = 7.2,
    hr: float = 68,
    hrv: float = 62,
    source: str = "demo_import",
    source_file: str | None = None,
) -> Path:
    """Utility: drop a realistic sandbox file for offline tests / first run."""
    path = metrics_path(usuario_activo)
    payload: dict[str, Any] = {
        "pasos_hoy": int(pasos),
        "horas_sueno_anoche": float(sueno),
        "hr_promedio_bpm": float(hr),
        "hrv_ms": float(hrv),
        "nivel_energia_estimado": estimar_energia(float(sueno), float(hrv)),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": source,
        "imported_at": time.time(),
    }
    if source_file:
        payload["source_file"] = source_file
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    append_metric_history(usuario_activo, payload)
    return path


def importar_csv_basico(usuario_activo: str, csv_path: Path) -> Path:
    """Import a minimal CSV with columns steps,sleep,hr,hrv (headers flexible)."""
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise FileNotFoundError(str(csv_path))
    with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        raise ValueError("CSV vacío")
    row = rows[-1]
    def _num(keys: tuple[str, ...], default: float) -> float:
        for key in keys:
            for rk, rv in row.items():
                if rk and rk.strip().lower() in keys and str(rv).strip():
                    try:
                        return float(str(rv).replace(",", "."))
                    except ValueError:
                        continue
        return default

    return escribir_metricas_demo(
        usuario_activo,
        pasos=int(_num(("pasos", "pasos_hoy", "steps"), 0)),
        sueno=_num(("sueno", "sueño", "sleep", "horas_sueno_anoche"), 7.0),
        hr=_num(("hr", "hr_promedio_bpm", "bpm"), 70),
        hrv=_num(("hrv", "hrv_ms"), 55),
        source="health_inbox_csv",
        source_file=csv_path.name,
    )


def importar_gpx_basico(usuario_activo: str, gpx_path: Path) -> Path:
    """Import GPX track: average HR from extensions + rough step estimate from distance."""
    import math
    import xml.etree.ElementTree as ET

    gpx_path = Path(gpx_path)
    if not gpx_path.is_file():
        raise FileNotFoundError(str(gpx_path))
    root = ET.parse(gpx_path).getroot()
    # Strip namespaces for simpler finds
    for node in root.iter():
        if "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]

    hrs: list[float] = []
    coords: list[tuple[float, float]] = []
    for trkpt in root.findall(".//trkpt"):
        try:
            lat = float(trkpt.attrib.get("lat") or 0)
            lon = float(trkpt.attrib.get("lon") or 0)
        except ValueError:
            continue
        if lat or lon:
            coords.append((lat, lon))
        for el in trkpt.iter():
            tag = (el.tag or "").lower()
            if tag in {"hr", "heartrate"} and el.text:
                try:
                    hrs.append(float(el.text))
                except ValueError:
                    pass

    def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
        r = 6371000.0
        p1, p2 = math.radians(a[0]), math.radians(b[0])
        dp = math.radians(b[0] - a[0])
        dl = math.radians(b[1] - a[1])
        x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(min(1.0, math.sqrt(x)))

    dist_m = 0.0
    for i in range(1, len(coords)):
        dist_m += _haversine_m(coords[i - 1], coords[i])
    # ~0.78 m per step walking heuristic
    pasos = int(dist_m / 0.78) if dist_m > 0 else 0
    hr = sum(hrs) / len(hrs) if hrs else 70.0
    if not coords and not hrs:
        raise ValueError("GPX sin track points / HR usable")

    return escribir_metricas_demo(
        usuario_activo,
        pasos=pasos,
        sueno=7.0,
        hr=hr,
        hrv=55.0,
        source="health_inbox_gpx",
        source_file=gpx_path.name,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import / demo smartwatch metrics into sandbox")
    parser.add_argument("--user", default="gsuss")
    parser.add_argument("--demo", action="store_true", help="Write demo smartwatch_metrics.json")
    parser.add_argument("--csv", type=Path, default=None, help="Import last row from CSV")
    args = parser.parse_args()
    if args.csv:
        out = importar_csv_basico(args.user, args.csv)
        print(f"[SMARTWATCH] CSV importado -> {out}")
    else:
        out = escribir_metricas_demo(args.user)
        print(f"[SMARTWATCH] Demo escrito -> {out}")
    print(procesar_datos_smartwatch(args.user))
