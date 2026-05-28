"""
Persistencia Optuna en SQLite para Optuna Dashboard (sin tocar el bucle de trading).

Variables:
  IA_OPTUNA_STORAGE_ENABLE=1
  IA_OPTUNA_STORAGE_URL=        — vacío → sqlite en logs/ia_optuna_trials.db
  IA_OPTUNA_STUDY_PREFIX=optimizacion_sharpe
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import optuna


def storage_enabled() -> bool:
    return os.environ.get("IA_OPTUNA_STORAGE_ENABLE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def ensure_optuna_db_dir() -> Path:
    from ia_paths import resolve_data_path

    db_file = resolve_data_path("IA_OPTUNA_DB_FILE", "logs/ia_optuna_trials.db")
    db_file.parent.mkdir(parents=True, exist_ok=True)
    return db_file


def optuna_storage_url() -> str | None:
    """
    URL de storage Optuna (SQLite). None = estudio en memoria (sin dashboard).
    """
    if not storage_enabled():
        return None
    raw = os.environ.get("IA_OPTUNA_STORAGE_URL", "").strip()
    if raw:
        return raw
    db_path = ensure_optuna_db_dir().resolve()
    return f"sqlite:///{db_path.as_posix()}"


def study_name_for_symbol(symbol: str) -> str:
    prefix = os.environ.get("IA_OPTUNA_STUDY_PREFIX", "optimizacion_sharpe").strip() or "optimizacion_sharpe"
    sym = symbol.strip().lower().replace(" ", "")
    return f"{prefix}_{sym}"


def create_persistent_study(
    symbol: str,
    *,
    direction: str = "maximize",
    pruner: Any | None = None,
    study_name_suffix: str | None = None,
) -> Any:
    """
    Crea o reanuda un estudio con SQLite (``load_if_exists=True``).
    """
    import optuna

    name = study_name_for_symbol(symbol)
    if study_name_suffix:
        name = f"{name}_{study_name_suffix}"

    storage = optuna_storage_url()
    if pruner is None:
        pruner = optuna.pruners.NopPruner()

    kwargs: dict = {
        "study_name": name,
        "direction": direction,
        "pruner": pruner,
    }
    if storage:
        kwargs["storage"] = storage
        kwargs["load_if_exists"] = True

    return optuna.create_study(**kwargs)


def dashboard_command_hint() -> str:
    """Comando para abrir Optuna Dashboard en consola separada."""
    storage = optuna_storage_url()
    if not storage:
        return "IA_OPTUNA_STORAGE_ENABLE=0 (sin persistencia SQLite)"
    try:
        port = int(os.environ.get("IA_OPTUNA_DASHBOARD_PORT", "8080").strip() or "8080")
    except ValueError:
        port = 8080
    return f"optuna-dashboard {storage} --port {port}"


def dashboard_port() -> int:
    try:
        return max(1024, min(65535, int(os.environ.get("IA_OPTUNA_DASHBOARD_PORT", "8080").strip() or "8080")))
    except ValueError:
        return 8080
