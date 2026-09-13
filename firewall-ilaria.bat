@echo off
:: Inbound TCP 8787 for private/LAN so Android can reach the PC host.
title Ilaria - Firewall 8787
chcp 65001 >nul
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo [!] Hace falta Administrador para crear la regla.
  echo [!] Clic derecho -^> Ejecutar como administrador.
  pause
  exit /b 1
)

call :ensure "Ilaria HUD 8787 LAN" TCP 8787 "Ilaria FastAPI HUD + Android LAN"
call :ensure "Ilaria discover UDP 8788" UDP 8788 "Ilaria phone finds this PC on LAN"
echo.
echo Proba: celu en Wi-Fi, Ilaria abierta, app busca sola (UDP 8788 + TCP 8787).
pause
exit /b 0

:ensure
set RULE=%~1
set PROTO=%~2
set PORT=%~3
set DESC=%~4
netsh advfirewall firewall show rule name="%RULE%" >nul 2>&1
if %errorlevel% equ 0 (
  echo [i] Ya existe: %RULE%
) else (
  echo [+] Creando %RULE% ...
  netsh advfirewall firewall add rule name="%RULE%" dir=in action=allow protocol=%PROTO% localport=%PORT% profile=private enable=yes description="%DESC%"
  if errorlevel 1 (
    echo Fallo al crear la regla.
    pause
    exit /b 1
  )
)
exit /b 0
