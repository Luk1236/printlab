# Bambuddy-Fork: Bambu-Monitor-Port

**Version:** 1.0.0-bambu-port
**Basis:** Bambuddy 1.2.5.7 (AGPL-3.0)
**Stand:** 27.10.2026

Dieser Fork übernimmt die eigenständigen Funktionen des Bambu-Monitors in Bambuddy.
Die vollständige Beschreibung, Konfiguration und offene Punkte stehen in
`docs/BAMBU-MONITOR-PORT.md`.

## Enthalten

- Wartungsprogramme: Öl verteilen und Gewindestangen schmieren, mit Sicherheitsprüfung
  und Pflichtbestätigung „Platte frei“.
- Tür-Servo und Plattenwechsler/Magazin (Simulation oder konfigurierbare Befehle),
  inklusive Endschalterprüfung und Not-Halt.
- Wartungsdruck: Bewegungs-3MF aus dem neuesten geslicten Archiv, ohne Heizung/Filament.
- MakerWorld + PC-Slicen: FastAPI-Dienst, der Bambu Studio auf dem PC bedient und
  Bambuddys Sidecar-Schnittstelle erfüllt.
- Schicht-Stopp: Pause bei einer Zielschicht.
- Bauteil-Wächter: Kamera-Vergleich zwischen Schicht 2 und der Druckmitte, nur Warnung.
- Barrierefreiheit: WCAG-AA-Kontraste, Zoom wieder erlaubt, Axe ohne Verstöße auf der
  Wartungsseite.
- 56 neue Backend-Tests.

## Start

```powershell
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --loop asyncio
starte_pc_slicer.bat
```

PC-Slicer optional als Aufgabe beim Anmelden: `install_pc_slicer_task.ps1`.

## Lizenz

Bambuddy und dieser Fork stehen unter **AGPL-3.0**. Bei einer Weitergabe muss der Quellcode
mit angeboten werden. Es wird kein Code von Bambu Lab oder aus der Bambu-Handy-App
übernommen.

## Offen

Kamera-Einmessung, Erste-Schicht-Inspektor, Queue-Integration, PC-Slicer-Fortschritt/
Plattenwahl, voller Linux-/CI-Testlauf, Docker-/ARM-Build und Deployment.
