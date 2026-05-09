"""
Comprueba operaciones del bot (BOT_MAGIC) en MT5 en la última ventana de horas.

Si no hay deals en ese intervalo, incrementa un nivel y ajusta `params_optimized.json`
(un paso más permisivo cada ejecución vacía).

Uso:
  python check_idle_tune.py
  python check_idle_tune.py --hours 2

Programar (Windows): ver `schedule_idle_check_2h.ps1`
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

from local_env import load_env_file


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _state_path() -> Path:
    return _project_root() / "ia_idle_tune_state.json"


def _params_path() -> Path:
    return _project_root() / "params_optimized.json"


def _log(msg: str) -> None:
    p = _project_root() / "ia_idle_tune.log"
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(msg)


def count_deals_with_magic(*, hours: float, magic: int) -> int:
    utc_to = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(hours=hours)
    wide_from = utc_from - timedelta(days=2)
    try:
        mt5.history_select(wide_from, utc_to)
    except Exception:
        pass
    deals = mt5.history_deals_get(wide_from, utc_to)
    if not deals:
        return 0
    ts_cut = int(utc_from.timestamp())
    ts_hi = int(utc_to.timestamp())
    n = 0
    for d in deals:
        if int(getattr(d, "magic", -1) or -1) != int(magic):
            continue
        t = int(getattr(d, "time", 0) or 0)
        if ts_cut <= t <= ts_hi:
            n += 1
    return n


def apply_tune_step(params: dict[str, Any], step: int) -> list[str]:
    """Aplica un solo paso; devuelve lista de cambios descriptivos."""
    changes: list[str] = []
    if step == 1:
        mc = int(float(params.get("IA_MIN_CONFIDENCE", 62)))
        lo = int(float(params.get("IA_BREAKOUT_LOOKBACK", 18)))
        cp = int(float(params.get("IA_REGIME_ATR_CRISIS_PCTL", 97)))
        nmc = max(52, mc - 3)
        nlo = max(10, lo - 3)
        ncp = min(99, cp + 1)
        if nmc != mc:
            params["IA_MIN_CONFIDENCE"] = nmc
            changes.append(f"IA_MIN_CONFIDENCE {mc}->{nmc}")
        if nlo != lo:
            params["IA_BREAKOUT_LOOKBACK"] = nlo
            changes.append(f"IA_BREAKOUT_LOOKBACK {lo}->{nlo}")
        if ncp != cp:
            params["IA_REGIME_ATR_CRISIS_PCTL"] = ncp
            changes.append(f"IA_REGIME_ATR_CRISIS_PCTL {cp}->{ncp}")
    elif step == 2:
        if int(params.get("ATR_FILTER", 1)) != 0:
            params["ATR_FILTER"] = 0
            changes.append("ATR_FILTER -> 0")
    elif step == 3:
        if str(params.get("IA_REGIME_ENABLE", "1")) != "0":
            params["IA_REGIME_ENABLE"] = "0"
            changes.append("IA_REGIME_ENABLE -> 0")
    elif step == 4:
        mc = int(float(params.get("IA_MIN_CONFIDENCE", 55)))
        lo = int(float(params.get("IA_BREAKOUT_LOOKBACK", 15)))
        nmc = max(50, mc - 4)
        nlo = max(10, lo - 3)
        if nmc != mc:
            params["IA_MIN_CONFIDENCE"] = nmc
            changes.append(f"IA_MIN_CONFIDENCE {mc}->{nmc}")
        if nlo != lo:
            params["IA_BREAKOUT_LOOKBACK"] = nlo
            changes.append(f"IA_BREAKOUT_LOOKBACK {lo}->{nlo}")
    elif step == 5:
        mc = int(float(params.get("IA_MIN_CONFIDENCE", 50)))
        nmc = max(48, mc - 3)
        if nmc != mc:
            params["IA_MIN_CONFIDENCE"] = nmc
            changes.append(f"IA_MIN_CONFIDENCE {mc}->{nmc}")
    else:
        changes.append("(sin más pasos automáticos; revisar manualmente)")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--hours",
        type=float,
        default=float(os.environ.get("IA_IDLE_CHECK_HOURS", "2").strip() or "2"),
        help="Ventana hacia atrás para buscar deals del bot (horas).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra qué haría sin escribir JSON.",
    )
    args = ap.parse_args()
    hours = max(0.25, args.hours)

    load_env_file()
    magic = int(os.environ.get("BOT_MAGIC", "260505"))
    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        _log(f"[idle-tune] MT5 init falló: {mt5.last_error()}")
        return 1

    try:
        n = count_deals_with_magic(hours=hours, magic=magic)
        _log(f"[idle-tune] deals magic={magic} (cualquier símbolo) últimas {hours}h: {n}")

        st: dict[str, Any] = {}
        sp = _state_path()
        if sp.is_file():
            try:
                st = json.loads(sp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                st = {}

        if n > 0:
            st["tier"] = 0
            st["last_trade_seen_utc"] = datetime.now(timezone.utc).isoformat()
            if not args.dry_run:
                sp.write_text(json.dumps(st, indent=2), encoding="utf-8")
            _log("[idle-tune] Hay actividad; contador de ajustes en 0. Sin cambios.")
            return 0

        tier = int(st.get("tier", 0))
        max_tier = 5
        if tier >= max_tier:
            _log("[idle-tune] Ya aplicado nivel máximo; revisar mercado/reglas.")
            return 0

        new_step = tier + 1
        pp = _params_path()
        if not pp.is_file():
            _log(f"[idle-tune] Falta {pp.name}")
            return 2

        data = json.loads(pp.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            _log("[idle-tune] params JSON inválido")
            return 2

        chg = apply_tune_step(data, new_step)
        data["last_idle_tune_utc"] = datetime.now(timezone.utc).isoformat()
        data["last_idle_tune_step"] = new_step
        st["tier"] = new_step
        st["last_idle_tune_utc"] = data["last_idle_tune_utc"]

        if args.dry_run:
            _log(f"[idle-tune] dry-run paso {new_step}: {chg}")
            return 0

        with pp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

        sp.write_text(json.dumps(st, indent=2), encoding="utf-8")
        _log(
            f"[idle-tune] Sin operaciones: aplicado paso {new_step}/{max_tier}. "
            + ("; ".join(chg) if chg else "sin cambios de clave conocidas")
        )
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main())
