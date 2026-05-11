"""
Auto-trading en bucle: misma señal que ia_scanner_loop (M15 + filtro H4).
Solo cuenta DEMO, requiere IA_AUTO_ENABLE=1, volumen fijo y SL/TP por % de precio.

  python ia_auto_trade_loop.py

Ctrl+C para salir.

Checklist técnico (archivos en la raíz del proyecto):
  ia_auto_trade_loop.py — ejecutor; llama a cargar_configuracion_optimizada() al inicio.
  ia_scanner_loop.py — señales (incluye IA_SLOPE_MIN_ABS_PCT cuando IA_SLOPE_FILTER está activo).
  signal_analysis.py — RSI, ATR, SMA / pack de confianza.
  optuna_walkforward.py — optimización; escribe params_optimized.json.
  .env — MT5, riesgo, símbolos; no versionar secretos.

Primer arranque / optimización sugerido (.env): IA_AUTO_SL_MODE=atr, IA_AUTO_RISK_BUNDLE_PERCENT=1
(junto con IA_AUTO_RISK_BUNDLE_TRADES), IA_AUTO_SPREAD_DYNAMIC=1, IA_SCAN_SYMBOLS=XAUUSD.
Flujo: (opcional) limpiar spread_samples_XAUUSD.csv -> recolectar spreads con scanner o bucle ->
python optuna_walkforward.py -> python ia_auto_trade_loop.py y verificar "Configuración optimizada cargada".

.env recomendado antes de ejecutar:
  IA_AUTO_ENABLE=1
  IA_SCAN_SYMBOLS=XAUUSD
  IA_AUTO_SL_PRICE_PERCENT=5
  RR=2
  — con SL 5 % del precio y RR=2 el TP queda a 10 % del precio.
  IA_AUTO_LOTS=0.01 — solo si no usás sizing por riesgo.
  IA_AUTO_RISK_BUNDLE_PERCENT=5 — % del equity repartido en IA_AUTO_RISK_BUNDLE_TRADES operaciones (riesgo por trade = bundle/trades).
  IA_AUTO_RISK_BUNDLE_TRADES=5
  IA_AUTO_MAX_TRADES=5 — opcional; corta el bucle tras N órdenes enviadas ok.
  IA_EXEC_QUALITY_ENABLE / IA_EXEC_QUALITY_CSV — log CSV de precio pedido vs ejecutado y spread (trade_audit).
  IA_LOG_MAX_MB — rota execution_quality.csv al superar el tamaño (default 5; 0 = off; ver ia_utils).
  IA_EXEC_SLIP_GUARD_ENABLE=1 — no abre nueva orden si el slippage promedio reciente según CSV supera el
    umbral (delega en trade_audit.check_slippage_safety; ver slippage_guard_allows_order).
    Alias: IA_MAX_SLIPPAGE_AVG (si no definís IA_EXEC_SLIP_GUARD_MAX_AVG_PTS), IA_SLIPPAGE_WINDOW.

  IA_AUTO_MULTI_PER_ROUND=1 — en cada pasada de escaneo, intentar todos los símbolos con señal (no parar en la primera orden).
  IA_AUTO_BURST_DELAY_S=3 — pausa entre órdenes en la misma ronda (varios símbolos u oportunidades seguidas).
  IA_AUTO_STACK_SAME_SYMBOL=0 — si 1, ignora “ya hay posición” y permite otra orden en el mismo símbolo (solo si tu cuenta lo permite; más riesgo).
  IA_AUTO_COOLDOWN_S=900 — entre rondas de escaneo sigue el intervalo; para más reentradas seguidas bajá este valor.
  DEVIATION=20
  IA_AUTO_MAX_SPREAD_POINTS — mismo criterio que MAX_SPREAD_POINTS del bot (default 50); 0 = sin filtro

Opcional: IA_SCAN_HOUR_START / IA_SCAN_HOUR_END (si START > END, ventana cruza medianoche) / IA_AUTO_USE_HOURS=0
Opcional: IA_AUTO_SINGLE_INSTANCE=1 (default), IA_AUTO_LOCK_FILE — una sola instancia del bot;
  IA_AUTO_SPREAD_SAMPLE_MAX_MB — rota spread_samples_*.csv al superar el tamaño (default 8).
Opcional: SENTIMENT_FILTER=1 — filtra con sentiment_news (TextBlob; NEWS_API_KEY opcional en NewsAPI)
Opcional: IA_AUTO_STOP_AT=22:00 — hora local del PC; el bucle sale al llegar esa hora y
  puede enviar reporte Telegram (IA_AUTO_TELEGRAM_REPORT=1, default activo si definís STOP_AT).
Opcional: IA_AUTO_TELEGRAM_TRADES=1 — tras cada orden enviada ok, aviso por Telegram (default 1 si hay TELEGRAM_*).
Opcional: IA_AUTO_MEMORY_ENABLE=1 — guarda cada cierre del BOT_MAGIC en CSV (buenas/malas) para analizar y mejorar.
Opcional: precierre fin de semana (gaps) — cierre_viernes.gestionar_precierre_fin_de_semana:
  IA_WEEKEND_CLOSE_ENABLE=1, IA_WEEKEND_CLOSE_HOUR, IA_WEEKEND_TZ, IA_WEEKEND_RESUME_* (ver cierre_viernes.py).
Opcional: reporte_semanal.intentar_enviar_reporte_semanal_si_toca — IA_REPORTE_SEMANAL_ENABLE=1,
  sábados hora local IA_REPORTE_SEMANAL_HOUR (ver reporte_semanal.py).
Opcional: botón pánico Telegram — IA_TELEGRAM_PANIC_ENABLE=1, comandos /DETENER y /INICIAR (ver telegram_listener.py).
Opcional: IA_AUTO_ALLOW_WINDOWS_SLEEP=1 — permitir suspensión en Windows (default: el bucle la inhibe mientras corre).
Opcional — Fase 1 / cuenta real (PnL cerrado BOT_MAGIC, moneda de la cuenta):
  IA_AUTO_DAILY_PROFIT_TARGET_USD=45   — no abre nuevas órdenes si el PnL neto del día (cerrados) >= valor
  IA_AUTO_DAILY_MAX_LOSS_USD=60       — no abre nuevas órdenes si el PnL neto del día <= -valor
  IA_AUTO_DAILY_PNL_TZ=America/Argentina/Buenos_Aires  — día calendario para el cómputo anterior
  IA_AUTO_STOP_LOOP_ON_DAILY_PROFIT=1 — al cumplir meta: sale del bucle ("uno y fuera"); default 0 = solo pausa nuevas entradas
  IA_AUTO_STOP_LOOP_ON_DAILY_MAX_LOSS=1 — al cumplir tope pérdida: sale del bucle (recomendado 1 en real)

  Lotaje fijo (sin sizing por riesgo): dejá vacíos IA_AUTO_RISK_* y usá IA_AUTO_LOTS=0.04 (o 0.05).
Opcional — Bitácora Fase 1 (CSV tipo Excel; ia_trading_journal.py, convive con límites diarios):
  IA_JOURNAL_ENABLE=1
  IA_JOURNAL_CSV=ia_phase1_journal.csv
  IA_JOURNAL_STATE=ia_trading_journal_state.json
  IA_JOURNAL_TZ=   — vacío = misma TZ que IA_AUTO_DAILY_PNL_TZ
  IA_JOURNAL_USE_EQUITY=0 — 1 = usar equity en lugar de balance
  IA_JOURNAL_GRAD_USD=1250  IA_JOURNAL_FLOOR_USD=900  IA_JOURNAL_ALERTS=1 (Telegram al cruzar meta/piso)
Opcional: tras `python optuna_walkforward.py`, se genera `params_optimized.json` (recomendado; fecha en
  last_optimization_date) más `ia_optuna_best.*`. El bot aplica esos valores sobre el .env al arrancar
  y, por defecto, al inicio de cada ronda de escaneo (IA_OPTUNA_RELOAD_EACH_ROUND=1).
  IA_OPTUNA_APPLY=0 desactiva; IA_OPTUNA_PARAMS_PATH= ruta a otro JSON por activo.

Relajación automática si no hay órdenes (después de la apertura NY):
  IA_AUTO_RELAX_ENABLE=1 (default), IA_AUTO_RELAX_AFTER_HOURS=2, IA_AUTO_RELAX_STEP_HOURS=1.5,
  IA_AUTO_RELAX_MAX_LEVEL=3, IA_AUTO_RELAX_OPEN_HOUR=8 (America/New_York), IA_SCAN_VOLUME_RELAX vía nivel 1.

Demo con más señales desde el arranque:
  IA_BOT_RELAX_SIGNALS=1 — ignora confirmación estricta de volumen M15; desactiva alineación EMA H4 y momentum
  (ver ia_scanner IA_SCAN_SKIP_VOLUME_CONFIRM).

La distancia SL respeta el mayor entre % de precio (IA_AUTO_SL_PRICE_PERCENT) y
trade_stops_level×point del bróker.

Riesgo dinámico (recomendado): con IA_AUTO_RISK_BUNDLE_PERCENT / IA_AUTO_RISK_BUNDLE_TRADES o
IA_AUTO_RISK_PER_TRADE_PERCENT, el lote se calcula para que, si se activa el SL, la pérdida sea ~ese
% de la equity. Con IA_AUTO_SL_MODE=atr, un ATR más alto aleja el SL; la pérdida por 1 lote sube y
el volumen baja — mismo riesgo en dinero (mt5.order_calc_profit sobre 1 lote, precio entrada→SL).

"""

from __future__ import annotations

import atexit
import ctypes
import json
import os
import re
import sys
import time
import csv
from datetime import date, datetime, time as dt_time, timezone, timedelta

import MetaTrader5 as mt5

from pathlib import Path

from local_env import apply_optuna_overrides, load_env_file
from ia_trading_journal import journal_add_note, journal_flush_shutdown, journal_mark_opened_today, journal_tick
from ia_scanner_loop import analizar_ia, es_horario_seguro, validate_scan_session_env
from m15_ma_scan import _resolve_scan_symbol
from ia_auto_memory import sync_memory_from_mt5, summary_from_csv
from signal_analysis import _atr_series, _true_ranges
from ia_auto_expert import (
    dxy_blocks_gold_buy,
    dxy_context_for_alert,
    manage_all_bot_positions_expert,
    pro_session_allows_order,
    session_context_for_alert,
    shakeout_reentry_window_active,
)
from cierre_viernes import gestionar_precierre_fin_de_semana
from reporte_semanal import intentar_enviar_reporte_semanal_si_toca
from telegram_listener import (
    cancelar_ordenes_pendientes_bot_panico,
    cerrar_posiciones_panico_ia_auto,
    poll_telegram_panic_commands,
)
from telegram_utils import enviar_alerta_telegram
from mt5_prices import (
    BOT_MAGIC,
    mt5_copy_rates_from_pos_cached,
    _allowed_filling_modes_symbol,
    _position_side_for_bot,
    _round_down_to_step,
    _telegram_configured,
    _telegram_send,
    es_spread_valido,
    closed_positions_pnls_by_magic,
)
from ia_risk_manager import calcular_lotaje_dinamico
from ia_utils import execution_quality_max_mb_from_env, rotar_log_por_tamaño
from trade_audit import (
    execution_quality_csv_path,
    log_execution_quality,
    log_trade_entry,
    slippage_guard_allows_order,
)


_IA_PAUSE_POR_COMANDO_TELEGRAM = False
_LOCK_OWNED = False
_IA_DAILY_LIMIT_NOTIFIED_DAY: str | None = None
_IA_DAILY_LIMIT_NOTIFIED_TAG: str | None = None


def _virtual_capital_state_path() -> Path:
    root = Path(__file__).resolve().parent
    name = os.environ.get("IA_AUTO_VIRTUAL_CAPITAL_STATE", "").strip() or "ia_virtual_capital.json"
    p = Path(name)
    return p if p.is_absolute() else (root / p)


def _virtual_capital_enabled() -> bool:
    return os.environ.get("IA_AUTO_VIRTUAL_CAPITAL_ENABLE", "0").strip().lower() in ("1", "true", "yes")


def _day_bounds_utc_trading_day() -> tuple[datetime, datetime]:
    try:
        from zoneinfo import ZoneInfo

        tz_name = os.environ.get("IA_AUTO_DAILY_PNL_TZ", "America/Argentina/Buenos_Aires").strip()
        tz = ZoneInfo(tz_name or "America/Argentina/Buenos_Aires")
    except Exception:
        tz = timezone.utc
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _daily_limits_usd_config() -> tuple[float | None, float | None]:
    pr = os.environ.get("IA_AUTO_DAILY_PROFIT_TARGET_USD", "").strip()
    lo = os.environ.get("IA_AUTO_DAILY_MAX_LOSS_USD", "").strip()
    try:
        pt = float(pr.replace(",", ".")) if pr else None
    except ValueError:
        pt = None
    try:
        ml = float(lo.replace(",", ".")) if lo else None
    except ValueError:
        ml = None
    if pt is not None and pt <= 0:
        pt = None
    if ml is not None and ml <= 0:
        ml = None
    return pt, ml


def _daily_realized_pnl_bot_account_currency() -> float | None:
    try:
        uf, ut = _day_bounds_utc_trading_day()
        pnls = closed_positions_pnls_by_magic(BOT_MAGIC, uf, ut, history_lookback_days=14)
        return float(sum(pnls))
    except Exception:
        return None


def _daily_limit_state() -> tuple[float | None, str | None]:
    pt, ml = _daily_limits_usd_config()
    if pt is None and ml is None:
        return None, None
    pnl = _daily_realized_pnl_bot_account_currency()
    if pnl is None:
        return None, None
    if pt is not None and pnl >= pt:
        return pnl, "profit_cap"
    if ml is not None and pnl <= -ml:
        return pnl, "loss_cap"
    return pnl, None


def _maybe_reset_daily_notify() -> None:
    global _IA_DAILY_LIMIT_NOTIFIED_DAY, _IA_DAILY_LIMIT_NOTIFIED_TAG
    try:
        from zoneinfo import ZoneInfo

        tz_name = os.environ.get("IA_AUTO_DAILY_PNL_TZ", "America/Argentina/Buenos_Aires").strip()
        tz = ZoneInfo(tz_name or "America/Argentina/Buenos_Aires")
        day_key = datetime.now(tz).date().isoformat()
    except Exception:
        day_key = date.today().isoformat()
    if _IA_DAILY_LIMIT_NOTIFIED_DAY != day_key:
        _IA_DAILY_LIMIT_NOTIFIED_DAY = day_key
        _IA_DAILY_LIMIT_NOTIFIED_TAG = None


def _stop_loop_on_daily_profit() -> bool:
    return os.environ.get("IA_AUTO_STOP_LOOP_ON_DAILY_PROFIT", "0").strip().lower() in ("1", "true", "yes")


def _stop_loop_on_daily_max_loss() -> bool:
    if not os.environ.get("IA_AUTO_DAILY_MAX_LOSS_USD", "").strip():
        return False
    raw = os.environ.get("IA_AUTO_STOP_LOOP_ON_DAILY_MAX_LOSS", "").strip()
    if raw == "":
        return True
    return raw.lower() in ("1", "true", "yes")


def _maybe_announce_daily_limit(kind: str, pnl: float) -> None:
    global _IA_DAILY_LIMIT_NOTIFIED_TAG
    try:
        from zoneinfo import ZoneInfo

        tz_name = os.environ.get("IA_AUTO_DAILY_PNL_TZ", "America/Argentina/Buenos_Aires").strip()
        tz = ZoneInfo(tz_name or "America/Argentina/Buenos_Aires")
        day_key = datetime.now(tz).date().isoformat()
    except Exception:
        day_key = date.today().isoformat()
    tag = f"{day_key}:{kind}"
    if _IA_DAILY_LIMIT_NOTIFIED_TAG == tag:
        return
    _IA_DAILY_LIMIT_NOTIFIED_TAG = tag
    if kind == "profit_cap":
        plain = (
            f"IA_AUTO límite diario: meta alcanzada; PnL hoy (cerrados BOT_MAGIC) ≈ {pnl:+.2f}. "
            "Sin nuevas órdenes."
        )
        html = (
            f"<b>IA_AUTO límite diario</b>\nMeta alcanzada: PnL hoy ≈ <code>{pnl:+.2f}</code> "
            "(cerrados BOT_MAGIC). Sin nuevas órdenes."
        )
    else:
        plain = (
            f"IA_AUTO límite diario: tope de pérdida; PnL hoy ≈ {pnl:+.2f}. Sin nuevas órdenes."
        )
        html = (
            f"<b>IA_AUTO límite diario</b>\nTope de pérdida: PnL hoy ≈ <code>{pnl:+.2f}</code>. "
            "Sin nuevas órdenes."
        )
    print(plain)
    try:
        journal_add_note(
            "Límite diario: meta de ganancia (sin nuevas entradas)"
            if kind == "profit_cap"
            else "Límite diario: tope de pérdida (sin nuevas entradas)"
        )
    except Exception:
        pass
    try:
        enviar_alerta_telegram(html)
    except Exception:
        pass


def _load_or_init_virtual_capital_state() -> dict:
    """
    State mínimo:
      - start_usd: float
      - start_utc: ISO string (UTC)
    """
    p = _virtual_capital_state_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "{}")
            if isinstance(data, dict) and "start_usd" in data and "start_utc" in data:
                return data
        except Exception:
            pass
    try:
        start_usd = float(os.environ.get("IA_AUTO_VIRTUAL_CAPITAL_START_USD", "1000").strip() or "1000")
    except ValueError:
        start_usd = 1000.0
    start_usd = max(1.0, float(start_usd))
    data = {
        "start_usd": start_usd,
        "start_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass
    return data


def _virtual_equity_usd_now() -> float | None:
    """
    Equity virtual = start_usd + PnL neto (profit+commission+swap) de cierres BOT_MAGIC desde start_utc.
    Retorna None si no está habilitado.
    """
    if not _virtual_capital_enabled():
        return None
    st = _load_or_init_virtual_capital_state()
    try:
        start_usd = float(st.get("start_usd", 1000.0) or 1000.0)
    except (TypeError, ValueError):
        start_usd = 1000.0
    start_usd = max(1.0, float(start_usd))
    start_iso = str(st.get("start_utc", "") or "").strip()
    try:
        start_dt = datetime.fromisoformat(start_iso)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
    except Exception:
        start_dt = datetime.now(timezone.utc) - timedelta(days=3650)
    now_dt = datetime.now(timezone.utc)
    try:
        pnls = closed_positions_pnls_by_magic(BOT_MAGIC, start_dt, now_dt, history_lookback_days=30)
    except Exception:
        return None
    v = start_usd + float(sum(pnls))
    return max(1.0, float(v))


def _effective_risk_percent_for_account(risk_percent_cfg: float, *, account_equity: float) -> float:
    """
    Si IA_AUTO_VIRTUAL_CAPITAL_ENABLE=1, interpreta `risk_percent_cfg` como % del capital virtual,
    y lo traduce al % equivalente sobre la equity real de la cuenta.
    """
    if account_equity <= 0:
        return float(risk_percent_cfg)
    v_eq = _virtual_equity_usd_now()
    if v_eq is None:
        return float(risk_percent_cfg)
    risk_money = v_eq * (float(risk_percent_cfg) / 100.0)
    return (risk_money / float(account_equity)) * 100.0


def _send_status_telegram() -> None:
    """
    Resumen rápido para Telegram (/STATUS).
    """
    try:
        import market_regime
    except Exception:
        market_regime = None  # type: ignore[assignment]

    try:
        acct = mt5.account_info()
        equity = float(getattr(acct, "equity", 0.0) or 0.0) if acct is not None else 0.0

        positions = mt5.positions_get() or []
        open_bot_positions = [
            p for p in positions if int(getattr(p, "magic", 0) or 0) == BOT_MAGIC
        ]
        n_open = len(open_bot_positions)

        total_risk_pct = _bot_total_risk_percent(equity)
        total_risk_txt = f"{total_risk_pct:.2f}%" if total_risk_pct is not None else "N/D"

        raw_symbols = os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD")
        req_first = (raw_symbols.split(",")[0] or "").strip() or "XAUUSD"
        try:
            sym = _resolve_scan_symbol(req_first) or req_first
        except Exception:
            sym = req_first

        regime_line = "Régimen: N/D"
        if os.environ.get("IA_REGIME_ENABLE", "0").strip().lower() in ("1", "true", "yes") and market_regime:
            try:
                snap = market_regime.classify_regime_rules(sym)
                if snap is not None:
                    regime_line = f"Régimen: {snap.label.value} ({snap.detail})"
            except Exception:
                regime_line = "Régimen: (no disponible)"

        paused_txt = "PAUSADO por Telegram" if _IA_PAUSE_POR_COMANDO_TELEGRAM else "ACTIVO"
        cap_raw = os.environ.get("IA_AUTO_MAX_TOTAL_RISK_PERCENT", "").strip()
        cap_txt = cap_raw if cap_raw else "deshabilitado"

        msg = (
            "<b>IA_AUTO STATUS</b>\n"
            f"Estado: <b>{paused_txt}</b>\n"
            f"AutoEnable: <code>{os.environ.get('IA_AUTO_ENABLE','') or '0'}</code>\n"
            f"Equipo: equity=<code>{equity:.2f}</code>\n"
            f"Posiciones abiertas BOT_MAGIC: <code>{n_open}</code>\n"
            f"Riesgo total abierto: <code>{total_risk_txt}</code> (cap=<code>{cap_txt}</code>)\n"
            f"{regime_line}\n"
            "\n"
            "<i>Recomendación:</i> si el bot no envía operaciones, revisá consola + filtros."
        )

        enviar_alerta_telegram(msg)
    except Exception as e:
        print(f"[TG] /STATUS error: {e}", file=sys.stderr)


def aplicar_escucha_boton_panico_ia() -> None:
    """
    Polling Telegram (getUpdates). /DETENER desde TELEGRAM_CHAT_ID: opcional cerrar BOT_MAGIC + pausa ciclo.
    /INICIAR (o /GO) reanuda escaneos (no cierra solo).
    """
    global _IA_PAUSE_POR_COMANDO_TELEGRAM

    if os.environ.get("IA_TELEGRAM_PANIC_ENABLE", "0").strip().lower() not in ("1", "true", "yes"):
        return

    cmd = poll_telegram_panic_commands()
    if cmd is None:
        return

    if cmd == "STATUS":
        _send_status_telegram()
        return

    if cmd == "STOP":
        print("[panic] Comando Telegram /DETENER → cierre BOT + pausa ciclo hasta /INICIAR")
        ok_close = fa_close = 0
        nop = 0
        if os.environ.get("IA_TELEGRAM_PANIC_CLOSE_POSITIONS", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            ok_close, fa_close = cerrar_posiciones_panico_ia_auto()
        nop = cancelar_ordenes_pendientes_bot_panico()
        enviar_alerta_telegram(
            f"<b>IA_AUTO detenido</b> (/DETENER)\n"
            f"Cierre posiciones BOT_MAGIC: OK≈{ok_close}, fallidas≈{fa_close}\n"
            f"Órdenes pendientes borradas: {nop}\n"
            "<i>Reactivar: /INICIAR</i>",
        )
        _IA_PAUSE_POR_COMANDO_TELEGRAM = True
        return

    if cmd == "RESUME":
        print("[panic] Comando Telegram /INICIAR → reanudación de escaneo")
        enviar_alerta_telegram(
            "<b>IA_AUTO reactivado</b> (/INICIAR)\n<i>Escaneo y órdenes habilitados de nuevo.</i>",
        )
        _IA_PAUSE_POR_COMANDO_TELEGRAM = False


def cargar_configuracion_optimizada() -> list[str]:
    """
    Aplica params_optimized.json / ia_optuna_best.* sobre os.environ (ver local_env).
    Devuelve la lista de claves aplicadas; lista vacía si no hay fichero o IA_OPTUNA_APPLY=0.
    """
    return apply_optuna_overrides()


def _spread_points(info, bid: float, ask: float) -> float | None:
    point = float(getattr(info, "point", 0.0) or 0.0)
    if point <= 0:
        return None
    if ask <= 0 or bid <= 0:
        return None
    return max(0.0, (ask - bid) / point)


def _spread_sample_path(symbol: str) -> Path:
    root = Path(__file__).resolve().parent
    name = os.environ.get("IA_AUTO_SPREAD_SAMPLE_CSV", "").strip()
    if not name:
        safe = "".join([c for c in symbol if c.isalnum() or c in ("_", "-")]) or "SYMBOL"
        name = f"spread_samples_{safe}.csv"
    return root / name


def _maybe_rotate_spread_sample_file(path: Path) -> None:
    raw = os.environ.get("IA_AUTO_SPREAD_SAMPLE_MAX_MB", "8").strip() or "8"
    try:
        mb = float(raw)
    except ValueError:
        mb = 8.0
    if mb <= 0:
        return
    max_bytes = int(mb * 1024 * 1024)
    try:
        if not path.is_file() or path.stat().st_size <= max_bytes:
            return
    except OSError:
        return
    bak = path.parent / (path.name + ".bak")
    try:
        if bak.is_file():
            bak.unlink()
        path.rename(bak)
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _append_spread_sample(path: Path, ts: int, spread_pts: float) -> None:
    try:
        _maybe_rotate_spread_sample_file(path)
    except OSError:
        pass
    write_header = not path.is_file()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["time_utc", "ts", "spread_points"])
        w.writerow([datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(), ts, f"{spread_pts:.3f}"])


def _percentile(arr: list[float], p: float) -> float | None:
    if not arr:
        return None
    if p <= 0:
        return min(arr)
    if p >= 100:
        return max(arr)
    xs = sorted(arr)
    k = (len(xs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    if c == f:
        return xs[f]
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def _spread_dynamic_allows_trade(symbol: str, now_ts: int, cur_spread_pts: float) -> bool:
    if os.environ.get("IA_AUTO_SPREAD_DYNAMIC", "1").strip().lower() in ("0", "false", "no"):
        return True
    try:
        hours = float(os.environ.get("IA_AUTO_SPREAD_WINDOW_HOURS", "24").strip() or "24")
    except ValueError:
        hours = 24.0
    try:
        pctl = float(os.environ.get("IA_AUTO_SPREAD_PCTL", "80").strip() or "80")
    except ValueError:
        pctl = 80.0
    try:
        min_samples = int(os.environ.get("IA_AUTO_SPREAD_MIN_SAMPLES", "80").strip() or "80")
    except ValueError:
        min_samples = 80
    hours = max(1.0, min(hours, 168.0))
    cutoff = now_ts - int(hours * 3600)

    path = _spread_sample_path(symbol)
    samples: list[float] = []
    if path.is_file():
        try:
            with path.open(encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                for row in r:
                    try:
                        ts = int(float(row.get("ts", "0") or "0"))
                        if ts < cutoff:
                            continue
                        samples.append(float(row.get("spread_points", "0") or "0"))
                    except ValueError:
                        continue
        except OSError:
            pass

    # si todavía no hay suficiente historial, no bloqueamos
    if len(samples) < min_samples:
        return True
    thr = _percentile(samples, pctl)
    if thr is None:
        return True
    return cur_spread_pts <= thr


def _fail(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) no es fiable en Windows para "¿existe el proceso?"
        try:
            k = ctypes.windll.kernel32
            synchronize = 0x00100000
            h = k.OpenProcess(synchronize, False, pid)
            if h:
                k.CloseHandle(h)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _single_instance_lock_path() -> Path:
    raw = os.environ.get("IA_AUTO_LOCK_FILE", "").strip()
    root = Path(__file__).resolve().parent
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else root / p
    return root / "ia_auto_trade_loop.lock"


def _release_single_instance_lock() -> None:
    global _LOCK_OWNED
    if not _LOCK_OWNED:
        return
    path = _single_instance_lock_path()
    try:
        if path.is_file():
            parts = path.read_text(encoding="utf-8").strip().split()
            if parts and int(parts[0]) == os.getpid():
                path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
    _LOCK_OWNED = False


def _acquire_single_instance_lock() -> None:
    global _LOCK_OWNED
    if os.environ.get("IA_AUTO_SINGLE_INSTANCE", "1").strip().lower() in ("0", "false", "no"):
        return
    path = _single_instance_lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    mypid = os.getpid()
    for _ in range(6):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, f"{mypid}\n".encode("ascii"))
            finally:
                os.close(fd)
            _LOCK_OWNED = True
            atexit.register(_release_single_instance_lock)
            return
        except FileExistsError:
            try:
                parts = path.read_text(encoding="utf-8").strip().split()
                old = int(parts[0]) if parts else -1
            except (OSError, ValueError):
                old = -1
            if old > 0 and old != mypid and _process_alive(old):
                _fail(
                    f"Ya hay otra instancia del bot (PID {old}). "
                    f"Cerrala o borrá el lock si es viejo: {path}"
                )
            try:
                path.unlink()
            except OSError:
                time.sleep(0.08)
        except OSError as e:
            _fail(f"No se pudo crear lock de instancia única ({path}): {e}")
    _fail(f"No se pudo adquirir lock tras reintentos: {path}")


def _validate_ia_auto_numeric_env() -> None:
    """Evita crash por .env / JSON mal formados en rutas numéricas críticas."""

    def _need_float(key: str, default: str, *, positive: bool = False, min_v: float | None = None) -> None:
        raw = os.environ.get(key, default).strip() or default
        try:
            v = float(raw)
        except ValueError:
            _fail(f"[ENV] {key} debe ser numérico, recibí {raw!r}")
        if positive and v <= 0:
            _fail(f"[ENV] {key} debe ser > 0, recibí {v}")
        if min_v is not None and v < min_v:
            _fail(f"[ENV] {key} debe ser >= {min_v}, recibí {v}")

    _need_float("RR", "2", positive=True)
    sl_mode = os.environ.get("IA_AUTO_SL_MODE", "percent").strip().lower()
    if sl_mode in ("atr", "atr_m5"):
        _need_float("IA_AUTO_SL_ATR_MULT", "1.6", positive=True)
        ap_raw = os.environ.get("IA_AUTO_ATR_PERIOD", "14").strip() or "14"
        try:
            ap = int(ap_raw)
        except ValueError:
            _fail(f"[ENV] IA_AUTO_ATR_PERIOD debe ser entero, recibí {ap_raw!r}")
        if ap < 2:
            _fail(f"[ENV] IA_AUTO_ATR_PERIOD debe ser >= 2, recibí {ap}")
    else:
        _need_float("IA_AUTO_SL_PRICE_PERCENT", "5", positive=True)

    _need_float("IA_SCAN_INTERVAL_S", "30", positive=True)
    _need_float("IA_AUTO_COOLDOWN_S", "900", min_v=0.0)
    _need_float("IA_AUTO_BURST_DELAY_S", "3", min_v=0.0)

    dev_raw = os.environ.get("DEVIATION", os.environ.get("IA_AUTO_DEVIATION", "20")).strip() or "20"
    try:
        dev = int(dev_raw)
    except ValueError:
        _fail(f"[ENV] DEVIATION / IA_AUTO_DEVIATION debe ser entero, recibí {dev_raw!r}")
    if dev < 0:
        _fail(f"[ENV] DEVIATION debe ser >= 0, recibí {dev}")

    mx = os.environ.get("IA_AUTO_MAX_TRADES", "").strip()
    if mx:
        try:
            mxi = int(mx)
        except ValueError:
            _fail(f"[ENV] IA_AUTO_MAX_TRADES debe ser entero >= 0, recibí {mx!r}")
        if mxi < 0:
            _fail(f"[ENV] IA_AUTO_MAX_TRADES debe ser >= 0, recibí {mxi}")

    mc = os.environ.get("IA_MIN_CONFIDENCE", "").strip()
    if mc:
        try:
            mcv = float(mc)
        except ValueError:
            _fail(f"[ENV] IA_MIN_CONFIDENCE debe ser numérico, recibí {mc!r}")
        if mcv < 0 or mcv > 100:
            _fail(f"[ENV] IA_MIN_CONFIDENCE razonable 0–100, recibí {mcv}")

    spr_mb = os.environ.get("IA_AUTO_SPREAD_SAMPLE_MAX_MB", "").strip()
    if spr_mb:
        try:
            smb = float(spr_mb)
        except ValueError:
            _fail(f"[ENV] IA_AUTO_SPREAD_SAMPLE_MAX_MB debe ser numérico, recibí {spr_mb!r}")
        if smb < 0:
            _fail(f"[ENV] IA_AUTO_SPREAD_SAMPLE_MAX_MB debe ser >= 0 (0 = sin límite), recibí {smb}")


def _windows_prevent_sleep_while_running() -> None:
    """Evita que Windows entre en suspensión por inactividad mientras corre este proceso (solo Windows)."""
    if os.name != "nt":
        return
    if os.environ.get("IA_AUTO_ALLOW_WINDOWS_SLEEP", "").strip().lower() in ("1", "true", "yes"):
        return
    try:
        es_continuous = 0x80000000
        es_system_required = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)
        print("Windows: suspensión por inactividad inhibida mientras IA_AUTO está activo (Ctrl+C libera).")
    except Exception:
        pass


def _windows_release_sleep_inhibit() -> None:
    if os.name != "nt":
        return
    try:
        es_continuous = 0x80000000
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous)
    except Exception:
        pass


def _parse_local_stop_at(raw: str) -> tuple[int, int] | None:
    """Parse '22', '22:00', '22:30' → hora local (0–23, 0–59)."""
    s = raw.strip()
    if not s:
        return None
    s = s.replace(".", ":")
    parts = s.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h, m


def _demo_only_or_exit() -> None:
    if os.environ.get("IA_AUTO_DEMO_ONLY", "0").strip().lower() in ("0", "false", "no"):
        return
    account = mt5.account_info()
    if account is None:
        _fail("No hay cuenta conectada en MT5 (account_info=None). Logueate en el terminal.")
    server = str(getattr(account, "server", "") or "")
    if "DEMO" not in server.upper():
        _fail(f"Bloqueado: server='{server}' no parece DEMO (solo cuentas demo).")


def _elapsed_hours_since_session_open_ny() -> float | None:
    """
    Horas desde la 'apertura' de sesión (NY). None si aún no llegó esa hora hoy.
    TZ y hora configurables (IA_AUTO_RELAX_TZ, IA_AUTO_RELAX_OPEN_HOUR/MINUTE).
    """
    try:
        from zoneinfo import ZoneInfo

        tz_name = os.environ.get("IA_AUTO_RELAX_TZ", "America/New_York").strip() or "America/New_York"
        tz = ZoneInfo(tz_name)
    except Exception:
        return None
    now = datetime.now(tz)
    try:
        oh = int(os.environ.get("IA_AUTO_RELAX_OPEN_HOUR", "8").strip() or "8")
        om = int(os.environ.get("IA_AUTO_RELAX_OPEN_MINUTE", "0").strip() or "0")
    except ValueError:
        oh, om = 8, 0
    sod = now.replace(hour=oh, minute=om, second=0, microsecond=0)
    if now < sod:
        return None
    return (now - sod).total_seconds() / 3600.0


def _maybe_advance_auto_relax(elapsed_h: float | None, trades_sent: int, ctx: dict) -> None:
    """Sube ctx['level'] si pasó tiempo desde apertura NY y no hubo órdenes."""
    if trades_sent > 0:
        return
    if elapsed_h is None:
        return
    if os.environ.get("IA_AUTO_RELAX_ENABLE", "1").strip().lower() in ("0", "false", "no"):
        return
    try:
        h1 = float(os.environ.get("IA_AUTO_RELAX_AFTER_HOURS", "2").strip() or "2")
    except ValueError:
        h1 = 2.0
    try:
        step = float(os.environ.get("IA_AUTO_RELAX_STEP_HOURS", "1.5").strip() or "1.5")
    except ValueError:
        step = 1.5
    try:
        max_lv = int(os.environ.get("IA_AUTO_RELAX_MAX_LEVEL", "3").strip() or "3")
    except ValueError:
        max_lv = 3
    max_lv = max(1, min(5, max_lv))
    lv = int(ctx.get("level", 0))
    while lv < max_lv:
        thr_next = h1 + lv * step
        if elapsed_h < thr_next:
            break
        lv += 1
        ctx["level"] = lv
        print(
            f"[auto-relax] nivel {lv}/{max_lv} "
            f"(~{elapsed_h:.2f}h desde apertura NY configurada; sin órdenes aún)."
        )


def _reapply_auto_relax_patches(ctx: dict) -> None:
    """
    Tras recargar Optuna: vuelve a aplicar relajaciones según ctx['level'].
    Usa valores base del JSON y resta/suma deltas fijos (no compone ronda a ronda).
    """
    lv = int(ctx.get("level", 0))
    if lv <= 0:
        os.environ.pop("IA_SCAN_VOLUME_RELAX", None)
        if os.environ.get("__IA_SCAN_SKIP_VOL_FROM_RELAX", "0") == "1":
            os.environ.pop("IA_SCAN_SKIP_VOLUME_CONFIRM", None)
            os.environ.pop("__IA_SCAN_SKIP_VOL_FROM_RELAX", None)
        os.environ["IA_REGIME_BLOCK_HIGH_VOL"] = str(ctx.get("block_hv_base", "1"))
        os.environ["IA_M15_MOMENTUM_MIN_BODY_RATIO"] = str(ctx.get("mom_br_base", "0.45"))
        return

    try:
        mc0 = int(float(os.environ.get("IA_MIN_CONFIDENCE", "68").strip() or "68"))
    except ValueError:
        mc0 = 68
    try:
        cp0 = int(float(os.environ.get("IA_REGIME_ATR_CRISIS_PCTL", "95").strip() or "95"))
    except ValueError:
        cp0 = 95

    if lv >= 1:
        os.environ["IA_MIN_CONFIDENCE"] = str(max(55, mc0 - 3))
        os.environ["IA_REGIME_ATR_CRISIS_PCTL"] = str(min(99, cp0 + 3))
        os.environ["IA_SCAN_VOLUME_RELAX"] = "1"
        os.environ["IA_SCAN_SKIP_VOLUME_CONFIRM"] = "1"
        os.environ["__IA_SCAN_SKIP_VOL_FROM_RELAX"] = "1"
    if lv >= 2:
        relaxed_mom = (
            os.environ.get("IA_AUTO_RELAX_MOMENTUM_BODY", "").strip() or "0.35"
        )
        os.environ["IA_M15_MOMENTUM_MIN_BODY_RATIO"] = relaxed_mom
        try:
            lb0 = int(float(os.environ.get("IA_BREAKOUT_LOOKBACK", "30").strip() or "30"))
        except ValueError:
            lb0 = 30
        os.environ["IA_BREAKOUT_LOOKBACK"] = str(max(10, lb0 - 5))
    else:
        os.environ["IA_M15_MOMENTUM_MIN_BODY_RATIO"] = str(ctx.get("mom_br_base", "0.45"))
    if lv >= 3:
        os.environ["IA_REGIME_BLOCK_HIGH_VOL"] = "0"
    else:
        os.environ["IA_REGIME_BLOCK_HIGH_VOL"] = str(ctx.get("block_hv_base", "1"))


def _apply_demo_relaxed_signals() -> None:
    """
    Demo: aumenta probabilidad de entradas (menos filtros en el gatillo M15).
    Activar IA_BOT_RELAX_SIGNALS=1 en .env (no cambia sizing ni riesgo del bot).
    """
    if os.environ.get("IA_BOT_RELAX_SIGNALS", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return
    os.environ["IA_SCAN_SKIP_VOLUME_CONFIRM"] = "1"
    os.environ["IA_SCAN_SOFT_TRIGGER"] = "1"
    os.environ["IA_SCAN_SKIP_BREAKOUT"] = "1"
    os.environ["IA_H4_EMA_ALIGN_ENABLE"] = "0"
    os.environ["IA_M15_MOMENTUM_ENABLE"] = "0"


def _risk_percent_per_trade() -> float | None:
    """
    % del equity a arriesgar por operación.
    Si IA_AUTO_RISK_BUNDLE_PERCENT y IA_AUTO_RISK_BUNDLE_TRADES están definidos: bundle/trades.
    Si no, IA_AUTO_RISK_PER_TRADE_PERCENT solo.
    """
    bundle_raw = os.environ.get("IA_AUTO_RISK_BUNDLE_PERCENT", "").strip()
    n_raw = os.environ.get("IA_AUTO_RISK_BUNDLE_TRADES", "").strip()
    single_raw = os.environ.get("IA_AUTO_RISK_PER_TRADE_PERCENT", "").strip()
    try:
        if bundle_raw and n_raw:
            b = float(bundle_raw)
            n = float(n_raw)
            if b > 0 and n > 0:
                return b / n
        if single_raw:
            s = float(single_raw)
            if s > 0:
                return s
        # Alias simple (nuevo): si no usás bundle ni per-trade, podés poner IA_RISK_PERCENT=1.0
        alias_raw = os.environ.get("IA_RISK_PERCENT", "").strip()
        if alias_raw:
            a = float(alias_raw)
            if a > 0:
                return a
    except ValueError:
        pass
    return None


def _telegram_trades_enabled() -> bool:
    raw = os.environ.get("IA_AUTO_TELEGRAM_TRADES", "1").strip().lower()
    return raw not in ("0", "false", "no")


def _confidence_from_signal(sig: str) -> int | None:
    m = re.search(r"conf\s+(\d+)", sig, re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _notify_trade_telegram(
    simbolo: str,
    side_label: str,
    vol: float,
    price: float,
    sl: float,
    tp: float,
    result,
    session_trade_num: int | None,
    *,
    ia_confidence: int | None = None,
    trailing_tp: bool = False,
) -> None:
    if not _telegram_trades_enabled():
        return

    ai = mt5.account_info()
    cur = str(getattr(ai, "currency", "") or "") if ai else ""
    deal = int(getattr(result, "deal", 0) or 0)
    order_id = int(getattr(result, "order", 0) or 0)
    retcode = int(getattr(result, "retcode", 0) or 0)
    num_line = f"Operación #{session_trade_num}\n" if session_trade_num else ""

    rich = os.environ.get("IA_AUTO_TELEGRAM_RICH", "1").strip().lower() not in ("0", "false", "no")
    if rich:
        try:
            from telegram_utils import enviar_alerta_telegram, format_operacion_alert_html

            try:
                rr = float(os.environ.get("RR", "2").strip() or "2")
            except ValueError:
                rr = 2.0
            msg_html = format_operacion_alert_html(
                simbolo,
                side_label=side_label,
                score=ia_confidence,
                volume=vol,
                sl=sl,
                tp=tp,
                trailing_tp=trailing_tp,
                rr=rr,
                dxy_line=dxy_context_for_alert(),
                session_line=session_context_for_alert(),
            )
            msg_html += f"\n\n<code>Precio {price:.5f} {cur}</code>\n<code>deal={deal} order={order_id} ret={retcode}</code>"
            if num_line:
                msg_html = f"{num_line}\n" + msg_html
            if enviar_alerta_telegram(msg_html):
                return
        except Exception as e:
            print(f"[TG] alerta enriquecida fallo, texto plano: {e}", file=sys.stderr)

    if not _telegram_configured():
        return
    msg = (
        f"IA_AUTO · nueva orden\n"
        f"{num_line}"
        f"{simbolo} {side_label}\n"
        f"Volumen {vol}\n"
        f"Precio {price:.5f} {cur}\n"
        f"SL {sl:.5f} · TP {tp:.5f}\n"
        f"deal={deal} order={order_id} retcode={retcode}"
    )
    if not _telegram_send(msg):
        print("[TG] No se pudo enviar aviso de operación.", file=sys.stderr)


def _loss_per_lot_from_entry_sl(
    *,
    simbolo: str,
    info,
    entry_price: float,
    sl_price: float,
) -> float | None:
    """
    Pérdida estimada en dinero por 1 lote si toca SL.

    Usa trade_tick_size/value (mismo criterio que mt5_prices para sizing por riesgo).
    """
    tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
    tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
    if tick_size <= 0 or tick_value <= 0:
        return None
    sl_dist = abs(entry_price - sl_price)
    if sl_dist <= 1e-12:
        return None
    return (sl_dist / tick_size) * tick_value


def _risk_percent_for_entry_sl_volume(
    *,
    simbolo: str,
    info,
    entry_price: float,
    sl_price: float,
    volume: float,
    equity: float,
) -> float | None:
    if equity <= 0 or volume <= 0:
        return None
    loss_per_lot = _loss_per_lot_from_entry_sl(
        simbolo=simbolo, info=info, entry_price=entry_price, sl_price=sl_price
    )
    if loss_per_lot is None or loss_per_lot <= 0:
        return None
    return (loss_per_lot * volume) / equity * 100.0


def _bot_total_risk_percent(equity: float) -> float | None:
    """
    Suma riesgo estimado al SL de todas las posiciones del bot (BOT_MAGIC) en la cuenta.
    """
    if equity <= 0:
        return None
    total = 0.0
    any_ok = False
    for p in mt5.positions_get() or []:
        try:
            magic = int(getattr(p, "magic", 0) or 0)
        except Exception:
            magic = 0
        if magic != BOT_MAGIC:
            continue
        symbol = str(getattr(p, "symbol", "") or "")
        if not symbol:
            continue
        info = mt5.symbol_info(symbol)
        if info is None:
            continue
        try:
            entry_price = float(getattr(p, "price_open", 0.0) or 0.0)
            sl_price = float(getattr(p, "sl", 0.0) or 0.0)
            volume = float(getattr(p, "volume", 0.0) or 0.0)
        except Exception:
            continue
        if entry_price <= 0 or sl_price <= 0 or volume <= 0:
            continue
        rp = _risk_percent_for_entry_sl_volume(
            simbolo=symbol,
            info=info,
            entry_price=entry_price,
            sl_price=sl_price,
            volume=volume,
            equity=equity,
        )
        if rp is None:
            continue
        any_ok = True
        total += rp
    return total if any_ok else None


def _total_risk_cap_allows_new_order(
    *,
    simbolo: str,
    info,
    entry_price: float,
    sl_price: float,
    volume: float,
) -> tuple[bool, str]:
    """
    True si el bot puede abrir una nueva posición sin superar IA_AUTO_MAX_TOTAL_RISK_PERCENT.

    Best-effort: si no se puede calcular el riesgo (tick size/value, sl faltante, etc.)
    entonces no bloquea la orden (fail-open).
    """
    cap_raw = os.environ.get("IA_AUTO_MAX_TOTAL_RISK_PERCENT", "").strip()
    if not cap_raw:
        return True, ""
    try:
        cap = float(cap_raw)
    except ValueError:
        return True, ""
    if cap <= 0:
        return True, ""

    acct = mt5.account_info()
    equity = float(getattr(acct, "equity", 0.0) or 0.0) if acct is not None else 0.0
    if equity <= 0:
        return True, ""

    cur_risk_pct = _bot_total_risk_percent(equity)
    new_risk_pct = _risk_percent_for_entry_sl_volume(
        simbolo=simbolo,
        info=info,
        entry_price=entry_price,
        sl_price=sl_price,
        volume=volume,
        equity=equity,
    )
    if cur_risk_pct is None or new_risk_pct is None:
        return True, ""

    after = cur_risk_pct + new_risk_pct
    if after > cap:
        return False, (
            f"riesgo_total={after:.2f}% (abierto={cur_risk_pct:.2f}% + nueva={new_risk_pct:.2f}%) "
            f"> cap {cap:.2f}%"
        )
    return True, ""


def enviar_orden(
    simbolo: str,
    buy: bool,
    *,
    session_trade_num: int | None = None,
    ia_confidence: int | None = None,
) -> bool:
    mt5.symbol_select(simbolo, True)
    info = mt5.symbol_info(simbolo)
    if info is None:
        code, msg = mt5.last_error()
        print(f"Sin symbol_info para {simbolo}. ({code}) {msg}", file=sys.stderr)
        return False

    trade_mode = getattr(info, "trade_mode", None)
    if trade_mode is not None and int(trade_mode) == mt5.SYMBOL_TRADE_MODE_DISABLED:
        print(f"{simbolo}: trading deshabilitado para este símbolo.", file=sys.stderr)
        return False

    tick = mt5.symbol_info_tick(simbolo)
    if tick is None:
        code, msg = mt5.last_error()
        print(f"Sin tick para {simbolo}. ({code}) {msg}", file=sys.stderr)
        return False

    now = time.time()
    tick_time = float(getattr(tick, "time", 0.0) or 0.0)
    if tick_time and (now - tick_time) > 15:
        print(f"{simbolo}: cotización stale (>{now - tick_time:.0f}s). No envío.", file=sys.stderr)
        return False

    lim_sp_raw = os.environ.get(
        "IA_AUTO_MAX_SPREAD_POINTS",
        os.environ.get("MAX_SPREAD_POINTS", "50"),
    ).strip()
    try:
        lim_sp = int(lim_sp_raw) if lim_sp_raw else 0
    except ValueError:
        lim_sp = 50
    if not es_spread_valido(simbolo, lim_sp):
        return False

    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    if bid <= 0 or ask <= 0:
        return False

    sp_pts = _spread_points(info, bid, ask)
    if sp_pts is not None:
        try:
            _append_spread_sample(_spread_sample_path(simbolo), int(time.time()), float(sp_pts))
        except Exception:
            pass
        if not _spread_dynamic_allows_trade(simbolo, int(time.time()), float(sp_pts)):
            print(
                f"{simbolo}: spread dinámico bloquea entrada "
                f"(actual ~{sp_pts:.1f} pts vs histórico). "
                f"IA_AUTO_SPREAD_DYNAMIC=0 para desactivar.",
                file=sys.stderr,
            )
            return False

    ok_slip, slip_why = slippage_guard_allows_order(simbolo)
    if not ok_slip:
        print(
            f"{simbolo}: bloqueado por slippage reciente ({slip_why}). "
            "IA_EXEC_SLIP_GUARD_ENABLE=0 o subí IA_EXEC_SLIP_GUARD_MAX_AVG_PTS.",
            file=sys.stderr,
        )
        return False

    price = ask if buy else bid
    digits = int(getattr(info, "digits", 5) or 5)
    point = float(getattr(info, "point", 0.0) or 0.0)
    stops_level = int(getattr(info, "trade_stops_level", 0) or 0)
    min_dist = float(stops_level) * point if stops_level > 0 and point > 0 else 0.0

    try:
        rr = float(os.environ.get("RR", "2").strip() or "2")
    except ValueError:
        rr = 2.0
    rr = max(1e-9, rr)
    tp_mode = os.environ.get("IA_AUTO_TP_MODE", "").strip().lower()
    use_trailing_tp = tp_mode in ("trailing_atr", "trail", "trailing")

    if not pro_session_allows_order():
        print(f"{simbolo}: fuera de ventana IA_PRO_SESSION_* (sesion bancaria).", file=sys.stderr)
        return False

    sl_mode = os.environ.get("IA_AUTO_SL_MODE", "percent").strip().lower()
    sl_dist = 0.0
    if sl_mode in ("atr", "atr_m5"):
        try:
            atr_period = int(os.environ.get("IA_AUTO_ATR_PERIOD", "14").strip() or "14")
        except ValueError:
            atr_period = 14
        try:
            atr_mult = float(
                os.environ.get(
                    "IA_AUTO_SL_ATR_MULT",
                    os.environ.get("IA_ATR_SL_MULT", "1.6"),
                ).strip()
                or "1.6"
            )
        except ValueError:
            atr_mult = 1.6
        m5 = mt5_copy_rates_from_pos_cached(simbolo, mt5.TIMEFRAME_M5, 0, 400)
        if m5 is None or len(m5) < atr_period + 10:
            return False
        highs0 = [float(r["high"]) for r in m5]
        lows0 = [float(r["low"]) for r in m5]
        closes0 = [float(r["close"]) for r in m5]
        trs0 = _true_ranges(highs0, lows0, closes0)
        ser = _atr_series(trs0, atr_period)
        if not ser:
            return False
        atr = float(ser[-1])
        sl_dist = max(atr * atr_mult, min_dist)
    else:
        try:
            sl_pct = float(os.environ.get("IA_AUTO_SL_PRICE_PERCENT", "5").strip() or "5") / 100.0
        except ValueError:
            sl_pct = 0.05
        sl_pct = max(1e-12, min(sl_pct, 0.99))
        sl_dist = max(price * sl_pct, min_dist)
    tp_dist = sl_dist * rr
    if buy:
        sl = price - sl_dist
        tp = (price + tp_dist) if not use_trailing_tp else 0.0
        typ = mt5.ORDER_TYPE_BUY
    else:
        sl = price + sl_dist
        tp = (price - tp_dist) if not use_trailing_tp else 0.0
        typ = mt5.ORDER_TYPE_SELL

    if buy and dxy_blocks_gold_buy(simbolo):
        print(f"{simbolo}: filtro DXY bloquea COMPRAS (indice alcista).", file=sys.stderr)
        return False

    sl = round(float(sl), digits)
    if use_trailing_tp:
        tp = 0.0
    else:
        tp = round(float(tp), digits)

    rper = _risk_percent_per_trade()
    if rper is not None:
        acct = mt5.account_info()
        equity_now = float(getattr(acct, "equity", 0.0) or 0.0) if acct is not None else 0.0
        rper_eff = _effective_risk_percent_for_account(float(rper), account_equity=equity_now)
        vcalc = calcular_lotaje_dinamico(
            simbolo,
            buy=buy,
            entry_price=price,
            sl_price=sl,
            riesgo_percent=rper_eff,
            info=info,
        )
        if vcalc is None:
            print(
                "[IA_AUTO] No se pudo calcular volumen por riesgo (order_calc_profit); "
                "usá IA_AUTO_LOTS o revisá símbolo.",
                file=sys.stderr,
            )
            return False
        vol = vcalc
    else:
        raw_vol = float(os.environ.get("IA_AUTO_LOTS", "0.01"))
        vol_step = float(getattr(info, "volume_step", 0.01) or 0.01)
        vol_min = float(getattr(info, "volume_min", 0.01) or 0.01)
        vol = max(vol_min, _round_down_to_step(raw_vol, vol_step))
        vol_max = float(getattr(info, "volume_max", 0.0) or 0.0)
        if vol_max > 0:
            vol = min(vol, vol_max)

    ok_cap, why_cap = _total_risk_cap_allows_new_order(
        simbolo=simbolo,
        info=info,
        entry_price=float(price),
        sl_price=float(sl),
        volume=float(vol),
    )
    if not ok_cap:
        print(f"[RISK_CAP] Orden cancelada: {simbolo} {why_cap}", file=sys.stderr)
        return False

    deviation = int(os.environ.get("DEVIATION", os.environ.get("IA_AUTO_DEVIATION", "20")))
    comment = (os.environ.get("IA_AUTO_COMMENT") or "IA_AUTO")[:31]
    filling_modes = _allowed_filling_modes_symbol(simbolo)

    for fm in filling_modes:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": simbolo,
            "volume": float(vol),
            "type": typ,
            "price": float(price),
            "sl": float(sl),
            "tp": float(tp),
            "deviation": deviation,
            "magic": BOT_MAGIC,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": int(fm),
        }
        result = mt5.order_send(request)
        if result is None:
            code, msg = mt5.last_error()
            print(f"order_send=None ({code}) {msg}", file=sys.stderr)
            continue
        retcode = int(getattr(result, "retcode", -1))
        if getattr(result, "deal", 0) or getattr(result, "order", 0):
            side = "COMPRA" if buy else "VENTA"
            px_exec = getattr(result, "price", None)
            if px_exec is not None:
                try:
                    px_exec = float(px_exec)
                except (TypeError, ValueError):
                    px_exec = None
            log_execution_quality(
                symbol=simbolo,
                side=side,
                price_requested=float(price),
                price_executed=px_exec,
                spread_points=float(sp_pts) if sp_pts is not None else None,
                retcode=retcode,
                volume=float(vol),
                deal=int(getattr(result, "deal", 0) or 0),
                symbol_point=float(point) if point and point > 0 else None,
            )
            print(f"Orden enviada: {simbolo} {side} vol={vol} SL={sl:.5f} TP={tp:.5f}")
            _notify_trade_telegram(
                simbolo,
                side,
                vol,
                price,
                sl,
                tp,
                result,
                session_trade_num,
                ia_confidence=ia_confidence,
                trailing_tp=use_trailing_tp,
            )
            return True
        print(
            f"Rechazado filling={fm} retcode={retcode} comment={getattr(result, 'comment', '')}",
            file=sys.stderr,
        )

    return False


def main() -> None:
    load_env_file()
    applied = cargar_configuracion_optimizada()
    if applied:
        print("Configuración optimizada cargada.")
        keys = ", ".join(sorted(applied)[:14])
        more = " ..." if len(applied) > 14 else ""
        print(f"  ({len(applied)} claves: {keys}{more})")

    # Debug rápido: mostrar en consola por qué se descartan señales (ver ia_scanner_loop.log_filtro_descarte)
    if os.environ.get("IA_AUTO_DEBUG_WAITING", "0").strip().lower() in ("1", "true", "yes"):
        os.environ["IA_SCAN_DEBUG_FILTERS"] = "1"
        os.environ.setdefault("IA_SCAN_DASHBOARD", "1")

    enable = os.environ.get("IA_AUTO_ENABLE", "").strip().lower() in ("1", "true", "yes")
    if not enable:
        _fail(
            "Definí IA_AUTO_ENABLE=1 en .env para confirmar que querés auto-trading en esta cuenta."
        )

    validate_scan_session_env()
    _validate_ia_auto_numeric_env()
    _acquire_single_instance_lock()

    os.environ.setdefault("IA_SCAN_QUIET", "1")

    raw = os.environ.get("IA_SCAN_SYMBOLS", "XAUUSD")
    requested_list = [a.strip() for a in raw.split(",") if a.strip()]
    interval = float(os.environ.get("IA_SCAN_INTERVAL_S", "30"))
    cooldown = float(os.environ.get("IA_AUTO_COOLDOWN_S", "900"))
    multi_per_round = os.environ.get("IA_AUTO_MULTI_PER_ROUND", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    try:
        burst_delay = float(os.environ.get("IA_AUTO_BURST_DELAY_S", "3"))
    except ValueError:
        burst_delay = 3.0
    burst_delay = max(0.0, burst_delay)
    stack_same_symbol = os.environ.get("IA_AUTO_STACK_SAME_SYMBOL", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    use_hours = os.environ.get("IA_AUTO_USE_HOURS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )

    mt5_path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not ok:
        code, msg = mt5.last_error()
        _fail(f"No se pudo inicializar MT5. ({code}) {msg}")

    try:
        stopped_deadline = False
        session_start_utc: datetime | None = None
        telegram_report = False

        ti = mt5.terminal_info()
        if ti is not None and not bool(getattr(ti, "trade_allowed", False)):
            _fail("trade_allowed=False: activá Algo Trading / AutoTrading en MT5.")

        _demo_only_or_exit()

        resolved_map: list[tuple[str, str]] = []
        for req in requested_list:
            r = _resolve_scan_symbol(req)
            if not r:
                print(f"{req}: símbolo no operable, se omite.", file=sys.stderr)
                continue
            resolved_map.append((req, r))
        if not resolved_map:
            _fail("No hay símbolos válidos.")

        stop_hm = _parse_local_stop_at(os.environ.get("IA_AUTO_STOP_AT", ""))
        deadline_local: datetime | None = None
        if stop_hm:
            sh, sm = stop_hm
            deadline_local = datetime.combine(date.today(), dt_time(hour=sh, minute=sm))

        tg_raw = os.environ.get("IA_AUTO_TELEGRAM_REPORT", "").strip().lower()
        if tg_raw in ("",):
            telegram_report = stop_hm is not None
        else:
            telegram_report = tg_raw in ("1", "true", "yes")

        print(
            f"Auto-trading DEMO | simbolos={len(resolved_map)} | intervalo={interval}s | "
            f"cooldown tras orden={cooldown}s | multi/ronda={multi_per_round} | "
            f"burst={burst_delay}s | stack mismo simbolo={stack_same_symbol} | Ctrl+C salir"
            + (
                f" | cierre local {os.environ.get('IA_AUTO_STOP_AT')} -> Telegram"
                if stop_hm and telegram_report
                else (f" | cierre local {os.environ.get('IA_AUTO_STOP_AT')}" if stop_hm else "")
            )
        )
        rpt = _risk_percent_per_trade()
        sl_d = os.environ.get("IA_AUTO_SL_PRICE_PERCENT", "5")
        rr_d = os.environ.get("RR", "2")
        if rpt is not None:
            bundle_note = ""
            if os.environ.get("IA_AUTO_RISK_BUNDLE_PERCENT", "").strip():
                bundle_note = (
                    f" bundle {os.environ.get('IA_AUTO_RISK_BUNDLE_PERCENT')}% / "
                    f"{os.environ.get('IA_AUTO_RISK_BUNDLE_TRADES', '?')} ops |"
                )
            sl_mode_banner = os.environ.get("IA_AUTO_SL_MODE", "percent").strip().lower()
            if sl_mode_banner in ("atr", "atr_m5"):
                am = os.environ.get("IA_AUTO_SL_ATR_MULT", "1.6")
                print(
                    f"Riesgo objetivo ~{rpt:.2f}% equity por operacion |{bundle_note} "
                    f"lote dinamico (order_calc_profit): SL = ATR M5 x {am} "
                    f"(mas volatilidad -> SL mas lejos -> menos lote) | RR {rr_d}"
                )
            else:
                print(
                    f"Riesgo objetivo ~{rpt:.2f}% equity por operacion |{bundle_note} "
                    f"lote dinamico | SL {sl_d}% precio | RR {rr_d} -> "
                    f"TP ~{float(sl_d) * float(rr_d):.0f}% precio (SL*RR)"
                )
        else:
            lots_d = os.environ.get("IA_AUTO_LOTS", "0.01")
            print(f"Volumen fijo IA_AUTO_LOTS={lots_d} | SL {sl_d}% | RR {rr_d}")

        pt_d, ml_d = _daily_limits_usd_config()
        if pt_d is not None or ml_d is not None:
            tz_b = os.environ.get("IA_AUTO_DAILY_PNL_TZ", "America/Argentina/Buenos_Aires").strip()
            parts: list[str] = []
            if pt_d is not None:
                parts.append(f"meta PnL cerrado >= {pt_d:.0f} -> sin nuevas entradas")
            if ml_d is not None:
                parts.append(f"max pérdida diaria {ml_d:.0f} -> sin nuevas entradas")
            ex: list[str] = []
            if _stop_loop_on_daily_profit():
                ex.append("salir del bucle al cumplir meta")
            if ml_d is not None and _stop_loop_on_daily_max_loss():
                ex.append("salir del bucle al tope pérdida")
            sfx = f" | {'; '.join(ex)}" if ex else ""
            print(f"Límites diarios (TZ {tz_b or 'UTC'}): {' | '.join(parts)}{sfx}")

        if deadline_local is not None and datetime.now() >= deadline_local:
            print(
                f"Ya pasó la hora de cierre ({os.environ.get('IA_AUTO_STOP_AT')}) hoy; no se opera.",
                file=sys.stderr,
            )
            return

        session_start_utc = datetime.now(timezone.utc)

        _windows_prevent_sleep_while_running()

        max_trades_raw = os.environ.get("IA_AUTO_MAX_TRADES", "").strip()
        try:
            max_trades = int(max_trades_raw) if max_trades_raw else 0
        except ValueError:
            max_trades = 0
        trades_sent_session = 0

        resolved_symbols_only = [sym for _, sym in resolved_map]

        relax_ctx: dict = {"level": 0}

        while True:
            if os.environ.get("IA_OPTUNA_RELOAD_EACH_ROUND", "1").strip().lower() not in (
                "0",
                "false",
                "no",
            ):
                cargar_configuracion_optimizada()

            try:
                journal_tick()
            except Exception as e:
                print(f"[bitácora] {e}", file=sys.stderr)

            if "mom_br_base" not in relax_ctx:
                relax_ctx["mom_br_base"] = os.environ.get(
                    "IA_M15_MOMENTUM_MIN_BODY_RATIO", "0.45"
                )
                relax_ctx["block_hv_base"] = os.environ.get("IA_REGIME_BLOCK_HIGH_VOL", "1")

            try:
                _mx_log = execution_quality_max_mb_from_env()
                if _mx_log > 0:
                    rotar_log_por_tamaño(execution_quality_csv_path(), _mx_log)
            except Exception:
                pass

            if trades_sent_session > 0 and int(relax_ctx.get("level", 0)) > 0:
                print("[auto-relax] reinicio tras orden; niveles de relajación a cero.")
                relax_ctx["level"] = 0

            elapsed_relax = _elapsed_hours_since_session_open_ny()
            _maybe_advance_auto_relax(elapsed_relax, trades_sent_session, relax_ctx)
            _reapply_auto_relax_patches(relax_ctx)
            _apply_demo_relaxed_signals()

            aplicar_escucha_boton_panico_ia()

            if _IA_PAUSE_POR_COMANDO_TELEGRAM:
                print(
                    f"{datetime.now().strftime('%H:%M:%S')} [panic] Ciclo IA en PAUSA (/INICIAR desde Telegram)."
                )
                time.sleep(max(float(interval), 5.0))
                continue

            try:
                intentar_enviar_reporte_semanal_si_toca()
            except Exception as e:
                print(f"[reporte-semanal] {e}", file=sys.stderr)

            try:
                # Gestión activa: breakeven (IA_BE_ENABLE) + trailing ATR si IA_AUTO_TP_MODE=trailing_atr
                manage_all_bot_positions_expert(resolved_symbols_only)
            except Exception as e:
                print(f"[pos-mgmt] {e}", file=sys.stderr)

            try:
                if gestionar_precierre_fin_de_semana():
                    try:
                        wk_sl = float(os.environ.get("IA_WEEKEND_LOOP_SLEEP_S", "").strip() or "0")
                    except ValueError:
                        wk_sl = 0.0
                    if wk_sl <= 0:
                        wk_sl = max(float(interval), 60.0)
                    print(
                        f"[WEEKEND] Pausa fin de semana (sin nuevas órdenes); "
                        f"próxima comprobación en ~{wk_sl:.0f}s | Ctrl+C salir"
                    )
                    try:
                        n_mem = sync_memory_from_mt5(BOT_MAGIC)
                        if n_mem > 0 and os.environ.get("IA_AUTO_MEMORY_LOG", "1").strip().lower() not in (
                            "0",
                            "false",
                            "no",
                        ):
                            print(f"[memoria] +{n_mem} | {summary_from_csv()}")
                    except Exception as e:
                        print(f"[memoria] {e}", file=sys.stderr)
                    time.sleep(wk_sl)
                    continue
            except Exception as e:
                print(f"[WEEKEND] {e}", file=sys.stderr)

            if deadline_local is not None and datetime.now() >= deadline_local:
                print(f"Sesión terminada (cierre programado {os.environ.get('IA_AUTO_STOP_AT')}).")
                stopped_deadline = True
                break

            if use_hours and not es_horario_seguro():
                time.sleep(interval)
                continue

            _maybe_reset_daily_notify()
            pnl_d, lim_k = _daily_limit_state()
            if lim_k is not None and pnl_d is not None:
                _maybe_announce_daily_limit(lim_k, pnl_d)
                stop_p = lim_k == "profit_cap" and _stop_loop_on_daily_profit()
                stop_l = lim_k == "loss_cap" and _stop_loop_on_daily_max_loss()
                if stop_p or stop_l:
                    lab = "meta diaria" if stop_p else "tope pérdida diaria"
                    print(f"Fin bucle: {lab}.")
                    break
                time.sleep(max(float(interval), 5.0))
                continue

            traded_this_round = False
            for requested, sym in resolved_map:
                if not stack_same_symbol and _position_side_for_bot(sym) is not None:
                    continue

                sig = analizar_ia(sym)
                if os.environ.get("SENTIMENT_FILTER", "0").strip().lower() in ("1", "true", "yes"):
                    try:
                        from sentiment_news import sentiment_allows_trade

                        if not sentiment_allows_trade(sym, sig):
                            continue
                    except Exception as e:
                        print(f"[SENTIMENT] {e}", file=sys.stderr)

                if "COMPRA CONFIRMADA" in sig:
                    if enviar_orden(
                        sym,
                        buy=True,
                        session_trade_num=trades_sent_session + 1,
                        ia_confidence=_confidence_from_signal(sig),
                    ):
                        log_trade_entry(symbol=sym, side="BUY", ia_confidence=_confidence_from_signal(sig))
                        traded_this_round = True
                        trades_sent_session += 1
                        tag = requested if sym == requested else f"{requested}->{sym}"
                        print(f"ALERTA {tag}: COMPRA @ {datetime.now().strftime('%H:%M:%S')}")
                        if max_trades > 0 and trades_sent_session >= max_trades:
                            break
                        if multi_per_round:
                            time.sleep(burst_delay)
                            continue
                        try:
                            sc = float(os.environ.get("IA_SHAKEOUT_COOLDOWN_S", "0").strip() or "0")
                        except ValueError:
                            sc = 0.0
                        cd_use = sc if shakeout_reentry_window_active(sym, True) else cooldown
                        time.sleep(cd_use)
                        break
                elif "VENTA CONFIRMADA" in sig:
                    if enviar_orden(
                        sym,
                        buy=False,
                        session_trade_num=trades_sent_session + 1,
                        ia_confidence=_confidence_from_signal(sig),
                    ):
                        log_trade_entry(symbol=sym, side="SELL", ia_confidence=_confidence_from_signal(sig))
                        traded_this_round = True
                        trades_sent_session += 1
                        tag = requested if sym == requested else f"{requested}->{sym}"
                        print(f"ALERTA {tag}: VENTA @ {datetime.now().strftime('%H:%M:%S')}")
                        if max_trades > 0 and trades_sent_session >= max_trades:
                            break
                        if multi_per_round:
                            time.sleep(burst_delay)
                            continue
                        try:
                            sc = float(os.environ.get("IA_SHAKEOUT_COOLDOWN_S", "0").strip() or "0")
                        except ValueError:
                            sc = 0.0
                        cd_use = sc if shakeout_reentry_window_active(sym, False) else cooldown
                        time.sleep(cd_use)
                        break

            if max_trades > 0 and trades_sent_session >= max_trades:
                print(f"Límite IA_AUTO_MAX_TRADES={max_trades} alcanzado; fin de sesión.")
                break

            try:
                n_mem = sync_memory_from_mt5(BOT_MAGIC)
                if n_mem > 0 and os.environ.get("IA_AUTO_MEMORY_LOG", "1").strip().lower() not in (
                    "0",
                    "false",
                    "no",
                ):
                    print(f"[memoria] +{n_mem} cierre(s) registrado(s) | {summary_from_csv()}")
            except Exception as e:
                print(f"[memoria] {e}", file=sys.stderr)

            if not traded_this_round:
                print(f"{datetime.now().strftime('%H:%M:%S')} escaneando...")
            time.sleep(interval)

    except KeyboardInterrupt:
        print("Auto-trading detenido.")
    finally:
        _windows_release_sleep_inhibit()
        if stopped_deadline and telegram_report and session_start_utc is not None:
            from telegram_hour_pnl import send_pnl_window_telegram

            utc_end = datetime.now(timezone.utc)
            ok_tg = send_pnl_window_telegram(
                session_start_utc,
                utc_end,
                heading="Reporte sesión IA_AUTO (hasta horario)",
            )
            if ok_tg:
                print("Reporte enviado por Telegram.")
            else:
                print(
                    "No se pudo enviar el reporte por Telegram (TELEGRAM_* en .env o red).",
                    file=sys.stderr,
                )
        mt5.shutdown()


if __name__ == "__main__":
    main()
