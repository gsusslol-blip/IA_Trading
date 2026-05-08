"""
Backtesting walk-forward (MT5) para validar si la señal "aprende" o solo tuvo suerte.

Modelo: regla base (engulfing + volumen + filtro H4) + breakout + slope H1 + score/filtros (RSI/ATR/umbral).
Ejecución: entradas en M15 (apertura de la vela siguiente al patrón).
Salida SL/TP intrabar en M15: en cada vela se usa high/low; si low alcanza SL o high alcanza TP,
se asume ese precio (orden pesimista: SL antes que TP si la vela barre ambos).
Breakout: IA_BREAKOUT_LOOKBACK fija N; el máximo/mínimo de las últimas N velas (sin la vela actual)
define el nivel de ruptura.

Uso:
  python backtest_walkforward.py

Variables (.env):
  BT_SYMBOL                 default XAUUSD
  BT_MONTHS_TOTAL           default 8      (meses hacia atrás)
  BT_TRAIN_MONTHS           default 3
  BT_TEST_MONTHS            default 1
  BT_STEP_MONTHS            default 1
  BT_SL_PCT                 default 5
  BT_RR                     default 2
  BT_SL_MODE                default percent (o atr)
  BT_MIN_TRADES             default 10     (si test tiene menos, no se considera fiable)

Parámetros a optimizar / fijar:
  IA_MIN_CONFIDENCE          (default 75)
  RSI_FILTER                 (0/1)
  RSI_BUY_MIN / RSI_SELL_MAX
  ATR_FILTER                 (0/1)
  ATR_PCTL_MIN / ATR_PCTL_MAX
  IA_BREAKOUT_LOOKBACK
  IA_SLOPE_MIN_ABS_PCT
  IA_AUTO_SL_ATR_MULT (si BT_SL_MODE=atr)
  IA_REGIME_* — meta-régimen (ADX/ATR) coherente con market_regime / ia_scanner_loop si IA_REGIME_ENABLE=1.
    (timestamps como UTC; coherente con ia_scanner_loop si el servidor MT5 usa UTC).

Nota:
  Esto no usa la API de Strategy Tester de MT5; usa históricos del terminal via copy_rates_range.
  Es suficiente para comparar reglas/umbral, no para ejecución exacta del broker.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from local_env import load_env_file
from market_regime import classify_regime_rules_from_hlc, regime_trend_allowed
from signal_analysis import _atr_series, _percentile_rank, _rsi_wilder, _tf_bias_label, _true_ranges


@dataclass
class Trade:
    t_entry: datetime
    side: str  # BUY/SELL
    entry: float
    sl: float
    tp: float
    t_exit: datetime
    exit: float
    pnl_points: float


def _max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for x in equity:
        if x > peak:
            peak = x
        dd = peak - x
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _sharpe_like(pnls: list[float]) -> float:
    # Sharpe-like sobre PnL por trade (en puntos); sirve para comparar parámetros.
    if len(pnls) < 5:
        return 0.0
    mean = sum(pnls) / len(pnls)
    var = sum((x - mean) ** 2 for x in pnls) / (len(pnls) - 1)
    if var <= 1e-12:
        return 0.0
    return (mean / (var ** 0.5)) * (len(pnls) ** 0.5)


def metrics_ext(trades: list[Trade]) -> dict[str, float]:
    if not trades:
        return {"n": 0.0, "net": 0.0, "wr": 0.0, "avg": 0.0, "max_dd": 0.0, "sharpe": 0.0, "pf": 0.0}
    pnls = [t.pnl_points for t in trades]
    n = len(pnls)
    wins = [x for x in pnls if x > 0]
    losses = [-x for x in pnls if x < 0]
    net = sum(pnls)
    eq: list[float] = []
    s = 0.0
    for x in pnls:
        s += x
        eq.append(s)
    max_dd = _max_drawdown(eq)
    pf = (sum(wins) / sum(losses)) if losses else (999.0 if wins else 0.0)
    return {
        "n": float(n),
        "net": float(net),
        "wr": float(len(wins) / n) if n else 0.0,
        "avg": float(net / n) if n else 0.0,
        "max_dd": float(max_dd),
        "sharpe": float(_sharpe_like(pnls)),
        "pf": float(pf),
    }


def _month_floor_utc(dt: datetime) -> datetime:
    d = dt.astimezone(timezone.utc)
    return datetime(d.year, d.month, 1, tzinfo=timezone.utc)


def _add_months(dt: datetime, months: int) -> datetime:
    y, m = dt.year, dt.month
    m2 = m - 1 + months
    y2 = y + m2 // 12
    m3 = (m2 % 12) + 1
    return datetime(y2, m3, 1, tzinfo=timezone.utc)


def _engulfing_m15(m15_prev, m15_cur) -> str | None:
    # Reutiliza la idea del scanner: alcista/bajista simple
    prev_open = float(m15_prev["open"])
    prev_close = float(m15_prev["close"])
    cur_open = float(m15_cur["open"])
    cur_close = float(m15_cur["close"])
    if cur_close > prev_open and cur_open < prev_close:
        return "BUY"
    if cur_close < prev_open and cur_open > prev_close:
        return "SELL"
    return None


def _h4_trend_ok(h4_rates, i_h4: int, side: str) -> bool:
    # Precio vs SMA20 en H4
    if i_h4 < 21:
        return False
    closes = [float(r["close"]) for r in h4_rates[: i_h4 + 1]]
    sma20 = sum(closes[-20:]) / 20
    price = closes[-1]
    trend = "ALTA" if price > sma20 else "BAJA"
    return (side == "BUY" and trend == "ALTA") or (side == "SELL" and trend == "BAJA")


def _find_last_index_by_time(rates, t: int) -> int:
    # rates sorted asc by time, return last idx with time <= t
    lo, hi = 0, len(rates) - 1
    out = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        tm = int(rates[mid]["time"])
        if tm <= t:
            out = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return out


def _passes_rsi(side: str, rsi: float | None) -> bool:
    if rsi is None:
        return True
    if os.environ.get("RSI_FILTER", "0").strip().lower() not in ("1", "true", "yes"):
        return True
    buy_min = float(os.environ.get("RSI_BUY_MIN", "45"))
    sell_max = float(os.environ.get("RSI_SELL_MAX", "55"))
    if side == "BUY":
        return rsi >= buy_min
    if side == "SELL":
        return rsi <= sell_max
    return True


def _passes_atr(atr_pctl: float | None) -> bool:
    if atr_pctl is None:
        return True
    if os.environ.get("ATR_FILTER", "0").strip().lower() not in ("1", "true", "yes"):
        return True
    pmin = float(os.environ.get("ATR_PCTL_MIN", "15"))
    pmax = float(os.environ.get("ATR_PCTL_MAX", "85"))
    return pmin <= atr_pctl <= pmax


def _confidence(side: str, m15_b: str, h1_b: str, h4_b: str) -> int:
    # Score compacto (18..92) similar al esquema de signal_analysis (sin swings para backtest rápido)
    score = 42
    if side == "BUY":
        score += 18 if m15_b == "alcista" else (-12 if m15_b == "bajista" else 0)
        score += 8 if h1_b == "alcista" else (-6 if h1_b == "bajista" else 0)
        score += 8 if h4_b == "alcista" else (-14 if h4_b == "bajista" else 0)
    else:
        score += 18 if m15_b == "bajista" else (-12 if m15_b == "alcista" else 0)
        score += 8 if h1_b == "bajista" else (-6 if h1_b == "alcista" else 0)
        score += 8 if h4_b == "bajista" else (-14 if h4_b == "alcista" else 0)
    return max(18, min(92, score))


def _liquidity_ny_allows_utc_bar(bar_time_utc: int) -> bool:
    """Misma lógica que el scanner NY: timestamps de velas tratados como UTC → hora en New York."""
    if os.environ.get("IA_LIQUIDITY_SESSION_NY_ENABLE", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return True
    try:
        from zoneinfo import ZoneInfo

        dt_ny = datetime.fromtimestamp(bar_time_utc, tz=timezone.utc).astimezone(ZoneInfo("America/New_York"))
        h = dt_ny.hour
    except Exception:
        return True
    try:
        h0 = int(os.environ.get("IA_LIQUIDITY_NY_HOUR_START", "8").strip() or "8")
        h1 = int(os.environ.get("IA_LIQUIDITY_NY_HOUR_END", "16").strip() or "16")
    except ValueError:
        return True
    return h0 <= h <= h1


def backtest_window(symbol: str, utc_from: datetime, utc_to: datetime) -> list[Trade]:
    m5 = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, utc_from, utc_to)
    m15 = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M15, utc_from, utc_to)
    h1 = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, utc_from, utc_to)
    h4 = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H4, utc_from, utc_to)
    m5 = [] if m5 is None else list(m5)
    m15 = [] if m15 is None else list(m15)
    h1 = [] if h1 is None else list(h1)
    h4 = [] if h4 is None else list(h4)
    if len(m15) < 200 or len(h1) < 60 or len(h4) < 40 or len(m5) < 400:
        return []

    # Precompute M5 ATR percentiles and RSI series in a rolling manner
    closes_m5 = [float(r["close"]) for r in m5]
    highs_m5 = [float(r["high"]) for r in m5]
    lows_m5 = [float(r["low"]) for r in m5]
    trs = _true_ranges(highs_m5, lows_m5, closes_m5)
    atr_period = int(os.environ.get("ATR_PERIOD", "14"))
    atr_hist = _atr_series(trs, atr_period)
    # atr_hist aligns to trs index => closes index offset 1, plus window; we just use tail slice for percentile rank

    sl_mode = os.environ.get("BT_SL_MODE", "percent").strip().lower()
    sl_pct = float(os.environ.get("BT_SL_PCT", os.environ.get("IA_AUTO_SL_PRICE_PERCENT", "5")))
    rr = float(os.environ.get("BT_RR", os.environ.get("RR", "2")))
    try:
        min_conf = int(float(os.environ.get("IA_MIN_CONFIDENCE", "75")))
    except ValueError:
        min_conf = 75

    out: list[Trade] = []
    in_trade = False
    i = 2
    while i < len(m15) - 2:
        if in_trade:
            i += 1
            continue

        prev = m15[i - 1]
        cur = m15[i]
        t = int(cur["time"])

        base = _engulfing_m15(prev, cur)
        if base is None:
            i += 1
            continue

        # volume confirm on M15
        if int(cur["tick_volume"]) <= int(prev["tick_volume"]):
            i += 1
            continue

        if not _liquidity_ny_allows_utc_bar(t):
            i += 1
            continue

        # H4 filter (simple)
        ih4 = _find_last_index_by_time(h4, t)
        if ih4 < 0 or not _h4_trend_ok(h4, ih4, base):
            i += 1
            continue

        # Breakout: rango reciente de `lb` velas (IA_BREAKOUT_LOOKBACK / Optuna); close rompe hi/lo.
        try:
            lb = int(os.environ.get("IA_BREAKOUT_LOOKBACK", "20").strip() or "20")
        except ValueError:
            lb = 20
        lb = max(10, min(120, lb))
        if i > lb + 2:
            recent = m15[i - lb - 1 : i - 1]
            hi = max(float(r["high"]) for r in recent)
            lo = min(float(r["low"]) for r in recent)
            close = float(cur["close"])
            if base == "BUY" and close <= hi:
                i += 1
                continue
            if base == "SELL" and close >= lo:
                i += 1
                continue

        # Multi-TF bias labels (M15/H1/H4 SMA20/50)
        im15 = i
        ih1 = _find_last_index_by_time(h1, t)
        if ih1 < 60:
            i += 1
            continue

        if os.environ.get("IA_REGIME_ENABLE", "0").strip().lower() in ("1", "true", "yes"):
            tf_reg = os.environ.get("IA_REGIME_TIMEFRAME", "H1").strip().upper()
            if tf_reg == "H4":
                if ih4 < 50:
                    i += 1
                    continue
                rh = [float(h4[k]["high"]) for k in range(ih4 + 1)]
                rl = [float(h4[k]["low"]) for k in range(ih4 + 1)]
                rc = [float(h4[k]["close"]) for k in range(ih4 + 1)]
            elif tf_reg == "M15":
                if i < 50:
                    i += 1
                    continue
                rh = [float(m15[k]["high"]) for k in range(i + 1)]
                rl = [float(m15[k]["low"]) for k in range(i + 1)]
                rc = [float(m15[k]["close"]) for k in range(i + 1)]
            else:
                if ih1 < 50:
                    i += 1
                    continue
                rh = [float(h1[k]["high"]) for k in range(ih1 + 1)]
                rl = [float(h1[k]["low"]) for k in range(ih1 + 1)]
                rc = [float(h1[k]["close"]) for k in range(ih1 + 1)]
            snap_bt = classify_regime_rules_from_hlc(rh, rl, rc)
            if not regime_trend_allowed(snap_bt):
                i += 1
                continue

        # Regime slope filter on H1 SMA
        if os.environ.get("IA_SLOPE_FILTER", "1").strip().lower() not in ("0", "false", "no"):
            try:
                period = int(os.environ.get("IA_SLOPE_SMA_PERIOD", "50"))
            except ValueError:
                period = 50
            try:
                look = int(os.environ.get("IA_SLOPE_LOOKBACK", "10"))
            except ValueError:
                look = 10
            try:
                min_abs = float(os.environ.get("IA_SLOPE_MIN_ABS_PCT", "0.03"))
            except ValueError:
                min_abs = 0.03
            if ih1 < period + look + 2:
                i += 1
                continue
            closes_h1 = [float(r["close"]) for r in h1[: ih1 + 1]]
            sma_now = sum(closes_h1[-period:]) / period
            sma_prev = sum(closes_h1[-period - look : -look]) / period
            slope_pct = ((sma_now - sma_prev) / sma_prev) * 100.0 if sma_prev else 0.0
            if abs(slope_pct) < min_abs:
                i += 1
                continue
            if base == "BUY" and slope_pct < 0:
                i += 1
                continue
            if base == "SELL" and slope_pct > 0:
                i += 1
                continue
        m15_b = _tf_bias_label([float(r["close"]) for r in m15[: im15 + 1]])
        h1_b = _tf_bias_label([float(r["close"]) for r in h1[: ih1 + 1]])
        h4_b = _tf_bias_label([float(r["close"]) for r in h4[: ih4 + 1]])

        conf = _confidence(base, m15_b, h1_b, h4_b)
        if conf < min_conf:
            i += 1
            continue

        # RSI on M5 up to this time
        im5 = _find_last_index_by_time(m5, t)
        rsi = _rsi_wilder(closes_m5[: im5 + 1], 14) if im5 > 60 else None
        if not _passes_rsi(base, rsi):
            i += 1
            continue

        # ATR percentile on M5
        atr_pctl = None
        if len(atr_hist) > 60 and im5 > atr_period + 60:
            # approximate: use last ATR value available near this point
            # atr_hist index corresponds to trs index (len(closes)-1), so map im5 -> trs index ~ im5-1
            trs_idx = max(0, im5 - 1)
            atr_idx = trs_idx - (atr_period - 1)
            if 0 <= atr_idx < len(atr_hist):
                atr_val = float(atr_hist[atr_idx])
                sample = atr_hist[max(0, atr_idx - 300) : atr_idx + 1]
                atr_pctl = _percentile_rank(atr_val, sample)
        if not _passes_atr(atr_pctl):
            i += 1
            continue

        # Entry at next M15 open
        nxt = m15[i + 1]
        entry = float(nxt["open"])
        if entry <= 0:
            i += 1
            continue
        if sl_mode in ("atr", "atr_m5"):
            try:
                atr_mult = float(os.environ.get("IA_AUTO_SL_ATR_MULT", "1.6"))
            except ValueError:
                atr_mult = 1.6
            atr_val_use = None
            if len(atr_hist) > 0 and im5 > atr_period + 10:
                trs_idx = max(0, im5 - 1)
                atr_idx = trs_idx - (atr_period - 1)
                if 0 <= atr_idx < len(atr_hist):
                    atr_val_use = float(atr_hist[atr_idx])
            if atr_val_use is None or atr_val_use <= 0:
                i += 1
                continue
            sl_dist = atr_val_use * atr_mult
        else:
            sl_dist = entry * (sl_pct / 100.0)
        tp_dist = sl_dist * rr
        if base == "BUY":
            sl = entry - sl_dist
            tp = entry + tp_dist
        else:
            sl = entry + sl_dist
            tp = entry - tp_dist

        # Intrabar M15: por vela, high/low vs SL/TP (no solo cierre).
        j = i + 1
        exit_price = entry
        exit_time = datetime.fromtimestamp(int(m15[j]["time"]), tz=timezone.utc)
        hit = False
        while j < len(m15) - 1:
            bar = m15[j]
            hi = float(bar["high"])
            lo = float(bar["low"])
            tbar = datetime.fromtimestamp(int(bar["time"]), tz=timezone.utc)
            if base == "BUY":
                # Pesimista: si la vela barre SL y TP, cuenta SL primero.
                if lo <= sl:
                    exit_price = sl
                    exit_time = tbar
                    hit = True
                    break
                if hi >= tp:
                    exit_price = tp
                    exit_time = tbar
                    hit = True
                    break
            else:
                # SELL: TP abajo — mismo criterio pesimista (SL primero si ambos).
                if hi >= sl:
                    exit_price = sl
                    exit_time = tbar
                    hit = True
                    break
                if lo <= tp:
                    exit_price = tp
                    exit_time = tbar
                    hit = True
                    break
            j += 1
        if not hit:
            # close at last close of window
            bar = m15[j]
            exit_price = float(bar["close"])
            exit_time = datetime.fromtimestamp(int(bar["time"]), tz=timezone.utc)

        pnl_points = (exit_price - entry) if base == "BUY" else (entry - exit_price)
        out.append(
            Trade(
                t_entry=datetime.fromtimestamp(int(nxt["time"]), tz=timezone.utc),
                side=base,
                entry=entry,
                sl=sl,
                tp=tp,
                t_exit=exit_time,
                exit=exit_price,
                pnl_points=pnl_points,
            )
        )
        in_trade = False
        # jump to exit bar to avoid overlapping
        i = max(i + 1, j)
    return out


@contextlib.contextmanager
def backtest_env_overlay(params: dict[str, object]) -> Iterator[None]:
    """Aplica parámetros del trial sobre os.environ y restaura al salir."""
    saved: dict[str, str | None] = {}
    try:
        for k, v in params.items():
            ks = str(k)
            saved[ks] = os.environ.get(ks)
            os.environ[ks] = str(v)
        yield
    finally:
        for ks, old in saved.items():
            if old is None:
                os.environ.pop(ks, None)
            else:
                os.environ[ks] = old


def run_backtest(
    symbol: str,
    utc_from: datetime,
    utc_to: datetime,
    params: dict[str, object],
) -> list[Trade]:
    """
    Punto de integración Optuna: mismo motor que `backtest_window`, con parámetros del trial.

    `params` son claves de .env (ej. IA_MIN_CONFIDENCE, IA_AUTO_SL_ATR_MULT, BT_SL_MODE=atr).
    No usa un DataFrame precomputado: las reglas leen rates vía MT5 como en producción.
    """
    with backtest_env_overlay(params):
        return backtest_window(symbol, utc_from, utc_to)


def _metrics(trades: list[Trade]) -> dict[str, float]:
    if not trades:
        return {"n": 0, "net": 0.0, "wr": 0.0, "avg": 0.0}
    pnls = [t.pnl_points for t in trades]
    n = len(pnls)
    wins = sum(1 for x in pnls if x > 0)
    net = sum(pnls)
    return {"n": float(n), "net": float(net), "wr": wins / n, "avg": net / n}


def main() -> None:
    load_env_file()
    symbol = os.environ.get("BT_SYMBOL", os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD").split(",")[0]).strip() or "XAUUSD"
    months_total = int(os.environ.get("BT_MONTHS_TOTAL", "8"))
    train_m = int(os.environ.get("BT_TRAIN_MONTHS", "3"))
    test_m = int(os.environ.get("BT_TEST_MONTHS", "1"))
    step_m = int(os.environ.get("BT_STEP_MONTHS", "1"))
    min_trades = int(os.environ.get("BT_MIN_TRADES", "10"))

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        raise SystemExit(f"MT5 init fail: {mt5.last_error()}")

    try:
        now = datetime.now(timezone.utc)
        end = _month_floor_utc(now)
        start = _add_months(end, -months_total)

        print(f"Walk-forward {symbol} | desde {start.date()} hasta {end.date()} (UTC)")
        print(f"train={train_m}m test={test_m}m step={step_m}m | min_trades_test={min_trades}")

        cur = start
        fold = 0
        agg_net = 0.0
        agg_n = 0
        while True:
            train_from = cur
            train_to = _add_months(train_from, train_m)
            test_to = _add_months(train_to, test_m)
            if test_to > end:
                break

            fold += 1
            # En esta versión, no "entrenamos" modelos; solo validamos regla con parámetros actuales.
            trades_test = backtest_window(symbol, train_to, test_to)
            m = _metrics(trades_test)
            n = int(m["n"])
            tag = "OK" if n >= min_trades else "POCOS"
            print(f"fold {fold}: test {train_to.date()}..{test_to.date()} | n={n} | net={m['net']:+.2f} | wr={m['wr']*100:5.1f}% | {tag}")
            if n >= min_trades:
                agg_net += float(m["net"])
                agg_n += n
            cur = _add_months(cur, step_m)

        print(f"TOTAL (solo folds con n>={min_trades}): trades={agg_n} | net={agg_net:+.2f} (puntos)")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()

