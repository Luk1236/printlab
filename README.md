<p align="center">
  <img src="static/img/printlab_dark.png" alt="PrintLab" width="300">
</p>

<h1 align="center">PrintLab</h1>

<p align="center">
  <strong>Deine Drucker. Keine Cloud. Deine Regeln.</strong><br>
  Selbst gehostete Verwaltung für Bambu-Lab-Drucker mit Plattenwechsler, Kamera-Prüfung und Angebotskalkulator.
</p>

---

## Was PrintLab kann

**Grundfunktionen:** Druckarchiv, Live-Überwachung, Warteschlange und Planung, Dateiverwaltung,
Filament-/Spulenverwaltung, Benachrichtigungen, Kamera, Virtual Printer, Benutzer und Rechte.

**Eigene Erweiterungen (P2S-Werkstatt):**

- **Wartungsprogramme** – Öl verteilen und Gewindestangen schmieren, mit Sicherheitsprüfung und
  Pflichtbestätigung „Platte frei“; Wartungsdruck direkt in die Warteschlange.
- **Tür und Plattenwechsler** – Magazin mit Simulations- und Befehlsmodus, Endschalterprüfung,
  Not-Halt. Automatischer Plattenwechsel nach Druckende (Abkühlung, Türprüfung, nur bei wartendem
  Auftrag, abbrechbar, Füllstand-Warnung).
- **Optik-Prüfung (nur Warnung)** – Kamera-Einmessung über vier Plattenecken, Leerbett-Prüfung beim
  Start, Bauteil-Wächter (auch pro Auftrag), Erste-Schicht-Inspektor, Spaghetti-/Abbruch-Erkennung.
- **Schicht-Stopp** – Pause bei einer Zielschicht.
- **Angebotskalkulator** – Material, Strom, Stundenlohn und Aufschlag; Preisliste je Material;
  Angebot direkt am Warteschlangen-Auftrag; Monatsreport mit CSV-Export.
- **PC-Slicer** – Bambu Studio auf dem PC als Slicer-Dienst, mit Zugriffsschutz.
- Deutsche Oberfläche, helles und dunkles Prusa-Design, Barrierefreiheit nach WCAG AA.

Die laufende Aufgabenliste steht in [`TODO.md`](TODO.md), die Änderungen je Version in
[`CHANGELOG.md`](CHANGELOG.md), die Beschreibung der Erweiterungen in
[`docs/BAMBU-MONITOR-PORT.md`](docs/BAMBU-MONITOR-PORT.md).

## Schnellstart

Voraussetzungen: Python 3.10+, Node.js (nur zum Bauen der Oberfläche), ein Bambu-Lab-Drucker im
LAN-Modus mit aktiviertem Developer Mode.

```powershell
cd <Projektordner>
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --loop asyncio
```

Dann <http://127.0.0.1:8000> öffnen und der Einrichtung folgen. PC-Slicer (optional):
`starte_pc_slicer.bat`.

Docker (baut aus diesem Quellcode):

```bash
docker compose up -d --build
```

Zugriffsschutz des PC-Slicers, Umgebungsvariablen und Betriebshinweise stehen in den Dokumenten
unter [`docs/`](docs/).

## Tests

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/unit/test_auto_plate_change_refinements.py -q
cd frontend; npx vitest run; npx tsc --noEmit
```

## Herkunft und Lizenz

PrintLab ist eine **veränderte Version von [Bambuddy](https://github.com/maziggy/bambuddy)**
(Basisstand 1.2.5.7) und steht wie dieses unter der **GNU Affero General Public License v3.0**.
Die Lizenz steht in [`LICENSE`](LICENSE), Herkunft und Änderungen in [`NOTICE`](NOTICE).
Wer PrintLab über ein Netzwerk nutzt, hat Anspruch auf den zugehörigen Quellcode
(AGPL-3.0 §13); Weitergaben müssen den Quellcode mitliefern.

PrintLab ist ein unabhängiges Projekt und steht in keiner Verbindung zu Bambu Lab.
