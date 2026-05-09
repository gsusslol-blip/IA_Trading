"""
Registro de auditoría de entradas del bot (para aprendizaje y debugging).

Esto NO cambia la lógica de trading; solo persiste evidencia de cada orden enviada OK:
  - tiempo (UTC)
  - símbolo, lado, score (conf)
  - snapshot de parámetros IA_* relevantes (los que existan en el entorno)

Activa con:
  IA_TRADE_AUDIT_ENABLE=1
  IA_TRADE_AUDIT_CSV=trade_entries.csv  (opcional)

Calidad de ejecución / slippage (MT5 tras orden OK):
  IA_EXEC_QUALITY_ENABLE=1 (default activo si no ponés 0)
  IA_EXEC_QUALITY_CSV=execution_quality.csv
  IA_EXEC_SLIP_SPREAD_WARN_RATIO=3 — aviso stderr si slip_pts > spread * ratio con spread bajo
  IA_EXEC_WARN_MAX_SPREAD_POINTS=50 — solo avisar si spread actual <= este umbral
  IA_EXEC_WARN_MIN_SLIPPAGE_POINTS=2 — ignorar ruido por debajo de esto (puntos)
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _enabled() -> bool:
    return os.environ.get("IA_TRADE_AUDIT_ENABLE", "0").strip().lower() in ("1", "true", "yes")


def _path() -> Path:
    root = Path(__file__).resolve().parent
    name = os.environ.get("IA_TRADE_AUDIT_CSV", "").strip() or "trade_entries.csv"
    p = Path(name)
    return p if p.is_absolute() else (root / p)


def _snapshot_params() -> dict[str, str]:
    """
    Captura parámetros claves (si existen) para reproducibilidad.
    Mantener lista corta y estable.
    """
    keys = [
        "IA_MIN_CONFIDENCE",
        "IA_BREAKOUT_LOOKBACK",
        "IA_SLOPE_FILTER",
        "IA_SLOPE_MIN_ABS_PCT",
        "RSI_FILTER",
        "RSI_BUY_MIN",
        "RSI_SELL_MAX",
        "ATR_FILTER",
        "ATR_PCTL_MIN",
        "ATR_PCTL_MAX",
        "BT_SL_MODE",
        "IA_AUTO_SL_ATR_MULT",
        "IA_BE_ENABLE",
        "IA_BE_TRIGGER_RR",
        "IA_BE_BUFFER_POINTS",
        "IA_AUTO_TP_MODE",
        "IA_AUTO_TRAIL_ATR_MULT",
        "IA_LIQUIDITY_SESSION_NY_ENABLE",
        "IA_LIQUIDITY_NY_HOUR_START",
        "IA_LIQUIDITY_NY_HOUR_END",
        "IA_DXY_FILTER_ENABLE",
        "IA_DXY_SCORE_ENABLE",
        "IA_DXY_SYMBOL",
        "IA_DXY_SLOPE_MODE",
        "RR",
    ]
    out: dict[str, str] = {}
    for k in keys:
        v = os.environ.get(k)
        if v is not None:
            out[k] = str(v)
    return out


def _exec_quality_enabled() -> bool:
    return os.environ.get("IA_EXEC_QUALITY_ENABLE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _maybe_warn_slip_vs_spread(
    *,
    symbol: str,
    side: str,
    slippage_points: float | None,
    spread_points: float | None,
) -> None:
    try:
        ratio = float(os.environ.get("IA_EXEC_SLIP_SPREAD_WARN_RATIO", "3").strip() or "3")
    except ValueError:
        ratio = 3.0
    try:
        max_sp = float(os.environ.get("IA_EXEC_WARN_MAX_SPREAD_POINTS", "50").strip() or "50")
    except ValueError:
        max_sp = 50.0
    try:
        min_slip = float(os.environ.get("IA_EXEC_WARN_MIN_SLIPPAGE_POINTS", "2").strip() or "2")
    except ValueError:
        min_slip = 2.0
    if spread_points is None or spread_points != spread_points:
        return
    if slippage_points is None or slippage_points != slippage_points:
        return
    if spread_points > max_sp:
        return
    if slippage_points < min_slip:
        return
    if ratio > 0 and slippage_points <= spread_points * ratio:
        return
    print(
        f"[EXEC] {symbol} {side}: slippage alto vs spread "
        f"(slip_pts={slippage_points:.2g} spread_pts={spread_points:.2g} ratio_lim={ratio:.3g}); "
        "revisá liquidez/requotes.",
        file=sys.stderr,
    )


def _exec_quality_path() -> Path:
    root = Path(__file__).resolve().parent
    name = os.environ.get("IA_EXEC_QUALITY_CSV", "").strip() or "execution_quality.csv"
    p = Path(name)
    return p if p.is_absolute() else (root / p)


def log_execution_quality(
    *,
    symbol: str,
    side: str,
    price_requested: float,
    price_executed: float | None,
    spread_points: float | None,
    retcode: int,
    volume: float,
    deal: int = 0,
    symbol_point: float | None = None,
) -> None:
    """
    Slippage vs precio pedido (market) y spread observado. Best-effort CSV.
    ``symbol_point`` (MT5 ``symbol_info.point``) permite ``slippage_points`` en puntos del bróker.
    """
    if not _exec_quality_enabled():
        return
    try:
        p = _exec_quality_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        write_header = not p.is_file()
        pe = float(price_executed) if price_executed is not None else float("nan")
        slip = (
            abs(float(price_requested) - pe)
            if pe == pe
            else float("nan")
        )
        try:
            pt = float(symbol_point) if symbol_point is not None else 0.0
        except (TypeError, ValueError):
            pt = 0.0
        if pt != pt:  # NaN
            pt = 0.0
        slip_pts: float | None = None
        if pt > 0 and slip == slip:
            slip_pts = slip / pt
        sp_txt = "" if spread_points is None else f"{float(spread_points):.4g}"
        slip_pts_txt = "" if slip_pts is None else f"{slip_pts:.6g}"
        ts = datetime.now(timezone.utc).isoformat()
        with p.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(
                    [
                        "time_utc",
                        "symbol",
                        "side",
                        "volume",
                        "price_requested",
                        "price_executed",
                        "slippage_abs",
                        "slippage_points",
                        "spread_points",
                        "retcode",
                        "deal",
                    ]
                )
            w.writerow(
                [
                    ts,
                    symbol,
                    side,
                    f"{volume:.6g}",
                    f"{price_requested:.8f}",
                    f"{pe:.8f}" if pe == pe else "",
                    f"{slip:.8f}" if slip == slip else "",
                    slip_pts_txt,
                    sp_txt,
                    retcode,
                    deal,
                ]
            )
        _maybe_warn_slip_vs_spread(
            symbol=symbol,
            side=side,
            slippage_points=slip_pts,
            spread_points=float(spread_points) if spread_points is not None else None,
        )
    except Exception:
        return


def log_trade_entry(*, symbol: str, side: str, ia_confidence: int | None) -> None:
    """
    Best-effort append. Nunca levanta excepción.
    """
    if not _enabled():
        return
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        write_header = not p.is_file()
        ts = datetime.now(timezone.utc).isoformat()
        conf = "" if ia_confidence is None else str(int(ia_confidence))
        params = _snapshot_params()
        # Serialize params as key=value;key=value
        params_s = ";".join([f"{k}={params[k]}" for k in sorted(params.keys())])
        line = f"{ts},{symbol},{side},{conf},{params_s}\n"
        with p.open("a", encoding="utf-8", newline="") as f:
            if write_header:
                f.write("time_utc,symbol,side,ia_confidence,params\n")
            f.write(line)
    except Exception:
        return

