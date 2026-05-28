"""
Entrena el clasificador ML (RandomForest) desde ``trade_audit_ml.csv``.

  python ia_trainer.py

Optimización de parámetros (Sharpe / Optuna fin de semana): ``ia_auto_optimizer.py`` +
``optuna_walkforward.py`` con ``IA_OPTUNA_OBJECTIVE=sharpe`` (ver ``ia_optuna_sharpe.py``).
Este módulo entrena el filtro ML; no confundir con el estudio Optuna de la estrategia.

Variables:
  IA_ML_TRAIN_AUTO_ENABLE=1
  IA_ML_TRAIN_WEEKDAY=6          # 0=lun … 6=dom (default domingo tras semana demo)
  IA_ML_TRAIN_MIN_SAMPLES=30
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ia_audit_logger import audit_csv_path, inicializar_csv_auditoria
from ia_intelligence_layer import _model_path


def _state_path() -> Path:
    root = Path(__file__).resolve().parent
    raw = os.environ.get("IA_ML_TRAIN_STATE", "ia_ml_train_state.json").strip()
    p = Path(raw)
    return p if p.is_absolute() else root / p


def _load_state() -> dict[str, Any]:
    p = _state_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(**fields: Any) -> None:
    data = _load_state()
    data.update(fields)
    data["updated_utc"] = datetime.now(timezone.utc).isoformat()
    _state_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def train_auto_enabled() -> bool:
    return os.environ.get("IA_ML_TRAIN_AUTO_ENABLE", "0").strip().lower() in ("1", "true", "yes")


def debe_entrenar_ml_semanal(*, force: bool = False) -> bool:
    if force:
        return True
    if not train_auto_enabled():
        return False
    try:
        want = int(os.environ.get("IA_ML_TRAIN_WEEKDAY", "6").strip() or "6")
    except ValueError:
        want = 6
    if datetime.now().weekday() != want:
        return False
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return str(_load_state().get("last_train_date", "")) != today


def auto_entrenar_modelo_ia(
    *,
    csv_path: Path | None = None,
    model_out: Path | None = None,
) -> bool:
    """
    Lee el CSV de auditoría, entrena RandomForest y guarda ``filtro_falsos_rompimientos.pkl``.
    Features: spread_pts, hora_utc, adx_m15, distancia_ema_h4, atr_m15_pct.
    """
    try:
        import joblib
        import pandas as pd
        from sklearn.ensemble import RandomForestClassifier
    except ImportError:
        print("[trainer] Instalá scikit-learn y joblib.", flush=True)
        return False

    inicializar_csv_auditoria()
    path = csv_path or audit_csv_path()
    if not path.is_file():
        print(f"[trainer] No existe {path}", flush=True)
        return False

    try:
        min_n = int(os.environ.get("IA_ML_TRAIN_MIN_SAMPLES", "30").strip() or "30")
    except ValueError:
        min_n = 30

    df = pd.read_csv(path)
    feat_cols = ["spread_pts", "hora_utc", "adx_m15", "distancia_ema_h4", "atr_m15_pct"]
    for c in feat_cols + ["resultado"]:
        if c not in df.columns:
            print(f"[trainer] Falta columna {c} en {path}", flush=True)
            return False

    df = df.dropna(subset=["resultado"])
    if len(df) < min_n:
        print(f"[trainer] Datos insuficientes: {len(df)}/{min_n}", flush=True)
        return False

    X = df[feat_cols].astype(float)
    y = df["resultado"].astype(int)
    print(f"[trainer] Entrenando con {len(df)} muestras…", flush=True)

    clf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    clf.fit(X, y)
    out = model_out or _model_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, out)
    acc = float((clf.predict(X) == y).mean())
    print(f"[trainer] Modelo guardado en {out} (accuracy in-sample ~{acc:.2f})", flush=True)
    _save_state(last_train_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"), samples=len(df))
    return True


def main() -> int:
    from local_env import load_env_file

    load_env_file()
    return 0 if auto_entrenar_modelo_ia() else 1


if __name__ == "__main__":
    raise SystemExit(main())
