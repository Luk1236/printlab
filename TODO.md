# TODO — Bambuddy-Fork (Bambu-Monitor-Port)

**Stand:** 27.10.2026
**Basis:** Bambuddy 1.2.5.7 (AGPL-3.0)
**Branch:** `bambu-monitor-port`

## Fertig

- Wartungsprogramme: Öl verteilen, Gewindestangen schmieren (P2S, Sicherheitsprüfung,
  Pflichtbestätigung „Platte frei“).
- Tür-Servo und Plattenwechsler/Magazin: Simulations- und Befehlsmodus, Endschalterprüfung,
  Not-Halt, Magazinstand in `data/magazine.json`.
- Wartungsdruck: Bewegungs-3MF aus dem neuesten geslicten Archiv, ohne Heizung/Filament.
- MakerWorld + PC-Slicen: FastAPI-Dienst (`backend/app/pc_slicer.py`) für Bambu Studio,
  Bambuddy-Sidecar konfiguriert, echter Slice getestet.
- Schicht-Stopp: Pause bei Zielschicht.
- Bauteil-Wächter: Kamera-Vergleich Schicht 2 ↔ Druckmitte, nur Warnung.
- Erste-Schicht-Inspektor: Helligkeit/Kontrast/Kanten der Schichten 1–5, nur Warnung.
- Kamera-Einmessung: vier Plattenecken anklicken, Homographie in die
  Plattenaufsicht; Bauteil-Wächter und Erste-Schicht-Inspektor erhalten das
  entzerrte Bild (27.10.2026).
- Automatischer Plattenwechsel: nach „completed" warten auf Abkühlung (45 °C),
  Türprüfung, dann Wechsel; Fehlerzustand sichtbar in der Wartungskarte.
  Schalter in der Wartungskarte, Konfiguration in `data/hardware.json`.
- Angebotskalkulator: Material (Gramm × €/kg, Spoolman-Walzen rechnen mit dem
  Walzenpreis), Energie (Dauer × Leistung × €/kWh), Stundenlohn, Aufschlag.
  Karte auf der Finanz-Seite; Raten (Stundenlohn, Aufschlag, Leistung) direkt
  in der Karte einstellbar. Neuer Endpunkt `GET /api/v1/quote`.
- Sicherheit: Platte-frei-Pflicht, Tür-Endschalterprüfung, Not-Halt (auch bei Druck/offline).
- Barrierefreiheit: WCAG-AA-Kontraste, Zoom erlaubt, Axe auf der Wartungsseite ohne Verstöße.
- 64 neue Backend-Tests; Frontend-Suite, TypeScript, i18n-Parität und Build grün.

## Offen — nach Priorität

### P1 Optik abschließen
- [x] Kamera-Einmessung über vier Plattenecken (Homographie) — erledigt 27.10.2026.
- [x] Leerbett-Prüfung beim Druckstart (Referenz per Klick, Warn-Kanal) — 27.10.2026.
- [x] Spaghetti-/Abbruch-Erkennung ab ~75 % der Schichten (Fleck-Verstreutheit,
      zusammenhängende Komponenten, nur Warnung) — 27.10.2026.
- [x] Part-Watcher pro Auftrag: Regeln „Namensfragment → Schwelle/an/aus",
      erster Treffer gewinnt (`data/part_watcher.json` → overrides).

### P2 Queue und Automatik
- [X] Automatischer Plattenwechsel nach Druckende (Abkühlung, Türprüfung, Fehlerzustand) — erledigt 27.10.2026.
- [X] Wartungsdruck direkt in die Warteschlange — `queue=true` am
      Wartungsdruck-Endpunkt; 3MF in der Bibliothek, Auftrag geplant.
- [X] Hardware-Konfiguration in der UI (Befehle/Modus/Zeitlimit) — Hardware-Admin-Karte.
- [X] Magazinverwaltung in der UI (Status klicken zum Wechseln, Etiketten).
- [X] Audit-Log: `data/audit_log.jsonl` + Protokoll in der Karte (Benachrichtigungen
      folgen mit dem Telegram/E-Mail-Ausbau).
- [ ] Automatik-Verfeinerungen: „Nur wenn Auftrag wartet" ist drin
      (`only_with_queue`); offen: Abbruch mitten im Wechsel, Füllstand-Warnung.

### P3 PC-Slicer alltagstauglich
- [X] Plattenwahl (`plate`): `--export-plate N`, Fallback auf alle Platten bei
      älteren CLIs; G-code-Auszug wählt `plate_N.gcode`. (27.10.2026)
- [x] Fortschritt: Seitecar meldet bewusst 404 → Bambuddy nutzt seine
      Zeitüberwachung (dokumentiert im `pc_slicer.py`).
- [x] Autostart als Windows-Dienst (Aufgabe ist vorhanden: `install_pc_slicer_task.ps1`).
- [ ] Voller E2E-Test: MakerWorld → PC-Slicer → Queue.
- [ ] Token/Firewall, sobald der Dienst nicht nur auf `127.0.0.1` lauscht.

### P4 Engineering und Betrieb
- [X] CI auf dem Fork-Branch: `.github/workflows/ci.yml` lauscht jetzt auch auf
      `bambu-monitor-port` (Backend-Lint/-Test/Frontend wie Upstream).
- [X] Lokales Backup: `werkzeuge/backup_erstellen.ps1` (getestet) +
      tägliche Aufgabe `install_backup_task.ps1`. GitHub-Backup ist ohnehin
      in Bambuddy selbst eingebaut (Einstellungen → Backup).
- [ ] Volle Upstream-Suite auf Linux/CI (Windows scheitert an Pfad-Trennern).
- [ ] Docker-/ARM-Build und Test auf Pi 4/5.
- [ ] Frontend-Tests für die Wartungskarte; Backend-Meldungen für alle 15 Sprachen.
- [ ] Auth einschalten (wartet auf das Passwort), HTTPS/Tailscale.
- [x] Kalkulator am Warteschlangen-Auftrag: Zeitstrahl lädt bei Hover
      `GET /quote/for-archive/{id}` (Material/Energie/Arbeit/Aufschlag).
- [x] Monats-Report: Statistik-Seite hat Monatsaggregation + CSV-Export
      (vom Upstream; PDF-Report optional später).
- [x] Preisliste: `data/price_list.json` + Editor in der Kalkulator-Karte;
      `GET /quote?material=TPU` nimmt die Liste.
- [ ] Release-Paket und Installationsanleitung für Pi 4/5.

### P5 Oberfläche
- [ ] Wartungskarte in einen eigenen Tab „Hardware & Optik“ aufteilen.
- [ ] Mobilansicht der neuen Bedienelemente prüfen.
- [ ] Fehlermeldungen/Fokus vereinheitlichen; Einrichtungsassistent für Hardware.

### Optional (bewusst nicht im Fokus)
- Verschlüsselte Sicherung, Angebotskalkulator, PV-/Tarifsteuerung, Kiosk, Drucker-Simulator.
- Cloud-Steuerung/`fun`/Bambu Connect — passt nicht zu Bambuddys LAN-Only-Architektur;
  dafür bleibt der Bambu-Monitor die richtige Wahl.

## Persönliche Anpassung (27.10.2026)

- Rebrand als **PrintLab** (vorher „Bambu Monitor“), deutsche Oberfläche als
  Standard, dunkles Design voreingestellt, eigene Logos/Icons.
- **Prusa-Design** für hell + dunkel: Prusa-Orange (#fa6831, aus Prusa-Link-Web),
  flache Kacheln, Prusa-Connect-Hellpalette, PrusaSlicer-Dunkelpalette.
  Funktionen unverändert (Theming nur über die zentralen CSS-Variablen).
- Versionsverwaltung: private Repo **Luk1236/printlab**, Tags + Releases
  (Start: v1.0.0), Schema/Siehe `docs/VERSIONING.md`.
- P2S aus der alten `config.ini` übernommen (IP, Seriennummer, Zugangscode, P2S, Werkstatt);
  aktuell offline.
- Einstellungen: EUR, 22 €/kg, 0,35 €/kWh, PC-Slicer `http://127.0.0.1:3001`.
- **Login:** Das alte Passwort erfüllt Bambuddys Komplexitätsregel nicht (kein Großbuchstabe).
  Ein neues Passwort wird **nicht** vom Assistenten gesetzt oder im Chat ausgegeben.
  Stattdessen: `werkzeugedmin_passwort_setzen.py` ausführen, Passwort selbst eingeben
  (getpass, keine Anzeige). Danach Server neu starten und mit `lukas` + neuem Passwort anmelden.
  Notfall: `--deaktivieren`.
- **Modellimport:** 2 Dateien in die Bibliothek übernommen
  (`Einmess_Marken_P2S.gcode.3mf`, `Tuer_Oeffner_Kompakt.stl`).
  3 Dateien (`Oel_verteilen`, `Wartung_Gewindestangen`, `Einmess_Marken_P2S.stl`) sind
  OneDrive-Platzhalter und konnten nicht gelesen werden — OneDrive starten/hydratisieren.
- Warteschlange/Historie/Protokolle noch nicht importiert (eigene Schema-Übernahme nötig).

## Start

```powershell
cd C:\Users\lukas\OneDrive\Desktop\Bambuddy-Fork
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --loop asyncio
starte_pc_slicer.bat
```

## Aufräumen (27.10.2026)

Entfernt: Demo-Datenbank, `data/`, `logs/`, `maintenance/`, Laufzeit-JSONs
(`hardware.json`, `magazine.json`, `layer_alerts.json`, `part_watcher.json`,
`first_layer_inspector.json`), `__pycache__` sowie temporäre Screenshots/Testdateien.

Behalten: Quellcode, `.venv`, `frontend/node_modules`, `static/` (Build), Doku.
Der nächste Start von Bambuddy beginnt wieder mit der Einrichtung (Auth aus, keine
Demo-Drucker). Die echten Daten des Bambu-Monitors wurden **nicht** angefasst.

## Commits

- `8c6eb57` Port der Monitor-Funktionen
- `ba41320` Bauteil-Wächter
- `c833ac4` Not-Halt und PC-Slicer-Autostart
- `b35e3f2` Erste-Schicht-Inspektor

Nicht gepusht. Lizenz: AGPL-3.0.
