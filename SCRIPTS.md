# Tabla única: scripts del proyecto IA_Trading

Última verificación automática: `python run_tests.py` → **11 tests OK**; `python -m compileall` sobre el proyecto sin errores.

> **Nota:** Las pruebas automáticas no abren MetaTrader 5 ni envían órdenes reales. Para validar en vivo: terminal MT5 abierto, cuenta logueada, `.env` configurado.

## Biblioteca (no se ejecuta sola)

| Módulo | Rol |
|--------|-----|
| `local_env.py` | Carga `.env`. |
| `mt5_prices.py` | Indicadores, órdenes, Telegram, PnL por `magic`, spread, bot demo principal si `RUN_BOT=1`. |
| `signal_analysis.py` | Métricas auxiliares (p. ej. confianza / RSI) para mensajes. |
| `sentiment_news.py` | TextBlob + titulares (NewsAPI opcional); filtros de sentimiento. |

---

## Ejecutables (`python <archivo>`)

| Script | Para qué sirve | Comando | Variables / condiciones importantes |
|--------|----------------|---------|-------------------------------------|
| **`run_tests.py`** | Pruebas automáticas (sintaxis, imports, mocks). | `python run_tests.py` | Sin MT5. Salida 0 = OK. |
| **`mt5_prices.py`** | Lectura de precios; opcional una orden (`PLACE_TRADE=1`) o **bot demo** (`RUN_BOT=1`). | `python mt5_prices.py` | `MT5_PATH`, `TRADE_SYMBOL`, `RUN_BOT`, `PLACE_TRADE`, `SIGNALS_ONLY`, etc. |
| **`mt5_status.py`** | Estado cuenta / posiciones / deals recientes. | `python mt5_status.py` | `MT5_PATH` |
| **`signal_now.py`** | Señal actual + envío Telegram. | `python signal_now.py` | `TELEGRAM_*`, `TRADE_SYMBOL` |
| **`evening_signal.py`** | Análisis tipo “21:00” → Telegram. | `python evening_signal.py` / `--daemon` | `EVENING_*`, Telegram |
| **`m15_ma_scan.py`** | Escaneo M15 SMA rápida/lenta. | `python m15_ma_scan.py` | `MA_SCAN_SYMBOLS`, `MA_FAST`, `MA_SLOW` |
| **`m15_engulfing_scan.py`** | Patrón + volumen M15 + opcional filtro H4. | `python m15_engulfing_scan.py` | `ENGULFING_*`, `ENGULFING_H4_FILTER` |
| **`ia_scanner_loop.py`** | Bucle alertas COMPRA/VENTA (M15+H4), sin órdenes. | `python ia_scanner_loop.py` | `IA_SCAN_*`, Telegram opcional |
| **`ia_auto_trade_loop.py`** | Auto-trading **solo DEMO**; SL/TP; spread. | `python ia_auto_trade_loop.py` | **`IA_AUTO_ENABLE=1`**, `IA_SCAN_SYMBOLS`, `SENTIMENT_FILTER`, `PROFIT_MAX`, `WINRATE_*` |
| **`ia_news_alert_loop.py`** | Loop con intento filtro noticias + Telegram. | `python ia_news_alert_loop.py` | **`IA_NEWS_ALERT_ENABLE=1`** |
| **`sentiment_m15_loop.py`** | M15 simple + sentimiento binario + órdenes (vía `enviar_orden`). | `python sentiment_m15_loop.py` | **`IA_SENTIMENT_M15_ENABLE=1`** |
| **`daily_report_loop.py`** | Reporte diario PnL (magic) a hora local → Telegram. | `python daily_report_loop.py` | **`DAILY_REPORT_ENABLE=1`**, `REPORT_HOUR`, `REPORT_TZ`, Telegram |
| **`bot_pnl_report.py`** | Resumen histórico PnL / win rate (cerradas). | `python bot_pnl_report.py` | `BOT_PNL_DAYS`, `TRADE_SYMBOL`, `BOT_MAGIC` |
| **`close_all_positions.py`** | Cierra posiciones abiertas (por tickets). | `python close_all_positions.py` | `CLOSE_DEVIATION`, MT5 |
| **`telegram_hola.py`** | Prueba mínima Telegram (“hola”). | `python telegram_hola.py` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **`send_tg_preview.py`** | Preview mensaje VIP sin MT5 en vivo. | `python send_tg_preview.py` | Telegram |
| **`preview_tg_messages.py`** | Previsualización variantes Telegram. | `python preview_tg_messages.py` | — |
| **`backtest_walkforward.py`** | Walk-forward backtest (M15) con filtros RSI/ATR/umbral. | `python backtest_walkforward.py` | `BT_*`, `IA_MIN_CONFIDENCE`, `RSI_*`, `ATR_*` |
| **`optuna_walkforward.py`** | Optuna: busca mejores parámetros con walk-forward. | `python optuna_walkforward.py` | `OPTUNA_*`, `BT_*` |

---

## Comprobación rápida recomendada

1. `python run_tests.py` → debe terminar en **OK**.
2. MT5 abierto → `python mt5_status.py`.
3. Con Telegram configurado → `python telegram_hola.py` o `python signal_now.py`.
4. Demo + auto-trading solo si entendés el riesgo → `IA_AUTO_ENABLE=1` y `python ia_auto_trade_loop.py`.

Los scripts de trading fuerte (`ia_*`, `sentiment_m15_loop`, `daily_report_loop`) tienen **flag explícito** `*_ENABLE=1` para no arrancar por error.
