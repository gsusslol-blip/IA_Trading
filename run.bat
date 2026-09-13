@echo off
title ILARIA - Sistema Asistente Local
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ===================================================
echo [!] Inicializando Ilaria
echo ===================================================
echo HUD: http://localhost:8787/
echo Celular: Wi-Fi, no 4G. La app busca la PC sola.

cmd /c "powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\ensure_piper.ps1""

if exist "%~dp0owner-local.bat" call "%~dp0owner-local.bat"
if exist "%~dp0.local-owner.bat" call "%~dp0.local-owner.bat"

set HUD_HOST=0.0.0.0
set HUD_PORT=8787
set JARVIS_OPEN_BROWSER=1
set LLM_PROVIDER=auto
set OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
set OLLAMA_MODEL=gemma2:2b
set STT_PROVIDER=faster-whisper
set FASTER_WHISPER_MODEL=base
set WHISPER_DEVICE=cpu

if not exist .venv\Scripts\python.exe py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -c "import fastapi,webview,edge_tts" 2>nul
if errorlevel 1 python -m pip install -r requirements.txt
python -c "import faster_whisper" 2>nul
if errorlevel 1 python -m pip install faster-whisper

where ollama >nul 2>&1
if errorlevel 1 echo [!] Falta Ollama: https://ollama.com  ollama pull gemma2:2b
if not exist .env copy .env.example .env

echo [+] Puerto 8787 en esta PC y en la LAN
python main.py
pause
