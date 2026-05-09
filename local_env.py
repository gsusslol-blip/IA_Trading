"""Carga variables opcionales desde un archivo .env (sin dependencias externas)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_env_file(path: str | None = None) -> None:
    """
    Lee KEY=value por línea. No sobrescribe variables ya definidas en el proceso.
    Busca primero ENV_FILE o `.env` junto a este módulo, luego `./.env`.
    """
    if path:
        paths = [path]
    else:
        env_override = os.environ.get("ENV_FILE")
        here = Path(__file__).resolve().parent
        paths = []
        if env_override:
            paths.append(env_override)
        paths.append(str(here / ".env"))
        paths.append(".env")

    p = None
    for candidate in paths:
        if candidate and os.path.isfile(candidate):
            p = candidate
            break
    if not p:
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _env_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return repr(value) if value != int(value) else str(int(value))
    return str(value)


# Claves solo informativas en params_optimized.json / ia_optuna_best.json (no van a os.environ)
_JSON_META_KEYS_ENV = frozenset(
    {
        "last_optimization_date",
        "saved_utc",
        "source",
        "mode",
        "symbol",
        "best_value",
        "fold_index",
        "study_name",
        "saved_iso",
    }
)


def _coerce_optuna_val(v: Any) -> Any:
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    return v


def write_params_optimized_json(
    best_params: dict[str, Any],
    *,
    root: Path | None = None,
    **meta: Any,
) -> Path:
    """
    Escribe `params_optimized.json` en la raíz del proyecto: formato plano (parámetros + meta +
    last_optimization_date al final). El bot puede recargar este archivo cada ronda del loop.
    """
    root = root or _project_root()
    path = root / "params_optimized.json"
    flat: dict[str, Any] = {}
    for k in sorted(best_params.keys()):
        flat[str(k)] = _coerce_optuna_val(best_params[k])
    for k, v in meta.items():
        flat[str(k)] = _coerce_optuna_val(v)
    flat["last_optimization_date"] = datetime.now(timezone.utc).isoformat()
    with path.open("w", encoding="utf-8") as f:
        json.dump(flat, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def save_optuna_best_params(
    best_params: dict[str, Any],
    *,
    root: Path | None = None,
    basename: str = "ia_optuna_best",
    **meta: Any,
) -> tuple[Path, Path]:
    """
    Escribe `basename.json`, `basename.env` y `params_optimized.json` (plano + fecha).
    Usado por optuna_walkforward tras el último fold o estudio conjunto.
    Retorna (env_path, json_path, params_optimized_path).
    """
    root = root or _project_root()
    json_path = root / f"{basename}.json"
    env_path = root / f"{basename}.env"

    payload: dict[str, Any] = {
        "saved_utc": datetime.now(timezone.utc).isoformat(),
        "params": {k: _coerce_optuna_val(best_params[k]) for k in sorted(best_params.keys())},
    }
    for k, v in meta.items():
        payload[k] = v
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    lines = [
        "# Generado por optuna_walkforward — se aplica al iniciar ia_auto_trade_loop si IA_OPTUNA_APPLY=1",
        f"# saved_utc={payload['saved_utc']}",
    ]
    for k, v in sorted(best_params.items()):
        lines.append(f"{k}={_env_str(_coerce_optuna_val(v))}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    optimized_path = write_params_optimized_json(best_params, root=root, **meta)
    return env_path, json_path, optimized_path


def _load_env_override(path: Path) -> list[str]:
    """Lee KEY=value y fuerza os.environ[key] (incluso si ya existía)."""
    applied: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ[key] = val
                applied.append(key)
    return applied


def _apply_json_to_environ(data: dict[str, Any]) -> list[str]:
    """Aplica un dict JSON a os.environ; respeta anidado `params` o formato plano (params_optimized)."""
    flat = _flatten_optuna_json_payload(data)
    applied: list[str] = []
    for k, v in flat.items():
        os.environ[k] = _env_str(v)
        applied.append(k)
    return applied


def _flatten_optuna_json_payload(data: dict[str, Any]) -> dict[str, Any]:
    """
    Extrae parámetros tuneables desde params_optimized / ia_optuna_best (respeta IA_OPTUNA_EXCLUDE_KEYS).
    Sin efectos sobre os.environ.
    """
    exclude_raw = os.environ.get("IA_OPTUNA_EXCLUDE_KEYS", "").strip()
    exclude = {k.strip() for k in exclude_raw.split(",") if k.strip()} if exclude_raw else set()
    if isinstance(data, dict) and "params" in data and isinstance(data["params"], dict):
        raw = data["params"]
    else:
        raw = {k: v for k, v in data.items() if str(k) not in _JSON_META_KEYS_ENV}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        ks = str(k)
        if ks in _JSON_META_KEYS_ENV:
            continue
        if ks in exclude:
            continue
        out[ks] = v
    return out


def load_optuna_flat_params() -> dict[str, Any]:
    """
    Lee el primer JSON válido entre IA_OPTUNA_PARAMS_PATH / params_optimized.json / ia_optuna_best.json.
    Respeta IA_OPTUNA_APPLY (si está desactivado devuelve ``{}``). No modifica ``os.environ``.
    """
    if os.environ.get("IA_OPTUNA_APPLY", "1").strip().lower() in ("0", "false", "no"):
        return {}
    root = _project_root()
    explicit = os.environ.get("IA_OPTUNA_PARAMS_PATH", "").strip()
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    else:
        paths.extend([root / "params_optimized.json", root / "ia_optuna_best.json"])

    for p in paths:
        if not p.is_file() or p.suffix.lower() != ".json":
            continue
        try:
            with p.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        flat = _flatten_optuna_json_payload(data)
        if not flat:
            continue
        return {str(k): _coerce_optuna_val(v) for k, v in flat.items()}
    return {}


def merge_optuna_into_config(config_dict: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Fusiona parámetros de Optuna en un dict **y** en ``os.environ`` (prioridad sobre claves repetidas).

    Útil para pipelines que cargan knobs en dict y siguen usando módulos que leen sólo variables de
    entorno. Equivalente aplicado sólo sobre el JSON elegido por ``load_optuna_flat_params()``;
    llamá típicamente después de ``load_env_file()`` y antes de iniciar scanners/bots.
    """
    out = dict(config_dict or {})
    flat = load_optuna_flat_params()
    if not flat:
        return out
    out.update(flat)
    for k, v in flat.items():
        os.environ[str(k)] = _env_str(v)
    return out


def apply_optuna_overrides() -> list[str]:
    """
    Tras `load_env_file()`, aplica parámetros guardados por Optuna walk-forward.

    Control:
      IA_OPTUNA_APPLY=0 — no aplicar
      IA_OPTUNA_PARAMS_PATH — ruta explícita a .json o .env

    Si IA_OPTUNA_PARAMS_PATH está vacío, se intenta en orden:
      params_optimized.json -> ia_optuna_best.json -> ia_optuna_best.env

    JSON: bloque \"params\" (legacy) o archivo plano con last_optimization_date (se ignora en env).
    """
    if os.environ.get("IA_OPTUNA_APPLY", "1").strip().lower() in ("0", "false", "no"):
        return []
    report_once = os.environ.get("IA_OPTUNA_REPORT_OVERRIDES", "0").strip().lower() in ("1", "true", "yes")
    already = os.environ.get("__IA_OPTUNA_REPORTED", "0") == "1"
    root = _project_root()
    explicit = os.environ.get("IA_OPTUNA_PARAMS_PATH", "").strip()
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    else:
        paths.extend(
            [
                root / "params_optimized.json",
                root / "ia_optuna_best.json",
                root / "ia_optuna_best.env",
            ]
        )

    for p in paths:
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf == ".json":
            before: dict[str, str] = {}
            if report_once and not already:
                # Snapshot solo de claves candidatas (para no copiar todo el env).
                try:
                    with p.open(encoding="utf-8") as f0:
                        tmp = json.load(f0)
                    if isinstance(tmp, dict):
                        if "params" in tmp and isinstance(tmp["params"], dict):
                            cand = [str(k) for k in tmp["params"].keys()]
                        else:
                            cand = [str(k) for k in tmp.keys() if str(k) not in _JSON_META_KEYS_ENV]
                        for k in cand:
                            if k in os.environ:
                                before[k] = os.environ.get(k, "")
                except Exception:
                    before = {}
            with p.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return []
            applied = _apply_json_to_environ(data)
            if report_once and not already and applied:
                changed = [k for k in applied if before.get(k) != os.environ.get(k)]
                if changed:
                    sample = ", ".join(changed[:12]) + (" ..." if len(changed) > 12 else "")
                    print(f"[optuna] overrides aplicados ({len(changed)}): {sample}")
                os.environ["__IA_OPTUNA_REPORTED"] = "1"
            return applied
        if suf == ".env" or p.name.endswith(".env"):
            return _load_env_override(p)
    return []
