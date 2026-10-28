# Startet den PC-Slicer beim Anmelden als Windows-Aufgabe.
# Aufruf (PowerShell, im Projektordner):
#   powershell -ExecutionPolicy Bypass -File .\install_pc_slicer_task.ps1
# Entfernen:
#   Unregister-ScheduledTask -TaskName "PrintLab PC Slicer" -Confirm:$false

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat = Join-Path $root "starte_pc_slicer.bat"
if (-not (Test-Path $bat)) {
    throw "starte_pc_slicer.bat nicht gefunden: $bat"
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

# Alte Aufgabe unter dem Vorgänger-Namen entfernen, falls vorhanden.
if (Get-ScheduledTask -TaskName "Bambuddy PC Slicer" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "Bambuddy PC Slicer" -Confirm:$false
    Write-Output "Alte Aufgabe 'Bambuddy PC Slicer' entfernt."
}

Register-ScheduledTask `
    -TaskName "PrintLab PC Slicer" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Bambu Studio PC-Slicer fuer PrintLab (Port 3001)" `
    -Force | Out-Null

Write-Output "Aufgabe 'PrintLab PC Slicer' eingerichtet."
Write-Output "Status:  Get-ScheduledTask -TaskName 'PrintLab PC Slicer'"
Write-Output "Starten: Start-ScheduledTask -TaskName 'PrintLab PC Slicer'"