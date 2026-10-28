# Lokale Sicherung von PrintLab: Datenbank + Konfigurationen + Geheimnisse.
# Aufruf (PowerShell):
#   powershell -ExecutionPolicy Bypass -File .\werkzeuge\backup_erstellen.ps1
# Ziel: <Projekt>\backup\<JJJJ-MM-TT>\ — alte Sicherungen bleiben 14 Tage.
# Hinweis: Bei laufendem Server zusätzlich .db-wal/.db-shm kopiert, SQLite
# übernimmt die Journal-Dateien beim Wiederherstellen mit.
# Seit dem Rebrand (v1.2.1) heisst die Produktivdatenbank printlab.db; die alte
# bambuddy.db wird mitgesichert, falls sie noch nicht migriert wurde.

param(
    [int]$KeepDays = 14
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$date = (Get-Date).ToString("yyyy-MM-dd")
$dest = Join-Path $root "backup\$date"
New-Item -ItemType Directory -Force $dest | Out-Null

function Copy-Existing([string]$path) {
    if (Test-Path -LiteralPath $path) {
        Copy-Item -LiteralPath $path $dest -Recurse -Force
    }
}

# Datenbanken (Root; neue und alte Namen samt Journal-Dateien)
foreach ($name in @(
    "printlab.db", "printlab.db-wal", "printlab.db-shm",
    "bambuddy.db", "bambuddy.db-wal", "bambuddy.db-shm"
)) {
    foreach ($dir in @($root, (Join-Path $root "data"))) {
        Copy-Existing (Join-Path $dir $name)
    }
}

# Hardware-/Magazin-Konfiguration (gemeinsam + pro Drucker)
foreach ($dir in @($root, (Join-Path $root "data"))) {
    foreach ($pattern in @("hardware.json", "hardware_*.json", "magazine.json", "magazine_*.json")) {
        Get-ChildItem $dir -Filter $pattern -File -ErrorAction SilentlyContinue |
            ForEach-Object { Copy-Existing $_.FullName }
    }
}

# PrintLab-Konfigurationen und -Verläufe in data/
foreach ($name in @(
    "audit_log.jsonl", "price_list.json", "quote_history.json",
    "spaghetti_check.json", "part_watcher.json", "first_layer_inspector.json",
    "bed_empty_check.json", "layer_alerts.json"
)) {
    Copy-Existing (Join-Path $root "data\$name")
}

# Geheimnisse (Anmelde- und MFA-Schlüssel) aus data/
foreach ($name in @(".jwt_secret", ".mfa_encryption_key")) {
    Copy-Existing (Join-Path $root "data\$name")
}

# Kamera-Einmessung (Referenzbilder)
Copy-Existing (Join-Path $root "data\plate_calibration")

# Alte Sicherungen löschen
$limit = (Get-Date).AddDays(-$KeepDays)
Get-ChildItem (Join-Path $root "backup") -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.CreationTime -lt $limit } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Output "Backup erstellt: $dest"