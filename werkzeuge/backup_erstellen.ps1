# Lokale Sicherung von PrintLab: Datenbank + Konfigurationen.
# Aufruf (PowerShell):
#   powershell -ExecutionPolicy Bypass -File .\werkzeuge\backup_erstellen.ps1
# Ziel: <Projekt>\backup\<JJJJ-MM-TT>\ — alte Sicherungen bleiben 14 Tage.
# Hinweis: Bei laufendem Server zusätzlich .db-wal/.db-shm kopiert, SQLite
# übernimmt die Journal-Dateien beim Wiederherstellen mit.

param(
    [int]$KeepDays = 14
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$date = (Get-Date).ToString("yyyy-MM-dd")
$dest = Join-Path $root "backup\$date"
New-Item -ItemType Directory -Force $dest | Out-Null

foreach ($name in @("bambuddy.db", "bambuddy.db-wal", "bambuddy.db-shm", "hardware.json", "magazine.json")) {
    foreach ($dir in @($root, (Join-Path $root "data"))) {
        $src = Join-Path $dir $name
        if (Test-Path $src) { Copy-Item $src $dest -Force }
    }
}
if (Test-Path (Join-Path $root "data\plate_calibration")) {
    Copy-Item (Join-Path $root "data\plate_calibration") $dest -Recurse -Force
}

# Alte Sicherungen löschen
$limit = (Get-Date).AddDays(-$KeepDays)
Get-ChildItem (Join-Path $root "backup") -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.CreationTime -lt $limit } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Output "Backup erstellt: $dest"