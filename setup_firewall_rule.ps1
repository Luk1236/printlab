<#
   Setup Firewall-Regel für PrintLab PC-Slicer (Port 3001)
   Führt aus: Neue Inbound-Regel für TCP Port 3001 erstellt
   Ausgeführt von: Admin (PowerShell als Administrator)
#>

# Prüfen, ob Script als Admin läuft
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $principal.HasFlag([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Error "Dieses Script muss als Administrator ausgeführt werden!"
    Write-Host "Rechtsklick auf PowerShell → 'Als Administrator ausführen'"
    exit 1
}

# Firewall-Regel für Port 3001 (TCP)
$ruleName = "PrintLab PC-Slicer Port 3001"
$ruleDisplayName = "Erlaubt PrintLab PC-Slicer-Kommunikation über Port 3001"
$ruleDescription = "Erlaubt eingehende TCP-Verbindungen auf Port 3001 für den PC-Slicer"

# Regellöschung falls schon vorhanden (idempotent)
Write-Host "Prüfe existierende Firewall-Regel '$ruleName'..."
Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule -Confirm:Write more

# Neue Inbound-Regel hinzufügen
Write-Host "Erstelle Firewall-Regel für TCP Port 3001..."
New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3001 -Enabled True

Write-Host ""
Write-Host "✓ Firewall-Regel '$ruleName' wurde erstellt."
Write-Host "  Protokoll: TCP"
Write-Host "  lokale Port: 3001"
Write-Host "  Aktion: Erlauben"
Write-Host ""
Write-Host "Zum Löschen später:"
Write-Host "  Remove-NetFirewallRule -DisplayName `'$ruleName`'"

# Status prüfen
$check = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($check) {
    Write-Host ""
    Write-Host "✓ Firewall-Regel aktiv und wirksam."
} else {
    Write-Warn "⚠ Firewall-Regel konnte nicht erstellt werden. Möglicherweise ist die Gruppenrichtlinie aktiv."
}