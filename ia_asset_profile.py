"""
Perfil por activo: clase (oro / EUR / JPY / índice) y reglas DXY + multiplicadores ATR por símbolo.
"""

from __future__ import annotations

import os
from enum import Enum


class AssetClass(str, Enum):
    GOLD = "gold"
    FX_EUR_QUOTE = "fx_eur"
    FX_JPY = "fx_jpy"
    INDEX = "index"
    OTHER = "other"


def classify_trade_symbol(symbol: str) -> AssetClass:
    """
    Heurística por nombre MT5 (soporta sufijos del bróker: EURUSDm, NAS100.c, etc.).
    """
    u = symbol.upper().replace(" ", "").replace(".", "").replace("#", "")
    if "XAU" in u or "GOLD" in u:
        return AssetClass.GOLD
    if "JPY" in u and "USD" in u:
        return AssetClass.FX_JPY
    if "EUR" in u and "USD" in u:
        return AssetClass.FX_EUR_QUOTE
    index_keys = (
        "US30",
        "US500",
        "SPX",
        "SP500",
        "NAS",
        "NDX",
        "USTEC",
        "US100",
        "DJ30",
        "DOW",
        "DE30",
        "GER40",
        "UK100",
    )
    if any(k in u for k in index_keys):
        return AssetClass.INDEX
    return AssetClass.OTHER


def env_float_for_symbol(symbol: str, env_key: str, default: float) -> float:
    """
    Orden: ``{env_key}_{SYMBOL}`` (ej. IA_AUTO_SL_ATR_MULT_EURUSD) → ``env_key`` global.
    """
    sym = symbol.upper().replace(".", "").replace("#", "").replace("_", "")
    for key in (f"{env_key}_{sym}", env_key):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return float(default)


def symbol_sl_atr_mult(symbol: str) -> float:
    """Multiplicador ATR para SL inicial (por clase; override por símbolo en .env)."""
    cls = classify_trade_symbol(symbol)
    defaults = {
        AssetClass.GOLD: 2.0,
        AssetClass.FX_EUR_QUOTE: 1.6,
        AssetClass.FX_JPY: 1.6,
        AssetClass.INDEX: 2.2,
        AssetClass.OTHER: 1.6,
    }
    base = defaults.get(cls, 1.6)
    return env_float_for_symbol(
        symbol,
        "IA_AUTO_SL_ATR_MULT",
        env_float_for_symbol(symbol, "IA_ATR_SL_MULT", base),
    )


def symbol_trail_atr_mult(symbol: str) -> float:
    cls = classify_trade_symbol(symbol)
    defaults = {
        AssetClass.GOLD: 2.5,
        AssetClass.FX_EUR_QUOTE: 2.0,
        AssetClass.FX_JPY: 2.0,
        AssetClass.INDEX: 2.5,
        AssetClass.OTHER: 2.5,
    }
    base = defaults.get(cls, 2.5)
    return env_float_for_symbol(symbol, "IA_AUTO_TRAIL_ATR_MULT", base)


def dxy_blocks_buy(symbol: str) -> bool:
    """
    DXY alcista: bloquea COMPRAS en oro y EURUSD.
    DXY bajista: bloquea COMPRAS en USDJPY (yen fuerte).
    Índices: sin filtro DXY por defecto (IA_DXY_INDEX_FILTER=1 para activar bloqueo en risk-off).
    """
    from ia_auto_expert import get_dxy_bias_cached

    bias = get_dxy_bias_cached()
    if bias in ("OFF", "NEUTRAL", "UNKNOWN"):
        return False

    cls = classify_trade_symbol(symbol)
    if cls in (AssetClass.GOLD, AssetClass.FX_EUR_QUOTE):
        return bias == "BULLISH"
    if cls == AssetClass.FX_JPY:
        return bias == "BEARISH"
    if cls == AssetClass.INDEX:
        if os.environ.get("IA_DXY_INDEX_FILTER", "0").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            return False
        return bias == "BEARISH"
    return False


def dxy_context_line(symbol: str) -> str:
    from ia_auto_expert import get_dxy_bias_cached

    bias = get_dxy_bias_cached()
    cls = classify_trade_symbol(symbol).value
    block = dxy_blocks_buy(symbol)
    return f"DXY={bias} | clase={cls} | bloquea_COMPRA={block}"
