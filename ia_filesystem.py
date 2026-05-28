"""
Inicialización de carpetas y CSV base del bot (modelos ML, auditoría, calidad de ejecución).

Invocar al arranque de ``ia_auto_trade_loop`` (antes del bucle principal).
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from ia_paths import project_root

_ROOT = project_root()

_EXEC_QUALITY_HEADERS = [
    "time_utc",
    "symbol",
    "side",
    "volume",
    "price_requested",
    "price_executed",
    "slippage_abs",
    "slippage_points",
    "spread_points",
    "retcode",
    "deal",
]


def _resolve_env_path(env_key: str, default: str) -> Path:
    from ia_paths import resolve_data_path

    return resolve_data_path(env_key, default)


def _ensure_csv(path: Path, headers: list[str]) -> bool:
    """Crea CSV con cabecera si no existe. Devuelve True si creó archivo nuevo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return False
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(headers)
    return True


def _ensure_model_dir() -> Path:
    model_path = _resolve_env_path("IA_ML_MODEL_PATH", "modelos/filtro_falsos_rompimientos.pkl")
    folder = model_path.parent
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def inicializar_entorno_directorios(*, quiet: bool = False) -> None:
    """
    Crea ``modelos/``, ``logs/``, ``config/``, mapas ``core|trading|execution/``,
    ``journal_backup/`` y CSV base si faltan.
    """
    root = _ROOT
    created: list[str] = []

    for name in ("modelos", "logs", "config", "core", "trading", "execution", "journal_backup"):
        d = root / name
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            created.append(name)

    _ensure_model_dir()

    try:
        from ia_audit_logger import audit_enabled, inicializar_csv_auditoria

        if audit_enabled():
            p_ml = inicializar_csv_auditoria()
            if p_ml.is_file() and p_ml.stat().st_size == 0:
                created.append(str(p_ml.name))
    except Exception as e:
        if not quiet:
            print(f"[fs] auditoría ML: {e}", flush=True)

    exec_path = _resolve_env_path("IA_EXEC_QUALITY_CSV", "logs/execution_quality.csv")
    if _ensure_csv(exec_path, _EXEC_QUALITY_HEADERS):
        created.append(str(exec_path.name))

    pending = _resolve_env_path("IA_ML_AUDIT_PENDING", "logs/ia_audit_pending.json")
    pending.parent.mkdir(parents=True, exist_ok=True)
    if not pending.is_file():
        pending.write_text("{}", encoding="utf-8")
        created.append(pending.name)

    written = pending.with_suffix(".written.json")
    if not written.is_file():
        written.write_text("[]", encoding="utf-8")

    if created and not quiet:
        print(f"[fs] Entorno listo (creado: {', '.join(created)})", flush=True)
    elif not quiet:
        print("[fs] Entorno de archivos verificado.", flush=True)
