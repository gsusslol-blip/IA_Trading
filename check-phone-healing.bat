@echo off
title ILARIA - Check phone healing
cd /d "%~dp0"
chcp 65001 >nul
echo ===================================================
echo [!] Tests mantenimiento celular + abrir HUD
echo ===================================================
if not exist .venv\Scripts\python.exe (
  echo Falta .venv. Corre run.bat primero.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m unittest tests.test_phone_hands tests.test_phone_healing -v
echo.
echo HUD: http://localhost:8787/
start "" "http://localhost:8787/"
echo Si Ilaria no esta corriendo, usa el acceso "Ilaria" del escritorio.
pause
