"""
Capa de inteligencia: filtro ML de falsos rompimientos + auto-tune de spread por auditoría.

Variables:
  IA_ML_FILTER_ENABLE=1
  IA_ML_MODEL_PATH=modelos/filtro_falsos_rompimientos.pkl
  IA_ML_MIN_PROB=0.60
  IA_EXEC_AUTOTUNE_ENABLE=1
  IA_EXEC_AUTOTUNE_WINDOW=10
  IA_EXEC_AUTOTUNE_SLIP_PTS=20
  IA_AUTO_SPREAD_STRICT_PCTL=60   # si slippage abusivo, baja percentil dinámico
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ia_indicators import obtener_snapshot_completo
from trade_audit import execution_quality_csv_path


def _ml_enabled() -> bool:
    return os.environ.get("IA_ML_FILTER_ENABLE", "0").strip().lower() in ("1", "true", "yes")


def _model_path() -> Path:
    raw = os.environ.get("IA_ML_MODEL_PATH", "modelos/filtro_falsos_rompimientos.pkl").strip()
    p = Path(raw)
    return p if p.is_absolute() else Path(__file__).resolve().parent / p


def _min_win_prob() -> float:
    try:
        return float(os.environ.get("IA_ML_MIN_PROB", "0.60").strip() or "0.60")
    except ValueError:
        return 0.60


def build_live_features(symbol: str, *, buy: bool) -> list[float]:
    """
    Features alineadas al entrenamiento: spread_pts, hora_utc, adx_m15, dist_ema_h4_pct, atr_pct_rank.
    """
    snap = obtener_snapshot_completo(symbol, buy=buy)
    return [
        float(snap["spread_pts"]),
        float(snap["hora_utc"]),
        float(snap["adx_m15"]),
        float(snap["distancia_ema_h4"]),
        float(snap["atr_m15_pct"]),
    ]


def filtro_inteligencia_artificial(features_mercado: list[float] | None = None) -> bool:
    """
    True = permitir trade. False = rechazar (probabilidad de éxito baja).
    Sin modelo entrenado → fail-open (True).
    """
    if not _ml_enabled():
        return True
    feats = features_mercado
    if feats is None:
        return True
    path = _model_path()
    if not path.is_file():
        return True
    try:
        import joblib
    except ImportError:
        return True
    try:
        modelo = joblib.load(path)
        proba = modelo.predict_proba([feats])[0]
        p_win = float(proba[1]) if len(proba) > 1 else float(proba[0])
    except Exception as e:
        print(f"[ML] filtro omitido: {e}", flush=True)
        return True
    if p_win < _min_win_prob():
        print(
            f"[ML] Trade rechazado: P(ganar)={p_win:.2f} < {_min_win_prob():.2f}",
            flush=True,
        )
        return False
    return True


def intelligence_allows_trade(symbol: str, *, buy: bool) -> tuple[bool, list[float]]:
    feats = build_live_features(symbol, buy=buy)
    ok = filtro_inteligencia_artificial(feats)
    return ok, feats


def auto_ajuste_spread_por_auditoria() -> bool:
    """
    Si el slippage medio reciente supera umbral, endurece ``IA_AUTO_SPREAD_PCTL`` en memoria.
    Devuelve True si activó modo estricto.
    """
    if os.environ.get("IA_EXEC_AUTOTUNE_ENABLE", "1").strip().lower() in ("0", "false", "no"):
        return False
    try:
        import pandas as pd
    except ImportError:
        return False

    path = execution_quality_csv_path()
    if not path.is_file():
        return False
    try:
        window = int(os.environ.get("IA_EXEC_AUTOTUNE_WINDOW", "10").strip() or "10")
    except ValueError:
        window = 10
    window = max(3, min(100, window))
    try:
        slip_thr = float(os.environ.get("IA_EXEC_AUTOTUNE_SLIP_PTS", "20").strip() or "20")
    except ValueError:
        slip_thr = 20.0

    try:
        df = pd.read_csv(path)
    except Exception:
        return False
    if df.empty or "slippage_points" not in df.columns or len(df) < window:
        return False
    pts = pd.to_numeric(df["slippage_points"].tail(window), errors="coerce").dropna()
    if len(pts) < window:
        return False
    avg = float(pts.mean())
    if avg != avg or avg <= slip_thr:
        return False

    try:
        strict_pctl = float(os.environ.get("IA_AUTO_SPREAD_STRICT_PCTL", "60").strip() or "60")
    except ValueError:
        strict_pctl = 60.0
    strict_pctl = max(40.0, min(95.0, strict_pctl))
    prev = os.environ.get("IA_AUTO_SPREAD_PCTL", "")
    os.environ["IA_AUTO_SPREAD_PCTL"] = str(int(strict_pctl))
    os.environ["IA_EXEC_AUTOTUNE_ACTIVE"] = "1"
    print(
        f"[autotune] Slippage medio {avg:.1f} pts > {slip_thr:g} (últimas {window}). "
        f"IA_AUTO_SPREAD_PCTL {prev or 'default'} -> {int(strict_pctl)}",
        flush=True,
    )
    try:
        from ia_autonomy_notify import notify_spread_autotune

        notify_spread_autotune(avg, strict_pctl)
    except Exception:
        pass
    return True


def train_breakout_filter_from_memory(
    *,
    csv_path: Path | None = None,
    model_out: Path | None = None,
) -> bool:
    """
    Legacy: entrena desde ``ia_auto_trade_memory.csv``.
    Preferir ``ia_trainer.auto_entrenar_modelo_ia`` + ``trade_audit_ml.csv``.
    """
    try:
        from ia_trainer import auto_entrenar_modelo_ia
        from ia_audit_logger import audit_csv_path

        if audit_csv_path().is_file():
            return auto_entrenar_modelo_ia(model_out=model_out)
    except ImportError:
        pass
    try:
        import joblib
        import pandas as pd
        from sklearn.ensemble import RandomForestClassifier
    except ImportError:
        print("[ML] Instalá scikit-learn y joblib para entrenar.", flush=True)
        return False

    root = Path(__file__).resolve().parent
    mem = csv_path or root / (
        os.environ.get("IA_AUTO_MEMORY_CSV", "ia_auto_trade_memory.csv").strip()
        or "ia_auto_trade_memory.csv"
    )
    if not mem.is_file():
        print(f"[ML] No existe {mem}", flush=True)
        return False
    df = pd.read_csv(mem)
    if len(df) < 30 or "label" not in df.columns:
        print("[ML] Mínimo 30 filas con columna label en memoria.", flush=True)
        return False

    rows_x: list[list[float]] = []
    rows_y: list[int] = []
    for _, row in df.iterrows():
        try:
            t = datetime.fromisoformat(str(row["time_close_utc"]).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        hour = t.hour + t.minute / 60.0
        # Misma dimensionalidad que build_live_features (histórico sin spread en entrada → 0)
        rows_x.append([0.0, hour, 20.0, 0.0, 50.0])
        rows_y.append(1 if str(row.get("label", "")).lower() == "good" else 0)

    if len(rows_x) < 30:
        print("[ML] Muestras insuficientes tras parseo.", flush=True)
        return False

    clf = RandomForestClassifier(n_estimators=120, max_depth=6, random_state=42)
    clf.fit(rows_x, rows_y)
    out = model_out or _model_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, out)
    print(f"[ML] Modelo guardado en {out} ({len(rows_x)} muestras)", flush=True)
    return True
