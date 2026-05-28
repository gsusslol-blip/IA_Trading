"""
Auto-optimización Optuna (fin de semana o manual).

Walk-forward real: entrena Optuna en el 70% inicial del histórico y valida Sharpe en el
30% OOS antes de escribir ``params_optimized.json``.

Uso:
  python ia_auto_optimizer.py
  python ia_auto_optimizer.py --symbol XAUUSD --force

Variables:
  IA_OPTUNA_AUTO_ENABLE=1
  IA_OPTUNA_AUTO_WEEKDAY=5          # 0=lun … 5=sáb, 6=dom
  IA_OPTUNA_AUTO_TRIALS=50
  IA_OPTUNA_AUTO_MONTHS=8
  IA_OPTUNA_WF_SPLIT_TRAIN=0.70
  IA_OPTUNA_OOS_MIN_SHARPE=0.0
  IA_OPTUNA_STORAGE_ENABLE=1
  IA_OPTUNA_STORAGE_URL=       — default sqlite:///logs/ia_optuna_trials.db
  IA_OPTUNA_DASHBOARD_PORT=8080

Dashboard (consola aparte, no bloquea el bot):
  optuna-dashboard sqlite:///.../logs/ia_optuna_trials.db --port 8080
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
from optuna_walkforward import _params_complete, objective_train_fold

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
) -> dict[str, Any] | None:
    """
    Optuna 70% IS + validación 30% OOS. Solo persiste params si OOS aprueba.
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
        months_total = int(
            os.environ.get("IA_OPTUNA_AUTO_MONTHS", os.environ.get("BT_MONTHS_TOTAL", "8")).strip() or "8"
        )
    except ValueError:
        months_total = 8

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
        from ia_optuna_sharpe import optuna_objective_mode
        from ia_walkforward_validate import (
            evaluar_params_oos,
            oos_params_aprobados,
            ventanas_is_oos,
        )

        train_from, train_to, test_from, test_to = ventanas_is_oos(months_total)
        obj = optuna_objective_mode()
        from ia_optuna_storage import (
            create_persistent_study,
            dashboard_command_hint,
            ensure_optuna_db_dir,
            optuna_storage_url,
        )

        ensure_optuna_db_dir()
        storage = optuna_storage_url()
        if storage:
            print(f"[optuna-auto] Persistencia SQLite: {storage}", flush=True)

        print(
            f"[optuna-auto] {sym} | IS [{train_from.date()} .. {train_to.date()}) | "
            f"OOS [{test_from.date()} .. {test_to.date()}) | trials={n_trials} | objetivo={obj}",
            flush=True,
        )
        study = create_persistent_study(sym, direction="maximize")
        study.optimize(
            lambda tr: objective_train_fold(tr, sym, train_from, train_to),
            n_trials=n_trials,
        )
        study.set_user_attr("train_from", train_from.isoformat())
        study.set_user_attr("train_to", train_to.isoformat())
        study.set_user_attr("test_from", test_from.isoformat())
        study.set_user_attr("test_to", test_to.isoformat())
        study.set_user_attr("objective_mode", obj)
        best = _params_complete(study)
        is_value = float(study.best_value)

        m_oos, trades_oos, sharpe_oos = evaluar_params_oos(sym, best, test_from, test_to)
        ok_oos, why_oos = oos_params_aprobados(m_oos, sharpe_oos=sharpe_oos)

        study.set_user_attr("oos_sharpe", float(sharpe_oos))
        study.set_user_attr("oos_net", float(m_oos.get("net", 0.0) or 0.0))
        study.set_user_attr("oos_n", int(m_oos.get("n", 0) or 0))
        study.set_user_attr("oos_approved", bool(ok_oos))

        print(
            f"[optuna-auto] IS value={is_value:.4f} | OOS Sharpe={sharpe_oos:.3f} net={m_oos.get('net', 0):.2f} "
            f"n={m_oos.get('n', 0)} | {why_oos}",
            flush=True,
        )
        if storage:
            print(f"[optuna-auto] Dashboard: {dashboard_command_hint()}", flush=True)
            try:
                port = int(os.environ.get("IA_OPTUNA_DASHBOARD_PORT", "8080").strip() or "8080")
            except ValueError:
                port = 8080
            print(f"[optuna-auto] Navegador: http://127.0.0.1:{port}/", flush=True)

        if not ok_oos:
            print(
                "[optuna-auto] RECHAZADO: no se guarda params_optimized.json (sobreoptimización / OOS débil).",
                file=sys.stderr,
                flush=True,
            )
            _save_state(
                last_run_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                symbol=sym,
                rejected_oos=True,
                oos_sharpe=sharpe_oos,
                is_best_value=is_value,
            )
            return None

        _env_p, _json_p, opt_p = save_optuna_best_params(
            best,
            symbol=sym,
            mode="auto_weekend_wf70_oos30",
            best_value=is_value,
            oos_sharpe=sharpe_oos,
            oos_net=float(m_oos.get("net", 0.0) or 0.0),
            oos_n=int(m_oos.get("n", 0) or 0),
            train_from=train_from.isoformat(),
            train_to=train_to.isoformat(),
            test_from=test_from.isoformat(),
            test_to=test_to.isoformat(),
        )
        print(f"[optuna-auto] OK OOS aprobado -> {opt_p.name}", flush=True)
        print(f"[optuna-auto] Params: {best}", flush=True)
        _save_state(
            last_run_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            symbol=sym,
            best_value=is_value,
            oos_sharpe=sharpe_oos,
            rejected_oos=False,
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
        result = ejecutar_optuna_semanal(sym, n_trials=n, force=args.force)
        return 0 if result is not None else 2
    except Exception as e:
        print(f"[optuna-auto] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
