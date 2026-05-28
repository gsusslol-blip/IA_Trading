"""
Rutas del proyecto (raíz, logs/, config/, modelos/).

Los módulos Python siguen en la raíz por compatibilidad; los datos viven bajo ``logs/`` y ``config/``.
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def project_root() -> Path:
    return _ROOT


def config_dir() -> Path:
    d = _ROOT / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = _ROOT / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def modelos_dir() -> Path:
    d = _ROOT / "modelos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_data_path(env_key: str, default_relative: str) -> Path:
    """
    Ruta absoluta para CSV/JSON de datos.

    ``default_relative`` puede ser ``logs/foo.csv`` o solo ``foo.csv`` (se coloca en ``logs/``).
    """
    raw = os.environ.get(env_key, "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else _ROOT / p
    rel = default_relative.replace("\\", "/")
    if "/" not in rel and not rel.startswith("logs"):
        rel = f"logs/{rel}"
    return _ROOT / rel
