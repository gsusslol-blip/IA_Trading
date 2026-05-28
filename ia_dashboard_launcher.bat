@echo off
title IA_Trading_Optuna_Dashboard
cd /d "%~dp0"

echo ===================================================
echo IA_TRADING - OPTUNA DASHBOARD
echo Navegador: http://127.0.0.1:8080  (o IA_OPTUNA_DASHBOARD_PORT en .env)
echo ===================================================
echo.

set "DB_PATH=logs\ia_optuna_trials.db"
if not exist "%DB_PATH%" (
    echo Advertencia: no existe %DB_PATH% todavia.
    echo Ejecuta primero: python ia_auto_optimizer.py --force
    echo El panel puede arrancar en espera hasta que exista la base SQLite.
    echo.
)

REM Usa ruta SQLite absoluta via Python (fiable en Task Scheduler / VPS)
python ia_optuna_dashboard.py %*
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Error al iniciar dashboard. Codigo: %EXIT_CODE%
    echo Instalar: pip install -r requirements.txt
    timeout /t 15 >nul
)
exit /b %EXIT_CODE%
