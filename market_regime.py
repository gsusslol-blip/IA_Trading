"""
Detección de régimen de mercado (meta-capa antes de la señal operativa).

Capa 1 — Reglas (default): ADX (fuerza tendencial), percentil de ATR (estrés vol),
Z-score del precio vs SMA, y compresión de rango reciente.

Capa 2 — ML (opcional): RandomForest u otro clf sklearn guardado con pickle/joblib;
features alineados con `build_regime_feature_row`. Si falla carga o sklearn, se cae a reglas.

.env:
  IA_REGIME_ENABLE=0|1
  IA_REGIME_MODE=rules|ml|hybrid   (hybrid = ML si hay modelo, si no reglas)
  IA_REGIME_TIMEFRAME — default H1 (nombre: H1, H4, M15)
  IA_REGIME_ADX_PERIOD, IA_REGIME_ADX_TREND_MIN, IA_REGIME_ADX_RANGE_MAX
  IA_REGIME_ATR_PERIOD, IA_REGIME_ATR_CRISIS_PCTL
  IA_REGIME_Z_SMA_PERIOD — ventana SMA para Z-score
  IA_REGIME_RANGE_COMPRESS_PCT — si rango N velas / precio < esto → lateralidad fuerte
  IA_REGIME_BLOCK_HIGH_VOL=1 — no operar tendencia en crisis vol
  IA_REGIME_BLOCK_TREND_IN_RANGE=1 — no usar módulo tendencia si régimen = rango
  IA_REGIME_ML_MODEL_PATH — ruta a .pkl / .joblib (clasificador con classes_ ordenadas)
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

import MetaTrader5 as mt5

from mt5_prices import mt5_copy_rates_from_pos_cached

from signal_analysis import _atr_series, _true_ranges


class RegimeLabel(str, Enum):
    TREND = "trend"
    RANGE = "range"
    HIGH_VOL = "high_vol"
    UNKNOWN = "unknown"


@dataclass
class RegimeSnapshot:
    label: RegimeLabel
    adx: float | None
    atr_pct_rank: float | None
    z_score: float | None
    range_compression: float | None
    source: str  # "rules" | "ml" | "hybrid_fallback"
    detail: str


def _tf_from_env() -> int:
    raw = os.environ.get("IA_REGIME_TIMEFRAME", "H1").strip().upper()
    mapping = {
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    return mapping.get(raw, mt5.TIMEFRAME_H1)


def _wilder_rma(series: list[float], period: int) -> list[float]:
    """Media móvil Wilder (RMA): primer valor = media simple de los primeros `period`."""
    if len(series) < period or period < 1:
        return []
    out = [sum(series[:period]) / period]
    for i in range(period, len(series)):
        out.append((out[-1] * (period - 1) + series[i]) / period)
    return out


def _adx_last(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """ADX Wilder (último valor, típicamente 0–100)."""
    n = len(closes)
    if n < period * 3 or period < 2:
        return None
    trs: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        p_dm = up_move if up_move > down_move and up_move > 0 else 0.0
        m_dm = down_move if down_move > up_move and down_move > 0 else 0.0
        h, low, pc = highs[i], lows[i], closes[i - 1]
        tr = max(h - low, abs(h - pc), abs(low - pc))
        trs.append(tr)
        plus_dm.append(p_dm)
        minus_dm.append(m_dm)

    tr_r = _wilder_rma(trs, period)
    p_dm_r = _wilder_rma(plus_dm, period)
    m_dm_r = _wilder_rma(minus_dm, period)
    if not tr_r or len(tr_r) != len(p_dm_r) or len(tr_r) != len(m_dm_r):
        return None

    dx_vals: list[float] = []
    for i in range(len(tr_r)):
        atr_i = tr_r[i]
        if atr_i <= 1e-12:
            continue
        pdi = 100.0 * p_dm_r[i] / atr_i
        mdi = 100.0 * m_dm_r[i] / atr_i
        denom = pdi + mdi
        if denom <= 1e-12:
            continue
        dx = 100.0 * abs(pdi - mdi) / denom
        dx_vals.append(dx)

    if len(dx_vals) < period:
        return None
    adx_r = _wilder_rma(dx_vals, period)
    if not adx_r:
        return None
    return float(min(100.0, max(0.0, adx_r[-1])))


def _percentile_rank(value: float, sample: list[float]) -> float | None:
    if not sample:
        return None
    arr = sorted(sample)
    below = sum(1 for x in arr if x < value)
    return 100.0 * below / len(arr)


def _z_score_last(closes: list[float], sma_period: int) -> float | None:
    if len(closes) < sma_period + 2:
        return None
    window = closes[-sma_period:]
    mu = sum(window) / sma_period
    var = sum((x - mu) ** 2 for x in window) / max(1, sma_period - 1)
    sigma = math.sqrt(var) if var > 0 else None
    if sigma is None or sigma < 1e-12:
        return None
    last = closes[-1]
    return (last - mu) / sigma


def _range_compression(highs: list[float], lows: list[float], lookback: int) -> float | None:
    if len(highs) < lookback + 1 or len(lows) < lookback + 1:
        return None
    hh = max(highs[-lookback:])
    ll = min(lows[-lookback:])
    mid = (highs[-1] + lows[-1]) / 2.0
    if mid <= 0:
        return None
    return (hh - ll) / mid * 100.0


def fetch_rates(symbol: str, timeframe: int, count: int):
    r = mt5_copy_rates_from_pos_cached(symbol, timeframe, 0, count)
    if r is None or len(r) < count // 2:
        return None
    highs = [float(x["high"]) for x in r]
    lows = [float(x["low"]) for x in r]
    closes = [float(x["close"]) for x in r]
    return highs, lows, closes


def build_regime_feature_row(symbol: str) -> tuple[list[float] | None, str]:
    """
    Vector de features para ML (mismo orden que entrena el modelo offline).
    [adx, atr_pct_rank, z_score, range_compression_pct]
    """
    tf = _tf_from_env()
    try:
        nbar = int(os.environ.get("IA_REGIME_BARS", "200").strip() or "200")
    except ValueError:
        nbar = 200
    nbar = max(120, min(2000, nbar))
    pack = fetch_rates(symbol, tf, nbar)
    if pack is None:
        return None, "sin datos MT5"
    highs, lows, closes = pack
    try:
        p_adx = int(os.environ.get("IA_REGIME_ADX_PERIOD", "14").strip() or "14")
    except ValueError:
        p_adx = 14
    adx = _adx_last(highs, lows, closes, period=p_adx)

    try:
        p_atr = int(os.environ.get("IA_REGIME_ATR_PERIOD", "14").strip() or "14")
    except ValueError:
        p_atr = 14
    trs = _true_ranges(highs, lows, closes)
    atr_ser = _atr_series(trs, p_atr)
    atr_pct_rank = None
    if atr_ser and len(atr_ser) > 30:
        cur_atr = atr_ser[-1]
        ref = float(closes[-1]) if closes[-1] else 1.0
        cur_pct = (cur_atr / ref) * 100.0 if ref else None
        hist_pct = [(atr_ser[i] / closes[i + 1]) * 100.0 for i in range(len(atr_ser) - 1) if closes[i + 1]]
        if cur_pct is not None and hist_pct:
            atr_pct_rank = _percentile_rank(cur_pct, hist_pct)

    try:
        z_period = int(os.environ.get("IA_REGIME_Z_SMA_PERIOD", "20").strip() or "20")
    except ValueError:
        z_period = 20
    z = _z_score_last(closes, z_period)

    try:
        rl = int(os.environ.get("IA_REGIME_RANGE_LOOKBACK", "48").strip() or "48")
    except ValueError:
        rl = 48
    rc = _range_compression(highs, lows, rl)

    row = [
        float(adx if adx is not None else -1.0),
        float(atr_pct_rank if atr_pct_rank is not None else -1.0),
        float(z if z is not None else 0.0),
        float(rc if rc is not None else -1.0),
    ]
    return row, "ok"


def classify_regime_rules_from_hlc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> RegimeSnapshot:
    """
    Clasificación por reglas con OHLC ya recortados al instante t (backtest sin lookahead).
    """
    if len(closes) < 50:
        return RegimeSnapshot(
            RegimeLabel.UNKNOWN,
            None,
            None,
            None,
            None,
            "rules",
            "historia corta",
        )
    try:
        p_adx = int(os.environ.get("IA_REGIME_ADX_PERIOD", "14").strip() or "14")
    except ValueError:
        p_adx = 14
    adx = _adx_last(highs, lows, closes, period=p_adx)

    try:
        p_atr = int(os.environ.get("IA_REGIME_ATR_PERIOD", "14").strip() or "14")
    except ValueError:
        p_atr = 14
    trs = _true_ranges(highs, lows, closes)
    atr_ser = _atr_series(trs, p_atr)
    atr_pct_rank = None
    if atr_ser and len(atr_ser) > 30:
        cur_atr = atr_ser[-1]
        ref = float(closes[-1]) if closes[-1] else 1.0
        cur_pct = (cur_atr / ref) * 100.0 if ref else None
        hist_pct = [(atr_ser[i] / closes[i + 1]) * 100.0 for i in range(len(atr_ser) - 1) if closes[i + 1]]
        if cur_pct is not None and hist_pct:
            atr_pct_rank = _percentile_rank(cur_pct, hist_pct)

    try:
        z_period = int(os.environ.get("IA_REGIME_Z_SMA_PERIOD", "20").strip() or "20")
    except ValueError:
        z_period = 20
    z = _z_score_last(closes, z_period)

    try:
        rl = int(os.environ.get("IA_REGIME_RANGE_LOOKBACK", "48").strip() or "48")
    except ValueError:
        rl = 48
    rl_use = min(rl, max(10, len(closes) - 2))
    rc = _range_compression(highs, lows, rl_use)

    try:
        adx_trend = float(os.environ.get("IA_REGIME_ADX_TREND_MIN", "25").strip() or "25")
    except ValueError:
        adx_trend = 25.0
    try:
        adx_range = float(os.environ.get("IA_REGIME_ADX_RANGE_MAX", "22").strip() or "22")
    except ValueError:
        adx_range = 22.0
    try:
        crisis_pctl = float(os.environ.get("IA_REGIME_ATR_CRISIS_PCTL", "88").strip() or "88")
    except ValueError:
        crisis_pctl = 88.0
    try:
        compress_max = float(os.environ.get("IA_REGIME_RANGE_COMPRESS_PCT", "2.5").strip() or "2.5")
    except ValueError:
        compress_max = 2.5

    label = RegimeLabel.UNKNOWN
    detail_parts: list[str] = []

    if atr_pct_rank is not None and atr_pct_rank >= crisis_pctl:
        label = RegimeLabel.HIGH_VOL
        detail_parts.append(f"ATR_pctl>={crisis_pctl:.0f}")
    elif adx is not None and adx >= adx_trend:
        label = RegimeLabel.TREND
        detail_parts.append(f"ADX>={adx_trend:.0f}")
    elif adx is not None and adx <= adx_range:
        label = RegimeLabel.RANGE
        detail_parts.append(f"ADX<={adx_range:.0f}")
        if rc is not None and rc < compress_max:
            detail_parts.append("rango_comprimido")
    else:
        if adx is not None:
            detail_parts.append(f"ADX intermedio {adx:.1f}")
        label = RegimeLabel.TREND if (adx or 0) >= (adx_range + adx_trend) / 2 else RegimeLabel.RANGE

    return RegimeSnapshot(
        label,
        adx,
        atr_pct_rank,
        z,
        rc,
        "rules",
        "; ".join(detail_parts) if detail_parts else "heuristica",
    )


def classify_regime_rules(symbol: str) -> RegimeSnapshot:
    tf = _tf_from_env()
    try:
        nbar = int(os.environ.get("IA_REGIME_BARS", "200").strip() or "200")
    except ValueError:
        nbar = 200
    nbar = max(120, min(2000, nbar))
    pack = fetch_rates(symbol, tf, nbar)
    if pack is None:
        return RegimeSnapshot(
            RegimeLabel.UNKNOWN,
            None,
            None,
            None,
            None,
            "rules",
            "sin datos",
        )
    highs, lows, closes = pack
    return classify_regime_rules_from_hlc(highs, lows, closes)


def classify_regime_ml(symbol: str) -> RegimeSnapshot | None:
    path = os.environ.get("IA_REGIME_ML_MODEL_PATH", "").strip()
    if not path:
        return None
    import pathlib

    p = pathlib.Path(path)
    if not p.is_file():
        return None

    row, msg = build_regime_feature_row(symbol)
    if row is None:
        return None

    clf: Any = None
    try:
        import joblib

        clf = joblib.load(p)
    except Exception:
        try:
            import pickle

            with p.open("rb") as f:
                clf = pickle.load(f)
        except Exception:
            return None

    try:
        import numpy as np

        X = np.array([row], dtype=float)
    except Exception:
        X = [row]

    try:
        pred = clf.predict(X)[0]
    except Exception:
        return None

    label_map = {
        "trend": RegimeLabel.TREND,
        "range": RegimeLabel.RANGE,
        "high_vol": RegimeLabel.HIGH_VOL,
        "HIGH_VOL": RegimeLabel.HIGH_VOL,
        "TREND": RegimeLabel.TREND,
        "RANGE": RegimeLabel.RANGE,
        0: RegimeLabel.RANGE,
        1: RegimeLabel.TREND,
        2: RegimeLabel.HIGH_VOL,
    }
    lab = label_map.get(pred, RegimeLabel.UNKNOWN)
    return RegimeSnapshot(
        lab,
        row[0] if row[0] >= 0 else None,
        row[1] if row[1] >= 0 else None,
        row[2],
        row[3] if row[3] >= 0 else None,
        "ml",
        f"clase={pred!r}",
    )


def regime_trend_allowed(snap: RegimeSnapshot) -> bool:
    """
    True si el módulo de señal tipo tendencia actual puede operar dado el snapshot
    (respeta IA_REGIME_BLOCK_HIGH_VOL / IA_REGIME_BLOCK_TREND_IN_RANGE).
    """
    block_hv = os.environ.get("IA_REGIME_BLOCK_HIGH_VOL", "1").strip().lower() in ("1", "true", "yes")
    block_rng = os.environ.get("IA_REGIME_BLOCK_TREND_IN_RANGE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if snap.label == RegimeLabel.HIGH_VOL and block_hv:
        return False
    if snap.label == RegimeLabel.RANGE and block_rng:
        return False
    return True


def evaluate_regime_for_trend_module(symbol: str) -> tuple[bool, RegimeSnapshot]:
    """
    ¿Permite ejecutar el módulo de señal tipo tendencia actual (analizar_ia)?
    Retorna (allowed, snapshot).
    """
    if os.environ.get("IA_REGIME_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        snap = RegimeSnapshot(RegimeLabel.UNKNOWN, None, None, None, None, "off", "IA_REGIME_ENABLE=0")
        return True, snap

    mode = os.environ.get("IA_REGIME_MODE", "rules").strip().lower()
    snap: RegimeSnapshot | None = None
    if mode == "rules":
        snap = classify_regime_rules(symbol)
    elif mode == "ml":
        snap = classify_regime_ml(symbol)
        if snap is None:
            snap = classify_regime_rules(symbol)
            snap = RegimeSnapshot(
                snap.label,
                snap.adx,
                snap.atr_pct_rank,
                snap.z_score,
                snap.range_compression,
                "hybrid_fallback",
                snap.detail + " | ml missing",
            )
    else:  # hybrid
        snap = classify_regime_ml(symbol)
        if snap is None:
            r = classify_regime_rules(symbol)
            snap = RegimeSnapshot(
                r.label,
                r.adx,
                r.atr_pct_rank,
                r.z_score,
                r.range_compression,
                "hybrid_fallback",
                r.detail + " | ml missing",
            )

    assert snap is not None

    allowed = regime_trend_allowed(snap)

    return allowed, snap


def regime_gate_should_skip(symbol: str) -> tuple[bool, str]:
    """
    True si hay que omitir la señal tendencial en esta pasada.
    Mensaje corto para logs (vacío si no skip).
    """
    ok, snap = evaluate_regime_for_trend_module(symbol)
    if ok:
        return False, ""
    return True, f"{snap.label.value}|{snap.source}|{snap.detail}"


def regime_gate_should_skip_from_hlc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> tuple[bool, str]:
    """
    Misma semántica que regime_gate_should_skip pero sin MT5: usa solo OHLC ya alineados al instante t.
    Si IA_REGIME_ENABLE=0 → no skip. Modo ml/hybrid: en replay se usan solo reglas sobre estos datos
    (sin modelo ML salvo que lo integres aparte).
    """
    if os.environ.get("IA_REGIME_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return False, ""
    mode = os.environ.get("IA_REGIME_MODE", "rules").strip().lower()
    if mode in ("ml", "hybrid"):
        snap = classify_regime_rules_from_hlc(highs, lows, closes)
        snap = RegimeSnapshot(
            snap.label,
            snap.adx,
            snap.atr_pct_rank,
            snap.z_score,
            snap.range_compression,
            "replay_rules",
            snap.detail + f" | replay({mode})",
        )
    else:
        snap = classify_regime_rules_from_hlc(highs, lows, closes)
    allowed = regime_trend_allowed(snap)
    if allowed:
        return False, ""
    return True, f"{snap.label.value}|{snap.source}|{snap.detail}"
