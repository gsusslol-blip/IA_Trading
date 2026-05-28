"""
Bucle de escaneo: M15 (patrón + volumen) alineado con tendencia H4 (precio vs SMA20).

  python ia_scanner_loop.py

Ctrl+C para salir.

Variables .env (opcionales):
  IA_SCAN_SYMBOLS     — comas, default XAUUSD
  IA_SCAN_INTERVAL_S  — segundos entre rondas (default 30)
  IA_SCAN_HOUR_START  — hora local inicio ventana (default 9)
  IA_SCAN_HOUR_END    — hora local fin (default 18)
    Si START > END (ej. 22 y 6), la ventana cruza medianoche (22:00–06:59 hora local).
  IA_LIQUIDITY_SESSION_NY_ENABLE — si 1, solo señales dentro de IA_LIQUIDITY_NY_HOUR_* hora NY
  IA_PRO_SESSION_TZ   — en ia_auto_expert, hora de sesión en zoneinfo (ej. America/New_York)
  IA_SCAN_QUIET       — si 1, solo imprime alertas confirmadas + fuera de horario ocasional
  IA_SLOPE_FILTER     — default 1; pendiente SMA H1 vs IA_SLOPE_MIN_ABS_PCT (régimen tendencia)
  IA_SCAN_VOLUME_RELAX — si 1, volumen M15 >= vela anterior (en vez de >); auto-relax o manual.
  IA_SCAN_SKIP_VOLUME_CONFIRM — si 1, ignora volumen tras engulfing+H4 (más trades en demo; más ruido).
  IA_SCAN_VOL_ROLL_BARS — si >0, filtro extra: tick_volume del gatillo vs media móvil en esa vela (requiere vol > media * IA_SCAN_VOL_FACTOR).
  IA_SCAN_SOFT_TRIGGER — si 1, vela impulsiva M15 (close vs open y vs vela anterior) en vez de engulfing estricto.
  IA_SCAN_SKIP_BREAKOUT — si 1, no exige ruptura del rango IA_BREAKOUT_LOOKBACK.
  IA_MT5_RATES_CACHE — si 1, caché de rates: sonda 1 vela y reutiliza bloque si no cambió la barra actual (mt5_prices + ``mt5_price_engine``).
  IA_SCAN_CLOSED_BAR_ONLY — default 1; si 0, señal sobre vela en formación (legacy; ver IA_SCAN_SIGNAL_ON_FORMING_BAR).
  IA_SCAN_SIGNAL_ON_FORMING_BAR — si 1, live usa iloc[-1]/[-2]; por defecto 0 → gatillo en vela cerrada (-2/-3).
  IA_SCAN_DEBUG_FILTERS — si 1, imprime motivo de cada descarte (ver log_filtro_descarte).
  IA_DXY_SCORE_ENABLE — mezcla DXY en el score final (ver signal_analysis.get_dxy_modifier).
  IA_MACRO_SCORE_SESSION_ENABLE / IA_MACRO_SCORE_SESSION_PENALTY — penalizar score fuera NY.
  IA_SCAN_DASHBOARD=1 — pantalla tipo radiografía tras score maestro (IA_SCAN_DASHBOARD_CLEAR=0 no borra consola).
  IA_REGIME_ENABLE — meta-capa régimen (ADX/ATR/Z/rango); ver market_regime.py.
  IA_H4_EMA_ALIGN_ENABLE — precio vs EMA H4 (distancia mínima % opcional).
  IA_M15_MOMENTUM_ENABLE — cuerpo/rango y cierre en tercio (vela operativa M15).
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5
import pandas as pd

from local_env import apply_optuna_overrides as _apply_optuna_overrides, load_env_file
from ia_replay import IAReplaySnapshot, dataframe_for_regime, replay_from_m15_h4_windows
from market_regime import regime_gate_should_skip, regime_gate_should_skip_from_hlc
from m15_ma_scan import _resolve_scan_symbol
from mt5_price_engine import PriceEngine, get_price_engine, rates_df_time_as_unix_seconds
from mt5_prices import mt5_copy_rates_from_pos_cached
from signal_analysis import (
    MarketPackRatesReplay,
    analyze_market_pack,
    aplicar_score_macro,
    get_dxy_modifier,
    macro_session_score_penalty_points,
)

TF_OPERATIVA = mt5.TIMEFRAME_M15
TF_MAYOR = mt5.TIMEFRAME_H4


def _resolve_ia_engine(engine: PriceEngine | None) -> PriceEngine:
    return engine if engine is not None else get_price_engine()


def _df_from_engine(pe: PriceEngine, symbol: str, tf: int, n: int) -> pd.DataFrame | None:
    df = pe.get_data(symbol, tf, n)
    return None if df is None or df.empty else df


def _scan_cfg_int(
    cfg: dict[str, Any] | None,
    cfg_key: str,
    env_key: str,
    *,
    default: int,
    lo: int,
    hi: int,
) -> int:
    if cfg:
        raw_c = cfg.get(cfg_key)
        if raw_c is not None and str(raw_c).strip() != "":
            try:
                return max(lo, min(hi, int(raw_c)))
            except (TypeError, ValueError):
                pass
    try:
        v = int(os.environ.get(env_key, str(default)).strip() or str(default))
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def _scan_cfg_bool(
    cfg: dict[str, Any] | None,
    cfg_key: str,
    env_key: str,
    *,
    default: bool = False,
) -> bool:
    if cfg:
        raw_c = cfg.get(cfg_key)
        if raw_c is not None and str(raw_c).strip() != "":
            return str(raw_c).strip().lower() in ("1", "true", "yes", "on")
    return os.environ.get(env_key, "1" if default else "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _scan_cfg_float(
    cfg: dict[str, Any] | None,
    cfg_key: str,
    env_key: str,
    *,
    default: float,
    lo: float,
    hi: float,
) -> float:
    if cfg:
        raw_c = cfg.get(cfg_key)
        if raw_c is not None and str(raw_c).strip() != "":
            try:
                return max(lo, min(hi, float(raw_c)))
            except (TypeError, ValueError):
                pass
    try:
        v = float(os.environ.get(env_key, str(default)).strip() or str(default))
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def _trigger_prev_ilocs(is_replay_snap: bool, use_closed_live: bool) -> tuple[int, int]:
    """
    Índices **negativos** en df_m15: vela del gatillo y la previa.
    ``iloc[-1]`` es la barra actual (replay / forming); live robusto usa ``-2/-3``.
    """
    if is_replay_snap:
        return -1, -2
    if use_closed_live:
        return -2, -3
    return -1, -2


def _filtros_debug_activos() -> bool:
    return os.environ.get("IA_SCAN_DEBUG_FILTERS", "0").strip().lower() in ("1", "true", "yes")

def _decision_log_activo() -> bool:
    return os.environ.get("IA_SCAN_DECISION_LOG", "0").strip().lower() in ("1", "true", "yes")


def _decision_log_path() -> Path:
    root = Path(__file__).resolve().parent
    name = os.environ.get("IA_SCAN_DECISION_LOG_CSV", "").strip() or "scan_decisions.csv"
    return (Path(name) if Path(name).is_absolute() else (root / name))


def _decision_log_append(row: list[str]) -> None:
    """
    Append simple CSV line for audit. Best-effort: never raises.
    Columns are written once if file is new.
    """
    if not _decision_log_activo():
        return
    try:
        p = _decision_log_path()
        write_header = not p.is_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="") as f:
            if write_header:
                f.write(
                    "time_local,symbol,stage,reason,actual,required,signal,conf_tech,conf_final,mod_dxy,pen_session,spread_pts\n"
                )
            f.write(",".join([s.replace("\n", " ").replace("\r", " ").replace(",", ";") for s in row]) + "\n")
    except Exception:
        return


def log_filtro_descarte(
    motivo: str,
    valor_actual: float | int | str,
    umbral_requerido: float | int | str,
    *,
    simbolo: str = "",
) -> None:
    """
    Consola: por qué se descartó una posible señal (solo si IA_SCAN_DEBUG_FILTERS=1).
    `valor_actual` / `umbral_requerido` pueden ser número o texto corto.
    """
    if not _filtros_debug_activos():
        return
    pre = f"{simbolo} | " if simbolo else ""
    if isinstance(valor_actual, str):
        va = valor_actual
    else:
        va = f"{float(valor_actual):.6g}" if isinstance(valor_actual, float) else str(valor_actual)
    if isinstance(umbral_requerido, str):
        ur = umbral_requerido
    else:
        ur = (
            f"{float(umbral_requerido):.6g}"
            if isinstance(umbral_requerido, float)
            else str(umbral_requerido)
        )
    print(f"{pre}[FILTRO] descartado | {motivo:24} | actual={va} | requerido={ur}")
    # Persist audit line (optional)
    _decision_log_append(
        [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            simbolo or "",
            "discard",
            motivo,
            va,
            ur,
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )


def iniciar_mt5() -> bool:
    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        print(f"Error al conectar MT5. ({code}) {msg}", file=sys.stderr)
        return False
    print("Conectado. Escaneando (Ctrl+C para salir).")
    return True


def obtener_datos(simbolo: str, tf: int, cantidad: int) -> pd.DataFrame | None:
    df = get_price_engine().get_data(simbolo, tf, cantidad)
    return None if df is None or df.empty else df


def validate_scan_session_env() -> None:
    """
    Valida IA_SCAN_HOUR_START / IA_SCAN_HOUR_END (enteros 0–23).
    Usar tras cargar .env / Optuna en procesos que escanean.
    """
    for key, default in (("IA_SCAN_HOUR_START", "9"), ("IA_SCAN_HOUR_END", "18")):
        raw = os.environ.get(key, default).strip() or default
        try:
            h = int(raw)
        except ValueError:
            print(f"[ENV] {key} debe ser entero 0-23, recibí {raw!r}", file=sys.stderr)
            raise SystemExit(1)
        if not (0 <= h <= 23):
            print(f"[ENV] {key} debe estar entre 0 y 23, recibí {h}", file=sys.stderr)
            raise SystemExit(1)


def es_horario_seguro() -> bool:
    try:
        h_start = int(os.environ.get("IA_SCAN_HOUR_START", "9").strip() or "9")
        h_end = int(os.environ.get("IA_SCAN_HOUR_END", "18").strip() or "18")
    except ValueError:
        h_start, h_end = 9, 18
    h_start = max(0, min(23, h_start))
    h_end = max(0, min(23, h_end))
    hora = datetime.now().hour
    if h_start <= h_end:
        return h_start <= hora <= h_end
    # Ventana que cruza medianoche (p. ej. 22–06 hora local)
    return hora >= h_start or hora <= h_end


def es_horario_operable_ny() -> bool:
    """
    Filtro opcional por liquidez en hora Nueva York (America/New_York), p. ej. 8–16.
    IA_LIQUIDITY_SESSION_NY_ENABLE=1 para activar (no confundir con IA_SCAN_HOUR_* en hora local).
    """
    if os.environ.get("IA_LIQUIDITY_SESSION_NY_ENABLE", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return True
    try:
        from zoneinfo import ZoneInfo

        h = datetime.now(ZoneInfo("America/New_York")).hour
    except Exception:
        h = datetime.now().hour
    try:
        h_start = int(os.environ.get("IA_LIQUIDITY_NY_HOUR_START", "8").strip() or "8")
        h_end = int(os.environ.get("IA_LIQUIDITY_NY_HOUR_END", "16").strip() or "16")
    except ValueError:
        return True
    return h_start <= h <= h_end


def _scanner_simbolo_es_oro(simbolo: str) -> bool:
    u = simbolo.upper().replace(" ", "")
    return "XAU" in u or "GOLD" in u


def sesion_operable_dashboard() -> bool:
    """Ventana local de escaneo ∩ ventana NY (esta última ignorada si liquidez NY está off)."""
    return es_horario_seguro() and es_horario_operable_ny()


def _dashboard_activo() -> bool:
    return os.environ.get("IA_SCAN_DASHBOARD", "0").strip().lower() in ("1", "true", "yes")


def _dashboard_clear_screen() -> bool:
    if os.environ.get("IA_SCAN_DASHBOARD_CLEAR", "1").strip().lower() in ("0", "false", "no"):
        return False
    return True


def _spread_pts_dashboard(simbolo: str) -> float | None:
    try:
        from mt5_prices import spread_points_from_tick

        return spread_points_from_tick(simbolo)
    except Exception:
        return None


def _lim_spread_points_env() -> int | None:
    raw = os.environ.get("IA_AUTO_MAX_SPREAD_POINTS", os.environ.get("MAX_SPREAD_POINTS", "")).strip()
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    return n if n > 0 else None


def _h4_ema_last(df_h4: pd.DataFrame, period: int) -> float | None:
    """EMA sobre close H4 (última vela del dataframe)."""
    if df_h4 is None or len(df_h4) < period + 2:
        return None
    ser = df_h4["close"].ewm(span=period, adjust=False).mean()
    v = ser.iloc[-1]
    if pd.isna(v):
        return None
    return float(v)


def _filtro_h4_ema_alineado(base: str, precio_h4: float, ema_h4: float, *, min_dist_pct: float) -> bool:
    """
    BUY: precio H4 al menos min_dist_pct % por encima de la EMA (si min_dist_pct=0, solo precio > ema).
    SELL: análogo por debajo.
    """
    if ema_h4 <= 0 or precio_h4 <= 0:
        return False
    dist_pct = (precio_h4 - ema_h4) / ema_h4 * 100.0
    if base == "BUY":
        return dist_pct >= min_dist_pct
    if base == "SELL":
        return dist_pct <= -min_dist_pct
    return False


def _filtro_m15_momentum_vela(
    base: str,
    row,
    *,
    min_body_ratio: float,
    close_in_third: bool,
) -> tuple[bool, str]:
    """
    Impulso en la vela operativa M15: body/range y opcionalmente cierre en tercio superior (BUY) o inferior (SELL).
    """
    try:
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
    except Exception:
        return False, "datos_vela"
    rng = h - l
    if rng <= 1e-12:
        return False, "rango_cero"
    body = abs(c - o)
    br = body / rng
    if br < min_body_ratio:
        return False, f"body_ratio={br:.3f}"
    if not close_in_third:
        return True, ""
    pos = (c - l) / rng
    if base == "BUY":
        if pos < (2.0 / 3.0):
            return False, f"close_tercio={pos:.3f}"
    else:
        if pos > (1.0 / 3.0):
            return False, f"close_tercio={pos:.3f}"
    return True, ""


def mostrar_dashboard_decision(
    *,
    simbolo: str,
    score_base: int,
    mod_dxy: int,
    pen_sesion: int,
    score_final: int,
    min_conf: int,
    passes_rsi: bool,
    passes_atr: bool,
    rsi_m5: float | None,
    spread_pts: float | None,
    lim_spread_pts: int | None,
) -> None:
    """
    Radiografía consola tras aplicar filtros hasta el score maestro.
    IA_SCAN_DASHBOARD=1 para activar.
    """
    if not _dashboard_activo():
        return
    if _dashboard_clear_screen():
        if os.name == "nt":
            os.system("cls")  # noqa: S605,S607
        else:
            os.system("clear")  # noqa: S605,S607

    now_s = datetime.now().strftime("%H:%M:%S")
    sep = "=" * 50
    print(sep)
    print(f" 🤖 IA TRADING BOT | ACTIVO: {simbolo} | {now_s}")
    print(sep)
    print(f" [IA] Score base:      {score_base:>6d}")
    emoji_dxy = "🟢" if mod_dxy > 0 else "🔴" if mod_dxy < 0 else "⚪"
    print(f" [DXY] Modificador:    {emoji_dxy} {mod_dxy:+d}")
    mac_on = os.environ.get("IA_MACRO_SCORE_SESSION_ENABLE", "0").strip().lower() in ("1", "true", "yes")
    pen_lab = f"-{pen_sesion}" if mac_on and pen_sesion else "0"
    print(f" [MACRO] Penal. NY:    {pen_lab} pts (IA_MACRO_SCORE_SESSION_ENABLE={'1' if mac_on else '0'})")

    hora_ok = sesion_operable_dashboard()
    estado_hora = "✅ OPEN" if hora_ok else "❌ CLOSED"
    print(f" [TIME] Sesión:        {estado_hora}  (scan local + NY si liquidez)")
    print(f" [FILT] RSI ok:        {'SÍ' if passes_rsi else 'NO'}  |  ATR ok: {'SÍ' if passes_atr else 'NO'}")
    if rsi_m5 is not None:
        print(f" [RSI] M5:             {rsi_m5:.1f}")
    print("-" * 50)

    cumple = score_final >= min_conf
    emoji_op = "✅ SI" if cumple else "❌ NO"
    print(f" [TOTAL] Score final:  {score_final:>6d}")
    print(f" [UMBRAL] Requerido:   {min_conf:>6d}")
    print(f" [OPERAR] ¿Aprobado?:  {emoji_op}")
    print("-" * 50)
    if spread_pts is not None:
        lim_s = f" lim {lim_spread_pts}" if lim_spread_pts else ""
        print(f" [SPREAD] Actual:      {spread_pts:.1f} pts{lim_s}")
    else:
        print(" [SPREAD] Actual:      N/D")
    print(sep)


def analizar_ia(
    simbolo: str,
    timeframe_m15: int | None = None,
    timeframe_h4: int | None = None,
    *,
    replay: IAReplaySnapshot | None = None,
    df_m15_override: pd.DataFrame | None = None,
    df_h4_override: pd.DataFrame | None = None,
    engine: PriceEngine | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    """
    Señal operativa:
    - Gatillo base: patrón tipo engulfing M15 + volumen + filtro H4.
    - Estructura: breakout M15 sobre/bajo rango reciente (IA_BREAKOUT_LOOKBACK).
    - Régimen (meta): `market_regime` — ADX/ATR/Z/rango (IA_REGIME_*), antes del gatillo.
    - Pendiente SMA H1 (IA_SLOPE_*): filtro adicional de tendencia vs chop.
    - Opcional: alineación EMA H4 (IA_H4_EMA_*); momentum vela M15 (IA_M15_MOMENTUM_*).
    - Filtro/score: `signal_analysis.analyze_market_pack` (multi‑TF + RSI + ATR).

    Modos datos:
      * Live: ``PriceEngine`` → ``get_data`` (caché MT5). Si ``engine`` es None se usa la instancia global.
      * ``replay``: instantánea multi‑TF ya alineada (backtest sin lookahead).
      * ``df_m15_override`` / ``df_h4_override``: se arma ``replay`` vía MT5 para M5/H1 (ver ``replay_from_m15_h4_windows``).
      * Live: por defecto gatillo en **vela cerrada** (``iloc[-2]``). ``IA_SCAN_SIGNAL_ON_FORMING_BAR=1`` o ``IA_SCAN_CLOSED_BAR_ONLY=0`` restaura usar la barra en formación.

    ``config`` (p. ej. desde params optimizados): opcional ``m15_context_bars``, ``breakout_lookback``,
    ``vol_roll_bars`` (0=desactivado; >0 exige tick_volume > media móvil * ``vol_factor`` en la vela gatillo),
    ``vol_factor`` (default 1.0; env ``IA_SCAN_VOL_FACTOR``).

    Núcleo índices: ``v_trigger`` / ``v_previa`` (M15) y ``v_h4`` = última fila de ``df_h4_for_trend``.

    timeframe_m15 / timeframe_h4: si None → M15/H4 estándar del módulo.
    """
    if replay is not None and (
        df_m15_override is not None or df_h4_override is not None
    ):
        return "Error: no usar replay junto con df_m15_override / df_h4_override"

    cfg: dict[str, Any] = dict(config) if config else {}
    pe = _resolve_ia_engine(engine)

    tf_m15_use = timeframe_m15 if timeframe_m15 is not None else TF_OPERATIVA
    tf_h4_use = timeframe_h4 if timeframe_h4 is not None else TF_MAYOR

    m15_need = _scan_cfg_int(
        cfg, "m15_context_bars", "IA_M15_CONTEXT_BARS", default=120, lo=60, hi=800
    )

    replay_eff: IAReplaySnapshot | None = replay
    if replay_eff is None and (df_m15_override is not None or df_h4_override is not None):
        dm_raw = (
            df_m15_override
            if df_m15_override is not None
            else _df_from_engine(pe, simbolo, tf_m15_use, m15_need)
        )
        dh_raw = (
            df_h4_override
            if df_h4_override is not None
            else _df_from_engine(pe, simbolo, tf_h4_use, max(80, 60))
        )
        if dm_raw is None or dh_raw is None or len(dm_raw) < 60 or len(dh_raw) < 20:
            return "Error datos M15/H4 (overrides)"
        dm = rates_df_time_as_unix_seconds(dm_raw)
        dh = rates_df_time_as_unix_seconds(dh_raw)
        if dm is None or dh is None:
            return "Error datos M15/H4 (overrides)"
        replay_eff = replay_from_m15_h4_windows(simbolo, dm, dh)
        if replay_eff is None:
            return "Error construyendo replay desde overrides"

    if replay_eff is not None:
        df_h4 = replay_eff.df_h4
        src = replay_eff.df_m15
        df_m15 = src.iloc[-m15_need:].copy() if len(src) > m15_need else src
    else:
        df_h4 = _df_from_engine(pe, simbolo, tf_h4_use, max(80, 60))
        if df_h4 is None or len(df_h4) < 20:
            return "Error datos H4"
        df_m15 = _df_from_engine(pe, simbolo, tf_m15_use, m15_need)
        if df_m15 is None or len(df_m15) < 60:
            return "Error datos M15"

    live_no_replay = replay_eff is None
    df_h4_for_trend = df_h4.iloc[:-1].copy() if live_no_replay and len(df_h4) >= 21 else df_h4
    v_h4 = df_h4_for_trend.iloc[-1]
    sma_h4 = df_h4_for_trend["close"].rolling(window=20).mean().iloc[-1]
    precio_h4 = float(v_h4["close"])
    if pd.isna(sma_h4):
        return "Error datos H4"
    sma_f = float(sma_h4)
    tendencia_h4 = "ALTA" if precio_h4 > sma_f else "BAJA"

    if replay_eff is None:
        skip_regime, regime_reason = regime_gate_should_skip(simbolo)
    else:
        dreg = dataframe_for_regime(replay_eff)
        if len(dreg) < 50:
            return "Sin señal clara"
        reg_h = [float(x) for x in dreg["high"].tolist()]
        reg_l = [float(x) for x in dreg["low"].tolist()]
        reg_c = [float(x) for x in dreg["close"].tolist()]
        skip_regime, regime_reason = regime_gate_should_skip_from_hlc(reg_h, reg_l, reg_c)
    if skip_regime:
        if _filtros_debug_activos():
            log_filtro_descarte(
                "REGIMEN_META",
                regime_reason,
                "módulo_tendencia_pausado",
                simbolo=simbolo,
            )
        return "Sin señal clara"

    lb_bp = _scan_cfg_int(
        cfg, "breakout_lookback", "IA_BREAKOUT_LOOKBACK", default=20, lo=10, hi=120
    )

    is_replay_snap = replay_eff is not None
    legacy_forming = os.environ.get("IA_SCAN_CLOSED_BAR_ONLY", "1").strip().lower() in (
        "0",
        "false",
        "no",
    )
    signal_on_forming = legacy_forming or os.environ.get(
        "IA_SCAN_SIGNAL_ON_FORMING_BAR", "0"
    ).strip().lower() in ("1", "true", "yes")
    use_closed_live = not signal_on_forming

    i_tr, i_pr = _trigger_prev_ilocs(is_replay_snap, use_closed_live)
    if is_replay_snap:
        need_rows = max(60, lb_bp + 4)
    elif use_closed_live:
        need_rows = max(60, lb_bp + 4, 63)
    else:
        need_rows = max(60, lb_bp + 4)
    if len(df_m15) < need_rows:
        return "Error datos M15"

    v_trigger = df_m15.iloc[i_tr]
    v_previa = df_m15.iloc[i_pr]

    vol_roll_bars = _scan_cfg_int(
        cfg, "vol_roll_bars", "IA_SCAN_VOL_ROLL_BARS", default=0, lo=0, hi=250
    )
    vol_factor = _scan_cfg_float(
        cfg, "vol_factor", "IA_SCAN_VOL_FACTOR", default=1.0, lo=0.01, hi=50.0
    )
    if vol_roll_bars > 0:
        avg_vol_s = df_m15["tick_volume"].rolling(vol_roll_bars).mean().iloc[i_tr]
        vt = float(v_trigger["tick_volume"])
        if pd.isna(avg_vol_s) or vt <= float(avg_vol_s) * vol_factor:
            if _filtros_debug_activos():
                log_filtro_descarte(
                    "VOLUMEN_ROLLING",
                    f"vol={vt:.4g} avg*fac={float(avg_vol_s) * vol_factor:.4g}" if not pd.isna(avg_vol_s) else vt,
                    f"media({vol_roll_bars}) * {vol_factor:g}",
                    simbolo=simbolo,
                )
            return "Sin señal clara"

    skip_vol_check = _scan_cfg_bool(cfg, "IA_SCAN_SKIP_VOLUME_CONFIRM", "IA_SCAN_SKIP_VOLUME_CONFIRM")
    vol_relax = _scan_cfg_bool(cfg, "IA_SCAN_VOLUME_RELAX", "IA_SCAN_VOLUME_RELAX")
    if skip_vol_check:
        vol_confirmado = True
    elif vol_relax:
        vol_confirmado = int(v_trigger["tick_volume"]) >= int(v_previa["tick_volume"])
    else:
        vol_confirmado = int(v_trigger["tick_volume"]) > int(v_previa["tick_volume"])
    alcista = float(v_trigger["close"]) > float(v_previa["open"]) and float(
        v_trigger["open"]
    ) < float(v_previa["close"])
    bajista = float(v_trigger["close"]) < float(v_previa["open"]) and float(
        v_trigger["open"]
    ) > float(v_previa["close"])

    soft_trig = _scan_cfg_bool(cfg, "IA_SCAN_SOFT_TRIGGER", "IA_SCAN_SOFT_TRIGGER")
    prev_close = float(v_previa["close"])
    cv = float(v_trigger["close"])
    ov = float(v_trigger["open"])
    impulse_buy = cv > ov and cv > prev_close
    impulse_sell = cv < ov and cv < prev_close

    quiet = os.environ.get("IA_SCAN_QUIET", "0").strip().lower() in ("1", "true", "yes")
    if not quiet:
        print(
            f"{simbolo} | H4: {tendencia_h4} | Vol: {'OK' if vol_confirmado else 'NO'}"
        )

    base = None
    if soft_trig:
        if impulse_buy and vol_confirmado and tendencia_h4 == "ALTA":
            base = "BUY"
        elif impulse_sell and vol_confirmado and tendencia_h4 == "BAJA":
            base = "SELL"
        else:
            if _filtros_debug_activos():
                st = (
                    f"soft impulse_buy={impulse_buy} impulse_sell={impulse_sell} "
                    f"vol_ok={vol_confirmado} H4={tendencia_h4}"
                )
                log_filtro_descarte("GATILLO_SOFT_M15_H4", st, "impulso+vol+H4", simbolo=simbolo)
            return "Sin señal clara"
    elif alcista and vol_confirmado and tendencia_h4 == "ALTA":
        base = "BUY"
    elif bajista and vol_confirmado and tendencia_h4 == "BAJA":
        base = "SELL"
    else:
        if _filtros_debug_activos():
            st = (
                f"alc={alcista} baj={bajista} vol_ok={vol_confirmado} "
                f"H4={tendencia_h4} need=BUY+ALTA|SELL+BAJA"
            )
            log_filtro_descarte("GATILLO_M15_H4", st, "patron+vol+H4 alineados", simbolo=simbolo)
        return "Sin señal clara"

    if os.environ.get("IA_H4_EMA_ALIGN_ENABLE", "0").strip().lower() in ("1", "true", "yes"):
        try:
            ema_p = int(os.environ.get("IA_H4_EMA_PERIOD", "20").strip() or "20")
        except ValueError:
            ema_p = 20
        ema_p = max(5, min(100, ema_p))
        try:
            min_dist = float(os.environ.get("IA_H4_EMA_MIN_DIST_PCT", "0").strip() or "0")
        except ValueError:
            min_dist = 0.0
        ema_h4 = _h4_ema_last(df_h4_for_trend, ema_p)
        if ema_h4 is None:
            if _filtros_debug_activos():
                log_filtro_descarte("H4_EMA_DATOS", "", f"EMA{ema_p} H4", simbolo=simbolo)
            return "Sin señal clara"
        if not _filtro_h4_ema_alineado(base, precio_h4, ema_h4, min_dist_pct=min_dist):
            if _filtros_debug_activos():
                dist_pct = (precio_h4 - ema_h4) / ema_h4 * 100.0 if ema_h4 else 0.0
                log_filtro_descarte(
                    "H4_EMA_ALIGN",
                    f"dist%={dist_pct:.4f} precio={precio_h4:.5f} ema={ema_h4:.5f}",
                    f">= {min_dist:.3f}% BUY | <= -{min_dist:.3f}% SELL",
                    simbolo=simbolo,
                )
            return "Sin señal clara"

    if os.environ.get("IA_M15_MOMENTUM_ENABLE", "0").strip().lower() in ("1", "true", "yes"):
        try:
            min_br = float(os.environ.get("IA_M15_MOMENTUM_MIN_BODY_RATIO", "0.45").strip() or "0.45")
        except ValueError:
            min_br = 0.45
        min_br = max(0.0, min(1.0, min_br))
        third_on = os.environ.get("IA_M15_MOMENTUM_CLOSE_IN_THIRD", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        ok_m, why_m = _filtro_m15_momentum_vela(
            base,
            v_trigger,
            min_body_ratio=min_br,
            close_in_third=third_on,
        )
        if not ok_m:
            if _filtros_debug_activos():
                log_filtro_descarte("M15_MOMENTUM", why_m, f"body>={min_br} tercio={third_on}", simbolo=simbolo)
            return "Sin señal clara"

    if (
        base == "BUY"
        and os.environ.get("IA_DXY_SCANNER_ENABLE", "1").strip().lower() in ("1", "true", "yes")
        and os.environ.get("IA_DXY_FILTER_ENABLE", "0").strip().lower() in ("1", "true", "yes")
    ):
        from ia_asset_profile import dxy_blocks_buy, dxy_context_line

        if dxy_blocks_buy(simbolo):
            if _filtros_debug_activos():
                log_filtro_descarte(
                    "DXY_MULTI",
                    dxy_context_line(simbolo),
                    "omitir BUY según clase activo",
                    simbolo=simbolo,
                )
            return "Sin señal clara"

    # Filtro de estructura: exigir ruptura del rango reciente en M15
    skip_bo = _scan_cfg_bool(cfg, "IA_SCAN_SKIP_BREAKOUT", "IA_SCAN_SKIP_BREAKOUT")
    lb = lb_bp
    if is_replay_snap:
        recent = df_m15.iloc[-(lb + 2) : -1]
    elif use_closed_live:
        recent = df_m15.iloc[-(lb + 3) : -2]
    else:
        recent = df_m15.iloc[-(lb + 2) : -1]
    if not skip_bo and len(recent) >= lb:
        hi = float(recent["high"].max())
        lo = float(recent["low"].min())
        close = float(v_trigger["close"])
        if base == "BUY" and close <= hi:
            if _filtros_debug_activos():
                log_filtro_descarte(
                    "ESTRUCTURA_BREAKOUT",
                    close,
                    f"close > hi_recent ({hi:.5f})",
                    simbolo=simbolo,
                )
            return "Sin señal clara"
        if base == "SELL" and close >= lo:
            if _filtros_debug_activos():
                log_filtro_descarte(
                    "ESTRUCTURA_BREAKOUT",
                    close,
                    f"close < lo_recent ({lo:.5f})",
                    simbolo=simbolo,
                )
            return "Sin señal clara"

    # Filtro de régimen (tendencia): pendiente SMA en H1 para evitar rango
    if os.environ.get("IA_SLOPE_FILTER", "1").strip().lower() not in ("0", "false", "no"):
        if replay_eff is not None:
            h1_rows = replay_eff.df_h1
            n_h1 = len(h1_rows)
            if n_h1 < 80:
                if _filtros_debug_activos():
                    log_filtro_descarte("REGIMEN_H1_DATOS", n_h1, ">=80 velas", simbolo=simbolo)
                return "Sin señal clara"
            closes = [float(x) for x in h1_rows["close"].tolist()]
        else:
            h1 = mt5_copy_rates_from_pos_cached(simbolo, mt5.TIMEFRAME_H1, 0, 120)
            if h1 is None or len(h1) < 80:
                if _filtros_debug_activos():
                    log_filtro_descarte(
                        "REGIMEN_H1_DATOS", len(h1) if h1 is not None else 0, ">=80 velas", simbolo=simbolo
                    )
                return "Sin señal clara"
            closes = [float(r["close"]) for r in h1]
            if len(closes) >= 2:
                closes = closes[:-1]
        period = int(os.environ.get("IA_SLOPE_SMA_PERIOD", "50"))
        look = int(os.environ.get("IA_SLOPE_LOOKBACK", "10"))
        need_bar = period + look + 2
        if len(closes) < need_bar:
            if _filtros_debug_activos():
                log_filtro_descarte("REGIMEN_H1_RANGO", len(closes), f">={need_bar} closes", simbolo=simbolo)
            return "Sin señal clara"
        sma_now = sum(closes[-period:]) / period
        sma_prev = sum(closes[-period - look : -look]) / period
        slope_pct = ((sma_now - sma_prev) / sma_prev) * 100.0 if sma_prev else 0.0
        try:
            min_abs = float(os.environ.get("IA_SLOPE_MIN_ABS_PCT", "0.03").strip() or "0.03")
        except ValueError:
            min_abs = 0.03
        if abs(slope_pct) < min_abs:
            if _filtros_debug_activos():
                log_filtro_descarte("REGIMEN_SLOPE_ABS", abs(slope_pct), f">= {min_abs} (abs %)", simbolo=simbolo)
            return "Sin señal clara"
        # Alineación de dirección de pendiente con la señal
        if base == "BUY" and slope_pct < 0:
            if _filtros_debug_activos():
                log_filtro_descarte("REGIMEN_SLOPE_SIGNO", slope_pct, "pendiente > 0 para BUY", simbolo=simbolo)
            return "Sin señal clara"
        if base == "SELL" and slope_pct > 0:
            if _filtros_debug_activos():
                log_filtro_descarte("REGIMEN_SLOPE_SIGNO", slope_pct, "pendiente < 0 para SELL", simbolo=simbolo)
            return "Sin señal clara"

    if replay_eff is not None:
        bid = float(replay_eff.bid)
        ask = float(replay_eff.ask)
        if bid <= 0 or ask <= 0:
            return "Error tick"
    else:
        tick = mt5.symbol_info_tick(simbolo)
        if tick is None:
            return "Error tick"
        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        if bid <= 0 or ask <= 0:
            return "Error tick"

    if _filtros_debug_activos() and replay_eff is None:
        try:
            from mt5_prices import spread_points_from_tick

            lim_raw = os.environ.get(
                "IA_AUTO_MAX_SPREAD_POINTS",
                os.environ.get("MAX_SPREAD_POINTS", "50"),
            ).strip()
            lim_sp = int(lim_raw) if lim_raw else 0
        except ValueError:
            lim_sp = 50
        sp_pts = spread_points_from_tick(simbolo)
        if sp_pts is not None and lim_sp > 0 and sp_pts > float(lim_sp):
            log_filtro_descarte(
                "SPREAD_VS_LIMITE",
                sp_pts,
                lim_sp,
                simbolo=simbolo,
            )

    try:
        min_conf = int(float(os.environ.get("IA_MIN_CONFIDENCE", "62").strip() or "62"))
    except ValueError:
        min_conf = 62

    # RR solo para el texto/plan de referencia; el bot real usa RR de su script.
    try:
        rr = float(os.environ.get("RR", "2").strip() or "2")
    except ValueError:
        rr = 2.0

    replay_pack = (
        MarketPackRatesReplay(
            m5=replay_eff.df_m5,
            m15=df_m15,
            h1=replay_eff.df_h1,
            h4=df_h4,
        )
        if replay_eff is not None
        else None
    )
    pack = analyze_market_pack(
        symbol=simbolo,
        signal=base,
        bid=bid,
        ask=ask,
        atr_m5=None,
        atr_period=int(os.environ.get("ATR_PERIOD", "14")),
        sl_atr_mult=float(os.environ.get("SL_ATR_MULT", "1.6")),
        rr=rr,
        rates_replay=replay_pack,
    )

    conf_tecnica = int(pack.confidence)
    conf_final = aplicar_score_macro(conf_tecnica, signal=base, trade_symbol=simbolo)
    mod_dxy_val = get_dxy_modifier(signal=base, trade_symbol=simbolo)
    pen_ses_val = macro_session_score_penalty_points()
    if _filtros_debug_activos():
        print(
            f"{simbolo} | [SCORE] técnica={conf_tecnica} dxyΔ={mod_dxy_val:+d} "
            f"sesión_NY_pen=-{pen_ses_val} → total={conf_final}"
        )

    mostrar_dashboard_decision(
        simbolo=simbolo,
        score_base=conf_tecnica,
        mod_dxy=mod_dxy_val,
        pen_sesion=pen_ses_val,
        score_final=conf_final,
        min_conf=min_conf,
        passes_rsi=pack.passes_rsi_filter,
        passes_atr=getattr(pack, "passes_atr_filter", True),
        rsi_m5=pack.rsi_m5,
        spread_pts=_spread_pts_dashboard(simbolo),
        lim_spread_pts=_lim_spread_points_env(),
    )
    # Snapshot row after macro score computed (even if later rejected)
    try:
        sp_pts = _spread_pts_dashboard(simbolo)
        _decision_log_append(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                simbolo,
                "score",
                "SCORE_MAESTRO",
                str(conf_tecnica),
                str(min_conf),
                base,
                str(conf_tecnica),
                str(conf_final),
                str(mod_dxy_val),
                str(pen_ses_val),
                f"{sp_pts:.2f}" if sp_pts is not None else "",
            ]
        )
    except Exception:
        pass

    if not pack.passes_rsi_filter:
        if _filtros_debug_activos():
            rv = float(pack.rsi_m5) if pack.rsi_m5 is not None else -1.0
            log_filtro_descarte("RSI_FILTRO", rv, "rangos RSI_* en .env", simbolo=simbolo)
        _decision_log_append(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                simbolo,
                "discard",
                "RSI_FILTRO",
                "0",
                "1",
                base,
                str(conf_tecnica),
                str(conf_final),
                str(mod_dxy_val),
                str(pen_ses_val),
                "",
            ]
        )
        return "Sin señal clara"
    if not getattr(pack, "passes_atr_filter", True):
        if _filtros_debug_activos():
            ap = float(pack.atr_percentile_m5) if pack.atr_percentile_m5 is not None else -1.0
            log_filtro_descarte("ATR_PCTL_FILTRO", ap, "ATR_PCTL_* en .env", simbolo=simbolo)
        _decision_log_append(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                simbolo,
                "discard",
                "ATR_PCTL_FILTRO",
                "0",
                "1",
                base,
                str(conf_tecnica),
                str(conf_final),
                str(mod_dxy_val),
                str(pen_ses_val),
                "",
            ]
        )
        return "Sin señal clara"
    if int(conf_final) < int(min_conf):
        if _filtros_debug_activos():
            log_filtro_descarte("CONFIANZA_IA", f"{conf_final} (téc {conf_tecnica})", min_conf, simbolo=simbolo)
        _decision_log_append(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                simbolo,
                "discard",
                "CONFIANZA_IA",
                str(conf_final),
                str(min_conf),
                base,
                str(conf_tecnica),
                str(conf_final),
                str(mod_dxy_val),
                str(pen_ses_val),
                "",
            ]
        )
        return "Sin señal clara"

    if _filtros_debug_activos():
        print(f"{simbolo} | [FILTRO] aprobada | {base} | conf_total={conf_final} (téc {conf_tecnica})")
    _decision_log_append(
        [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            simbolo,
            "approve",
            "APROBADA",
            str(conf_final),
            str(min_conf),
            base,
            str(conf_tecnica),
            str(conf_final),
            str(mod_dxy_val),
            str(pen_ses_val),
            "",
        ]
    )

    if base == "BUY":
        return f"COMPRA CONFIRMADA (conf {conf_final})"
    if base == "SELL":
        return f"VENTA CONFIRMADA (conf {conf_final})"

    return "Sin señal clara"


def main() -> None:
    load_env_file()
    _apply_optuna_overrides()
    validate_scan_session_env()
    raw = os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD")
    requested_list = [a.strip() for a in raw.split(",") if a.strip()]
    interval = float(os.environ.get("IA_SCAN_INTERVAL_S", "30"))

    if not iniciar_mt5():
        raise SystemExit(1)

    resolved_map: list[tuple[str, str]] = []
    try:
        for req in requested_list:
            r = _resolve_scan_symbol(req)
            if not r:
                print(f"{req}: símbolo no operable, se omite.", file=sys.stderr)
                continue
            resolved_map.append((req, r))
        if not resolved_map:
            print("No hay símbolos válidos.", file=sys.stderr)
            raise SystemExit(1)

        while True:
            if os.environ.get("IA_OPTUNA_RELOAD_EACH_ROUND", "1").strip().lower() not in (
                "0",
                "false",
                "no",
            ):
                _apply_optuna_overrides()

            if es_horario_seguro():
                for requested, sym in resolved_map:
                    mt5.symbol_select(sym, True)
                    resultado = analizar_ia(sym)
                    if "CONFIRMADA" in resultado:
                        tag = requested if sym == requested else f"{requested} -> {sym}"
                        print(
                            f"ALERTA: {tag} -> {resultado} @ "
                            f"{datetime.now().strftime('%H:%M:%S')}"
                        )
            else:
                if os.environ.get("IA_SCAN_QUIET", "0").strip().lower() not in (
                    "1",
                    "true",
                    "yes",
                ):
                    print("Fuera de ventana horaria configurada. Pausa.")

            time.sleep(interval)
    except KeyboardInterrupt:
        print("Scanner detenido.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
