"""
Comisiones ECN/Raw: detección por símbolo y ajuste de breakeven real.

Variables:
  IA_FEE_BE_ENABLE=1
  IA_FEE_AUDIT_DAYS=7
  IA_FEE_DEFAULT_PER_LOT=0   — override manual (ida+vuelta por 1 lote) si MT5 no expone comisión
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

_CACHE: dict[str, tuple[float, float]] = {}
_CACHE_TTL_S = 300.0


def fee_be_enabled() -> bool:
    return os.environ.get("IA_FEE_BE_ENABLE", "1").strip().lower() in ("1", "true", "yes")


def _audit_days() -> int:
    try:
        return max(1, int(os.environ.get("IA_FEE_AUDIT_DAYS", "7").strip() or "7"))
    except ValueError:
        return 7


def _default_per_lot_env() -> float | None:
    raw = os.environ.get("IA_FEE_DEFAULT_PER_LOT", "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except ValueError:
        return None


def _commission_from_history(symbol: str, magic: int | None) -> float:
    import MetaTrader5 as mt5

    from mt5_prices import BOT_MAGIC

    mag = int(magic if magic is not None else BOT_MAGIC)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=_audit_days())
    try:
        mt5.history_select(start, now)
    except Exception:
        pass
    deals = mt5.history_deals_get(start, now)
    if not deals:
        return 0.0
    for d in reversed(list(deals)):
        if str(getattr(d, "symbol", "") or "") != symbol:
            continue
        if int(getattr(d, "magic", -1) or -1) != mag:
            continue
        comm = float(getattr(d, "commission", 0.0) or 0.0)
        vol = float(getattr(d, "volume", 0.0) or 0.0)
        if comm != 0.0 and vol > 0:
            return abs(comm / vol) * 2.0
    return 0.0


def obtener_comision_por_lote(symbol: str, *, magic: int | None = None) -> float:
    """
    Comisión **ida y vuelta** en divisa de la cuenta por 1.0 lote estándar.
    """
    sym = symbol.strip()
    if not sym:
        return 0.0
    now = time.time()
    cached = _CACHE.get(sym)
    if cached and now - cached[1] < _CACHE_TTL_S:
        return cached[0]

    override = _default_per_lot_env()
    if override is not None:
        _CACHE[sym] = (override, now)
        return override

    import MetaTrader5 as mt5

    info = mt5.symbol_info(sym)
    if info is None:
        return 0.0

    comm_base = float(getattr(info, "commission_base", getattr(info, "comm_base", 0.0)) or 0.0)
    comm_type = int(getattr(info, "commission_type", getattr(info, "comm_type", 0)) or 0)

    comm_rt = 0.0
    if comm_base > 0:
        # Tipo 0/1: por lote o por volumen — asumimos ida+vuelta ≈ 2× comisión por lado
        if comm_type in (0, 1):
            comm_rt = abs(comm_base) * 2.0
    if comm_rt <= 0:
        comm_rt = _commission_from_history(sym, magic)

    comm_rt = round(comm_rt, 4)
    _CACHE[sym] = (comm_rt, now)
    return comm_rt


def delta_precio_breakeven_comision(
    symbol: str,
    volume: float,
    *,
    magic: int | None = None,
    info: Any = None,
) -> float:
    """
    Distancia en **precio** para cubrir comisión round-trip al tocar el BE.

    ``Δprecio = (comisión_por_lote × volumen) / (contract_size × volumen)``
    """
    if not fee_be_enabled():
        return 0.0
    try:
        vol = float(volume)
    except (TypeError, ValueError):
        return 0.0
    if vol <= 0:
        return 0.0

    if info is not None and _default_per_lot_env() is not None:
        comm = _default_per_lot_env() or 0.0
    else:
        comm = obtener_comision_por_lote(symbol, magic=magic)
    if comm <= 0:
        return 0.0

    if info is None:
        try:
            import MetaTrader5 as mt5

            info = mt5.symbol_info(symbol)
        except Exception:
            info = None
    if info is None:
        return 0.0
    contract = float(getattr(info, "trade_contract_size", 0.0) or 0.0)
    if contract <= 0:
        contract = 100.0
    total_comm = comm * vol
    denom = contract * vol
    if denom <= 0:
        return 0.0
    return total_comm / denom


def precio_breakeven_ajustado(
    symbol: str,
    *,
    buy: bool,
    entry_price: float,
    volume: float,
    buffer_price: float = 0.0,
    magic: int | None = None,
    info: Any = None,
) -> float:
    """
    Precio de SL breakeven que cubre comisión del bróker.

    BUY: entry + buffer + Δcomisión  
    SELL: entry - buffer - Δcomisión
    """
    op = float(entry_price)
    buf = float(buffer_price)
    delta = delta_precio_breakeven_comision(symbol, volume, magic=magic, info=info)
    if buy:
        return op + buf + delta
    return op - buf - delta
