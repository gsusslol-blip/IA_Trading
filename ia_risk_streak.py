"""
Modificador de riesgo por racha de pérdidas (deals MT5 del bot).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from mt5_prices import BOT_MAGIC

_CIRCUIT_UNTIL_MONO: float = 0.0
_LAST_STREAK_MULT: float = 1.0


def _env_on(key: str, default: str = "0") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")


def consecutive_bot_losses(
    *,
    lookback_hours: float = 72.0,
    symbol: str | None = None,
    magic_number: int | None = None,
) -> int:
    """
    Cuenta pérdidas consecutivas desde la más reciente (solo posiciones cerradas con PnL neto < 0).
    ``symbol`` opcional: solo deals de ese símbolo MT5.
    """
    if not _env_on("IA_STREAK_ENABLE", "1"):
        return 0
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=max(1.0, float(lookback_hours)))
    try:
        mt5.history_select(start, now)
    except Exception:
        pass
    deals = mt5.history_deals_get(start, now)
    if not deals:
        return 0

    by_pid: dict[int, list] = {}
    magic_want = int(magic_number) if magic_number is not None else BOT_MAGIC
    sym_u = symbol.upper().strip() if symbol else ""
    for d in deals:
        if int(getattr(d, "magic", -1) or -1) != magic_want:
            continue
        if sym_u and str(getattr(d, "symbol", "") or "").upper() != sym_u:
            continue
        pid = int(getattr(d, "position_id", 0) or 0)
        if pid <= 0:
            continue
        by_pid.setdefault(pid, []).append(d)

    closed: list[tuple[int, float]] = []
    for pid, dl in by_pid.items():
        dl.sort(key=lambda x: int(getattr(x, "time", 0) or 0))
        total = 0.0
        last_t = 0
        for d in dl:
            total += float(getattr(d, "profit", 0.0) or 0.0)
            total += float(getattr(d, "commission", 0.0) or 0.0)
            total += float(getattr(d, "swap", 0.0) or 0.0)
            if int(getattr(d, "entry", -1) or -1) == mt5.DEAL_ENTRY_OUT:
                last_t = int(getattr(d, "time", 0) or 0)
        if last_t > 0:
            closed.append((last_t, total))

    if not closed:
        return 0
    closed.sort(key=lambda x: x[0], reverse=True)

    streak = 0
    for _t, pnl in closed:
        if pnl < -1e-8:
            streak += 1
        else:
            break
    return streak


def trading_halted_by_streak() -> tuple[bool, str]:
    """True si el cortacircuitos temporal está activo."""
    global _CIRCUIT_UNTIL_MONO
    if _CIRCUIT_UNTIL_MONO <= 0:
        return False, ""
    if time.monotonic() >= _CIRCUIT_UNTIL_MONO:
        _CIRCUIT_UNTIL_MONO = 0.0
        return False, ""
    rem = _CIRCUIT_UNTIL_MONO - time.monotonic()
    return True, f"cortacircuitos {rem / 3600.0:.1f}h restantes"


def refresh_streak_risk_state() -> dict[str, float | int | bool]:
    """
    Actualiza multiplicador de riesgo y cortacircuitos; retorna snapshot para logs.
    """
    global _CIRCUIT_UNTIL_MONO, _LAST_STREAK_MULT
    if not _env_on("IA_STREAK_ENABLE", "1"):
        _LAST_STREAK_MULT = 1.0
        return {"enabled": False, "streak": 0, "mult": 1.0, "halted": False}

    try:
        need = int(os.environ.get("IA_STREAK_LOSSES", "3").strip() or "3")
    except ValueError:
        need = 3
    need = max(1, min(20, need))

    streak = consecutive_bot_losses()
    mult = 1.0
    if streak >= need:
        if _env_on("IA_STREAK_HALVE_RISK", "1"):
            mult = float(os.environ.get("IA_STREAK_RISK_MULT", "0.5").strip() or "0.5")
            mult = max(0.05, min(1.0, mult))
        try:
            halt_h = float(os.environ.get("IA_STREAK_HALT_HOURS", "0").strip() or "0")
        except ValueError:
            halt_h = 0.0
        if halt_h > 0:
            _CIRCUIT_UNTIL_MONO = time.monotonic() + halt_h * 3600.0
    else:
        if streak == 0:
            _CIRCUIT_UNTIL_MONO = 0.0
        mult = 1.0

    _LAST_STREAK_MULT = mult
    halted, _ = trading_halted_by_streak()
    return {
        "enabled": True,
        "streak": streak,
        "mult": mult,
        "halted": halted,
        "need": need,
    }


def apply_streak_to_risk_percent(risk_percent: float) -> float:
    """Aplica el multiplicador de racha al % de riesgo configurado."""
    refresh_streak_risk_state()
    return float(risk_percent) * float(_LAST_STREAK_MULT)


def verificar_cortacircuitos(
    symbol: str,
    magic_number: int | None = None,
    max_perdidas_seguidas: int = 3,
) -> bool:
    """
    API de integración: True = cuenta sana (puede operar), False = cortacircuitos activo.

    Respeta ``IA_STREAK_ENABLE``, halt temporal (``IA_STREAK_HALT_HOURS``) y racha global o por símbolo.
    """
    if not _env_on("IA_STREAK_ENABLE", "1"):
        return True
    halted, _why = trading_halted_by_streak()
    if halted:
        return False
    per_sym = _env_on("IA_STREAK_PER_SYMBOL", "0")
    try:
        lookback_h = float(os.environ.get("IA_STREAK_LOOKBACK_HOURS", "24").strip() or "24")
    except ValueError:
        lookback_h = 24.0
    try:
        need = int(os.environ.get("IA_STREAK_LOSSES", str(max_perdidas_seguidas)).strip() or max_perdidas_seguidas)
    except ValueError:
        need = max_perdidas_seguidas
    need = max(1, min(20, need))
    streak = consecutive_bot_losses(
        lookback_hours=lookback_h,
        symbol=symbol if per_sym else None,
        magic_number=magic_number,
    )
    if streak >= need:
        print(
            f"[cortacircuitos] {symbol}: racha de {streak} pérdidas (límite {need}).",
            flush=True,
        )
        try:
            from ia_autonomy_notify import notify_circuit_breaker

            try:
                halt_h = float(os.environ.get("IA_STREAK_HALT_HOURS", "0").strip() or "0")
            except ValueError:
                halt_h = 0.0
            notify_circuit_breaker(
                symbol,
                streak=streak,
                limit=need,
                per_symbol=per_sym,
                halt_hours=halt_h,
            )
        except Exception as e:
            print(f"[cortacircuitos] alerta TG: {e}", flush=True)
        return False
    return True
