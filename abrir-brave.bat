@echo off
set URL=http://localhost:8787/welcome
set "BRAVE="
if exist "%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe" set "BRAVE=%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"
if exist "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" set "BRAVE=C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
if exist "C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe" set "BRAVE=C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"

echo Ilaria tiene que estar corriendo (run.bat). Brave rompe https:// y 127.0.0.1
if defined BRAVE (
  start "" "%BRAVE%" --disable-https-upgrades --allow-insecure-localhost "%URL%"
) else (
  echo No encontre Brave. Abro Edge.
  start msedge "%URL%"
)
