"""
Registro de auditoría de entradas del bot (para aprendizaje y debugging).

Esto NO cambia la lógica de trading; solo persiste evidencia de cada orden enviada OK:
  - tiempo (UTC)
  - símbolo, lado, score (conf)
  - snapshot de parámetros IA_* relevantes (los que existan en el entorno)

Activa con:
  IA_TRADE_AUDIT_ENABLE=1
  IA_TRADE_AUDIT_CSV=trade_entries.csv  (opcional)
"""

from __future__ import annotations

import os
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

