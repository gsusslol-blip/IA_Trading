"""
Auto-optimización Optuna (fin de semana o manual).

Reutiliza el backtest y el objetivo de ``optuna_walkforward.py``; escribe
``params_optimized.json`` para que ``ia_auto_trade_loop`` lo aplique vía ``IA_OPTUNA_APPLY``.

Uso:
  python ia_auto_optimizer.py
  python ia_auto_optimizer.py --symbol XAUUSD --force

Variables:
  IA_OPTUNA_AUTO_ENABLE=1
  IA_OPTUNA_AUTO_WEEKDAY=5          # 0=lun … 5=sáb, 6=dom
  IA_OPTUNA_AUTO_TRIALS=50
  IA_OPTUNA_AUTO_MONTHS=8
  IA_OPTUNA_AUTO_TRAIN_MONTHS=3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5
import optuna

from local_env import load_env_file, save_optuna_best_params
from optuna_walkforward import (
    _params_complete,
    _walk_forward_windows,
    objective_train_fold,
)

_STATE_FILE = "ia_optuna_auto_state.json"


def _state_path() -> Path:
    raw = os.environ.get("IA_OPTUNA_AUTO_STATE_FILE", "").strip()
    root = Path(__file__).resolve().parent
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else root / p
    return root / _STATE_FILE


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


def optuna_auto_enabled() -> bool:
    return os.environ.get("IA_OPTUNA_AUTO_ENABLE", "0").strip().lower() in ("1", "true", "yes")


def debe_ejecutar_optuna_semanal(*, force: bool = False) -> bool:
    """True si toca correr hoy (día configurado) y aún no se optimizó hoy."""
    if force:
        return True
    if not optuna_auto_enabled():
        return False
    try:
        want_wd = int(os.environ.get("IA_OPTUNA_AUTO_WEEKDAY", "5").strip() or "5")
    except ValueError:
        want_wd = 5
    if datetime.now().weekday() != want_wd:
        return False
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last = str(_load_state().get("last_run_date", "") or "")
    return last != today


def ejecutar_optuna_semanal(
    symbol: str | None = None,
    *,
    n_trials: int | None = None,
    force: bool = False,
    manage_mt5: bool = True,
) -> dict[str, Any]:
    """
    Estudio Optuna in-sample sobre el último fold de entrenamiento walk-forward.
    Devuelve parámetros listos para ``params_optimized.json``.
    """
    load_env_file()
    sym = (
        (symbol or "").strip()
        or os.environ.get("BT_SYMBOL", "").strip()
        or os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").split(",")[0].strip()
        or "XAUUSD"
    )
    if not sym:
        raise ValueError("Símbolo vacío para optimización")

    try:
        months_total = int(os.environ.get("IA_OPTUNA_AUTO_MONTHS", os.environ.get("BT_MONTHS_TOTAL", "8")).strip() or "8")
    except ValueError:
        months_total = 8
    try:
        train_m = int(os.environ.get("IA_OPTUNA_AUTO_TRAIN_MONTHS", os.environ.get("BT_TRAIN_MONTHS", "3")).strip() or "3")
    except ValueError:
        train_m = 3
    test_m = 1
    step_m = 1

    if n_trials is None:
        try:
            n_trials = int(os.environ.get("IA_OPTUNA_AUTO_TRIALS", os.environ.get("OPTUNA_TRIALS", "50")).strip() or "50")
        except ValueError:
            n_trials = 50
    n_trials = max(5, min(500, int(n_trials)))

    did_init = False
    if manage_mt5:
        if mt5.terminal_info() is None:
            mt5_path = os.environ.get("MT5_PATH")
            ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
            if not ok:
                code, msg = mt5.last_error()
                raise RuntimeError(f"No se pudo inicializar MT5 ({code}) {msg}")
            did_init = True
    elif mt5.terminal_info() is None:
        raise RuntimeError("MT5 no inicializado (ejecutar_optuna_semanal con manage_mt5=False)")

    try:
        windows = _walk_forward_windows(months_total, train_m, test_m, step_m)
        if not windows:
            raise RuntimeError("Sin ventanas walk-forward; ajustá IA_OPTUNA_AUTO_MONTHS / TRAIN_MONTHS")
        train_from, train_to, _test_to = windows[-1]
        print(
            f"[optuna-auto] {sym} | train [{train_from.date()} .. {train_to.date()}) | trials={n_trials}",
            flush=True,
        )
        study = optuna.create_study(
            direction="maximize",
            study_name=f"ia_auto_{sym}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            pruner=optuna.pruners.NopPruner(),
        )
        study.optimize(
            lambda tr: objective_train_fold(tr, sym, train_from, train_to),
            n_trials=n_trials,
        )
        best = _params_complete(study)
        env_p, json_p, opt_p = save_optuna_best_params(
            best,
            symbol=sym,
            mode="auto_weekend",
            best_value=float(study.best_value),
        )
        print(f"[optuna-auto] OK value={study.best_value:.4f} -> {opt_p.name}", flush=True)
        print(f"[optuna-auto] Params: {best}", flush=True)
        _save_state(
            last_run_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            symbol=sym,
            best_value=float(study.best_value),
        )
        return best
    finally:
        if did_init:
            mt5.shutdown()


def main() -> int:
    load_env_file()
    ap = argparse.ArgumentParser(description="Optuna automático IA_Trading")
    ap.add_argument("--symbol", default="", help="Símbolo MT5 (default IA_SCAN_SYMBOLS)")
    ap.add_argument("--trials", type=int, default=0, help="Override n_trials")
    ap.add_argument("--force", action="store_true", help="Ignorar día de semana / ya corrido hoy")
    args = ap.parse_args()
    sym = args.symbol.strip() or None
    if not args.force and not debe_ejecutar_optuna_semanal():
        print("[optuna-auto] No toca ejecutar (día, IA_OPTUNA_AUTO_ENABLE o ya corrido hoy).", flush=True)
        return 0
    n = args.trials if args.trials > 0 else None
    try:
        ejecutar_optuna_semanal(sym, n_trials=n, force=args.force)
        return 0
    except Exception as e:
        print(f"[optuna-auto] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
