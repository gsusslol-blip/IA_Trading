@echo off
title [ILARIA v1.3.4] - Compilacion portatil
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

echo ==========================================================
echo [!] Protocolo de empaquetado portatil — Ilaria v1.3.4
echo [!] Workspace: %cd%
echo ==========================================================

:: 1. Liberar Ilaria.exe y dueños LISTENING de :8787 (no TIME_WAIT)
echo [!] Liberando puerto 8787 e instancias previas...
call "%~dp0free-port.bat"
ping -n 3 127.0.0.1 >nul

:: 2. Limpieza de caches PyInstaller / binario viejo
echo [+] Limpiando caches de build...
if exist "build" rmdir /s /q "build" 2>nul
if exist "dist\JARVIS\Ilaria.exe" (
  echo [!] Eliminando Ilaria.exe previo para evitar bloqueo de sobrescritura...
  del /q /f "dist\JARVIS\Ilaria.exe" >nul 2>&1
)

:: 3. Empaquetado con jarvis.spec (siempre desde .venv)
if not exist .venv\Scripts\python.exe (
  echo [+] Creando entorno .venv ...
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
echo [+] Dependencias + PyInstaller...
python -m pip install -q -r requirements.txt pyinstaller
echo [+] Invocando PyInstaller --clean jarvis.spec ...
python -m PyInstaller --noconfirm --clean jarvis.spec
if errorlevel 1 (
  echo [!] Fallo el empaquetado. Corre free-port.bat y reintenta.
  pause
  exit /b 1
)

:: 4. Persistencia local junto al exe
echo [+] Inyectando data/ y .env junto al binario...
if not exist "dist\JARVIS\data" mkdir "dist\JARVIS\data"
if exist .env copy /Y .env dist\JARVIS\.env >nul
if exist .env.example copy /Y .env.example dist\JARVIS\.env.example >nul
if exist data xcopy /E /I /Y data dist\JARVIS\data >nul
(
  echo Ilaria v1.3.4
  echo.
  echo Doble clic en Ilaria.exe
  echo HUD local + celular en la misma Wi-Fi ^(HUD_HOST=0.0.0.0^).
  echo Firewall: ejecuta firewall-ilaria.bat como Administrador una vez.
  echo Datos y .env quedan junto al exe ^(no los subas a internet^).
  echo Si no abre: WebView2 Runtime de Microsoft Edge.
) > dist\JARVIS\LEEME.txt

echo ==========================================================
echo [+] Listo: dist\JARVIS\Ilaria.exe
echo [!] Dev rapido: run.bat  ^|  Health: http://localhost:8787/health
echo ==========================================================
pause
exit /b 0
