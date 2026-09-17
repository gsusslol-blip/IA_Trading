@echo off
title ILARIA - Sistema Asistente Local
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ===================================================
echo             INICIALIZANDO ECOSISTEMA ILARIA
echo ===================================================
echo HUD: http://localhost:8787/
echo Celular: Wi-Fi (UDP 8788). OTA APK: /api/android/update
echo Updates PC: ILARIA_UPDATE_URL en .env (ZIP liviano, sin modelos).
echo.

:: Carpetas criticas (TTS cache, recovery, workspace seed)
if not exist "data\assets\tts_cache" mkdir "data\assets\tts_cache"
if not exist "data\tts-cache" mkdir "data\tts-cache"
if not exist "data\recovery" mkdir "data\recovery"
if not exist "data\workspace" mkdir "data\workspace"

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
set FASTER_WHISPER_MODEL=small
set WHISPER_DEVICE=cpu

if not exist .venv\Scripts\python.exe py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -c "import fastapi,webview,edge_tts" 2>nul
if errorlevel 1 python -m pip install -r requirements.txt
python -c "import faster_whisper" 2>nul
if errorlevel 1 python -m pip install faster-whisper

:: Ollama: soft check + launch if installed but idle
where ollama >nul 2>&1
if errorlevel 1 (
  echo [!] Falta Ollama: https://ollama.com  — ollama pull gemma2:2b
) else (
  tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe">NUL
  if errorlevel 1 (
    echo [WARN] Ollama no esta activo. Intentando ollama serve...
    start "" /B ollama serve
    timeout /t 3 >nul
  ) else (
    echo [OK] Ollama activo.
  )
)
if not exist .env copy .env.example .env

echo.
echo ===================================================
echo     ILARIA EN: http://localhost:8787  (Python/FastAPI)
echo     Telegram: polling dentro de main.py si hay TELEGRAM_BOT_TOKEN
echo     Tunnel WAN: NGROK_AUTHTOKEN en .env (mismo proceso, no start /b)
echo     Health inbox: data\users\USER\workspace\inbox\  (CSV/JSON)
echo ===================================================
echo.
python main.py
pause
