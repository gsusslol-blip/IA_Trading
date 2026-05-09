from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import pandas as pd

from local_env import load_env_file

SYMBOLS = ("XAUUSD",)
BOT_CSV = os.environ.get("BOT_CSV", "bot_demo_log.csv")
BOT_MAGIC = int(os.environ.get("BOT_MAGIC", "260505"))

# copy_rates desde posición 0: se reutiliza mientras la vela más reciente (time) no cambie.
_rates_ttl_cache: dict[str, tuple[int, object]] = {}


def mt5_rates_cache_clear() -> None:
    _rates_ttl_cache.clear()


def mt5_rates_cache_enabled() -> bool:
    """Por defecto activado (menos llamadas al terminal por ronda); IA_MT5_RATES_CACHE=0 desactiva."""
    raw = os.environ.get("IA_MT5_RATES_CACHE", "1").strip().lower()
    return raw not in ("0", "false", "no")


def mt5_copy_rates_from_pos_cached(
    symbol: str,
    timeframe: int,
    start_pos: int,
    count: int,
):
    """Wrapper de copy_rates_from_pos con caché por (símbolo, TF, count) hasta nueva vela.

    Con caché activa: una lectura mínima (1 vela) para el ``time`` de la barra actual; si no
    cambió respecto al hit, se devuelve el bloque cacheado sin volver a pedir ``count`` velas.
    """
    if start_pos != 0 or not mt5_rates_cache_enabled():
        return mt5.copy_rates_from_pos(symbol, timeframe, start_pos, count)
    key = f"{symbol}\0{timeframe}\0{count}"
    probe = mt5.copy_rates_from_pos(symbol, timeframe, 0, 1)
    if probe is None or len(probe) == 0:
        return probe
    # Serie ordenada vieja→nueva: última fila = vela más reciente (en formación o recién cerrada).
    t_anchor = int(probe[-1]["time"])

    hit = _rates_ttl_cache.get(key)
    if hit is not None and hit[0] == t_anchor:
        return hit[1]

    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        return rates
    _rates_ttl_cache[key] = (t_anchor, rates)
    return rates


def get_rates_optimized(symbol: str, timeframe: int, n_bars: int) -> pd.DataFrame | None:
    """
    Precio OHLCV como DataFrame (columna ``time`` en segundos unix, igual que copy_rates).

    Si IA_MT5_RATES_CACHE=1, reaprovecha bloques hasta que cambie el timestamp de la última vela.
    Alias de compatibilidad: ``get_historical_data`` (misma firma).
    """
    rates = mt5_copy_rates_from_pos_cached(symbol, timeframe, 0, n_bars)
    if rates is None or len(rates) == 0:
        return None
    return pd.DataFrame(rates)


def get_historical_data(symbol: str, timeframe: int, n_bars: int) -> pd.DataFrame | None:
    """Nombre alternativo esperado por scripts externos / backtests."""
    return get_rates_optimized(symbol, timeframe, n_bars)


def ensure_unix_time(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """
    Fuerza la columna ``time`` a segundos unix ``int64`` (mismo criterio que ``copy_rates`` / replay).

    Cubre: índice ``DatetimeIndex``, columna ``time`` en ``datetime64``, numéricos o texto parseable.
    No añade ``time_unix``: se normaliza ``time`` para que ``replay_from_m15_h4_windows`` y código legacy
    comparen enteros sin fricción con el ``PriceEngine`` (datetime).
    """
    if df is None:
        return None
    if df.empty:
        return df.copy()

    def _epoch_seconds_series(series: pd.Series) -> pd.Series:
        ts = pd.to_datetime(series, utc=True, errors="coerce")

        def _one(z: object) -> int:
            if pd.isna(z):
                return 0
            return int(pd.Timestamp(z).timestamp())

        return ts.map(_one).astype("int64", copy=False)

    out = df.copy()
    # Índice temporal → columna ``time``
    if isinstance(out.index, pd.DatetimeIndex):
        secs = [int(pd.Timestamp(t).timestamp()) if pd.notna(t) else 0 for t in out.index]
        body = out.reset_index(drop=True)
        if "time" in body.columns:
            body = body.drop(columns=["time"])
        body.insert(0, "time", secs)
        out = body

    if "time" not in out.columns:
        return out

    s = out["time"]
    if pd.api.types.is_datetime64_any_dtype(s):
        out["time"] = _epoch_seconds_series(s)
    elif pd.api.types.is_numeric_dtype(s):
        out["time"] = pd.to_numeric(s, errors="coerce").fillna(0).astype("int64")
    else:
        out["time"] = _epoch_seconds_series(s)
    return out


def _env_winrate_target() -> float:
    """WINRATE_TARGET en .env: 0.85 o 85 → 85 % aciertos; 0 o vacío = desactivado."""
    raw = os.environ.get("WINRATE_TARGET", "").strip()
    if not raw:
        return 0.0
    try:
        v = float(raw.replace(",", "."))
        if v > 1.0:
            v /= 100.0
        return max(0.0, min(1.0, v))
    except ValueError:
        return 0.0


def closed_trade_winrate_stats(pnls: list[float]) -> tuple[float, int, int, int]:
    """(winrate 0..1, ganadoras, perdedoras, break-even/cero)."""
    if not pnls:
        return 0.0, 0, 0, 0
    wins = sum(1 for x in pnls if x > 0)
    losses = sum(1 for x in pnls if x < 0)
    flat = len(pnls) - wins - losses
    return wins / len(pnls), wins, losses, flat


def closed_bot_trade_pnls(symbol: str, magic: int, *, days: int = 3650) -> list[float]:
    """
    PnL neto por operación cerrada (profit + commission + swap por position_id),
    ordenado por tiempo de cierre, todos los cierres en la ventana de `days`.
    """
    utc_to = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(days=days)
    try:
        mt5.history_select(utc_from, utc_to)
    except Exception:
        pass
    deals = mt5.history_deals_get(utc_from, utc_to)
    if not deals:
        return []
    agg: dict[int, float] = {}
    times: dict[int, int] = {}
    for d in deals:
        if int(getattr(d, "magic", -1) or -1) != int(magic):
            continue
        if str(getattr(d, "symbol", "") or "") != symbol:
            continue
        pid = int(getattr(d, "position_id", 0) or 0)
        if pid <= 0:
            continue
        agg[pid] = agg.get(pid, 0.0) + float(getattr(d, "profit", 0.0) or 0.0)
        agg[pid] += float(getattr(d, "commission", 0.0) or 0.0)
        agg[pid] += float(getattr(d, "swap", 0.0) or 0.0)
        t = int(getattr(d, "time", 0) or 0)
        times[pid] = max(times.get(pid, 0), t)
    if not agg:
        return []
    ordered = sorted(agg.keys(), key=lambda p: times.get(p, 0))
    return [agg[p] for p in ordered]


def closed_positions_pnls_by_magic(
    magic: int,
    utc_from: datetime,
    utc_to: datetime,
    *,
    history_lookback_days: int = 14,
) -> list[float]:
    """
    PnL neto por posición cerrada (cualquier símbolo) con ese magic; solo incluye cierres cuyo
    último deal cae en [utc_from, utc_to] (UTC).

    Se pide historial unos días antes de utc_from para no perder deals de apertura al usar
    history_deals_get solo por fecha de cierre.
    """
    uf = utc_from if utc_from.tzinfo else utc_from.replace(tzinfo=timezone.utc)
    ut = utc_to if utc_to.tzinfo else utc_to.replace(tzinfo=timezone.utc)
    uf_wide = uf - timedelta(days=max(0, int(history_lookback_days)))
    try:
        mt5.history_select(uf_wide, ut)
    except Exception:
        pass
    deals = mt5.history_deals_get(uf_wide, ut)
    if not deals:
        return []
    agg: dict[int, float] = {}
    times: dict[int, int] = {}
    for d in deals:
        if int(getattr(d, "magic", -1) or -1) != int(magic):
            continue
        pid = int(getattr(d, "position_id", 0) or 0)
        if pid <= 0:
            continue
        agg[pid] = agg.get(pid, 0.0) + float(getattr(d, "profit", 0.0) or 0.0)
        agg[pid] += float(getattr(d, "commission", 0.0) or 0.0)
        agg[pid] += float(getattr(d, "swap", 0.0) or 0.0)
        t = int(getattr(d, "time", 0) or 0)
        times[pid] = max(times.get(pid, 0), t)
    if not agg:
        return []
    ts_lo = int(uf.timestamp())
    ts_hi = int(ut.timestamp())
    ordered_ids = sorted(
        [pid for pid in agg if ts_lo <= times.get(pid, 0) <= ts_hi],
        key=lambda p: times.get(p, 0),
    )
    return [agg[pid] for pid in ordered_ids]


def _recent_closed_position_pnls(symbol: str, magic: int, *, days: int = 7, max_positions: int = 40) -> list[float]:
    """
    PnL neto por posición cerrada (profit+commission+swap agrupados por position_id),
    ordenado por tiempo de cierre, últimos max_positions.
    """
    pnls = closed_bot_trade_pnls(symbol, magic, days=days)
    if not pnls:
        return []
    return pnls[-max_positions:]


def _adaptive_sl_rr_risk(
    base_sl_mult: float,
    base_rr: float,
    base_risk_pct: float,
    pnls: list[float],
) -> tuple[float, float, float, str]:
    """
    Ajusta SL (×ATR), RR y % riesgo según winrate y racha reciente.
    Límites vía env: ADAPT_SL_MIN/MAX, ADAPT_RR_MIN/MAX, ADAPT_RISK_MIN/MAX, ADAPT_STEP_*.
    WINRATE_TARGET (p.ej. 0.85): si % aciertos < objetivo y hay muestras suficientes,
    acerca el TP (↓RR) y ensancha el SL un poco; no garantiza alcanzar el % en todos los mercados.
    """
    profit_max = os.environ.get("PROFIT_MAX", "").strip().lower() in ("1", "true", "yes")
    rr_win_boost = 1.28 if profit_max else 1.0

    sl_min = float(os.environ.get("ADAPT_SL_MIN", "0.9"))
    sl_max = float(os.environ.get("ADAPT_SL_MAX", "2.8"))
    rr_min = float(os.environ.get("ADAPT_RR_MIN", "1.3"))
    rr_max = float(os.environ.get("ADAPT_RR_MAX", "4.0"))
    risk_min = float(os.environ.get("ADAPT_RISK_MIN", "0.02"))
    risk_max = float(os.environ.get("ADAPT_RISK_MAX", "0.12"))
    step_sl = float(os.environ.get("ADAPT_STEP_SL", "0.1"))
    step_rr = float(os.environ.get("ADAPT_STEP_RR", "0.2"))
    step_risk = float(os.environ.get("ADAPT_STEP_RISK", "0.015"))

    sl = max(sl_min, min(sl_max, base_sl_mult))
    rr = max(rr_min, min(rr_max, base_rr))
    rk = max(risk_min, min(risk_max, base_risk_pct))

    if not pnls:
        return sl, rr, rk, "sin operaciones cerradas en ventana"

    wins = sum(1 for x in pnls if x > 0)
    n = len(pnls)
    wr = wins / n if n else 0.5
    wt_goal = _env_winrate_target()

    notes: list[str] = []
    last3 = pnls[-3:] if len(pnls) >= 3 else pnls

    # Racha de pérdidas: recortar riesgo y TP, SL un poco más apretado
    if len(last3) >= 2 and sum(1 for x in last3 if x < 0) >= 2:
        sl = max(sl_min, sl - step_sl * 0.8)
        rr = max(rr_min, rr - step_rr * 0.6)
        rk = max(risk_min, rk - step_risk)
        notes.append("racha pérdidas")

    # Win rate bajo: menos ambición en TP, SL más corto, menos riesgo por trade
    if n >= 5 and wr < float(os.environ.get("ADAPT_WINRATE_LOW", "0.42")):
        sl = max(sl_min, base_sl_mult - step_sl)
        rr = max(rr_min, base_rr - step_rr)
        rk = max(risk_min, base_risk_pct - step_risk)
        notes.append(f"winrate {wr:.0%}")

    # Buen desempeño: un poco más de RR y margen en SL (menos stops por ruido)
    # No subir RR si estamos persiguiendo un objetivo de aciertos y aún no lo alcanzamos.
    if n >= 5 and wr > float(os.environ.get("ADAPT_WINRATE_HIGH", "0.58")):
        if not (wt_goal > 0 and wr + 1e-12 < wt_goal):
            sl = min(sl_max, base_sl_mult + step_sl * 0.6)
            rr = min(rr_max, base_rr + step_rr * 0.7 * rr_win_boost)
            rk = min(risk_max, base_risk_pct + step_risk * 0.5)
            notes.append(f"winrate {wr:.0%}")

    # Objetivo explícito de % aciertos (WINRATE_TARGET): por debajo → TP más cercano (↓RR), SL algo más ancho.
    min_tr = int(os.environ.get("WINRATE_TARGET_MIN_TRADES", "10"))
    sens = float(os.environ.get("WINRATE_TARGET_SENS", "6.0"))
    if wt_goal > 0 and n >= min_tr:
        if wr + 1e-12 < wt_goal:
            gap = wt_goal - wr
            rr = max(rr_min, rr - step_rr * min(3.0, gap * sens))
            sl = min(sl_max, sl + step_sl * min(1.5, gap * sens * 0.18))
            rk = max(risk_min, rk - step_risk * min(1.0, gap * sens * 0.12))
            notes.append(f"aciertos {wr:.0%}→obj {wt_goal:.0%}")
        else:
            notes.append(f"aciertos {wr:.0%} ≥ obj {wt_goal:.0%}")

    note = "; ".join(notes) if notes else "margen base"
    sl = max(sl_min, min(sl_max, sl))
    rr = max(rr_min, min(rr_max, rr))
    rk = max(risk_min, min(risk_max, rk))
    return sl, rr, rk, note


def _safe_get(obj, name: str):
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _print_symbol_diag(symbol: str) -> None:
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    print(f"[DIAG] symbol={symbol}")
    if info is None:
        code, message = mt5.last_error()
        print(f"[DIAG] symbol_info=None last_error=({code}) {message}")
        return

    # Key fields that often explain "No prices"
    fields = [
        "visible",
        "select",
        "trade_mode",
        "trade_exemode",
        "currency_base",
        "currency_profit",
        "currency_margin",
        "spread",
        "digits",
        "volume_min",
        "volume_max",
        "volume_step",
        "trade_stops_level",
        "trade_freeze_level",
        "trade_tick_size",
        "trade_tick_value",
        "filling_mode",
        "expiration_mode",
    ]
    for f in fields:
        print(f"[DIAG] {f}={_safe_get(info, f)}")

    if tick is None:
        code, message = mt5.last_error()
        print(f"[DIAG] tick=None last_error=({code}) {message}")
    else:
        now = time.time()
        t = float(_safe_get(tick, "time") or 0.0)
        age = (now - t) if t else None
        print(f"[DIAG] tick_time_utc={_fmt_ts(t)} age_s={age}")
        print(f"[DIAG] bid={_safe_get(tick,'bid')} ask={_safe_get(tick,'ask')} last={_safe_get(tick,'last')}")

    # Market depth sometimes indicates whether quotes are usable
    try:
        if mt5.market_book_add(symbol):
            book = mt5.market_book_get(symbol) or []
            print(f"[DIAG] market_book_levels={len(book)}")
        else:
            code, message = mt5.last_error()
            print(f"[DIAG] market_book_add failed last_error=({code}) {message}")
    finally:
        try:
            mt5.market_book_release(symbol)
        except Exception:
            pass


def _fmt_ts(ts: int | float | None) -> str:
    if not ts:
        return "N/A"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _fail(msg: str, exit_code: int = 1) -> "None":
    print(msg, file=sys.stderr)
    raise SystemExit(exit_code)


def _round_down_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return (value // step) * step


def _fit_volume_to_free_margin(
    symbol: str,
    side_norm: str,
    price: float,
    volume: float,
    info: object,
    margin_ratio: float,
) -> float:
    """
    Baja el volumen hasta que order_calc_margin quepa en margen_libre * margin_ratio.
    """
    ot = mt5.ORDER_TYPE_BUY if side_norm == "buy" else mt5.ORDER_TYPE_SELL
    vol_min = float(getattr(info, "volume_min", 0.0) or 0.0)
    vol_step = float(getattr(info, "volume_step", 0.0) or 0.0)
    original = float(volume)
    v = float(volume)

    def margin_needed(vol: float) -> float | None:
        r = mt5.order_calc_margin(ot, symbol, float(vol), float(price))
        return float(r) if r is not None else None

    for _ in range(120):
        acct = mt5.account_info()
        if acct is None:
            _fail("account_info=None al ajustar margen.")
        free = float(getattr(acct, "margin_free", 0.0) or 0.0)
        if free <= 0:
            _fail("Sin margen libre en la cuenta.")
        cap = free * margin_ratio

        need = margin_needed(v)
        if need is None:
            return v

        if v <= vol_min + 1e-12:
            if need > cap:
                _fail(
                    f"Incluso el volumen mínimo ({vol_min}) requiere margen ~{need:.2f}; "
                    f"solo hay ~{cap:.2f} disponible (ratio={margin_ratio}). "
                    "Aumentá saldo en la cuenta o reducí RISK_PERCENT / SL."
                )
            return vol_min

        if need <= cap:
            if v + 1e-9 < original:
                print(
                    f"[TRADE] Volumen ajustado por margen: {original:.4f} -> {v:.4f} "
                    f"(margen_req={need:.2f} <= cap={cap:.2f} libre={free:.2f})"
                )
            return v

        factor = (cap / need) * 0.99
        if factor >= 0.999:
            factor = 0.5
        nv = v * factor
        if vol_step > 0:
            nv = _round_down_to_step(nv, vol_step)
        nv = max(vol_min, nv)
        if nv >= v:
            if vol_step > 0 and v > vol_min:
                nv = max(vol_min, _round_down_to_step(v - vol_step, vol_step))
            else:
                nv = vol_min
        v = nv

    _fail("No se pudo ajustar el volumen al margen libre tras varios intentos.")


def _normalize_symbol(s: str) -> str:
    # Keep only alnum characters for matching (e.g. "DJ30." -> "DJ30")
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _find_symbol_fallback(requested: str) -> str | None:
    """
    Try to find a close symbol name when the exact one isn't selectable.
    Prefers exact normalized match, then prefix match, then contains match.
    """
    norm_req = _normalize_symbol(requested)
    symbols = mt5.symbols_get()
    if not symbols:
        return None

    scored: list[tuple[int, str]] = []
    for s in symbols:
        name = getattr(s, "name", "")
        if not name:
            continue
        norm_name = _normalize_symbol(name)
        if norm_name == norm_req:
            score = 0
        elif norm_name.startswith(norm_req) or norm_req.startswith(norm_name):
            score = 1
        elif norm_req in norm_name or norm_name in norm_req:
            score = 2
        else:
            continue
        scored.append((score, name))

    if not scored:
        return None

    scored.sort(key=lambda x: (x[0], len(x[1])))
    return scored[0][1]


def _candidate_symbols(requested: str, limit: int = 10) -> list[str]:
    # Prefer MT5-side filtering via group patterns, and avoid pathological 1-2 char matches.
    raw = requested.upper()
    tokens = [_normalize_symbol(t) for t in "".join(ch if ch.isalnum() else " " for ch in raw).split()]
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        tokens = [_normalize_symbol(requested)]
    tokens = [t for t in tokens if len(t) >= 3]

    seen: set[str] = set()
    out: list[str] = []

    # Query symbols_get with group masks like "*XAUUSD*"
    for tok in tokens:
        group = f"*{tok}*"
        syms = mt5.symbols_get(group=group) or []
        for s in syms:
            name = getattr(s, "name", "")
            if not name or len(name) < 3 or name in seen:
                continue
            seen.add(name)
            out.append(name)
            if len(out) >= limit:
                return out

    # Fallback: scan all symbols but require meaningful normalized overlap
    norm_req = _normalize_symbol(requested)
    all_syms = mt5.symbols_get() or []
    for s in all_syms:
        name = getattr(s, "name", "")
        if not name or len(name) < 3 or name in seen:
            continue
        n = _normalize_symbol(name)
        if len(n) < 3:
            continue
        if n == norm_req or n.startswith(norm_req) or norm_req.startswith(n) or (len(norm_req) >= 4 and norm_req in n):
            seen.add(name)
            out.append(name)
            if len(out) >= limit:
                break

    return out


def _first_working_tick(symbols: list[str]) -> tuple[str, object] | None:
    for name in symbols:
        tick = mt5.symbol_info_tick(name)
        if tick is not None:
            return name, tick
    return None


def _print_group_hint(requested: str) -> None:
    raw = requested.upper()
    tokens = [_normalize_symbol(t) for t in "".join(ch if ch.isalnum() else " " for ch in raw).split()]
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        return
    # Print a small sample of symbols the terminal knows about for these tokens.
    for tok in tokens[:2]:
        group = f"*{tok}*"
        syms = mt5.symbols_get(group=group) or []
        names = [getattr(s, "name", "") for s in syms if getattr(s, "name", "")][:30]
        if names:
            print(f"[{requested}] Símbolos en Market Watch que matchean {group}: {', '.join(names)}")


def _resolve_trade_symbol(requested: str) -> str:
    """
    Resolve requested symbol to a terminal-known symbol that returns ticks.
    """
    direct = mt5.symbol_info_tick(requested)
    if direct is not None:
        return requested

    candidates = [requested]
    fallback = _find_symbol_fallback(requested)
    if fallback and fallback not in candidates:
        candidates.append(fallback)
    candidates.extend([c for c in _candidate_symbols(requested, limit=30) if c not in candidates])

    working = _first_working_tick(candidates)
    if working is None:
        code, message = mt5.last_error()
        _print_group_hint(requested)
        _fail(f"No se pudo resolver un símbolo operable para '{requested}'. last_error=({code}) {message}")
    return working[0]


def _place_market_trade_with_risk(
    symbol: str,
    side: str,
    risk_percent: float = 0.05,
    win_percent: float = 10.0,
    sl_price_percent: float = 1.0,
    deviation: int = 20,
    max_retries: int = 20,
    retry_sleep_s: float = 0.5,
    *,
    rr_override: float | None = None,
) -> None:
    """
    Abre una orden de mercado calculando volumen para arriesgar risk_percent del equity.

    - risk_percent: % de equity a arriesgar si toca SL
    - win_percent: objetivo de ganancia aproximado como % del equity (se traduce a un TP en precio)
    - sl_price_percent: distancia del SL como % del precio actual (sirve para calcular volumen)
    """
    side_norm = side.strip().lower()
    if side_norm not in ("buy", "sell"):
        _fail("SIDE inválido. Usa SIDE=buy o SIDE=sell.")

    info = mt5.symbol_info(symbol)
    if info is None:
        code, message = mt5.last_error()
        _fail(f"No se pudo leer symbol_info({symbol}). last_error=({code}) {message}")

    # Basic trading availability checks (best-effort; fields vary by broker)
    trade_mode = getattr(info, "trade_mode", None)
    if trade_mode is not None and int(trade_mode) == mt5.SYMBOL_TRADE_MODE_DISABLED:
        _fail(f"{symbol}: trading deshabilitado para este símbolo (trade_mode=DISABLED).")

    # Asegurar símbolo visible (puede fallar en algunos terminales; lo intentamos igual)
    mt5.symbol_select(symbol, True)

    account = mt5.account_info()
    if account is None:
        code, message = mt5.last_error()
        _fail(f"No se pudo leer account_info(). last_error=({code}) {message}")

    equity = float(getattr(account, "equity", 0.0) or 0.0)
    if equity <= 0:
        _fail(f"Equity inválido ({equity}).")

    # We'll refresh ticks right before sending; use a placeholder price for sizing.
    tick0 = mt5.symbol_info_tick(symbol)
    if tick0 is None:
        code, message = mt5.last_error()
        _fail(f"No hay tick para {symbol}. last_error=({code}) {message}")

    price0 = float(tick0.ask if side_norm == "buy" else tick0.bid)
    if price0 <= 0:
        _fail(f"Precio inválido ({price0}).")

    sl_dist = price0 * (sl_price_percent / 100.0)
    if sl_dist <= 0:
        _fail("SL distance inválida.")

    # SL must be on the loss side:
    # - BUY: SL below entry
    # - SELL: SL above entry
    sl = price0 - sl_dist if side_norm == "buy" else price0 + sl_dist

    # Convert win_percent equity target into an approximate price move:
    # profit_money_per_lot = (tp_dist / tick_size) * tick_value
    # => tp_dist = profit_money_target * tick_size / tick_value / volume
    # But volume depends on SL; compute volume first from SL risk.

    tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
    tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
    if tick_size <= 0 or tick_value <= 0:
        _fail(
            f"{symbol}: trade_tick_size/value inválidos (tick_size={tick_size}, tick_value={tick_value}). "
            "No puedo calcular volumen por riesgo."
        )

    risk_money = equity * (risk_percent / 100.0)
    loss_per_lot = (abs(sl_dist) / tick_size) * tick_value
    if loss_per_lot <= 0:
        _fail("No se pudo calcular pérdida por lote.")

    raw_volume = risk_money / loss_per_lot

    vol_min = float(getattr(info, "volume_min", 0.0) or 0.0)
    vol_max = float(getattr(info, "volume_max", 0.0) or 0.0)
    vol_step = float(getattr(info, "volume_step", 0.0) or 0.0)

    volume = raw_volume
    if vol_step > 0:
        volume = _round_down_to_step(volume, vol_step)
    if vol_min > 0:
        volume = max(volume, vol_min)
    if vol_max > 0:
        volume = min(volume, vol_max)

    auto_margin = os.environ.get("AUTO_MARGIN_CAP", "1").strip().lower() not in ("0", "false", "no")
    if auto_margin:
        margin_ratio = float(os.environ.get("MARGIN_USE_RATIO", "0.92"))
        volume = _fit_volume_to_free_margin(symbol, side_norm, price0, volume, info, margin_ratio)

    if volume <= 0:
        _fail(f"Volumen calculado inválido ({volume}).")

    win_money = equity * (win_percent / 100.0)
    # TP distance:
    # - If WIN_PERCENT > 0: approximate equity-target TP (legacy behavior)
    # - Else: use RR multiple of SL distance (preferred for consistent R-multiples)
    if win_percent > 0:
        tp_dist = (win_money * tick_size) / (tick_value * volume)
    else:
        rr_eff = float(rr_override) if rr_override is not None else float(os.environ.get("RR", "2.5"))
        tp_dist = abs(sl_dist) * rr_eff

    # TP must be on the profit side:
    # - BUY: TP above entry
    # - SELL: TP below entry
    tp = price0 + tp_dist if side_norm == "buy" else price0 - tp_dist

    order_type = mt5.ORDER_TYPE_BUY if side_norm == "buy" else mt5.ORDER_TYPE_SELL

    # Try multiple filling modes and retry on transient "No prices".
    # Filter filling modes by symbol capabilities (RETURN often unsupported)
    fm_all = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    filling_mask = int(getattr(info, "filling_mode", 0) or 0)
    filling_modes = [fm for fm in fm_all if filling_mask & (1 << fm)]
    if not filling_modes:
        filling_modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]
    last_result = None
    for attempt in range(1, max_retries + 1):
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            code, message = mt5.last_error()
            print(f"[TRADE] attempt={attempt} tick=None last_error=({code}) {message}")
            time.sleep(retry_sleep_s)
            continue

        # Avoid sending when quotes are stale (typical cause of "No prices")
        now = time.time()
        tick_time = float(getattr(tick, "time", 0.0) or 0.0)
        if tick_time and (now - tick_time) > 15:
            print(f"[TRADE] attempt={attempt} stale tick age_s={now - tick_time:.1f} (market closed/no quotes?)")
            time.sleep(retry_sleep_s)
            continue

        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        price = float(ask if side_norm == "buy" else bid)
        if price <= 0 or bid <= 0 or ask <= 0:
            print(f"[TRADE] attempt={attempt} invalid bid/ask bid={bid} ask={ask}")
            time.sleep(retry_sleep_s)
            continue

        # Recompute SL/TP around the fresh price
        sl = price - sl_dist if side_norm == "buy" else price + sl_dist
        tp = price + tp_dist if side_norm == "buy" else price - tp_dist

        print(
            f"[TRADE] attempt={attempt} {symbol} side={side_norm} equity={equity:.2f} risk_money={risk_money:.2f} "
            f"bid={bid} ask={ask} price={price} sl={sl} tp={tp} volume={volume} deviation={deviation}"
        )

        for fm in filling_modes:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume),
                "type": order_type,
                "price": float(price),
                "sl": float(sl),
                "tp": float(tp),
                "deviation": int(deviation),
                "magic": BOT_MAGIC,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": int(fm),
            }

            # Margin sanity check (avoid absurd volumes)
            try:
                margin_req = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY if side_norm == "buy" else mt5.ORDER_TYPE_SELL, symbol, float(volume), float(price))
                free_margin = float(getattr(mt5.account_info(), "margin_free", 0.0) or 0.0)
                if margin_req is not None and free_margin > 0 and float(margin_req) > free_margin:
                    print(
                        f"[TRADE] Insufficient margin tras tick: need={margin_req} free={free_margin} volume={volume}. "
                        "Probá bajar MARGIN_USE_RATIO o desactivar AUTO_MARGIN_CAP solo para diagnosticar."
                    )
                    _fail("Margen insuficiente para el volumen actual en este precio.")
            except Exception:
                pass

            # Pre-check helps diagnose "No prices"/restrictions without sending
            try:
                check = mt5.order_check(request)
                if check is not None:
                    print(f"[TRADE] check filling={fm} -> {check}")
            except Exception as e:
                print(f"[TRADE] order_check error: {e}")

            result = mt5.order_send(request)
            last_result = result
            if result is None:
                code, message = mt5.last_error()
                print(f"[TRADE] filling={fm} result=None last_error=({code}) {message}")
                # If the broker complains about args, don't spam retries.
                if code in (-2, -3):
                    _fail(f"order_send rechazado por argumentos. last_error=({code}) {message}")
                continue

            retcode = int(getattr(result, "retcode", -999999))
            comment = str(getattr(result, "comment", ""))
            print(f"[TRADE] filling={fm} retcode={retcode} comment={comment} result={result}")

            # 10009 / 10008 are common success codes (done / placed). Keep broad: deal or order non-zero.
            if getattr(result, "deal", 0) or getattr(result, "order", 0):
                return

            # Transient: no prices -> retry outer loop after sleep
            if "No prices" in comment or retcode in (10021,):
                continue

        time.sleep(retry_sleep_s)

    _fail(f"No se pudo ejecutar la orden tras {max_retries} reintentos. last_result={last_result}")


def _sma(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def _log_csv(line: str) -> None:
    new = not os.path.exists(BOT_CSV)
    with open(BOT_CSV, "a", encoding="utf-8") as f:
        if new:
            f.write("time_utc,symbol,bid,ask,fast_sma,slow_sma,signal,trade_result\n")
        f.write(line + "\n")


def _telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def _telegram_signal_style() -> str:
    """plain | vip | rich — por defecto vip (resumido); rich = análisis extendido."""
    return os.environ.get("TELEGRAM_STYLE", "vip").strip().lower()


def _telegram_tf_label_human(tf: str) -> str:
    t = (tf or "").strip().upper()
    if t == "M5":
        return "5 minutos (M5)"
    if t == "M15":
        return "15 minutos (M15)"
    if t == "M30":
        return "30 minutos (M30)"
    if t == "H1":
        return "1 hora (H1)"
    return tf or "—"


def _telegram_signal_message_vip(
    symbol: str,
    signal: str,
    bid: float,
    ask: float,
    tf_entry: str,
    tf_trend: str,
    *,
    atr_val: float | None = None,
    atr_period: int = 14,
    m5_secs_left: int | None = None,
) -> str:
    """Alerta estilo canal: compacta por defecto (TELEGRAM_VIP_COMPACT), marco M5 explícito."""
    spread = ask - bid if ask >= bid else 0.0
    lab = os.environ.get("TELEGRAM_TZ_LABEL", "").strip()
    huso = f"📊 Huso: ({lab})" if lab else "📊 Huso: (UTC)"
    compact = os.environ.get("TELEGRAM_VIP_COMPACT", "1").strip().lower() not in ("0", "false", "no")
    show_atr = os.environ.get("TELEGRAM_VIP_SHOW_ATR", "0").strip().lower() in ("1", "true", "yes")

    if signal == "BUY":
        dline = f"• {symbol} — COMPRA 🟢"
    elif signal == "SELL":
        dline = f"• {symbol} — VENTA 🔴"
    else:
        dline = f"• {symbol} — HOLD ⚪"

    now_utc = datetime.now(timezone.utc)
    op = now_utc.strftime("%H:%M:%S")

    if compact:
        lines = [
            "🚥 SEÑAL 🚥",
            huso,
            "",
            dline,
            f"• {tf_entry} entrada · filtro {tf_trend} · {op} UTC · {bid:.2f}/{ask:.2f} · sp {spread:.2f}",
        ]
        if m5_secs_left is not None and m5_secs_left >= 0:
            ml, s5 = m5_secs_left // 60, m5_secs_left % 60
            lines.append(f"• Próx. cierre vela M5 ~ {ml}m {s5}s")
        if show_atr and atr_val is not None:
            lines.append(f"• ATR({atr_period}) ≈ {atr_val:.2f}")
    else:
        marco = _telegram_tf_label_human(tf_entry)
        lines = [
            "🚥 SEÑAL 🚥",
            huso,
            "",
            dline,
            f"• Operación (alerta): {op} UTC",
            f"• Marco: {marco} · Filtro {tf_trend}",
        ]
        if m5_secs_left is not None and m5_secs_left >= 0:
            ml, s5 = m5_secs_left // 60, m5_secs_left % 60
            lines.append(f"• Cierra vela {tf_entry} ~ en {ml}m {s5}s")
        lines.append(f"• Precio: {bid:.2f} / {ask:.2f} · spread {spread:.2f}")
        if atr_val is not None:
            lines.append(f"• ATR({atr_period}) ≈ {atr_val:.2f}")

    if os.environ.get("SIGNALS_ONLY", "").strip().lower() in ("1", "true", "yes"):
        lines.append("")
        lines.append("Solo alertas (sin órdenes auto).")

    return "\n".join(lines)


def _telegram_operation_guidance(
    signal: str,
    tf_entry: str,
    tf_trend: str,
    trend_detail: str | None,
) -> str:
    """Responde en claro: qué operación (BUY/SELL/HOLD) y en qué momento actúa la alerta."""
    td = (trend_detail or "").strip()
    td_suffix = f" {td}" if td else ""

    if signal == "BUY":
        return (
            "🎯 QUÉ OPERAR: COMPRA (BUY)\n"
            f"⏱ MOMENTO: esta alerta — el sistema marcó COMPRA ahora: SMA rápida > lenta en {tf_entry} "
            f"y el filtro en {tf_trend} permite compras.{td_suffix}\n"
            "• Entrada manual: abrís BUY en tu plataforma con el precio actual (bid/ask más abajo).\n"
        )
    if signal == "SELL":
        return (
            "🎯 QUÉ OPERAR: VENTA (SELL)\n"
            f"⏱ MOMENTO: esta alerta — el sistema marcó VENTA ahora: SMA rápida < lenta en {tf_entry} "
            f"y el filtro en {tf_trend} permite ventas.{td_suffix}\n"
            "• Entrada manual: abrís SELL en tu plataforma con el precio actual.\n"
        )
    return (
        "🎯 QUÉ OPERAR: NO ENTRAR (HOLD)\n"
        f"⏱ MOMENTO: ahora no hay entrada BUY/SELL según esta estrategia "
        f"(cruce en {tf_entry} o filtro en {tf_trend}).{td_suffix}\n"
        "• Esperá una nueva alerta cuando salga BUY o SELL; no forzar dirección.\n"
    )


def _telegram_signal_message_text(
    symbol: str,
    signal: str,
    bid: float,
    ask: float,
    fast_sma: float,
    slow_sma: float,
    tf_entry: str,
    tf_trend: str,
    extra_footer: str | None = None,
    *,
    atr_val: float | None = None,
    atr_period: int = 14,
    sl_atr_mult: float = 1.5,
    rr: float = 2.5,
    trend_detail: str | None = None,
    m5_secs_left: int | None = None,
) -> str:
    """Construye el cuerpo del mensaje (plain, vip o rich)."""
    spread = ask - bid if ask >= bid else 0.0
    style = _telegram_signal_style()
    if style in ("vip", "short", "channel", "resumen"):
        msg = _telegram_signal_message_vip(
            symbol,
            signal,
            bid,
            ask,
            tf_entry,
            tf_trend,
            atr_val=atr_val,
            atr_period=atr_period,
            m5_secs_left=m5_secs_left,
        )
        if extra_footer and os.environ.get("TELEGRAM_VIP_EXTRA", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            msg += f"\n\n{extra_footer}"
        return msg

    guidance = _telegram_operation_guidance(signal, tf_entry, tf_trend, trend_detail)
    if style in ("plain", "compact", "0", "false"):
        msg = (
            f"{symbol}\n"
            f"{guidance}"
            f"---\n"
            f"Señal cruda: {signal}\n"
            f"Precio bid/ask: {bid:.2f} / {ask:.2f} (spread {spread:.2f})\n"
            f"SMA rápida/lenta ({tf_entry}): {fast_sma:.5f} / {slow_sma:.5f}\n"
            f"Filtro tendencia: {tf_trend}\n"
            f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        if os.environ.get("SIGNALS_ONLY", "").strip().lower() in ("1", "true", "yes"):
            msg += "\n\nModo: solo alerta (el bot no abre órdenes)."
        if extra_footer:
            msg += f"\n\n{extra_footer}"
        return msg

    # rich / osiris / detallado (texto plano con secciones; sin Markdown para evitar símbolos raros)
    sig_emoji = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "⚪"
    header = f"✅ {symbol} {sig_emoji} ✅\n"
    td = trend_detail or f"Marco referencia: {tf_trend} (filtro del bot)."
    body = (
        f"{guidance}\n"
        f"\n📌 Lectura operativa (instantáneo)\n"
        f"• Dirección sistema: {signal}\n"
        f"• Bid → Ask: {bid:.2f} → {ask:.2f} | Spread: {spread:.2f}\n"
        f"• SMA rápida / lenta ({tf_entry}): {fast_sma:.5f} / {slow_sma:.5f}\n"
        f"• Filtro / contexto ({tf_trend}): {td}\n"
    )

    deep_block = ""
    deep_on = False
    try:
        from signal_analysis import (
            analyze_market_pack,
            deep_analysis_enabled,
            telegram_confidence_threshold,
            telegram_should_send_signal,
        )

        deep_on = deep_analysis_enabled()
        if deep_on:
            pack = analyze_market_pack(symbol, signal, bid, ask, atr_val, atr_period, sl_atr_mult, rr)
            thr = telegram_confidence_threshold()
            if telegram_should_send_signal(pack.confidence, pack.passes_rsi_filter):
                deep_block = pack.text_block
            else:
                rsi_txt = f"{pack.rsi_m5:.1f}" if pack.rsi_m5 is not None else "N/D"
                reason = (
                    "RSI_FILTER no alinea con la dirección."
                    if not pack.passes_rsi_filter
                    else f"confianza ~{pack.confidence}% < umbral {thr:.0f}%."
                )
                deep_block = (
                    f"\n🔕 Señal filtrada (modo precisión)\n• {reason}\n"
                    f"• Confianza ~{pack.confidence}% | RSI M5 ≈ {rsi_txt}\n"
                    "• Revisá CSV para seguimiento completo o bajá SIGNAL_MIN_CONFIDENCE / RSI_FILTER.\n"
                )
    except Exception as e:
        deep_block = f"\n(Análisis extendido no disponible: {e})"

    mid = (bid + ask) / 2.0
    compact_vol = ""
    if not deep_on:
        if atr_val is not None and mid > 0:
            sd = float(atr_val * sl_atr_mult)
            pct = (sd / mid) * 100.0
            compact_vol = (
                f"\n📈 Referencia rápida\n"
                f"• ATR({atr_period}) M5 ≈ {atr_val:.5f} | SL típico ATR×{sl_atr_mult} ≈ {sd:.5f} (~{pct:.3f}% precio) | RR {rr}\n"
            )
        else:
            compact_vol = "\n📈 Referencia rápida\n• ATR M5 no disponible en este instante.\n"

    body += compact_vol + deep_block

    if os.environ.get("SIGNALS_ONLY", "").strip().lower() in ("1", "true", "yes"):
        body += "\n• Modo solo señales: el script no envía órdenes.\n"
    if extra_footer:
        body += f"\n📝 Detalle extra\n{extra_footer}\n"
    body += f"\n🕐 UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
    return header + body


def _telegram_notify_signal(
    symbol: str,
    signal: str,
    bid: float,
    ask: float,
    fast_sma: float,
    slow_sma: float,
    tf_entry: str,
    tf_trend: str,
    extra_footer: str | None = None,
    *,
    atr_val: float | None = None,
    atr_period: int = 14,
    sl_atr_mult: float = 1.5,
    rr: float = 2.5,
    trend_detail: str | None = None,
    m5_secs_left: int | None = None,
) -> bool:
    """Notifica cambio de señal (texto legible en Telegram)."""
    if not _telegram_configured():
        return False
    msg = _telegram_signal_message_text(
        symbol,
        signal,
        bid,
        ask,
        fast_sma,
        slow_sma,
        tf_entry,
        tf_trend,
        extra_footer,
        atr_val=atr_val,
        atr_period=atr_period,
        sl_atr_mult=sl_atr_mult,
        rr=rr,
        trend_detail=trend_detail,
        m5_secs_left=m5_secs_left,
    )
    return _telegram_send_telegram_message(msg)


def _telegram_send_telegram_message(msg: str) -> bool:
    """Envía texto; usa Markdown solo si TELEGRAM_PARSE_MODE=Markdown (por defecto texto plano)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params: dict[str, str] = {
        "chat_id": chat_id,
        "text": msg[:4090],
        "disable_web_page_preview": "true",
    }
    pm = os.environ.get("TELEGRAM_PARSE_MODE", "").strip()
    if pm:
        params["parse_mode"] = pm
    payload = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=float(os.environ.get("TELEGRAM_TIMEOUT_S", "15"))) as resp:
            raw = resp.read()
            if resp.status != 200:
                print(f"[TG] HTTP {resp.status}: {raw[:200]!r}")
                return False
            body = json.loads(raw.decode("utf-8"))
            if not body.get("ok"):
                print(f"[TG] API ok=false: {body!r}")
                return False
            return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"[TG] HTTPError {e.code}: {err_body[:400]}")
        return False
    except Exception as e:
        print(f"[TG] error enviando: {e}")
        return False


def _telegram_send(text: str) -> bool:
    """Alias: mismo envío que _telegram_send_telegram_message (mensajes simples / arranque)."""
    return _telegram_send_telegram_message(text)


def _telegram_notify_trade_line(symbol: str, line: str) -> None:
    if not _telegram_configured():
        return
    if os.environ.get("TELEGRAM_TRADES", "1").strip().lower() in ("0", "false", "no"):
        return
    st = _telegram_signal_style()
    if st in ("plain", "compact", "0", "false"):
        text = f"{symbol}\n{line}"
    elif st in ("vip", "short", "channel", "resumen"):
        text = f"🚥 {symbol}\n📌 {line}"
    else:
        text = f"✅ {symbol} ✅\n\n📌 Ejecución\n• {line}"
    _telegram_send_telegram_message(text)


def _atr(rates: list[dict], period: int) -> float | None:
    if period <= 1 or len(rates) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(rates)):
        high = float(rates[i]["high"])
        low = float(rates[i]["low"])
        prev_close = float(rates[i - 1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    window = trs[-period:]
    return sum(window) / period


def _slope(values: list[float], lookback: int) -> float | None:
    if lookback <= 1 or len(values) < lookback:
        return None
    return float(values[-1] - values[-lookback])


@dataclass(frozen=True)
class StrategySnapshot:
    """Lectura instantánea: precio, SMA M5, filtro M15, señal (misma lógica que el bot)."""

    symbol: str
    bid: float
    ask: float
    signal: str
    fast_sma: float
    slow_sma: float
    atr_val: float | None
    atr_period: int
    sl_atr_mult: float
    rr: float
    trend_detail: str
    secs_left_m5: int
    trend_ok_buy: bool
    trend_ok_sell: bool


def fetch_strategy_snapshot(requested_symbol: str | None = None) -> StrategySnapshot:
    """
    Calcula la señal actual (SMA M5 + filtro M15). Requiere `mt5.initialize()` previo.
    Raises RuntimeError si faltan datos.
    """
    sym = _resolve_trade_symbol(requested_symbol or os.environ.get("TRADE_SYMBOL", "XAUUSD"))
    fast = int(os.environ.get("FAST_SMA", "20"))
    slow = int(os.environ.get("SLOW_SMA", "50"))
    atr_period = int(os.environ.get("ATR_PERIOD", "14"))
    sl_atr_mult = float(os.environ.get("SL_ATR_MULT", "1.5"))
    rr = float(os.environ.get("RR", "2.5"))

    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        raise RuntimeError(f"No hay precio para {sym}")
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)

    trend_tf = mt5.TIMEFRAME_M15
    entry_tf = mt5.TIMEFRAME_M5
    trend_rates = mt5_copy_rates_from_pos_cached(sym, trend_tf, 0, max(slow, fast) + 10)
    entry_rates = mt5_copy_rates_from_pos_cached(sym, entry_tf, 0, max(slow, fast) + 10)
    if trend_rates is None or entry_rates is None:
        raise RuntimeError("No se pudieron leer velas")
    if len(trend_rates) < slow + 5 or len(entry_rates) < slow + 5:
        raise RuntimeError("Historial M5/M15 insuficiente para las SMA")

    trend_closes = [float(r["close"]) for r in trend_rates]
    trend_fast = _sma(trend_closes, fast)
    trend_slow = _sma(trend_closes, slow)
    trend_slope = _slope(trend_closes, lookback=10) or 0.0

    closes = [float(r["close"]) for r in entry_rates]
    fast_sma = _sma(closes, fast)
    slow_sma = _sma(closes, slow)
    atr_val = _atr(list(entry_rates), atr_period)

    if fast_sma is None or slow_sma is None:
        raise RuntimeError("SMA M5 no disponibles")

    signal = "HOLD"
    if fast_sma > slow_sma:
        signal = "BUY"
    elif fast_sma < slow_sma:
        signal = "SELL"

    trend_ok_buy = trend_fast is not None and trend_slow is not None and (trend_fast >= trend_slow and trend_slope >= 0)
    trend_ok_sell = trend_fast is not None and trend_slow is not None and (trend_fast <= trend_slow and trend_slope <= 0)

    if trend_fast is None or trend_slow is None:
        signal = "HOLD"
    else:
        if signal == "BUY" and not trend_ok_buy:
            signal = "HOLD"
        if signal == "SELL" and not trend_ok_sell:
            signal = "HOLD"

    last_bar = entry_rates[-1]
    bar_open = int(last_bar["time"])
    secs_left = max(0, bar_open + 5 * 60 - int(time.time()))

    if trend_fast is None or trend_slow is None:
        trend_detail = "M15: datos insuficientes para el filtro."
    elif trend_fast >= trend_slow and trend_slope >= 0:
        trend_detail = "M15 alineado alcista para el filtro (SMA rápida ≥ lenta, pendiente ≥ 0)."
    elif trend_fast <= trend_slow and trend_slope <= 0:
        trend_detail = "M15 alineado bajista para el filtro (SMA rápida ≤ lenta, pendiente ≤ 0)."
    else:
        trend_detail = "M15 en transición; el filtro puede anular la señal cruda en M5."

    return StrategySnapshot(
        symbol=sym,
        bid=bid,
        ask=ask,
        signal=signal,
        fast_sma=float(fast_sma),
        slow_sma=float(slow_sma),
        atr_val=atr_val,
        atr_period=atr_period,
        sl_atr_mult=sl_atr_mult,
        rr=rr,
        trend_detail=trend_detail,
        secs_left_m5=secs_left,
        trend_ok_buy=trend_ok_buy,
        trend_ok_sell=trend_ok_sell,
    )


def _position_side_for_bot(symbol: str, magic: int = BOT_MAGIC) -> str | None:
    """Si hay posición abierta con nuestro magic, devuelve 'BUY' o 'SELL'."""
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return None
    for p in positions:
        if int(getattr(p, "magic", 0) or 0) != magic:
            continue
        t = int(getattr(p, "type", -1))
        if t == mt5.POSITION_TYPE_BUY:
            return "BUY"
        if t == mt5.POSITION_TYPE_SELL:
            return "SELL"
    return None


def _bot_position_tickets(symbol: str, magic: int = BOT_MAGIC) -> list[int]:
    tickets: list[int] = []
    for p in mt5.positions_get(symbol=symbol) or []:
        if int(getattr(p, "magic", 0) or 0) != magic:
            continue
        t = int(getattr(p, "ticket", 0) or 0)
        if t > 0:
            tickets.append(t)
    return tickets


def _allowed_filling_modes_symbol(symbol: str) -> list[int]:
    info = mt5.symbol_info(symbol)
    if info is None:
        return [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]
    mask = int(getattr(info, "filling_mode", 0) or 0)
    modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    allowed = [m for m in modes if mask & (1 << m)]
    return allowed if allowed else [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]


def spread_points_from_tick(symbol: str) -> int | None:
    """
    Spread bid–ask en puntos del símbolo (según MT5 `point`).
    No usar ask/bid de symbol_info: hay que leer symbol_info_tick.
    """
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return None
    point = float(getattr(info, "point", 0.0) or 0.0)
    if point <= 0:
        return None
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return int(round((ask - bid) / point))


def es_spread_valido(symbol: str, limite_points: int) -> bool:
    """
    Filtro de spread antes de operar. `limite_points` es la misma unidad que MAX_SPREAD_POINTS
    del bot (puntos MT5; no confundir con \"pip\" clásico en Forex).
    Si limite_points <= 0, no filtra.
    """
    if limite_points <= 0:
        return True
    sp = spread_points_from_tick(symbol)
    if sp is None:
        print(f"{symbol}: no se pudo calcular spread.", file=sys.stderr)
        return False
    if sp > limite_points:
        print(
            f"Operación cancelada: spread {sp} puntos > límite {limite_points}",
            file=sys.stderr,
        )
        return False
    return True


def _close_position_ticket(ticket: int, deviation: int) -> bool:
    """Cierra una posición por ticket (mercado). True si ya no existe o se cerró OK."""
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        return True
    p = pos[0]
    symbol = str(getattr(p, "symbol", ""))
    vol = float(getattr(p, "volume", 0.0) or 0.0)
    ptype = int(getattr(p, "type", -1))
    magic = int(getattr(p, "magic", 0) or 0)

    if vol <= 0 or not symbol:
        print(f"[CLOSE] ticket={ticket} inválido symbol={symbol} vol={vol}")
        return False

    info = mt5.symbol_info(symbol)
    if info is None:
        code, message = mt5.last_error()
        print(f"[CLOSE] symbol_info=None ticket={ticket} last_error=({code}) {message}")
        return False

    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        code, message = mt5.last_error()
        print(f"[CLOSE] sin tick {symbol} ticket={ticket} last_error=({code}) {message}")
        return False

    if ptype == mt5.POSITION_TYPE_BUY:
        close_type = mt5.ORDER_TYPE_SELL
        price = float(getattr(tick, "bid", 0.0) or 0.0)
    elif ptype == mt5.POSITION_TYPE_SELL:
        close_type = mt5.ORDER_TYPE_BUY
        price = float(getattr(tick, "ask", 0.0) or 0.0)
    else:
        return False

    if price <= 0:
        return False

    comment = (os.environ.get("CLOSE_COMMENT") or "BOT_REV")[:31]
    filling_modes = _allowed_filling_modes_symbol(symbol)

    for fm in filling_modes:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": vol,
            "type": close_type,
            "position": int(ticket),
            "price": price,
            "deviation": int(deviation),
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": int(fm),
        }
        result = mt5.order_send(request)
        if result is None:
            continue
        retcode = int(getattr(result, "retcode", -999999))
        cmt = str(getattr(result, "comment", ""))
        if getattr(result, "deal", 0) or retcode in (10009, 10008):
            print(f"[CLOSE] OK ticket={ticket} symbol={symbol} vol={vol} retcode={retcode}")
            return True
        if "No prices" in cmt:
            time.sleep(0.3)
            continue

    print(f"[CLOSE] Falló ticket={ticket} symbol={symbol}")
    return False


def _close_all_bot_positions(symbol: str, deviation: int) -> bool:
    """
    Cierra todas las posiciones del bot en `symbol`. True si quedó flat (para ese magic).
    """
    for _ in range(32):
        tickets = _bot_position_tickets(symbol)
        if not tickets:
            return True
        if not _close_position_ticket(tickets[0], deviation):
            return False
        time.sleep(0.15)
    return _position_side_for_bot(symbol) is None


def run_demo_bot(symbol: str) -> None:
    """
    Demo bot: entrada en velas M5 + filtro tendencia M15.

    - M5_BAR_GATE=1 (default): solo evalúa señal / Telegram / órdenes al avanzar una vela M5 (~cada 5 min).
    - TELEGRAM_STYLE=vip (default): alertas cortas; TELEGRAM_VIP_COMPACT=1 resume en pocas líneas.
    - SIGNALS_ONLY=1: solo CSV + Telegram (sin órdenes automáticas).
    - PROFIT_MAX=1: perfil para TP más lejos (RR alto), adaptativo activado y más margen libre para volumen.
      Solo aplica valores que no hayas fijado ya en el entorno (setdefault).
    """
    if os.environ.get("PROFIT_MAX", "").strip().lower() in ("1", "true", "yes"):
        # Objetivo: mayor distancia TP vs SL (mismo riesgo % por trade → mayor payoff si acierta).
        os.environ.setdefault("RR", "3.5")
        os.environ.setdefault("ADAPTIVE_SLTP", "1")
        os.environ.setdefault("ADAPT_RR_MIN", "2.0")
        os.environ.setdefault("ADAPT_RR_MAX", "6.0")
        os.environ.setdefault("ADAPT_SL_MAX", "3.2")
        os.environ.setdefault("ADAPT_RISK_MAX", "0.14")
        os.environ.setdefault("ADAPT_STEP_RR", "0.28")
        os.environ.setdefault("ADAPT_WINRATE_HIGH", "0.52")
        os.environ.setdefault("MARGIN_USE_RATIO", "0.96")
        os.environ.setdefault("AUTO_MARGIN_CAP", "1")

    # Objetivo de % aciertos: permite suelo de RR más bajo (TP más cercano) aunque PROFIT_MAX suba RR_MAX.
    if _env_winrate_target() > 0:
        os.environ.setdefault("ADAPTIVE_SLTP", "1")
        raw_cap = os.environ.get("WINRATE_ADAPT_RR_MIN_CAP", "1.18").strip()
        if raw_cap:
            try:
                cap_v = float(raw_cap.replace(",", "."))
                prev = float(os.environ.get("ADAPT_RR_MIN", str(cap_v)))
                os.environ["ADAPT_RR_MIN"] = str(min(prev, cap_v))
            except ValueError:
                pass

    # Safety: only run on demo-like servers
    account = mt5.account_info()
    server = str(getattr(account, "server", "") or "")
    if "DEMO" not in server.upper():
        _fail(f"RUN_BOT bloqueado: server='{server}' no parece DEMO.")

    # Strategy + controls
    fast = int(os.environ.get("FAST_SMA", "20"))
    slow = int(os.environ.get("SLOW_SMA", "50"))
    trend_tf = mt5.TIMEFRAME_M15
    entry_tf = mt5.TIMEFRAME_M5
    atr_period = int(os.environ.get("ATR_PERIOD", "14"))
    sl_atr_mult = float(os.environ.get("SL_ATR_MULT", "1.5"))
    rr = float(os.environ.get("RR", "2.5"))  # TP = RR * SL distance
    poll_s = float(os.environ.get("POLL_S", "30"))
    max_trades = int(os.environ.get("MAX_TRADES", "3"))
    # MAX_TRADES < 0 => sin tope de operaciones (solo límites de riesgo/beneficio o Ctrl+C).
    # MAX_TRADES == 0 => no entra al bucle (smoke test sin órdenes).
    unlimited_trades = max_trades < 0
    signals_only = os.environ.get("SIGNALS_ONLY", "").strip().lower() in ("1", "true", "yes")
    if signals_only and max_trades <= 0:
        unlimited_trades = True  # streaming de señales continuo
    max_spread_points = int(os.environ.get("MAX_SPREAD_POINTS", "50"))

    # Performance targets are for the *period*, not per-trade.
    target_profit_percent = float(os.environ.get("TARGET_PROFIT_PERCENT", "15"))
    max_drawdown_percent = float(os.environ.get("MAX_DRAWDOWN_PERCENT", "5"))
    max_daily_loss_percent = float(os.environ.get("MAX_DAILY_LOSS_PERCENT", "3"))

    trades_done = 0
    last_signal: str | None = None
    telegram_last_sent: str | None = None
    last_m5_bar_open: int | None = None

    start_equity = float(getattr(account, "equity", 0.0) or 0.0)
    day_start_equity = start_equity
    day_key = datetime.now(timezone.utc).date().isoformat()

    m5_gate = os.environ.get("M5_BAR_GATE", "1").strip().lower() not in ("0", "false", "no")
    tg_style = os.environ.get("TELEGRAM_STYLE", "vip")
    max_trades_disp = "sin límite" if unlimited_trades else str(max_trades)
    profit_max_on = os.environ.get("PROFIT_MAX", "").strip().lower() in ("1", "true", "yes")
    print(
        f"[BOT] Running demo bot on {symbol} "
        f"trend_tf=M15 entry_tf=M5 fast={fast} slow={slow} atr={atr_period} sl_atr_mult={sl_atr_mult} rr={rr} "
        f"risk={os.environ.get('RISK_PERCENT','0.05')}% target_profit={target_profit_percent}% "
        f"max_dd={max_drawdown_percent}% max_daily_loss={max_daily_loss_percent}% "
        f"max_trades={max_trades_disp} poll_s={poll_s}s m5_bar_gate={'on' if m5_gate else 'off'} "
        f"telegram_style={tg_style} log_csv={BOT_CSV}"
        + (" | SIGNALS_ONLY (sin órdenes auto)" if signals_only else "")
        + (" | PROFIT_MAX (RR/ampliación TP + margen)" if profit_max_on else "")
    )
    if signals_only:
        print("[BOT] SIGNALS_ONLY=1 — solo alertas por Telegram + CSV; operá manualmente en MT5.")

    if _telegram_configured() and os.environ.get("TELEGRAM_STARTUP", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    ):
        start_msg = (
            "Bot en marcha\n"
            f"Símbolo: {symbol}\n"
            f"Log: {BOT_CSV}\n"
            f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        if signals_only:
            start_msg += "\nModo: solo señales (sin órdenes automáticas)."
        _telegram_send(start_msg)

    while unlimited_trades or trades_done < max_trades:
        # Reset daily equity baseline if day changed
        cur_day = datetime.now(timezone.utc).date().isoformat()
        if cur_day != day_key:
            day_key = cur_day
            acct = mt5.account_info()
            if acct is not None:
                day_start_equity = float(getattr(acct, "equity", day_start_equity) or day_start_equity)

        acct = mt5.account_info()
        if acct is None:
            time.sleep(poll_s)
            continue
        equity = float(getattr(acct, "equity", 0.0) or 0.0)
        if start_equity > 0:
            total_pnl_pct = (equity - start_equity) / start_equity * 100.0
            dd_pct = (equity - start_equity) / start_equity * 100.0
        else:
            total_pnl_pct = 0.0
            dd_pct = 0.0
        if day_start_equity > 0:
            daily_pnl_pct = (equity - day_start_equity) / day_start_equity * 100.0
        else:
            daily_pnl_pct = 0.0

        if total_pnl_pct >= target_profit_percent:
            print(f"[BOT] Target alcanzado: {total_pnl_pct:.2f}% >= {target_profit_percent:.2f}%. Parando.")
            return
        if dd_pct <= -max_drawdown_percent:
            _fail(f"[BOT] Max drawdown alcanzado: {dd_pct:.2f}% <= -{max_drawdown_percent:.2f}%. Parando.")
        if daily_pnl_pct <= -max_daily_loss_percent:
            _fail(f"[BOT] Max daily loss alcanzado: {daily_pnl_pct:.2f}% <= -{max_daily_loss_percent:.2f}%. Parando.")

        tick = mt5.symbol_info_tick(symbol)
        now = time.time()
        tick_time = float(getattr(tick, "time", 0.0) or 0.0) if tick else 0.0
        bid = float(getattr(tick, "bid", 0.0) or 0.0) if tick else 0.0
        ask = float(getattr(tick, "ask", 0.0) or 0.0) if tick else 0.0

        # If no fresh prices, just wait and keep logging.
        if not tick or bid <= 0 or ask <= 0 or (tick_time and (now - tick_time) > 30):
            _log_csv(f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},,,NO_PRICES,")
            time.sleep(poll_s)
            continue

        info = mt5.symbol_info(symbol)
        spread_pts = spread_points_from_tick(symbol)
        if spread_pts is None:
            spread_pts = int(getattr(info, "spread", 0) or 0) if info else 0
        if max_spread_points > 0 and spread_pts > max_spread_points:
            _log_csv(f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},,,SPREAD_HIGH,{spread_pts}")
            time.sleep(poll_s)
            continue

        # Trend filter on M15
        trend_rates = mt5_copy_rates_from_pos_cached(symbol, trend_tf, 0, max(slow, fast) + 10)
        if trend_rates is None or len(trend_rates) < slow + 5:
            _log_csv(f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},,,NO_TREND_RATES,")
            time.sleep(poll_s)
            continue
        trend_closes = [float(r["close"]) for r in trend_rates]
        trend_fast = _sma(trend_closes, fast)
        trend_slow = _sma(trend_closes, slow)
        trend_slope = _slope(trend_closes, lookback=10) or 0.0

        # Entry signals on M5
        entry_rates = mt5_copy_rates_from_pos_cached(symbol, entry_tf, 0, max(slow, fast) + 10)
        if entry_rates is None or len(entry_rates) < slow + 5:
            _log_csv(f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},,,NO_RATES,")
            time.sleep(poll_s)
            continue

        closes = [float(r["close"]) for r in entry_rates]
        fast_sma = _sma(closes, fast)
        slow_sma = _sma(closes, slow)
        atr_val = _atr(list(entry_rates), atr_period)
        if fast_sma is None or slow_sma is None:
            _log_csv(f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},,,NO_SMA,")
            time.sleep(poll_s)
            continue
        if atr_val is None or atr_val <= 0:
            _log_csv(f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},{fast_sma:.5f},{slow_sma:.5f},NO_ATR,")
            time.sleep(poll_s)
            continue

        bar_open = int(entry_rates[-1]["time"])
        m5_secs_left = max(0, bar_open + 5 * 60 - int(time.time()))

        if m5_gate:
            if last_m5_bar_open is not None and bar_open == last_m5_bar_open:
                time.sleep(poll_s)
                continue
            last_m5_bar_open = bar_open

        adapt_on = os.environ.get("ADAPTIVE_SLTP", "0").strip().lower() in ("1", "true", "yes")
        base_risk_pct = float(os.environ.get("RISK_PERCENT", "0.05"))
        pnls_hist: list[float] = []
        adapt_note = ""
        if adapt_on:
            pnls_hist = _recent_closed_position_pnls(
                symbol,
                BOT_MAGIC,
                days=int(os.environ.get("ADAPT_HISTORY_DAYS", "7")),
                max_positions=int(os.environ.get("ADAPT_MAX_POSITIONS", "40")),
            )
            dyn_sl, dyn_rr, dyn_risk, adapt_note = _adaptive_sl_rr_risk(
                sl_atr_mult, rr, base_risk_pct, pnls_hist
            )
            wr_disp = ""
            if pnls_hist:
                wr_v, _, _, _ = closed_trade_winrate_stats(pnls_hist)
                wr_disp = f" aciertos={wr_v:.1%}"
            print(
                f"[ADAPT] SL×ATR={dyn_sl:.3f} RR={dyn_rr:.3f} risk={dyn_risk:.4f}%{wr_disp} | "
                f"{adapt_note} | cerradas recientes={len(pnls_hist)}"
            )
        else:
            dyn_sl, dyn_rr, dyn_risk = sl_atr_mult, rr, base_risk_pct

        signal = "HOLD"
        if fast_sma > slow_sma:
            signal = "BUY"
        elif fast_sma < slow_sma:
            signal = "SELL"

        # Apply trend filter: only trade in direction of M15 trend
        if trend_fast is None or trend_slow is None:
            signal = "HOLD"
        else:
            if signal == "BUY" and not (trend_fast >= trend_slow and trend_slope >= 0):
                signal = "HOLD"
            if signal == "SELL" and not (trend_fast <= trend_slow and trend_slope <= 0):
                signal = "HOLD"

        _log_csv(
            f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},{fast_sma:.5f},{slow_sma:.5f},{signal},"
        )

        send_hold_tg = os.environ.get("TELEGRAM_SIGNAL_HOLD", "1").strip().lower() not in ("0", "false", "no")
        tg_extra = None
        if signals_only and atr_val is not None:
            mid_px = (bid + ask) / 2.0
            if mid_px > 0:
                sl_dist = float(atr_val * dyn_sl)
                tg_extra = (
                    f"Ref. manual (no es orden): SL ATR×{dyn_sl:.2f} ≈ {sl_dist:.2f} "
                    f"(~{(sl_dist / mid_px) * 100:.3f}% precio). RR={dyn_rr:.2f}. "
                    f"Riesgo ref {dyn_risk:.3f}% equity."
                )
        if trend_fast is None or trend_slow is None:
            trend_detail = "M15: datos insuficientes para el filtro."
        elif trend_fast >= trend_slow and trend_slope >= 0:
            trend_detail = "M15 alineado alcista para el filtro (SMA rápida ≥ lenta, pendiente ≥ 0)."
        elif trend_fast <= trend_slow and trend_slope <= 0:
            trend_detail = "M15 alineado bajista para el filtro (SMA rápida ≤ lenta, pendiente ≤ 0)."
        else:
            trend_detail = "M15 en transición; el filtro puede anular la señal cruda en M5."

        if telegram_last_sent != signal:
            if signal in ("BUY", "SELL") or send_hold_tg:
                if _telegram_notify_signal(
                    symbol,
                    signal,
                    bid,
                    ask,
                    fast_sma,
                    slow_sma,
                    "M5",
                    "M15",
                    extra_footer=tg_extra,
                    atr_val=atr_val,
                    atr_period=atr_period,
                    sl_atr_mult=dyn_sl,
                    rr=dyn_rr,
                    trend_detail=trend_detail,
                    m5_secs_left=m5_secs_left,
                ):
                    telegram_last_sent = signal
            else:
                telegram_last_sent = signal

        # Señal nueva: si hay posición contraria, cerrarla y abrir en la dirección de la señal (inversión).
        reverse_on = os.environ.get("BOT_REVERSE", "1").strip().lower() not in ("0", "false", "no")
        close_dev = int(os.environ.get("CLOSE_DEVIATION", os.environ.get("DEVIATION", "200")))

        if not signals_only and signal in ("BUY", "SELL") and signal != last_signal:
            pos_open = _position_side_for_bot(symbol)
            if pos_open is not None and pos_open != signal:
                if reverse_on:
                    print(f"[BOT] Inversión: cierre {pos_open} -> entrada {signal}")
                    if _close_all_bot_positions(symbol, close_dev):
                        _log_csv(
                            f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},{fast_sma:.5f},"
                            f"{slow_sma:.5f},{signal},CLOSED_FOR_REVERSAL"
                        )
                        _telegram_notify_trade_line(symbol, "Cierre previo OK (inversión de señal).")
                    else:
                        _log_csv(
                            f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},{fast_sma:.5f},"
                            f"{slow_sma:.5f},{signal},CLOSE_REVERSAL_FAILED"
                        )
                        _telegram_notify_trade_line(symbol, "Falló el cierre para invertir.")
                else:
                    _log_csv(
                        f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},{fast_sma:.5f},"
                        f"{slow_sma:.5f},{signal},REVERSAL_DISABLED"
                    )

            if _position_side_for_bot(symbol) is None:
                side = "buy" if signal == "BUY" else "sell"
                try:
                    mid = (bid + ask) / 2.0
                    sl_dist = float(atr_val * dyn_sl)
                    sl_px_percent = (sl_dist / mid) * 100.0 if mid > 0 else 1.0

                    _place_market_trade_with_risk(
                        symbol=symbol,
                        side=side,
                        risk_percent=float(dyn_risk),
                        win_percent=0.0,
                        sl_price_percent=sl_px_percent,
                        deviation=int(os.environ.get("DEVIATION", "200")),
                        max_retries=int(os.environ.get("MAX_RETRIES", "25")),
                        retry_sleep_s=float(os.environ.get("RETRY_SLEEP_S", "0.6")),
                        rr_override=float(dyn_rr),
                    )
                    trades_done += 1
                    _log_csv(
                        f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},{fast_sma:.5f},"
                        f"{slow_sma:.5f},{signal},SENT"
                    )
                    _telegram_notify_trade_line(symbol, f"Orden enviada ({signal}).")
                except SystemExit:
                    _log_csv(
                        f"{datetime.now(timezone.utc).isoformat()},{symbol},{bid},{ask},{fast_sma:.5f},"
                        f"{slow_sma:.5f},{signal},FAILED"
                    )
                    _telegram_notify_trade_line(symbol, f"Orden rechazada / error ({signal}).")

        pos_side = _position_side_for_bot(symbol) if not signals_only else None
        if pos_side is not None:
            last_signal = pos_side
        else:
            last_signal = signal
        time.sleep(poll_s)


def main() -> None:
    load_env_file()

    mt5_path = os.environ.get("MT5_PATH")
    initialized = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not initialized:
        code, message = mt5.last_error()
        msg = (
            "No se pudo inicializar MetaTrader 5.\n"
            "- Asegúrate de tener MetaTrader 5 abierto.\n"
            "- Asegúrate de estar logueado en tu cuenta dentro de MT5.\n"
        )
        if mt5_path:
            msg += f"- MT5_PATH={mt5_path}\n"
        msg += f"- last_error=({code}) {message}"
        _fail(msg)

    try:
        terminal_info = mt5.terminal_info()
        version = mt5.version()
        if terminal_info is None:
            code, message = mt5.last_error()
            _fail(
                "MT5 inicializó pero el terminal no está accesible (terminal_info=None).\n"
                f"- last_error=({code}) {message}\n"
                + (f"- MT5_PATH={mt5_path}\n" if mt5_path else "")
                + "Sugerencia: define MT5_PATH apuntando a terminal64.exe, por ejemplo:\n"
                + '  $env:MT5_PATH="C:\\Program Files\\MetaTrader 5\\terminal64.exe"'
            )

        account = mt5.account_info()
        print(
            "MT5 inicializado OK. "
            f"version={version} "
            f"terminal={getattr(terminal_info, 'name', 'N/A')} "
            f"trade_allowed={getattr(terminal_info, 'trade_allowed', 'N/A')} "
            f"account_login={getattr(account, 'login', 'N/A')} "
            f"server={getattr(account, 'server', 'N/A')}"
        )

        if os.environ.get("DIAG", "").strip() == "1":
            # Print diagnostics for the resolved tradable symbol
            resolved = _resolve_trade_symbol(os.environ.get("TRADE_SYMBOL", "XAUUSD"))
            _print_symbol_diag(resolved)

        # --- Price read ---
        last_active_symbol: str | None = None
        for symbol in SYMBOLS:
            # Prefer reading the tick directly; some terminals reject symbol_select even when ticks are available.
            direct_tick = mt5.symbol_info_tick(symbol)
            if direct_tick is not None:
                active_symbol = symbol
                tick = direct_tick
            else:
                candidates = [symbol]
                fallback = _find_symbol_fallback(symbol)
                if fallback and fallback not in candidates:
                    candidates.append(fallback)
                candidates.extend([c for c in _candidate_symbols(symbol, limit=10) if c not in candidates])

                working = _first_working_tick(candidates)
                if working is None:
                    code, message = mt5.last_error()
                    print(f"[{symbol}] No se pudo obtener tick para el símbolo ni candidatos. last_error=({code}) {message}")
                    if len(candidates) > 1:
                        print(f"[{symbol}] Candidatos detectados: {', '.join(candidates[:10])}")
                    _print_group_hint(symbol)
                    continue

                active_symbol, tick = working
                if active_symbol != symbol:
                    print(f"[{symbol}] Usando símbolo detectado: {active_symbol}")

            info = mt5.symbol_info(active_symbol)
            if info is None:
                code, message = mt5.last_error()
                print(f"[{symbol}] symbol_info() devolvió None (active={active_symbol}). last_error=({code}) {message}")
                continue

            # tick: time, bid, ask, last, volume, etc.
            print(
                f"[{symbol}] "
                f"active={active_symbol} "
                f"time_utc={_fmt_ts(getattr(tick, 'time', None))} "
                f"bid={getattr(tick, 'bid', None)} "
                f"ask={getattr(tick, 'ask', None)} "
                f"last={getattr(tick, 'last', None)} "
                f"spread={getattr(info, 'spread', None)} "
                f"digits={getattr(info, 'digits', None)}"
            )
            last_active_symbol = active_symbol

        # --- Optional trade ---
        if os.environ.get("PLACE_TRADE", "").strip() == "1":
            if not bool(getattr(terminal_info, "trade_allowed", False)):
                _fail("trade_allowed=False en el terminal. Activa AlgoTrading/AutoTrading en MT5 y vuelve a intentar.")

            requested = os.environ.get("TRADE_SYMBOL", "XAUUSD")
            side = os.environ.get("SIDE", "buy")
            risk = float(os.environ.get("RISK_PERCENT", "0.05"))
            win = float(os.environ.get("WIN_PERCENT", "10"))
            sl_px = float(os.environ.get("SL_PRICE_PERCENT", "1"))
            dev = int(os.environ.get("DEVIATION", "100"))
            retries = int(os.environ.get("MAX_RETRIES", "20"))
            sleep_s = float(os.environ.get("RETRY_SLEEP_S", "0.5"))

            trade_symbol = _resolve_trade_symbol(requested)
            if last_active_symbol and trade_symbol != last_active_symbol and requested in (
                "XAUUSD",
                "XAUUSD-ECN",
            ):
                # If we already resolved during price read, prefer that symbol
                trade_symbol = last_active_symbol

            _place_market_trade_with_risk(
                symbol=trade_symbol,
                side=side,
                risk_percent=risk,
                win_percent=win,
                sl_price_percent=sl_px,
                deviation=dev,
                max_retries=retries,
                retry_sleep_s=sleep_s,
            )

        # --- Optional demo bot ---
        if os.environ.get("RUN_BOT", "").strip() == "1":
            if not bool(getattr(terminal_info, "trade_allowed", False)):
                _fail("RUN_BOT: trade_allowed=False. Activa AlgoTrading/AutoTrading en MT5.")
            trade_symbol = _resolve_trade_symbol(os.environ.get("TRADE_SYMBOL", "XAUUSD"))
            run_demo_bot(trade_symbol)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
