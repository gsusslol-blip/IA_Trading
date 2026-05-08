$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\gSuss\AppData\Local\Python\bin\python.exe"
$Script = Join-Path $Root "watchdog_bot.py"

if (-not (Test-Path $Python)) {
  Write-Host "Python no encontrado en $Python"
  exit 1
}
if (-not (Test-Path $Script)) {
  Write-Host "watchdog_bot.py no encontrado en $Script"
  exit 1
}

$TaskName = "IA_Trading_Watchdog"
$IntervalMinutes = 60

# Crear / reemplazar tarea: cada 60 min.
# Runs under current user, without requiring admin.
$Schtasks = "$env:WINDIR\System32\schtasks.exe"
$Action = "`"$Python`" `"$Script`""

try {
  & $Schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
} catch {
  # OK si no existía
}

& $Schtasks /Create `
  /TN $TaskName `
  /SC MINUTE `
  /MO $IntervalMinutes `
  /TR $Action `
  /RL LIMITED `
  /F | Out-Null

Write-Host "OK: Tarea creada $TaskName cada $IntervalMinutes min."
Write-Host "Comando: $Action"

