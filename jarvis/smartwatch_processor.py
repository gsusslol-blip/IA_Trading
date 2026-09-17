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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import / demo smartwatch metrics into sandbox")
    parser.add_argument("--user", default="gsuss")
    parser.add_argument("--demo", action="store_true", help="Write demo smartwatch_metrics.json")
    parser.add_argument("--csv", type=Path, default=None, help="Import last row from CSV")
    args = parser.parse_args()
    if args.csv:
        out = importar_csv_basico(args.user, args.csv)
        print(f"[SMARTWATCH] CSV importado → {out}")
    else:
        out = escribir_metricas_demo(args.user)
        print(f"[SMARTWATCH] Demo escrito → {out}")
    print(procesar_datos_smartwatch(args.user))
