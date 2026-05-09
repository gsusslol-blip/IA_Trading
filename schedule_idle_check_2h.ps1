# Programa una comprobacion unica dentro de ~2 horas:
# cuenta deals BOT_MAGIC en MT5; si hay 0, ajusta params_optimized.json (ver check_idle_tune.py).
#
# Ejecutar desde PowerShell en la carpeta del proyecto:
#   .\schedule_idle_check_2h.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "$env:LOCALAPPDATA\Python\bin\python.exe"
if (-not (Test-Path $Python)) {
  $Python = "python"
}
$Bat = Join-Path $Root "run_idle_check.bat"
if (-not (Test-Path $Bat)) {
  Write-Host "No se encuentra run_idle_check.bat en $Root"
  exit 1
}

$TaskName = "IA_Trading_IdleCheck2h"
$When = (Get-Date).AddHours(2)
$sd = $When.ToString("MM/dd/yyyy")
$st = $When.ToString("HH:mm")
$Tr = $Bat
$Schtasks = Join-Path $env:WINDIR "System32\schtasks.exe"
if (-not (Test-Path -LiteralPath $Schtasks)) {
  $Schtasks = "schtasks"
}

$null = cmd /c "`"$Schtasks`" /Delete /TN `"$TaskName`" /F 2>nul"
$out = cmd /c "`"$Schtasks`" /Create /TN `"$TaskName`" /SC ONCE /SD $sd /ST $st /TR $Tr /RL LIMITED /F"
if ($LASTEXITCODE -ne 0) {
  Write-Host "[error] schtasks Create fallo: $out"
  exit 1
}

Write-Host "OK: tarea '$TaskName' programada para $sd $st (local)"
Write-Host "Comando: $Tr"
Write-Host "Log: $Root\ia_idle_tune.log"
