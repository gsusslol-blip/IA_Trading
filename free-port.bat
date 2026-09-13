@echo off
:: Free port 8787 and stop hung Ilaria / build locks on dist\JARVIS\data
chcp 65001 >nul
cd /d "%~dp0"
echo [!] Liberando Ilaria / puerto 8787 ...

taskkill /F /IM Ilaria.exe >nul 2>&1
if %errorlevel% equ 0 echo [+] Cerre Ilaria.exe

:: Kill only LISTENING owners of :8787 (not TIME_WAIT)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8787" ^| findstr "LISTENING"') do (
  echo [+] Matando PID %%P en :8787
  taskkill /F /PID %%P >nul 2>&1
)

:: Optional: unlock dist folder leftovers
if exist "dist\JARVIS\Ilaria.exe" (
  echo [i] dist\JARVIS listo para rebuild si no hay handles abiertos.
)

echo [+] Listo.
exit /b 0
