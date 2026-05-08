"""
Análisis de mercado para señales operativas (datos MT5 + reglas explícitas).

Incluye: multi‑TF, niveles por swings, ATR/percentil, RSI, índice de confianza heurístico
y referencias de SL/TP orientativas. No sustituye criterio propio ni garantiza resultados.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import MetaTrader5 as mt5


def _sma(closes: list[float], period: int) -> float | None:
    if period <= 0 or len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _tf_bias_label(closes: list[float], fast: int = 20, slow: int = 50) -> str:
    if len(closes) < slow + 2:
        return "N/D"
    f = _sma(closes, fast)
    s = _sma(closes, slow)
    if f is None or s is None:
        return "N/D"
    if f > s * 1.00005:
        return "alcista"
    if f < s * 0.99995:
        return "bajista"
    return "mixto"


def _rsi_wilder(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    if len(deltas) < period:
        return None
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss < 1e-12:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _true_ranges(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    trs: list[float] = []
    for i in range(1, len(closes)):
        h, low, pc = highs[i], lows[i], closes[i - 1]
        tr = max(h - low, abs(h - pc), abs(low - pc))
        trs.append(tr)
    return trs


def _atr_series(trs: list[float], period: int) -> list[float]:
    out: list[float] = []
    if period <= 1 or len(trs) < period:
        return out
    for i in range(period - 1, len(trs)):
        window = trs[i - period + 1 : i + 1]
        out.append(sum(window) / period)
    return out


def _percentile_rank(value: float, sample: list[float]) -> float | None:
    if not sample or value <= 0:
        return None
    arr = sorted(sample)
    below = sum(1 for x in arr if x < value)
    return 100.0 * below / len(arr)


def _swing_low_indices(lows: list[float]) -> list[int]:
    idx: list[int] = []
    for i in range(2, len(lows) - 2):
        if lows[i] <= lows[i - 1] and lows[i] <= lows[i - 2] and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
            idx.append(i)
    return idx


def _swing_high_indices(highs: list[float]) -> list[int]:
    idx: list[int] = []
    for i in range(2, len(highs) - 2):
        if highs[i] >= highs[i - 1] and highs[i] >= highs[i - 2] and highs[i] >= highs[i + 1] and highs[i] >= highs[i + 2]:
            idx.append(i)
    return idx


def _cluster_price_levels(prices: list[float], tol: float) -> list[tuple[float, int]]:
    if not prices or tol <= 0:
        return []
    sorted_p = sorted(prices)
    clusters: list[list[float]] = []
    cur: list[float] = [sorted_p[0]]
    for p in sorted_p[1:]:
        if p - cur[-1] <= tol:
            cur.append(p)
        else:
            clusters.append(cur)
            cur = [p]
    clusters.append(cur)
    out = [(sum(c) / len(c), len(c)) for c in clusters]
    out.sort(key=lambda x: -x[1])
    return out


def _touch_count_level(lows: list[float], highs: list[float], level: float, tol: float, kind: str) -> int:
    if kind == "support":
        return sum(1 for lo in lows if abs(lo - level) <= tol)
    return sum(1 for hi in highs if abs(hi - level) <= tol)


def _confidence_rules(
    signal: str,
    m15: str,
    h1: str,
    h4: str,
    near_support: bool,
    near_resistance: bool,
) -> tuple[int, list[str]]:
    notes: list[str] = []
    score = 42
    if signal == "BUY":
        if m15 == "alcista":
            score += 18
            notes.append("M15 alineado con compras.")
        elif m15 == "bajista":
            score -= 12
            notes.append("M15 contrario a compras.")
        if h1 == "alcista":
            score += 8
        elif h1 == "bajista":
            score -= 6
        if h4 == "alcista":
            score += 8
        elif h4 == "bajista":
            score -= 14
            notes.append("H4 bajista vs compra: conflicto de marco alto.")
        if near_support:
            score += 12
            notes.append("Cerca de soporte por swings M5.")
        if near_resistance:
            score -= 8
    elif signal == "SELL":
        if m15 == "bajista":
            score += 18
            notes.append("M15 alineado con ventas.")
        elif m15 == "alcista":
            score -= 12
        if h1 == "bajista":
            score += 8
        elif h1 == "alcista":
            score -= 6
        if h4 == "bajista":
            score += 8
        elif h4 == "alcista":
            score -= 14
            notes.append("H4 alcista vs venta: conflicto de marco alto.")
        if near_resistance:
            score += 12
            notes.append("Cerca de resistencia por swings M5.")
        if near_support:
            score -= 8
    else:
        score = 38
        notes.append("HOLD: sin sesgo claro en la estrategia base.")

    score = max(18, min(92, score))
    return score, notes


def _rsi_adjust_confidence(signal: str, rsi: float | None, score: int, notes: list[str]) -> int:
    if rsi is None:
        return score
    if signal == "BUY":
        if rsi >= 72:
            score -= 12
            notes.append(f"RSI({rsi:.0f}) sobrecompra — posible retroceso.")
        elif 48 <= rsi <= 68:
            score += 7
            notes.append(f"RSI({rsi:.0f}) impulso alcista razonable.")
        elif rsi <= 32:
            notes.append(f"RSI({rsi:.0f}) muy vendido — confirmar con estructura de precio.")
    elif signal == "SELL":
        if rsi <= 28:
            score -= 12
            notes.append(f"RSI({rsi:.0f}) sobreventa — rebote posible.")
        elif 32 <= rsi <= 52:
            score += 7
            notes.append(f"RSI({rsi:.0f}) presión vendedora coherente.")
        elif rsi >= 68:
            notes.append(f"RSI({rsi:.0f}) muy sobrecomprado — cuidado con continuación.")
    return max(18, min(92, score))


def _rsi_filter_blocks(signal: str, rsi: float | None) -> bool:
    """
    Si RSI_FILTER=1: endurece señales direccionales.
    Devuelve True si la señal pasa el filtro RSI (o HOLD siempre pasa).
    """
    if rsi is None:
        return True
    if os.environ.get("RSI_FILTER", "0").strip().lower() not in ("1", "true", "yes"):
        return True
    buy_min = float(os.environ.get("RSI_BUY_MIN", "42"))
    sell_max = float(os.environ.get("RSI_SELL_MAX", "58"))
    if signal == "HOLD":
        return True
    if signal == "BUY":
        return rsi >= buy_min
    if signal == "SELL":
        return rsi <= sell_max
    return True


def _reference_trade_plan(
    signal: str,
    mid: float,
    atr_m5: float | None,
    sl_atr_mult: float,
    rr: float,
    digits: int,
    sup_lvl: float | None,
    res_lvl: float | None,
) -> list[str]:
    lines = ["\n📍 Referencia operativa (vos ejecutás en el broker)"]
    if atr_m5 is None or mid <= 0:
        lines.append("• Sin ATR: definí SL/TP según tu plan y gestión de riesgo.")
        return lines
    sd = atr_m5 * sl_atr_mult
    if signal == "BUY":
        sl_cand = mid - sd
        tp_cand = mid + sd * rr
        lines.append(f"• Idea SL ~{sl_cand:.{digits}f} | TP RR{rr} ~{tp_cand:.{digits}f} (desde mid {mid:.{digits}f}).")
        if sup_lvl:
            lines.append(f"• Alternativa: SL lógico bajo soporte ~{sup_lvl:.{digits}f} si encaja con tu riesgo.")
    elif signal == "SELL":
        sl_cand = mid + sd
        tp_cand = mid - sd * rr
        lines.append(f"• Idea SL ~{sl_cand:.{digits}f} | TP RR{rr} ~{tp_cand:.{digits}f}.")
        if res_lvl:
            lines.append(f"• Alternativa: SL lógico sobre resistencia ~{res_lvl:.{digits}f}.")
    else:
        lines.append("• HOLD: esperar ruptura/claridad o reducir tamaño si operás manual.")
    lines.append("• Validá siempre spread, horario y tamaño de posición en tu cuenta.")
    return lines


@dataclass
class MarketAnalysisPack:
    confidence: int
    text_block: str
    rsi_m5: float | None
    passes_rsi_filter: bool
    atr_m5: float | None
    atr_percentile_m5: float | None
    passes_atr_filter: bool


def analyze_market_pack(
    symbol: str,
    signal: str,
    bid: float,
    ask: float,
    atr_m5: float | None,
    atr_period: int,
    sl_atr_mult: float,
    rr: float,
) -> MarketAnalysisPack:
    """
    Análisis completo + confianza 18–92 + texto para Telegram.
    """
    mid = (bid + ask) / 2.0
    spread = ask - bid if ask >= bid else 0.0
    info = mt5.symbol_info(symbol)
    digits = int(getattr(info, "digits", 2) or 2) if info is not None else 2
    point = float(getattr(info, "point", 0.0) or 0.0) if info is not None else 0.01

    m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 400)
    if atr_m5 is None and m5 is not None and len(m5) > atr_period + 5:
        highs0 = [float(r["high"]) for r in m5]
        lows0 = [float(r["low"]) for r in m5]
        closes0 = [float(r["close"]) for r in m5]
        trs0 = _true_ranges(highs0, lows0, closes0)
        ser = _atr_series(trs0, atr_period)
        if ser:
            atr_m5 = float(ser[-1])

    closes_m5: list[float] = []
    rsi_val: float | None = None
    if m5 is not None and len(m5) > 20:
        closes_m5 = [float(r["close"]) for r in m5]
        rsi_val = _rsi_wilder(closes_m5, 14)

    m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 250)
    h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 200)
    h4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 120)

    lines: list[str] = []

    m15_b = h1_b = h4_b = "N/D"
    if m15 is not None and len(m15) > 55:
        m15_b = _tf_bias_label([float(r["close"]) for r in m15])
    if h1 is not None and len(h1) > 55:
        h1_b = _tf_bias_label([float(r["close"]) for r in h1])
    if h4 is not None and len(h4) > 55:
        h4_b = _tf_bias_label([float(r["close"]) for r in h4])

    lines.append("\n📌 Post-análisis técnico (MT5, ventana reciente)")
    lines.append(f"• Multi-TF SMA20/50: M15 {m15_b} | H1 {h1_b} | H4 {h4_b}")

    if signal == "BUY" and h4_b == "bajista":
        lines.append("• ⚠️ Conflicto: señal compra vs H4 bajista.")
    elif signal == "SELL" and h4_b == "alcista":
        lines.append("• ⚠️ Conflicto: señal venta vs H4 alcista.")

    sup_txt = res_txt = "—"
    near_sup = near_res = False
    best_sup = best_res = None
    if m5 is not None and len(m5) > 80:
        atr_eff = float(atr_m5) if atr_m5 and atr_m5 > 0 else max(spread * 5.0, point * 50.0)
        lows = [float(r["low"]) for r in m5]
        highs = [float(r["high"]) for r in m5]
        tol = max(atr_eff * 0.2, spread * 2, point * 10)
        swing_low_prices = [lows[i] for i in _swing_low_indices(lows)]
        swing_high_prices = [highs[i] for i in _swing_high_indices(highs)]

        below = [p for p in swing_low_prices if p < mid]
        above = [p for p in swing_high_prices if p > mid]

        if below:
            clusters = _cluster_price_levels(below, tol)
            if clusters:
                lvl, _n = clusters[0]
                touches = _touch_count_level(lows, highs, lvl, tol, "support")
                bars = len(lows)
                days_apx = bars / (12 * 24)
                rel = min(97, 55 + min(42, touches * 3))
                sup_txt = f"SOPORTE ~{lvl:.{digits}f} | relevancia ~{rel}% | toques ~{touches} (~{days_apx:.1f} d M5)"
                near_sup = abs(mid - lvl) <= atr_eff * 1.1
                best_sup = lvl
        if above:
            clusters = _cluster_price_levels(above, tol)
            if clusters:
                lvl, _ = clusters[0]
                touches = _touch_count_level(lows, highs, lvl, tol, "resistance")
                bars = len(highs)
                days_apx = bars / (12 * 24)
                rel = min(97, 55 + min(42, touches * 3))
                res_txt = f"RESISTENCIA ~{lvl:.{digits}f} | relevancia ~{rel}% | toques ~{touches} (~{days_apx:.1f} d M5)"
                near_res = abs(lvl - mid) <= atr_eff * 1.1
                best_res = lvl

    lines.append("\n🧱 Niveles (swings M5 agrupados)")
    lines.append(f"• {sup_txt}")
    lines.append(f"• {res_txt}")

    ptxt = "N/D"
    atr_pctl: float | None = None
    if m5 is not None and len(m5) > atr_period + 60 and atr_m5:
        highs = [float(r["high"]) for r in m5]
        lows = [float(r["low"]) for r in m5]
        closes = [float(r["close"]) for r in m5]
        trs = _true_ranges(highs, lows, closes)
        atr_hist = _atr_series(trs, atr_period)
        if atr_hist:
            p = _percentile_rank(atr_m5, atr_hist[-min(400, len(atr_hist)) :])
            if p is not None:
                atr_pctl = float(p)
                sens = max(0.15, min(1.0, 1.0 - abs(p - 50) / 80))
                ptxt = f"ATR ~{atr_m5:.{max(2, digits)}f} | p~{p:.0f}% hist M5 | sens~{sens:.2f}"

    lines.append("\n📈 Volatilidad contextual")
    lines.append(f"• {ptxt}")
    lines.append(f"• Config bot: SL tipo ATR×{sl_atr_mult}, RR {rr}")

    if rsi_val is not None:
        lines.append(f"\n📉 RSI(14) M5 ≈ {rsi_val:.1f}")

    conf, cnotes = _confidence_rules(signal, m15_b, h1_b, h4_b, near_sup, near_res)
    conf = _rsi_adjust_confidence(signal, rsi_val, conf, cnotes)

    lines.append("\n🎯 Índice de confianza del modelo (heurístico)")
    lines.append(f"• Puntuación ~{conf}/100 (multi‑TF + niveles + RSI).")
    for n in cnotes[:5]:
        lines.append(f"  — {n}")

    lines.extend(
        _reference_trade_plan(signal, mid, atr_m5, sl_atr_mult, rr, digits, best_sup, best_res)
    )

    text_block = "\n".join(lines)
    passes = _rsi_filter_blocks(signal, rsi_val)
    passes_atr = True
    if os.environ.get("ATR_FILTER", "0").strip().lower() in ("1", "true", "yes"):
        # Si no hay ATR/percentil, dejamos pasar (evita bloquear por falta de datos).
        if atr_pctl is not None:
            try:
                pmin = float(os.environ.get("ATR_PCTL_MIN", "15").strip() or "15")
                pmax = float(os.environ.get("ATR_PCTL_MAX", "85").strip() or "85")
            except ValueError:
                pmin, pmax = 15.0, 85.0
            passes_atr = (pmin <= atr_pctl <= pmax)

    return MarketAnalysisPack(
        confidence=conf,
        text_block=text_block,
        rsi_m5=rsi_val,
        passes_rsi_filter=passes,
        atr_m5=atr_m5,
        atr_percentile_m5=atr_pctl,
        passes_atr_filter=passes_atr,
    )


def format_deep_analysis(
    symbol: str,
    signal: str,
    bid: float,
    ask: float,
    atr_m5: float | None,
    atr_period: int,
    sl_atr_mult: float,
    rr: float,
) -> str:
    return analyze_market_pack(symbol, signal, bid, ask, atr_m5, atr_period, sl_atr_mult, rr).text_block


def telegram_confidence_threshold() -> float:
    """Si PRECISE_SIGNALS=1, umbral por defecto más alto."""
    if os.environ.get("PRECISE_SIGNALS", "").strip().lower() in ("1", "true", "yes"):
        return float(os.environ.get("SIGNAL_MIN_CONFIDENCE", "52"))
    return float(os.environ.get("SIGNAL_MIN_CONFIDENCE", "0"))


def telegram_should_send_signal(confidence: int, passes_rsi_filter: bool, passes_atr_filter: bool = True) -> bool:
    if not passes_rsi_filter:
        return False
    if not passes_atr_filter:
        return False
    return confidence >= telegram_confidence_threshold()


def deep_analysis_enabled() -> bool:
    return os.environ.get("TELEGRAM_DEEP_ANALYSIS", "1").strip().lower() not in ("0", "false", "no")


def obtener_bias_dxy(
    *,
    symbol: str | None = None,
    bars: int | None = None,
) -> str:
    """
    Sesgo simple del índice dólar (USDX/DXY/etc. según tu bróker) en M15: pendiente de cierres.
    Pendiente ~ (close[-1]-close[0])/len(bars); umbral opcional vía IA_DXY_SLOPE_MIN_ABS_PCT (% sobre c0).
    Returns: BULLISH | BEARISH | N/D
    """
    sym = (symbol or os.environ.get("IA_DXY_SYMBOL", "").strip()).strip()
    if not sym:
        return "N/D"
    mt5.symbol_select(sym, True)
    try:
        nb = int(bars if bars is not None else os.environ.get("IA_DXY_BIAS_BARS", "20").strip() or "20")
    except ValueError:
        nb = 20
    nb = max(5, min(80, nb))
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, nb)
    if rates is None or len(rates) < 5:
        return "N/D"
    c0 = float(rates["close"][0])
    c1 = float(rates["close"][-1])
    if c0 <= 0:
        return "N/D"
    n = float(len(rates))
    slope = (c1 - c0) / n
    slope_pct = ((c1 - c0) / c0) * 100.0
    try:
        thr = float(os.environ.get("IA_DXY_SLOPE_MIN_ABS_PCT", "0").strip() or "0")
    except ValueError:
        thr = 0.0
    if thr > 0 and abs(slope_pct) < thr:
        return "N/D"
    return "BULLISH" if slope > 0 else "BEARISH"


def _symbol_es_oro_macro(sym: str) -> bool:
    u = sym.upper().replace(" ", "")
    return "XAU" in u or "GOLD" in u


def get_dxy_modifier(*, signal: str, trade_symbol: str = "") -> int:
    """
    Puntos a **sumar** al score técnico (compra en oro penalizada si el dólar sube en M15).

    Requiere IA_DXY_SCORE_ENABLE=1 y IA_DXY_SYMBOL. Sin datos → 0.

    BUY: retorno (close[-1]/close[0]-1) > umbral → penalidad; < -umbral → bonificación.
    SELL: lógica invertida (dólar fuerte suele ayudar ventas en XAU).

    Control: IA_DXY_SCORE_BARS (10), IA_DXY_SCORE_RETURN_THR (0.001), IA_DXY_SCORE_MAG (15),
    IA_DXY_SCORE_ALL_SYMBOLS=1 para aplicar también fuera de XAU/GOLD.
    """
    if os.environ.get("IA_DXY_SCORE_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return 0
    if trade_symbol and not _symbol_es_oro_macro(trade_symbol):
        if os.environ.get("IA_DXY_SCORE_ALL_SYMBOLS", "0").strip().lower() not in ("1", "true", "yes"):
            return 0
    sym = os.environ.get("IA_DXY_SYMBOL", "").strip()
    if not sym:
        sym = "USDX"
    mt5.symbol_select(sym, True)
    try:
        nb = int(os.environ.get("IA_DXY_SCORE_BARS", "10").strip() or "10")
    except ValueError:
        nb = 10
    nb = max(5, min(40, nb))
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, nb)
    if rates is None or len(rates) < nb:
        return 0
    c0 = float(rates["close"][0])
    c1 = float(rates["close"][-1])
    if c0 <= 0:
        return 0
    returns = (c1 - c0) / c0
    try:
        thr = float(os.environ.get("IA_DXY_SCORE_RETURN_THR", "0.001").strip() or "0.001")
    except ValueError:
        thr = 0.001
    try:
        mag = int(float(os.environ.get("IA_DXY_SCORE_MAG", "15").strip() or "15"))
    except ValueError:
        mag = 15
    mag = max(1, min(40, mag))
    side = signal.strip().upper()
    if side == "BUY":
        if returns > thr:
            return -mag
        if returns < -thr:
            return mag
    elif side == "SELL":
        if returns > thr:
            return mag
        if returns < -thr:
            return -mag
    return 0


def macro_session_score_penalty_points() -> int:
    """
    Puntos a **restar** del score si la hora NY está fuera de la ventana configurada.

    IA_MACRO_SCORE_SESSION_ENABLE=1. Usa America/New_York e IA_LIQUIDITY_NY_HOUR_START/END
    (misma referencia que el filtro de liquidez; no exige IA_LIQUIDITY_SESSION_NY_ENABLE).
    IA_MACRO_SCORE_SESSION_PENALTY default 20; 0 = desactivado.
    """
    if os.environ.get("IA_MACRO_SCORE_SESSION_ENABLE", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return 0
    try:
        pen = int(float(os.environ.get("IA_MACRO_SCORE_SESSION_PENALTY", "20").strip() or "20"))
    except ValueError:
        pen = 20
    if pen <= 0:
        return 0
    try:
        from zoneinfo import ZoneInfo

        h = datetime.now(ZoneInfo("America/New_York")).hour
    except Exception:
        h = datetime.now().hour
    try:
        h0 = int(os.environ.get("IA_LIQUIDITY_NY_HOUR_START", "8").strip() or "8")
        h1 = int(os.environ.get("IA_LIQUIDITY_NY_HOUR_END", "16").strip() or "16")
    except ValueError:
        return pen
    if h0 <= h <= h1:
        return 0
    return pen


def aplicar_score_macro(confianza_base: int, *, signal: str, trade_symbol: str) -> int:
    """confianza base (técnica) + DXY − penalización sesión; recorte razonable 0..100."""
    s = int(confianza_base)
    s += get_dxy_modifier(signal=signal, trade_symbol=trade_symbol)
    s -= macro_session_score_penalty_points()
    return max(0, min(100, s))
