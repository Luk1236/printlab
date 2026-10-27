# Legt eine taegliche Windows-Aufgabe an, die die lokale PrintLab-Sicherung
# ausfuehrt (siehe werkzeuge/backup_erstellen.ps1).
# Aufruf (PowerShell, im Projektordner):
#   powershell -ExecutionPolicy Bypass -File .\install_backup_task.ps1
# Entfernen:
#   Unregister-ScheduledTask -TaskName "PrintLab Backup" -Confirm:$false

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $root "werkzeuge\backup_erstellen.ps1"
if (-not (Test-Path $script)) {
    throw "backup_erstellen.ps1 nicht gefunden: $script"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At 04:00
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "PrintLab Backup" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Fuehrt werkzeuge/backup_erstellen.ps1 taeglich aus" `
    -Force | Out-Null

Write-Output "Aufgabe 'PrintLab Backup' eingerichtet (taeglich 04:00)."
Write-Output "Status:  Get-ScheduledTask -TaskName 'PrintLab Backup'"
Write-Output "Starten: Start-ScheduledTask -TaskName 'PrintLab Backup'"