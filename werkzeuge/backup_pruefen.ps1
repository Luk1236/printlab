# Prueft die neueste lokale Sicherung: Datenbank herauskopieren und
# SQLite-Integritaet pruefen (PRAGMA integrity_check).
# Aufruf (PowerShell, im Projektordner):
#   powershell -ExecutionPolicy Bypass -File .\werkzeuge\backup_pruefen.ps1
#
# Nutzt die Python-im-venv (sqlite3-Modul). Gibt OK/Mangelnd aus und setzt
# beim Fehlschlag einen Nicht-Null-Exitcode (faellt in Aufgaben auf).

param(
    [int]$KeepTempSeconds = 600
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backupRoot = Join-Path $root "backup"

$latest = Get-ChildItem $backupRoot -Directory -ErrorAction SilentlyContinue |
    Sort-Object CreationTime -Descending |
    Select-Object -First 1
if (-not $latest) {
    Write-Output "FEHLT: keine Sicherung unter $backupRoot vorhanden."
    exit 1
}

$candidateDb = @()
foreach ($name in @("printlab.db", "bambuddy.db")) {
    foreach ($dir in @($latest.FullName, (Join-Path $latest.FullName "data"))) {
        $candidateDb += (Join-Path $dir $name)
    }
}
$dbFile = $candidateDb | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $dbFile) {
    Write-Output "FEHLT: keine Datenbank (printlab.db / bambuddy.db) in $($latest.Name)."
    exit 1
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Output "FEHLT: .venv\Scripts\python.exe nicht gefunden — Pruefung nur moeglich, wenn venv installiert ist."
    exit 1
}

# Kopie nach temp (schaedigt die Sicherung nicht), Journal-Dateien mitnehmen.
$temp = Join-Path $env:TEMP "printlab_backup_check"
if (Test-Path $temp) { Remove-Item $temp -Recurse -Force }
New-Item -ItemType Directory -Force $temp | Out-Null
Copy-Item -LiteralPath $dbFile (Join-Path $temp "check.db") -Force
Get-ChildItem -LiteralPath (Split-Path $dbFile) -Filter "$([System.IO.Path]::GetFileName($dbFile))-*" -File -ErrorAction SilentlyContinue |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName (Join-Path $temp ("check" + $_.FullName.Substring($dbFile.Length))) -Force -ErrorAction SilentlyContinue }

$script = @'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
try:
    rows = con.execute("PRAGMA integrity_check").fetchall()
finally:
    con.close()
ok = [r[0] for r in rows] == ["ok"]
print("INTEGRITÄT:", "OK" if ok else rows)
sys.exit(0 if ok else 2)
'@
$check = Join-Path $temp "pruefen.py"
[System.IO.File]::WriteAllText($check, $script, (New-Object System.Text.UTF8Encoding($true)))

& $python -I $check (Join-Path $temp "check.db")
$integrity = $LASTEXITCODE

# Temp auftäumen (auch bei Erfolg).
Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -ArgumentList "/c", "ping -n $($KeepTempSeconds + 1) 127.0.0.1 > nul & rmdir /s /q `"$temp`"" | Out-Null

if ($integrity -eq 0) {
    Write-Output "OK: Sicherung $($latest.Name) — Datenbank lesbar, Integritaet ok ($([System.IO.Path]::GetFileName($dbFile)))."
    exit 0
}
Write-Output "MANGELND: Sicherung $($latest.Name) — Integritaetspruefung fehlgeschlagen (Code $integrity)."
exit $integrity