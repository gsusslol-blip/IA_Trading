@echo off
title [ILARIA] - APK Android (cliente LAN)
chcp 65001 >nul
cd /d "%~dp0"

set "JAVA_HOME=C:\Program Files\Microsoft\jdk-17.0.20.8-hotspot"
set "ANDROID_HOME=%~dp0.android-sdk"
set "ANDROID_SDK_ROOT=%ANDROID_HOME%"
set "Path=%JAVA_HOME%\bin;%Path%"

if not exist "%JAVA_HOME%\bin\java.exe" (
  echo [!] Falta OpenJDK 17. Instala: winget install Microsoft.OpenJDK.17
  pause
  exit /b 1
)
if not exist "%ANDROID_HOME%\platforms\android-35" (
  echo [!] Falta el SDK en .android-sdk ^(platforms;android-35^).
  echo     Corre antes el setup del SDK o Android Studio.
  pause
  exit /b 1
)

echo sdk.dir=%ANDROID_HOME:\=\\% > android\local.properties
:: Escape for local.properties format
powershell -NoProfile -Command ^
  "$p='%~dp0.android-sdk'.Replace('\','\\'); Set-Content -Path '%~dp0android\local.properties' -Value ('sdk.dir='+$p) -Encoding ASCII"

echo [+] Compilando APK debug (cliente Wi-Fi hacia la PC)...
cd /d "%~dp0android"
call gradlew.bat assembleDebug --no-daemon
if errorlevel 1 (
  echo [!] Fallo assembleDebug
  pause
  exit /b 1
)

if not exist "%~dp0dist" mkdir "%~dp0dist"
copy /Y "%~dp0android\app\build\outputs\apk\debug\app-debug.apk" "%~dp0dist\Ilaria-android.apk" >nul
echo.
echo [+] Listo: dist\Ilaria-android.apk
echo [!] El celular con 1.4.5+ se actualiza solo desde la PC (barra rosa en la app).
echo     Primera vez: USB. Despues: build-apk.bat + run.bat.
echo.
pause
exit /b 0
