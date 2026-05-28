# Arquitectura IA_Trading

Los **módulos `.py` permanecen en la raíz** del repositorio para no romper imports ni scripts del VPS.
Los **datos y secretos** se organizan en carpetas bajo esta raíz.

## Árbol lógico

```
IA_Trading/
├── modelos/                    # ML (.pkl entrenado por ia_trainer.py)
├── config/                     # .env (opcional), settings.json
├── logs/                       # CSV de auditoría y ejecución
├── core/                       # (mapa) motor MT5 e indicadores
├── trading/                    # (mapa) señales, oro, noticias
├── execution/                  # (mapa) gestión en vivo y Telegram
├── ia_auto_trade_loop.py       # Bucle principal
├── ia_trainer.py               # Entrenamiento ML
├── ia_watchdog.bat             # Reinicio automático en VPS Windows
└── watchdog_notify.py          # Alerta Telegram al caer el bot
```

## Mapa módulo → carpeta lógica

| Carpeta lógica | Archivos (raíz del repo) |
|----------------|--------------------------|
| **core** | `mt5_price_engine.py`, `mt5_prices.py`, `market_regime.py`, `ia_indicators.py`, `ia_d1_levels.py`, `ia_filesystem.py`, `ia_paths.py`, `ia_mt5_connection.py`, `ia_mt5_normalize.py`, `local_env.py` |
| **trading** | `ia_scanner_loop.py`, `signal_analysis.py`, `ia_gold_risk.py`, `ia_gold_risk_core.py`, `ia_news_filter.py`, `ia_asset_profile.py`, `ia_regime_autopilot.py`, `ia_risk_manager.py`, `ia_risk_streak.py` |
| **execution** | `ia_auto_expert.py`, `ia_remote_control.py`, `telegram_listener.py`, `ia_notifier.py`, `telegram_utils.py`, `ia_audit_logger.py`, `ia_intelligence_layer.py` |
| **raíz (orquestación)** | `ia_auto_trade_loop.py`, `ia_trainer.py`, `ia_auto_optimizer.py`, `optuna_walkforward.py`, `ia_memory_gc.py`, `ia_order_async.py`, `ia_walkforward_validate.py` |

## Datos en `logs/`

| Archivo | Variable `.env` | Uso |
|---------|-----------------|-----|
| `logs/trade_audit_ml.csv` | `IA_ML_AUDIT_CSV` | Dataset ML (apertura/cierre) |
| `logs/execution_quality.csv` | `IA_EXEC_QUALITY_CSV` | Slippage / spread |
| `logs/ia_audit_pending.json` | `IA_ML_AUDIT_PENDING` | Snapshots pendientes |
| `logs/watchdog_notify_state.json` | — | Cooldown alertas watchdog |
| `logs/ia_optuna_trials.db` | `IA_OPTUNA_DB_FILE` | Trials Optuna (Optuna Dashboard) |

Migración manual: si tenés CSV viejos en la raíz, muévelos a `logs/` o define las rutas en `.env`.

## Config en `config/`

- Copiá `.env.example` → `config/.env` (o seguí usando `.env` en la raíz).
- `ENV_FILE=config/.env` fuerza un archivo concreto.
- `config/settings.json` — parámetros no secretos (plantilla: `settings.json.example`).

## VPS Windows — arranque automático

0. `pip install -r requirements.txt` y `python ia_sanity_check.py` (debe terminar sin errores).
0b. Tras la primera optimización: `ia_dashboard_launcher.bat` (o `ia_optuna_dashboard.py`) → http://127.0.0.1:8080/ (consola separada del bot).
0c. VPS: Programador de tareas → al iniciar el equipo → `ia_dashboard_launcher.bat` (ejecutar aunque el usuario no haya iniciado sesión).
1. Ejecutar `ia_watchdog.bat` (no `ia_auto_trade_loop.py` directo).
2. `Win+R` → `shell:startup` → acceso directo a `ia_watchdog.bat`.
3. Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` en `.env`.
4. Opcional: `IA_WATCHDOG_ALERT_COOLDOWN_S=300`, `IA_WATCHDOG_TELEGRAM=1`.

## Certificación del sistema

- **Estrategia**: M15 + H4 + régimen H1.
- **Capital**: margen MT5, lotaje oro por `trade_contract_size`, tope de riesgo cartera.
- **Resiliencia**: noticias, reconexión MT5, watchdog + Telegram.
- **Fin de semana**: `ia_friday_closure` (viernes 19:30 UTC) + `ia_data_maintenance` (purga sábado) + Optuna.
- **IA**: Optuna + Random Forest + auditoría en `logs/`.
- **Supervisión**: `/PANIC` y alertas Telegram.
