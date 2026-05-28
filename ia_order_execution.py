"""
Ejecución MT5: prioridad de ORDER_FILLING según ``symbol_info.filling_mode``.

Variables:
  IA_FILLING_PREFER=ioc,fok,return   — orden de preferencia global
  IA_FILLING_GOLD_PREFER=ioc,fok,return — override para XAU/GOLD
"""

from __future__ import annotations

import os


def _mt5():
    import MetaTrader5 as mt5

    return mt5


def _is_gold(symbol: str) -> bool:
    u = symbol.upper().replace(" ", "")
    return "XAU" in u or "GOLD" in u


def _filling_constants() -> dict[str, int]:
    try:
        mt5 = _mt5()
        return {
            "fok": int(mt5.ORDER_FILLING_FOK),
            "ioc": int(mt5.ORDER_FILLING_IOC),
            "return": int(mt5.ORDER_FILLING_RETURN),
        }
    except Exception:
        return {"fok": 0, "ioc": 1, "return": 2}


def _parse_preference_list(raw: str) -> list[int]:
    name_to_const = _filling_constants()
    out: list[int] = []
    for part in raw.lower().replace(" ", "").split(","):
        if not part:
            continue
        c = name_to_const.get(part)
        if c is not None and c not in out:
            out.append(c)
    c = _filling_constants()
    default = [c["ioc"], c["fok"], c["return"]]
    return out or default


def _preference_order(symbol: str) -> list[int]:
    key = "IA_FILLING_GOLD_PREFER" if _is_gold(symbol) else "IA_FILLING_PREFER"
    default = "ioc,fok,return" if _is_gold(symbol) else "fok,ioc,return"
    raw = os.environ.get(key, os.environ.get("IA_FILLING_PREFER", default)).strip() or default
    return _parse_preference_list(raw)


def _allowed_mask(symbol: str) -> list[int]:
    mt5 = _mt5()
    info = mt5.symbol_info(symbol)
    if info is None:
        return [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]
    mask = int(getattr(info, "filling_mode", 0) or 0)
    all_modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
    allowed = [m for m in all_modes if mask & (1 << m)]
    return allowed if allowed else [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]


def prioridad_filling_modes(symbol: str) -> list[int]:
    """Modos permitidos por el bróker, ordenados por preferencia institucional (oro → IOC primero)."""
    allowed = set(_allowed_mask(symbol))
    ordered: list[int] = []
    for mode in _preference_order(symbol):
        if mode in allowed and mode not in ordered:
            ordered.append(mode)
    for mode in allowed:
        if mode not in ordered:
            ordered.append(mode)
    return ordered


def obtener_tipo_llenado_broker(symbol: str) -> int:
    """Modo de llenado recomendado (primer candidato compatible)."""
    mt5 = _mt5()
    modes = prioridad_filling_modes(symbol)
    return modes[0] if modes else mt5.ORDER_FILLING_FOK
