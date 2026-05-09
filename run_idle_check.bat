@echo off
cd /d "%~dp0"
"%LOCALAPPDATA%\Python\bin\python.exe" check_idle_tune.py %*
if not exist "%LOCALAPPDATA%\Python\bin\python.exe" python check_idle_tune.py %*
exit /b %ERRORLEVEL%
