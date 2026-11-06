@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo   Bambu Studio / OrcaSlicer PC-Slicer fuer PrintLab
echo ========================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo Fehler: .venv fehlt. Bitte zuerst:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

:: LAN und Tailscale-Netzwerke fuer den Zugriff vom Raspberry Pi freigeben
set PC_SLICER_ALLOWED_IPS=127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10

echo [OK] Python-Umgebung gefunden.
echo.
echo Wenn PrintLab auf einem Raspberry Pi laeuft:
echo Trage in PrintLab unter Einstellungen -^> Slicer diese Sidecar-URL ein:
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { Write-Host ('  http://' + $_.IPAddress + ':3001') }"
echo.
echo PC-Slicer lauscht auf allen Netzwerk-Schnittstellen (Port 3001)...
echo Zum Beenden dieses Fenster schliessen oder Strg+C druecken.
echo.

".venv\Scripts\python.exe" -m uvicorn backend.app.pc_slicer:app --host 0.0.0.0 --port 3001 --loop asyncio
pause
