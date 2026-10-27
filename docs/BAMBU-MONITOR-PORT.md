# Bambu-Monitor → Bambuddy: Portierungsstand

Dieser Ordner ist ein **Fork von Bambuddy** (AGPL-3.0, https://github.com/maziggy/bambuddy).
Ziel ist, die eigenständigen Funktionen des **Bambu-Monitors**
(`C:\Users\lukas\OneDrive\Desktop\Bambu-Monitor`) in Bambuddy zu integrieren.

> **Lizenz:** Bambuddy steht unter AGPL-3.0. Dieser Fork bleibt unter derselben Lizenz.
> Bei einer Weitergabe muss der Quellcode mit angeboten werden. Die portierten Ideen und
> Abläufe stammen aus dem eigenen Bambu-Monitor-Projekt; es wird kein Code von Bambu Lab
> oder aus der Bambu-Handy-App übernommen.

## Stand

| Funktion | Status | Ort |
|---|---|---|
| Wartungsprogramme (Öl / Gewindestangen) | **fertig** | `backend/app/services/maintenance_programs.py`, `backend/app/api/routes/maintenance_programs.py`, `frontend/src/components/MaintenanceProgramsCard.tsx` |
| Tür-Servo & Plattenwechsler (GPIO/Befehl) | **fertig** (Simulation/Befehl) | `backend/app/services/hardware_extension.py`, `backend/app/api/routes/hardware.py` |
| MakerWorld + lokales PC-Slicen | **fertig** (PC-Dienst + Integration) | `backend/app/services/slicer_cli.py`, `backend/app/pc_slicer.py` |
| Optische Prüfungen (Leerbett, Bauteil, Schicht) | **teilweise**: Schicht-Stopp + Bauteil-Wächter | `backend/app/services/layer_alerts.py`, `part_watcher.py` |
| Wartungsdruck (Bewegungs-3MF) | **fertig** | `backend/app/services/maintenance_print.py`, `backend/app/api/routes/maintenance_print.py` |
| Cloud-Steuerung / `fun`-Schutz / Bambu Connect | **bewusst nicht** | widerspricht Bambuddys LAN-Only-/Virtual-Printer-Architektur |

## Was der Bambu-Monitor kann, das Bambuddy nicht kann

| Alleinstellungsmerkmal | Im Fork |
|---|---|
| Öl- und Gewindestangenprogramme direkt aus der Oberfläche | ✅ eingebaut |
| Tür-Servo, Endschalter, Magazin und Plattenwechsler | ✅ eingebaut (Simulation/Befehl) |
| Wartungsdruck als reine Bewegungs-3MF | ✅ eingebaut |
| Schicht-Hinweise (Pause bei Zielschicht) | ✅ eingebaut |
| Bauteil-Wächter (Kamera-Vergleich) | ✅ eingebaut |
| Kamera-Einmessung, Referenzbild-Ausrichtung, Erste-Schicht-Inspektor | ⏳ geplant |
| MakerWorld-Download + lokales Slicen mit Bambu Studio CLI in einem Schritt | ✅ eingebaut (PC-Dienst) |
| Bambu-Cloud-Steuerung, `fun`-Schutzbit, Bambu Connect | ❌ nicht portiert (LAN-Only-Architektur) |
| PV-/Tarif-Zeitfenster, Angebotskalkulator | optional; Bambuddy hat Smart Plugs/Billing |

## 1. Wartungsprogramme (fertig)

Zwei Abläufe aus dem Bambu-Monitor, am P2S erprobt:

- **Öl verteilen:** Home, Z 0 → 30 → 150 → 30 mm, X 20 → 236 → 20, Y 20 → 236 → 20;
  standardmäßig zwei Durchgänge mit 60 s Pause.
- **Gewindestangen schmieren:** Home, Z 30, fünfmal hoch/runter, 30 s Ölen, fünfmal
  zurück, 30 s Pause, danach X/Y abfahren (ca. 7 Minuten).

Sicherheit (vor dem Start und **vor jedem Schritt** geprüft):

- Drucker verbunden und Zustand bekannt,
- kein Druck in `PREPARE`, `SLICING`, `RUNNING`, `PAUSE`,
- Düse und Bett höchstens 60 °C,
- nur P2S (256-mm-Bett; die XY-Grenzen sind fest),
- Stopp setzt ein Abbruchsignal; der laufende Schritt wird beendet,
- **Bestätigung „Platte frei"** ist Pflicht (`?platte_frei=1`); ohne sie antwortet die API mit 400.
  Die Oberfläche fragt vor dem Start nach.

API (unter `/api/v1`):

```
GET  /printers/{id}/maintenance-programs
POST /printers/{id}/maintenance-programs/{oil|rods}/start?runs=1..3
POST /printers/{id}/maintenance-programs/stop
```

Berechtigungen: Lesen `printers:read`, Start/Stop `printers:control`.
Die Oberfläche liegt oben auf der **Wartungsseite** (Karte „Wartungsprogramme“).

Tests:

```bash
python -m pytest backend/tests/unit/services/test_maintenance_programs.py \
                 backend/tests/unit/services/test_hardware_extension.py -q
# Frontend
cd frontend && npm run typecheck && npm run check:i18n && npm run build
```

### Wartungsdruck (3MF)

Aus `wartungsdruck.py` portiert: aus dem neuesten geslicten Archiv des P2S wird eine
3MF erzeugt, deren G-code nur bewegt (Home, Z-Zyklen, Ölpausen, X/Y) — ohne Heizen,
ohne Filament, mit neu berechneter MD5. Die Datei wird heruntergeladen und kann über
Bambuddys Dateimanager/Warteschlange gestartet werden.

- API: `POST /api/v1/printers/{id}/maintenance-print/{oil|rods}` (optional `archive_id`),
  `GET …/maintenance-print/{filename}` zum Herunterladen.
- Oberfläche: zwei Knöpfe „3MF · …" neben den Wartungsprogrammen; sie laden die Datei
  direkt herunter.
- Voraussetzung: mindestens ein geslictes P2S-Archiv als Vorlage. Ohne Archiv kommt
  eine klare Meldung.
- Tests: 5 (`test_maintenance_print.py`), u. a. kein `M104/M140/M109`, MD5 neu, Vorlage
  bleibt sonst unverändert.

## 2. Tür & Plattenwechsler (fertig)

Portiert aus `pi_gpio_controller.py`, `hardware_controller.py` und `plattenwechsler.py`.
Zwei Modi, konfiguriert in `data/hardware.json` (wird beim ersten Zugriff angelegt):

```json
{
  "mode": "simulated",
  "door_open_command": "python3 /opt/bambu/pi_gpio_controller.py door_open",
  "door_close_command": "python3 /opt/bambu/pi_gpio_controller.py door_close",
  "door_status_command": "",
  "plate_change_command": "python3 /opt/bambu/plattenwechsler.py swap",
  "timeout_seconds": 15
}
```

- **simulated** (Standard): keine Hardware, Zustände werden nur geführt — für PC/Tests.
- **command**: führt die konfigurierten Befehle aus. In Docker müssen GPIO-Geräte
  (`/dev/gpiochip0`) und das Skript im Container vorhanden sein; alternativ einen
  kleinen Host-Dienst ansprechen.
- Magazinstand und Wechselzähler liegen in `data/magazine.json` (3 Vorrat, 3 Ablage).
- Sicherheit im Befehlsmodus: nur bei verbundenem, nicht druckendem Drucker; Zeitlimit;
  ein Fehler bricht den Ablauf ab. Die Ausgabe `DOOR:OPEN/CLOSED/UNKNOWN` wird geprüft:
  ein unbekannter oder falscher Endschalterzustand lässt den Vorgang scheitern,
  statt einen falschen Zustand zu melden. Im Simulationsmodus sind die Aktionen zum Testen
  auch ohne Drucker erlaubt und als „(Simulation)" gekennzeichnet.
- API: `GET /api/v1/printers/{id}/hardware`, `POST …/door/open|close`,
  `POST …/plate/change`, `POST …/magazine/refill`. Rechte: `printers:read` bzw.
  `printers:control`.
- Oberfläche: Abschnitt „Tür & Plattenwechsler" in der Karte auf der Wartungsseite,
  inklusive Magazinfächer 1–6 (grün = Vorrat bereit, grau = leer/verbraucht,
  amber = Ablage belegt).

Live geprüft (Simulation, PC): Tür öffnen/schließen, Plattenwechsel (Fach 1 → Ablage 1,
Zähler 1), Magazin auffüllen. Im Befehlsmodus blockt die API ohne verbundenen Drucker.

## 3. MakerWorld + PC-Slicen (fertig)

Bambuddy importiert MakerWorld-Links bereits, lädt aber **ungeslicte** Quell-3MFs und kann
auf ARM nicht slicen. Der PC-Dienst kapselt Bambu Studio und bedient Bambuddys vorhandene
Sidecar-Schnittstelle; Bambuddys Einstellungen bleiben unverändert.

```powershell
# auf dem PC, im Bambuddy-Ordner (nutzt die vorhandene .venv)
.venv\Scripts\python.exe -m uvicorn backend.app.pc_slicer:app --host 127.0.0.1 --port 3001 --loop asyncio
```

In Bambuddy: **Einstellungen → Workflow → Slicer**
- „Slicer-API verwenden“ einschalten,
- „Bambu Studio sidecar URL“ auf `http://127.0.0.1:3001` setzen
  (läuft Bambuddy auf dem Pi: `http://<PC-IP>:3001`, Dienst dann mit `--host 0.0.0.0`
  starten und per Firewall auf das Heimnetz begrenzen).

Implementiert:

- `backend/app/services/slicer_cli.py`: schreibt die von Bambuddy gesendeten Profile,
  ruft `bambu-studio.exe` mit `--load-settings/--load-filaments/--arrange/--orient`
  auf, liest Druckzeit und Filament aus der 3MF.
- `backend/app/pc_slicer.py`: `POST /slice` (multipart `file`, `printerProfile`,
  `presetProfile`, `filamentProfile…`, `exportType`, `arrange`, `orient`),
  `GET /health`, `GET /slice/progress/{id}` (404 → Bambuddy nutzt seine Zeitüberwachung).
- Rückgabe als 3MF mit `X-Print-Time-Seconds` und `X-Filament-Used-G`.
- Live geprüft: FarmLoop-3MF (10,8 MB) durch den Dienst geslict → HTTP 200,
  **1.124 s / 4,18 g** für Platte 1, gültige 3MF.
- Bambuddy-Einstellungen live gesetzt (`use_slicer_api = true`, URL `http://127.0.0.1:3001`).
- Grenzen: `plate` wird ignoriert (CLI slict alle Platten), Fortschritt wird nicht
  gemeldet, der PC muss laufen und Bambu Studio installiert haben. Punkte-/Kaufmodelle
  bleiben gesperrt.
- Tests: 8 (`test_pc_slicer.py`).

## 4. Optische Prüfungen und Schicht-Stopp (teilweise)

Bambuddy hat Leerbett-Erkennung und Obico. Aus dem Bambu-Monitor kommen dazu:

- **Kamera-Einmessung** (vier Plattenecken anklicken) und Referenzbild-Ausrichtung,
- **Bauteil-Wächter** mit Objektbereich aus der `.3mf` (Plate-JSON),
- **Schicht-Hinweise** (melden/pausieren ab Zielschicht),
- **Erste-Schicht-Inspektor**.

### Schicht-Stopp (fertig)

Portiert aus `layer_alerts.py` des Monitors: pro Drucker lässt sich eine Zielschicht
setzen; erreicht der Druck sie, pausiert Bambuddy einmal (z. B. zum Einlegen von Magneten).

- Dienst `backend/app/services/layer_alerts.py`, Konfiguration in `data/layer_alerts.json`.
- Hängt im vorhandenen Layer-Callback von Bambuddy; erkennt einen neuen Druck an einer
  fallenden Schichtnummer oder einer anderen Auftragskennung und ist dann wieder scharf.
- API: `GET/PUT /api/v1/printers/{id}/layer-alert` (`enabled`, `layer`).
- Oberfläche: Feld „Schicht-Stopp (Pause bei Schicht)“ und Speichern in der Wartungskarte.
- Tests: 6 (`test_layer_alerts.py`), inkl. einmalige Pause, Reset bei neuem Druck,
  keine Pause bei deaktiviertem Hinweis oder nicht laufendem Druck.

### Bauteil-Wächter (fertig)

Portiert aus `teil_waechter.py`: Bei Schicht 2 wird ein Referenzbild gespeichert, etwa bei
der Hälfte des Drucks wird ein neues Bild verglichen. Kaum Unterschied = Warnung
(„Bauteil prüfen"), **ohne Eingriff**. Der Dienst hängt im Layer-Callback, nutzt Bambuddys
vorhandene Snapshot-Funktion (extern/gepuffert/frisch) und meldet über das bestehende
AI-Fehler-Ereignis.

- Konfiguration `data/part_watcher.json` (pro Drucker `enabled`, `threshold`).
- API: `GET/PUT /api/v1/printers/{id}/part-watcher`.
- Oberfläche: Häkchen „Bauteil-Wächter (Kamera-Vergleich)" in der Wartungskarte; eine
  Warnung erscheint dort rot.
- Vergleich: OpenCV, Graustufen, zentraler Bauraum-Ausschnitt; Standard-Schwelle 1,0.
- Tests: 8 (`test_part_watcher.py`) mit synthetischen Bildern, Reset bei neuem Druck,
  deaktiviert/ohne Bild.

### Noch offen: Kamera-Einmessung und Erste Schicht

Einbau in `backend/app/services/plate_detection.py`/`camera.py` und eine Erweiterung der
Drucker-Detailseite. Die vorhandene Bambuddy-Kamera-Infrastruktur (Fan-out, Snapshots)
wird genutzt, kein zweiter Stream.

## Sicherheit und Barrierefreiheit (27.10.2026)

- **Platte-frei-Bestätigung** vor Wartungsprogrammen (Backend-Pflicht + Rückfrage in der UI).
- **Tür-Endschalterprüfung** im Befehlsmodus: `DOOR:UNKNOWN` oder der falsche Zustand bricht ab.
- **Not-Halt** (`POST …/hardware/emergency-stop`) funktioniert bewusst auch bei Druck/offline,
  setzt die Tür auf „unbekannt“ und führt im Befehlsmodus `emergency_stop_command` aus.
- **Axe/WCAG AA** auf der Wartungsseite: 0 Verstöße. Dafür wurde der Grün-Akzent für weiße
  Schrift abgedunkelt (`#007a2e`), grüne Schrift bekommt einen helleren Text-Ton
  (`#4ade80` im Dark Mode), und die Viewport-Sperre (`user-scalable=no`) wurde entfernt.
- Der PC-Slicer hat einen Startknopf `starte_pc_slicer.bat`; `install_pc_slicer_task.ps1`
  legt ihn als Aufgabe beim Anmelden an.

## Geänderte Dateien (Stand jetzt)

- `backend/app/services/maintenance_programs.py` (neu)
- `backend/app/api/routes/maintenance_programs.py` (neu)
- `backend/app/services/maintenance_print.py` (neu)
- `backend/app/api/routes/maintenance_print.py` (neu)
- `backend/app/services/hardware_extension.py` (neu)
- `backend/app/api/routes/hardware.py` (neu)
- `backend/app/services/slicer_cli.py` (neu)
- `backend/app/pc_slicer.py` (neu)
- `backend/app/services/layer_alerts.py` (neu)
- `backend/app/services/part_watcher.py` (neu)
- `backend/app/api/routes/layer_alerts.py` (neu)
- `backend/app/api/routes/part_watcher.py` (neu)
- `starte_pc_slicer.bat` (neu)
- `install_pc_slicer_task.ps1` (neu)
- `FORK-CHANGELOG.md` (neu)
- `backend/app/main.py` (Router registriert)
- `backend/tests/unit/services/test_maintenance_programs.py` (neu, 14 Tests)
- `backend/tests/unit/services/test_maintenance_print.py` (neu, 5 Tests)
- `backend/tests/unit/services/test_hardware_extension.py` (neu, 9 Tests)
- `backend/tests/unit/services/test_pc_slicer.py` (neu, 8 Tests)
- `backend/tests/unit/services/test_layer_alerts.py` (neu, 6 Tests)
- `backend/tests/unit/services/test_part_watcher.py` (neu, 8 Tests)
- `frontend/src/components/MaintenanceProgramsCard.tsx` (neu, Programme + Hardware)
- `frontend/src/pages/MaintenancePage.tsx` (Karte eingebunden)
- `frontend/src/api/client.ts` (Typen und Methoden)
- `frontend/src/i18n/locales/*.ts` (15 Sprachen, Parität geprüft)
- `frontend/src/index.css`, `frontend/tailwind.config.js` (Kontrast/A11y)
- `frontend/index.html` (Zoom wieder erlaubt)
- `requirements.txt` (SQLAlchemy `<2.1` wegen Windows-Richtlinie)
- `data/hardware.json`, `data/magazine.json` (zur Laufzeit angelegt)

## Lokal auf dem PC starten

Getestet am 27.10.2026 auf Windows 11 mit Python 3.13 (x64):

```powershell
cd C:\Users\lukas\OneDrive\Desktop\Bambuddy-Fork
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --loop asyncio
```

Danach `http://127.0.0.1:8000` öffnen. Die Ersteinrichtung ist abgeschlossen, die
Authentifizierung ist für diesen lokalen Test **aus** (nur 127.0.0.1, nicht im Netz).
In der Datenbank liegt ein Demo-Drucker `P2S (Demo)` (offline) — dadurch ist die Karte
„Wartungsprogramme“ sichtbar. Für den echten P2S den Demo-Drucker löschen und den Drucker
mit IP, Seriennummer und Access Code hinzufügen (LAN + Entwicklermodus).

**Hinweis zur Umgebung:** Windows Application Control blockiert die unsignierte
SQLAlchemy-2.1-DLL (`_processors_cy`). Deshalb ist SQLAlchemy im Fork auf `>=2.0.38,<2.1`
begrenzt; 2.0.44 läuft mit dem Python-Fallback. Kein Fehler im Code, sondern eine
Richtlinie des PCs.

Live geprüft:

- Server startet, DB wird angelegt, UI lädt.
- `GET /api/v1/printers/1/maintenance-programs` liefert den Idle-Status.
- `POST .../oil/start` bei offline Drucker liefert sauber `400 Printer not connected`.
- Karte auf der Wartungsseite zeigt Druckerauswahl, beide Programme und den Sicherheitshinweis.
- Hardware-Simulation: `GET /api/v1/printers/1/hardware` liefert den Magazinstand;
  Tür öffnen/schließen, Plattenwechsel (Fach 1 → Ablage 1, Zähler 1) und Auffüllen laufen
  über die API und werden in der Karte angezeigt.
- Im Befehlsmodus blockt die Hardware-API ohne verbundenen Drucker (400).
- PC-Slicer: echter Bambu-Studio-Lauf über `POST /slice` → HTTP 200, 10,8 MB 3MF,
  1.124 s / 4,18 g; Bambuddy zeigt die Sidecar-URL in den Einstellungen.
- Wartungsdruck: Aus dem Demo-Archiv wurde eine 22,5-KB-Bewegungs-3MF erzeugt und
  heruntergeladen; `G28`/`G1 X236` enthalten, kein `M104/M140/M109`.
- Schicht-Stopp: API live gesetzt (`enabled`, Schicht 50) und gelesen; die Pause selbst
  ist mit 6 Unit-Tests abgedeckt (ohne echten Drucker).
- Bauteil-Wächter: API live aktiviert (Schwelle 1,0); der Bildvergleich ist mit 8 Tests
  abgedeckt, ein echter Kameradurchlauf steht ohne Drucker noch aus.
- Not-Halt: in der Simulation live ausgelöst (Tür → `unknown`); der Befehlspfad ist
  mit 3 Tests abgedeckt.

## Offene Punkte

- **Optik:** Kamera-Einmessung, Bauteil-Wächter und Erste-Schicht-Inspektor fehlen weiterhin;
  Schicht-Stopp ist fertig.
- **Queue-Integration:** Wartungsdruck landet noch nicht direkt in der Warteschlange;
  automatischer Plattenwechsel nach Druckende fehlt.
- **Auth/Deployment:** Bambuddy läuft lokal mit ausgeschalteter Authentifizierung; vor dem
  LAN-Betrieb einschalten. Der Fork ist noch nicht auf dem Pi installiert.
- Die **echte** Bewegung (GPIO/Servo/Wechsler) wurde nicht getestet: Der P2S ist derzeit
  nicht erreichbar, die Mechanik ist nicht gebaut. Die API ist live gegen die Simulation
  getestet; der Befehlspfad ist mit Testbefehlen abgedeckt.
- Die Wartungsprogramme und der Wechsler sind bewusst auf den P2S begrenzt. Für X1/P1
  ließen sich die XY-Grenzen parametrisieren, das ist aber nicht am Drucker verifiziert.
- Noch nicht portiert: **Kamera-Einmessung und Erste-Schicht-Inspektor**.
  Bambuddy hat bereits Leerbett-Erkennung, Obico und eine Erstschicht-Meldung; die
  Portierung braucht eine eigene Kalibrier-/Vergleichslogik auf Kamera-Snapshots.
  Der Schicht-Stopp ist fertig.
- Cloud-`fun`/Bambu Connect bleiben bewusst draußen.
- Kein Commit in diesem Fork; die Änderungen liegen im Arbeitsverzeichnis.
