"""
Optimización (Optuna) con esquema walk-forward.

Modo anidado (por defecto, OPTUNA_NESTED_WF=1):
  Por cada fold: ventana de entrenamiento [train_from, train_to) -> Optuna ajusta hiperparámetros
  solo con backtest en train; luego se fija best_params y se valida en [train_to, test_to) (OOS).

Modo conjunto (OPTUNA_NESTED_WF=0):
  Un solo estudio Optuna; cada trial se evalúa sumando métricas en las ventanas de test de todos
  los folds (no reoptimiza por fold en in-sample).

Uso:
  python optuna_walkforward.py

Variables:
  OPTUNA_TRIALS              default 100 (en modo anidado: trials por fold)
  OPTUNA_TIMEOUT_S           default 0 (sin timeout; en anidado aplica a cada estudio interno)
  OPTUNA_STUDY               default "ia_walkforward"
  OPTUNA_NESTED_WF           default 1  (0 = modo conjunto sobre ventanas test)
  OPTUNA_MIN_TOTAL_TRADES    default 5
  OPTUNA_LOW_SAMPLE_SCORE    default -1000
  OPTUNA_TRIAL_FAIL_SCORE    default -99999 — si el trial lanza excepción (MT5, datos, etc.)
  OPTUNA_DD_COEFF            default 0.7 — peso del max drawdown en la métrica
  OPTUNA_SHARPE_COEFF        default 15 — escala de sharpe (equiv. legacy 0.15*100)
  OPTUNA_PF_WEIGHT           default 8 — bonus por profit factor (cap interno pf<=6)
  OPTUNA_SPARSE_N25_PENALTY  default 35 — penalización por trade bajo el umbral 25 (menor = más suave)

Rangos de busqueda (_suggest_params) orientados a XAUUSD: confianza 62–75, SL ATR mult 1.5–3.0,
pendiente H1 0.01–0.05, breakout lookback 15–50 (M15); RSI/ATR categoricos siguen en el trial.
También BE_RATIO→IA_BE_TRIGGER_RR, TRAIL_ATR_MULT→IA_AUTO_TRAIL_ATR_MULT, START_HOUR→
IA_LIQUIDITY_NY_HOUR_START (útil si IA_LIQUIDITY_SESSION_NY_ENABLE=1 en backtest/live).
Meta-régimen (IA_REGIME_*): umbrales ADX tendencia/rango y crisis ATR — el backtest aplica la misma
lógica que market_regime cuando IA_REGIME_ENABLE=1.

Al terminar escribe `params_optimized.json` (plano + last_optimization_date), `ia_optuna_best.env`
y `ia_optuna_best.json`. El bot aplica `params_optimized.json` cada ronda (por defecto).

Usa backtest_walkforward.run_backtest + backtest_env_overlay.

--- Interpretar get_param_importances (fANOVA; valores relativos, no siempre suman 100%) ---

Si domina IA_AUTO_SL_ATR_MULT (suele destacar mucho frente al resto):
  El rendimiento depende fuerte de la volatilidad y del ancho del stop (ATR). Priorizar coherencia
  del SL por ATR en vivo; el oro a menudo sacude antes de definir direccion.

Si domina IA_SLOPE_MIN_ABS_PCT:
  El mercado en el backtest se parece a tendencia en H1; el filtro de regimen explica mucho el
  resultado. Valores altos = pocos trades pero menos lateral; normal operar poco.

Si domina IA_MIN_CONFIDENCE:
  El score / umbral de confianza explica mucho la metrica; el filtro de IA aporta edge respecto
  a otros knobs. Complementa bien con memoria de trades (ia_auto_memory) si la usas.

Si domina IA_BREAKOUT_LOOKBACK:
  La ventana de estructura (ruptura de rango) es clave. Considerar mas contexto M15 con
  IA_M15_CONTEXT_BARS en scanner/backtest si los niveles necesitan mas historia.

Peligro: importancias todas bajas / planas (ningun parametro claramente mas influyente):
  Mucho ruido, poco historico, o demasiados filtros / objetivo poco sensible. Ampliar
  BT_MONTHS_TOTAL y folds, revisar rango de busqueda Optuna o simplificar reglas.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import MetaTrader5 as mt5
import optuna

from backtest_walkforward import _add_months, _month_floor_utc, metrics_ext, run_backtest
from local_env import load_env_file, save_optuna_best_params
from optuna.importance import get_param_importances


def _print_importance_followup() -> None:
    """Linea de ayuda tras get_param_importances (detalle en docstring del modulo)."""
    print(
        "Nota: lee el bloque 'Interpretar get_param_importances' en el docstring de "
        "optuna_walkforward.py (SL ATR vs slope H1 vs confidence vs breakout vs datos insuficientes)."
    )


def _report_param_importances(study: optuna.Study, label: str) -> None:
    try:
        imp = get_param_importances(study)
        print(f"\n{label}", imp)
        _print_importance_followup()
    except Exception as e:
        print("Importancia de parametros: no disponible:", e)


def _walk_forward_windows(
    months_total: int, train_m: int, test_m: int, step_m: int
) -> list[tuple[datetime, datetime, datetime]]:
    """
    Genera folds: (train_from, train_to, test_to).
    Entrenamiento: [train_from, train_to). Test OOS: [train_to, test_to).
    """
    end = _month_floor_utc(datetime.now(timezone.utc))
    anchor_start = _add_months(end, -months_total)
    out: list[tuple[datetime, datetime, datetime]] = []
    cur = anchor_start
    while True:
        train_to = _add_months(cur, train_m)
        test_to = _add_months(train_to, test_m)
        if test_to > end:
            break
        out.append((cur, train_to, test_to))
        cur = _add_months(cur, step_m)
    return out


def _trial_fail_score() -> float:
    return float(os.environ.get("OPTUNA_TRIAL_FAIL_SCORE", "-99999"))


# Claves fijas del estudio (no pasan por suggest_*); hay que mezclarlas con study.best_params.
_FIXED_PARAMS_FOR_SAVED: dict[str, Any] = {
    "BT_SL_MODE": "atr",
    "IA_REGIME_ENABLE": "1",
}

# Nombres cortos en el estudio Optuna → claves .env aplicadas por apply_optuna_overrides
_OPTUNA_NAME_TO_ENV: dict[str, str] = {
    "BE_RATIO": "IA_BE_TRIGGER_RR",
    "TRAIL_ATR_MULT": "IA_AUTO_TRAIL_ATR_MULT",
    "START_HOUR": "IA_LIQUIDITY_NY_HOUR_START",
}


def _params_complete(study: optuna.Study) -> dict[str, Any]:
    """best_params de Optuna + fijos (BT_SL_MODE=atr, IA_REGIME_ENABLE=1) para JSON / OOS."""
    raw = dict(study.best_params)
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k == "IA_REGIME_ADX_GAP":
            continue
        env_k = _OPTUNA_NAME_TO_ENV.get(k, k)
        out[env_k] = v
    if "IA_REGIME_ADX_TREND_MIN" in raw and "IA_REGIME_ADX_GAP" in raw:
        out["IA_REGIME_ADX_RANGE_MAX"] = max(
            8, int(raw["IA_REGIME_ADX_TREND_MIN"]) - int(raw["IA_REGIME_ADX_GAP"])
        )
    out.update(_FIXED_PARAMS_FOR_SAVED)
    return out


def _suggest_params(trial: optuna.Trial) -> dict[str, Any]:
    """
    Rangos sugeridos para oro (XAUUSD): mas muestra en confianza baja, ATR mult amplio, slope y
    breakout acotados al comportamiento tipico M15/H1.
    """
    rsi_filter = trial.suggest_categorical("RSI_FILTER", [0, 1])
    atr_filter = trial.suggest_categorical("ATR_FILTER", [0, 1])
    slope_on = trial.suggest_categorical("IA_SLOPE_FILTER", [0, 1])
    be_rr = trial.suggest_float("BE_RATIO", 0.8, 1.2)
    trail_mult = trial.suggest_float("TRAIL_ATR_MULT", 2.0, 4.0)
    ny_start = trial.suggest_int("START_HOUR", 7, 10)
    trend_adx = trial.suggest_int("IA_REGIME_ADX_TREND_MIN", 23, 34)
    gap = trial.suggest_int("IA_REGIME_ADX_GAP", 4, 12)
    range_adx = max(8, trend_adx - gap)
    crisis_pctl = trial.suggest_int("IA_REGIME_ATR_CRISIS_PCTL", 82, 92)
    return {
        "IA_MIN_CONFIDENCE": trial.suggest_int("IA_MIN_CONFIDENCE", 62, 75),
        "IA_BREAKOUT_LOOKBACK": trial.suggest_int("IA_BREAKOUT_LOOKBACK", 15, 50, step=5),
        "IA_SLOPE_FILTER": str(int(slope_on)),
        "IA_SLOPE_MIN_ABS_PCT": trial.suggest_float("IA_SLOPE_MIN_ABS_PCT", 0.01, 0.05, step=0.005),
        "RSI_FILTER": rsi_filter,
        "RSI_BUY_MIN": trial.suggest_int("RSI_BUY_MIN", 35, 55),
        "RSI_SELL_MAX": trial.suggest_int("RSI_SELL_MAX", 45, 65),
        "ATR_FILTER": atr_filter,
        "ATR_PCTL_MIN": trial.suggest_int("ATR_PCTL_MIN", 5, 35),
        "ATR_PCTL_MAX": trial.suggest_int("ATR_PCTL_MAX", 65, 95),
        "BT_SL_MODE": "atr",
        "IA_AUTO_SL_ATR_MULT": trial.suggest_float("IA_AUTO_SL_ATR_MULT", 1.5, 3.0, step=0.1),
        "IA_BE_TRIGGER_RR": be_rr,
        "IA_AUTO_TRAIL_ATR_MULT": trail_mult,
        "IA_LIQUIDITY_NY_HOUR_START": ny_start,
        "IA_REGIME_ENABLE": "1",
        "IA_REGIME_ADX_TREND_MIN": trend_adx,
        "IA_REGIME_ADX_RANGE_MAX": range_adx,
        "IA_REGIME_ATR_CRISIS_PCTL": crisis_pctl,
    }


def _objective_weights() -> tuple[float, float, float, float, float]:
    """dd_coef, sharpe_coef, pf_weight, penalty_per_trade_under_25, min_trades."""
    try:
        dd_c = float(os.environ.get("OPTUNA_DD_COEFF", "0.7").strip() or "0.7")
    except ValueError:
        dd_c = 0.7
    try:
        sh_c = float(os.environ.get("OPTUNA_SHARPE_COEFF", "15").strip() or "15")
    except ValueError:
        sh_c = 15.0
    try:
        pf_w = float(os.environ.get("OPTUNA_PF_WEIGHT", "8").strip() or "8")
    except ValueError:
        pf_w = 8.0
    try:
        pen = float(os.environ.get("OPTUNA_SPARSE_N25_PENALTY", "35").strip() or "35")
    except ValueError:
        pen = 35.0
    try:
        min_tr = int(os.environ.get("OPTUNA_MIN_TOTAL_TRADES", "5").strip() or "5")
    except ValueError:
        min_tr = 5
    return dd_c, sh_c, pf_w, pen, float(min_tr)


def _partial_running(
    total_net: float, total_dd: float, sharpe_sum: float, *, pf: float = 1.0
) -> float:
    """Métrica agregada: net - λ*DD + sharpe_scale + bonus por profit factor (acotado)."""
    dd_c, sh_c, pf_w, _, _ = _objective_weights()
    # PF: en backtest puede explotar (999); acotamos para no dominar el objetivo
    pf_clamped = max(0.0, min(float(pf), 6.0))
    pf_bonus = pf_w * (pf_clamped - 1.0) if pf_w > 0 else 0.0
    return (total_net - dd_c * total_dd) + (sh_c * sharpe_sum) + pf_bonus


def _composite_score(
    total_net: float,
    total_dd: float,
    total_n: int,
    sharpe_sum: float,
    *,
    pf: float = 1.0,
) -> float:
    dd_c, sh_c, pf_w, pen_under_25, min_total_f = _objective_weights()
    min_total = int(min_total_f)
    if total_n < min_total:
        return float(os.environ.get("OPTUNA_LOW_SAMPLE_SCORE", "-1000"))
    if total_n < 25:
        sparse_pen = (25 - total_n) * pen_under_25
        pf_clamped = max(0.0, min(float(pf), 6.0))
        pf_bonus = pf_w * (pf_clamped - 1.0) if pf_w > 0 else 0.0
        return (total_net - dd_c * total_dd) + (sh_c * sharpe_sum) + pf_bonus - sparse_pen
    return _partial_running(total_net, total_dd, sharpe_sum, pf=pf)


def objective_train_fold(
    trial: optuna.Trial,
    symbol: str,
    train_from: datetime,
    train_to: datetime,
) -> float:
    """Optuna solo ve el backtest in-sample en [train_from, train_to)."""
    try:
        params = _suggest_params(trial)
        trades = run_backtest(symbol, train_from, train_to, params)
        m = metrics_ext(trades)
        n = int(m["n"])
        net = float(m["net"])
        dd = float(m["max_dd"])
        sharpe = float(m["sharpe"])
        pf = float(m["pf"])
        from ia_optuna_sharpe import objetivo_sharpe_desde_metricas, optuna_objective_mode

        if optuna_objective_mode() == "sharpe":
            value = objetivo_sharpe_desde_metricas(trades, m)
        else:
            value = _composite_score(net, dd, n, sharpe, pf=pf)
        trial.report(value, step=0)
        return value
    except optuna.TrialPruned:
        raise
    except Exception as e:
        print(f"[Optuna] Error en trial (train_fold): {e}")
        return _trial_fail_score()


def objective_joint_folds(
    trial: optuna.Trial, symbol: str, windows: list[tuple[datetime, datetime, datetime]]
) -> float:
    """
    Cada trial se evalúa en cada ventana de test OOS [train_to, test_to) y se agrega la métrica.
    """
    try:
        params = _suggest_params(trial)
        total_net = 0.0
        total_dd = 0.0
        total_n = 0
        sharpe_sum = 0.0
        pf_weighted = 0.0
        from ia_optuna_sharpe import optuna_objective_mode

        sharpe_mode = optuna_objective_mode() == "sharpe"
        all_trades: list[Any] = []
        for i, (_train_from, train_to, test_to) in enumerate(windows):
            trades = run_backtest(symbol, train_to, test_to, params)
            if sharpe_mode:
                all_trades.extend(trades)
            m = metrics_ext(trades)
            n_i = int(m["n"])
            total_n += n_i
            total_net += float(m["net"])
            total_dd += float(m["max_dd"])
            sharpe_sum += float(m["sharpe"])
            if n_i > 0:
                pf_weighted += float(m["pf"]) * n_i
            partial = _partial_running(total_net, total_dd, sharpe_sum)
            trial.report(partial, step=i)
            if trial.should_prune():
                raise optuna.TrialPruned()
        pf_avg = (pf_weighted / total_n) if total_n > 0 else 1.0

        if sharpe_mode:
            m_agg = metrics_ext(all_trades)
            from ia_optuna_sharpe import objetivo_sharpe_desde_metricas

            return objetivo_sharpe_desde_metricas(all_trades, m_agg)
        return _composite_score(total_net, total_dd, total_n, sharpe_sum, pf=pf_avg)
    except optuna.TrialPruned:
        raise
    except Exception as e:
        print(f"[Optuna] Error en trial (joint_folds): {e}")
        return _trial_fail_score()


def main() -> None:
    load_env_file()
    symbol = os.environ.get("BT_SYMBOL", os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").split(",")[0]).strip() or "XAUUSD"
    months_total = int(os.environ.get("BT_MONTHS_TOTAL", "10"))
    train_m = int(os.environ.get("BT_TRAIN_MONTHS", "3"))
    test_m = int(os.environ.get("BT_TEST_MONTHS", "1"))
    step_m = int(os.environ.get("BT_STEP_MONTHS", "1"))

    trials = int(os.environ.get("OPTUNA_TRIALS", "100"))
    timeout = int(os.environ.get("OPTUNA_TIMEOUT_S", "0"))
    study_name = os.environ.get("OPTUNA_STUDY", "ia_walkforward")
    nested = os.environ.get("OPTUNA_NESTED_WF", "1").strip().lower() not in ("0", "false", "no")

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        raise SystemExit(f"MT5 init fail: {mt5.last_error()}")

    try:
        windows = _walk_forward_windows(months_total, train_m, test_m, step_m)
        if not windows:
            raise SystemExit("No hay folds (ajusta BT_MONTHS_TOTAL / train/test/step).")
        to = timeout or None
        print(
            f"Optuna walk-forward {symbol} | mode={'nested (train->OOS per fold)' if nested else 'joint (sum OOS tests)'} "
            f"| folds={len(windows)} | trials_per_study={trials} timeout={timeout}s"
        )

        if nested:
            oos_nets: list[float] = []
            last_study: optuna.Study | None = None
            for fi, (train_from, train_to, test_to) in enumerate(windows):
                print(
                    f"\n--- Fold {fi + 1}/{len(windows)} | train [{train_from.date()} .. {train_to.date()}) -> "
                    f"OOS test [{train_to.date()} .. {test_to.date()}) ---"
                )
                study = optuna.create_study(
                    direction="maximize",
                    study_name=f"{study_name}_f{fi}",
                    pruner=optuna.pruners.NopPruner(),
                )
                study.optimize(
                    lambda tr: objective_train_fold(tr, symbol, train_from, train_to),
                    n_trials=trials,
                    timeout=to,
                )
                last_study = study
                print("  best_in_sample value:", study.best_value)
                oos_trades = run_backtest(symbol, train_to, test_to, _params_complete(study))
                oos = metrics_ext(oos_trades)
                oos_nets.append(float(oos["net"]))
                print(
                    f"  OOS: n={int(oos['n'])} net={oos['net']:.2f} max_dd={oos['max_dd']:.2f} "
                    f"sharpe={oos['sharpe']:.3f} wr={oos['wr']:.2f}"
                )

            if oos_nets:
                print("\n=== Resumen OOS (fuera de muestra) ===")
                print(f"  sum_net_oos: {sum(oos_nets):.2f}  (folds={len(oos_nets)})")
            if last_study is not None:
                env_p, json_p, opt_p = save_optuna_best_params(
                    _params_complete(last_study),
                    symbol=symbol,
                    mode="nested_last_fold",
                    best_value=float(last_study.best_value),
                    fold_index=len(windows) - 1,
                )
                print(f"\nBest params (ultimo fold) -> {opt_p.name} | {env_p.name} | {json_p.name}")
                _report_param_importances(last_study, "Importancia (ultimo fold, in-sample):")
        else:
            study = optuna.create_study(
                direction="maximize",
                study_name=study_name,
                pruner=optuna.pruners.MedianPruner(n_startup_trials=10, n_warmup_steps=1),
            )
            study.optimize(lambda tr: objective_joint_folds(tr, symbol, windows), n_trials=trials, timeout=to)
            print("\nBEST (criterio conjunto sobre tests)")
            print("  value:", study.best_value)
            for k, v in sorted(_params_complete(study).items()):
                print(f"  {k}={v}")
            env_p, json_p, opt_p = save_optuna_best_params(
                _params_complete(study),
                symbol=symbol,
                mode="joint_oos_tests",
                best_value=float(study.best_value),
            )
            print(f"\nBest params -> {opt_p.name} | {env_p.name} | {json_p.name}")
            _report_param_importances(study, "Importancia de parametros (estudio conjunto):")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
