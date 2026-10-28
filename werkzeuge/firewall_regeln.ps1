# Windows-Firewall-Regeln für PrintLab.
# Aufruf (PowerShell, als Administrator, im Projektordner):
#   powershell -ExecutionPolicy Bypass -File .\werkzeuge\firewall_regeln.ps1
#
# Standard: Backend (Port 8000) und PC-Slicer (Port 3001) sind NUR im lokalen
# Netz erreichbar — es werden die Scopes des LANs automatisch ermittelt. Wer
# strikter will, kann die Geräte-IPs beschränken:
#   .\werkzeuge\firewall_regeln.ps1 -AllowedIps "192.168.178.133,192.168.178.140"
# Entfernen:
#   powershell -ExecutionPolicy Bypass -File .\werkzeuge\firewall_regeln.ps1 -Remove

param(
    [string]$AllowedIps = "",   # kommagetrennt; leer = gesamtes lokales Subnetz
    [switch]$Remove
)

#requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$rules = @(
    @{ Name = "PrintLab Web";          Port = 8000 },
    @{ Name = "PrintLab PC Slicer";    Port = 3001 }
)

if ($Remove) {
    foreach ($rule in $rules) {
        Remove-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
        Write-Output "Regel entfernt: $($rule.Name)"
    }
    return
}

# Lokalen Netzadapter mit Standardroute finden und das Subnetz ableiten.
$subnet = ""
if (-not $AllowedIps) {
    $network = Get-NetIPConfiguration |
        Where-Object { $_.IPv4DefaultGateway } |
        Select-Object -First 1
    if ($network) {
        $ip = $network.IPv4Address.IPAddress
        $prefix = $network.IPv4Address.PrefixLength
        $subnet = "$ip/$prefix"
    } else {
        throw "Kein Netzadapter mit Standardroute gefunden — bitte -AllowedIps angeben."
    }
}
foreach ($rule in $rules) {
    $params = @{
        DisplayName  = $rule.Name
        Direction    = "Inbound"
        Protocol     = "TCP"
        LocalPort    = $rule.Port
        Action       = "Allow"
        Profile      = "Private,Domain"
    }
    if ($AllowedIps) {
        $params["RemoteAddress"] = $AllowedIps.Split(",") | ForEach-Object { $_.Trim() }
        $scope = $AllowedIps
    } else {
        $params["RemoteAddress"] = $subnet
        $scope = $subnet
    }
    Remove-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
    New-NetFirewallRule @params | Out-Null
    Write-Output "Regel angelegt: $($rule.Name) (TCP $($rule.Port), erlaubt: $scope)"
}

Write-Output ""
Write-Output "Hinweis: die Regeln gelten nur fuer Private-/Domänennetzwerke; in oeffentlichen"
Write-Output "Netzen bleibt PrintLab zu. Der PC-Slicer prueft darueber hinaus PC_SLICER_ALLOWED_IPS"
Write-Output "und PC_SLICER_TOKEN (siehe docs/HILFE.md)."