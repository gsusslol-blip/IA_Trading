# Plan de energía: menos probabilidad de suspensión con MT5/bot (Windows).
# El script ia_auto_trade_loop.py ya inhibe suspensión por inactividad mientras corre.
# Esto ajusta además el esquema activo (útil si cerrás la tapa del portátil u otro disparador).
#
# Uso (PowerShell):
#   .\keep_awake_power_plan.ps1
# Revertir valores razonables:
#   .\keep_awake_power_plan.ps1 -Restore
#
# Hibernate off suele requerir consola como Administrador:
#   powercfg /hibernate off

param(
    [switch]$Restore
)

$ErrorActionPreference = "Stop"

if ($Restore) {
    Write-Host "Restaurando: suspensión AC = 60 min, monitor AC = 15 min..."
    powercfg /change standby-timeout-ac 60
    powercfg /change monitor-timeout-ac 15
    exit 0
}

Write-Host "Ajustando esquema de energía activo (enchufado AC)..."
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 15
Write-Host "Listo: sin suspensión automática en AC; monitor puede apagarse a los 15 min."
Write-Host "Si el portátil sigue durmiendo al cerrar la tapa: Panel de control -> Opciones de energía -> Acción al cerrar la tapa."
