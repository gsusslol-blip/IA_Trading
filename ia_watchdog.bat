@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title IA_Trading_Watchdog

:: --- Python: preferir venv del proyecto ---
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

set "SCRIPT_PRINCIPAL=ia_auto_trade_loop.py"
set "RESTART_DELAY_S=10"

if not "%IA_WATCHDOG_RESTART_S%"=="" set "RESTART_DELAY_S=%IA_WATCHDOG_RESTART_S%"

echo ===================================================
echo   IA_TRADING - VPS WATCHDOG ACTIVADO
echo   Vigilancia 24/7 de %SCRIPT_PRINCIPAL%
echo   Carpeta: %CD%
echo ===================================================

"%PYTHON_EXE%" watchdog_notify.py --event started

:BUCLE_VIGILANCIA
echo [%date% %time%] Lanzando el bot principal...
"%PYTHON_EXE%" "%SCRIPT_PRINCIPAL%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo [%date% %time%] ALERTA: el bot termino (exit=%EXIT_CODE%).
"%PYTHON_EXE%" watchdog_notify.py --event stopped

echo Reiniciando en %RESTART_DELAY_S% segundos...
timeout /t %RESTART_DELAY_S% /nobreak >nul

goto BUCLE_VIGILANCIA
