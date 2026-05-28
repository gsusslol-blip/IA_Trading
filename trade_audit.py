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

Bloqueo de nuevas órdenes si el slippage reciente es malo (ia_auto_trade_loop.enviar_orden):
  IA_EXEC_SLIP_GUARD_ENABLE=1
  IA_EXEC_SLIP_GUARD_WINDOW=3 — últimas N filas del símbolo con slippage_points válido
    (alias alternativo si esta clave está vacía: IA_SLIPPAGE_WINDOW)
  IA_EXEC_SLIP_GUARD_MAX_AVG_PTS=8 — si el promedio de esas N supera esto, no envía (0 = desactiva umbral)
    Si no definís esta clave (o está vacía), se usa IA_MAX_SLIPPAGE_AVG.
  IA_EXEC_SLIP_GUARD_MIN_SAMPLES=3 — mínimo de muestras para aplicar (fail-open si hay menos)

Rotación del CSV execution_quality por tamaño (mantiene I/O rápido; guarda `.old`):
  IA_LOG_MAX_MB=5 — al superarlo renombra a execution_quality.csv.old (alias: IA_EXEC_LOG_MAX_MB).
  Poné ``0`` para desactivar.

``check_slippage_safety(..., symbol=None)`` — misma heurística vía ``pandas.read_csv``; con ``symbol=None``
usa las últimas ``window`` filas del CSV mezclando activos (modo “archivo crudo”).
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ia_utils import execution_quality_max_mb_from_env, rotar_log_por_tamaño


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
    from ia_paths import resolve_data_path

    return resolve_data_path("IA_EXEC_QUALITY_CSV", "logs/execution_quality.csv")


def execution_quality_csv_path() -> Path:
    """Ruta del CSV de calidad de ejecución (``IA_EXEC_QUALITY_CSV``), misma que usa el guard."""
    return _exec_quality_path()


def _exec_slip_guard_max_avg_pts_from_env() -> float:
    """
    Preferencia: ``IA_EXEC_SLIP_GUARD_MAX_AVG_PTS`` si viene definido (cadena no vacía; ``0`` desactiva).
    Si falta o está vacío, ``IA_MAX_SLIPPAGE_AVG``.
    """
    primary = os.environ.get("IA_EXEC_SLIP_GUARD_MAX_AVG_PTS")
    if primary is not None and str(primary).strip() != "":
        try:
            return float(primary.strip())
        except ValueError:
            return 0.0
    alt = os.environ.get("IA_MAX_SLIPPAGE_AVG", "").strip()
    if alt:
        try:
            v = float(alt)
            return v if v == v else 0.0
        except ValueError:
            return 0.0
    return 0.0


def _exec_slip_guard_window_from_env() -> int:
    """``IA_EXEC_SLIP_GUARD_WINDOW`` con fallback ``IA_SLIPPAGE_WINDOW``; default 3."""
    for key in ("IA_EXEC_SLIP_GUARD_WINDOW", "IA_SLIPPAGE_WINDOW"):
        raw = os.environ.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            return max(1, min(50, int(str(raw).strip())))
        except ValueError:
            continue
    return 3


def _exec_slip_guard_min_samples_from_env(window_eff: int) -> int:
    try:
        min_samples = int(
            os.environ.get("IA_EXEC_SLIP_GUARD_MIN_SAMPLES", str(window_eff)).strip() or str(window_eff)
        )
    except ValueError:
        min_samples = window_eff
    return max(1, min(min_samples, window_eff))


def is_market_safe_to_trade(
    csv_path: str | Path | None = None,
    *,
    symbol: str | None = None,
) -> bool:
    """
    Heurística rápida: ``True`` si el slippage promedio reciente no supera el umbral por entorno.

    Usa los mismos alias que ``slippage_guard_allows_order`` (sin necesidad de
    ``IA_EXEC_SLIP_GUARD_ENABLE``): ``IA_EXEC_SLIP_GUARD_MAX_AVG_PTS`` o ``IA_MAX_SLIPPAGE_AVG``,
    ventana ``IA_EXEC_SLIP_GUARD_WINDOW`` o ``IA_SLIPPAGE_WINDOW``.
    Con umbral ``<= 0`` siempre ``True`` (sin bloque).
    """
    max_avg = _exec_slip_guard_max_avg_pts_from_env()
    if max_avg <= 0:
        return True
    window = _exec_slip_guard_window_from_env()
    ms_eff = _exec_slip_guard_min_samples_from_env(window)
    p = Path(csv_path) if csv_path is not None else execution_quality_csv_path()
    ok, _ = check_slippage_safety(
        p,
        symbol=symbol,
        window=window,
        max_avg_points=max_avg,
        min_samples=ms_eff,
    )
    return ok


def check_slippage_safety(
    csv_path: str | Path | None,
    *,
    symbol: str | None = None,
    window: int = 3,
    max_avg_points: float = 50.0,
    min_samples: int | None = None,
) -> tuple[bool, str]:
    """
    ``True`` si el slippage promedio reciente es aceptable (fail-open).

    Con ``symbol`` filtra filas antes de tomar las últimas ``window`` orden cronológicas del CSV.
    Con ``symbol=None`` se usa ``DataFrame.tail(window)`` sobre el archivo completo (últimas N operaciones).

    Si ``max_avg_points`` <= 0, siempre ``True``.
    """
    try:
        w = max(1, min(250, int(window)))
    except (TypeError, ValueError):
        w = 3
    if max_avg_points <= 0:
        return True, ""

    ms = min_samples if min_samples is not None else w
    try:
        ms_i = int(ms)
    except (TypeError, ValueError):
        ms_i = w
    ms_eff = max(1, min(ms_i, w))

    p = Path(csv_path) if csv_path is not None else None
    if p is None or not p.is_file():
        return True, ""

    try:
        df = pd.read_csv(p)
    except (FileNotFoundError, OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return True, ""
    if df.empty or "slippage_points" not in df.columns:
        return True, ""

    if symbol:
        sym_u = symbol.strip().upper()
        col = df.get("symbol", pd.Series(dtype=str)).astype(str).str.strip().str.upper()
        df = df.loc[col == sym_u].reset_index(drop=True)

    tail = df.tail(w)
    if len(tail) < ms_eff:
        return True, ""

    pts = pd.to_numeric(tail["slippage_points"], errors="coerce")
    if pts.isna().all():
        return True, ""

    avg = float(pts.mean())
    if avg != avg:
        return True, ""
    if avg > max_avg_points:
        return False, f"slippage_avg={avg:.3g}pts (ventana={len(tail)}) > límite {max_avg_points:g}pts"

    return True, ""


def slippage_guard_allows_order(symbol: str) -> tuple[bool, str]:
    """
    Si ``IA_EXEC_SLIP_GUARD_ENABLE=1`` y existen muestras suficientes, delega en
    ``check_slippage_safety`` con el mismo CSV de ejecución.

    Fail-open: CSV inexistente, sin columna, pocas muestras, o ``MAX_AVG_PTS<=0`` → permite orden.
    """
    if os.environ.get("IA_EXEC_SLIP_GUARD_ENABLE", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return True, ""
    max_avg = _exec_slip_guard_max_avg_pts_from_env()
    if max_avg <= 0.0:
        return True, ""
    window = _exec_slip_guard_window_from_env()
    min_samples_eff = _exec_slip_guard_min_samples_from_env(window)

    p = _exec_quality_path()

    ok, msg = check_slippage_safety(
        p,
        symbol=symbol,
        window=window,
        max_avg_points=max_avg,
        min_samples=min_samples_eff,
    )
    return ok, msg


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
        try:
            mx = execution_quality_max_mb_from_env()
            if mx > 0:
                rotar_log_por_tamaño(p, mx)
        except Exception:
            pass
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

