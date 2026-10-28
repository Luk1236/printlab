# Changelog

Alle nennenswerten Änderungen an PrintLab. Versionsschema: siehe `docs/VERSIONING.md`.
PrintLab baut auf Bambuddy 1.2.5.7 auf (Herkunft und Lizenz: `NOTICE`).

## v1.2.2 (27.10.2026)

- **Meldungen auf Englisch:** Die Erweiterungs-Endpunkte (Hardware, Wartung, Kamera-Prüfungen, Angebote)
  übersetzen ihre Meldungen ins Englische, wenn die Oberfläche nicht auf Deutsch steht; unbekannte Texte bleiben
  deutsch. Die Oberfläche schickt dafür die gewählte Sprache mit.
- **Fehler behoben:** Die Meldung zur gesperrten Befehls-Konfiguration enthielt statt `` ein Klingelzeichen
  (`werkzeugedmin_passwort_setzen.py`); relative Pfade in der Datenbank werden jetzt immer mit `/` gespeichert
  (Windows ↔ Linux/Pi austauschbar).
- **Name:** SpoolBuddy heißt in der Oberfläche jetzt „PrintLab Spool“ (Logo ersetzt).
- **Release-Workflow:** `.github/workflows/release.yml` baut beim Tag ein Image für amd64 und arm64 (ungetestet).
- **Tests:** Auf Windows übersprungene POSIX-Tests stehen in `backend/tests/windows_skips.txt` und laufen in der Linux-CI.

## v1.2.1 (27.10.2026)

- **Sicherheit:** Hardware-Befehle lassen sich nur noch mit eingeschalteter Anmeldung ändern; Befehle
  können als Liste (Programm + Argumente, ohne Shell) angegeben werden.
- **Not-Halt** beendet den laufenden Hardware-Befehl und sperrt danach alles, bis die Sperre aufgehoben wird.
- **Unvollständiger Wechsel** (z. B. Tür schließt nicht) wird erkannt, das Magazin nachgeführt und der
  nächste Wechsel gesperrt, bis die Mechanik als geprüft bestätigt ist.
- **Automatik:** Ergebnisse im Audit-Log (auch nach Neustart sichtbar), Benachrichtigung bei Fehlern und
  Magazin-Warnung, optional „Platte frei“ per Kamera automatisch bestätigen (Standard aus, nur bei sicherem
  Ergebnis), Schalter „Nur wenn ein Auftrag wartet“, „Wechsel abbrechen“.
- **PC-Slicer:** Zugriffsschutz (Loopback, `PC_SLICER_ALLOWED_IPS`, `PC_SLICER_TOKEN`).
- **Angebot:** als PDF drucken.
- **Fehler behoben:** fehlende Importe (`Response`, `Printer`), falsche Übersetzungsschlüssel in der
  Hardware-Karte und im Kalkulator, fehlende Schaltfläche „Einmessung löschen“.
- **Magazin pro Drucker:** Jeder Drucker hat sein eigenes Magazin und seine eigene Hardware-Konfiguration
  (`magazine_<id>.json`, `hardware_<id>.json`); der erste Drucker übernimmt den bisherigen gemeinsamen Stand.
- **Angebotsverlauf:** Angebote pro Kunde speichern, filtern, löschen, Summe je Kunde.
- **Statistik als PDF** drucken (Kennzahlen des gewählten Zeitraums).
- **Umbenennung nach innen:** Datenbank `printlab.db` (wird beim Start automatisch aus `bambuddy.db` umbenannt),
  Umgebungsvariablen `PRINTLAB_*` (die alten `BAMBUDDY_*` gelten weiter), Protokoll `printlab.log`, Sicherungen
  `printlab-backup-*` (ältere werden weiter erkannt), Prometheus-Kennzahlen `printlab_*`, MQTT-Standardpräfix
  `printlab`, HTTP-Header `X-PrintLab-*`, Windows-Installer und Dienst `PrintLab`, Docker-/systemd-Namen.
- **Eigene Hilfe** (`docs/HILFE.md`) statt externem Wiki; Pi-Anleitung (`docs/INSTALLATION-PI.md`).
- **Entfernt:** Spenden-Aufforderungen (Oberfläche und Dienst), Upstream-Veröffentlichungsskripte, Upstream-Changelog.
- **Eigenständig:** Update-Prüfung, Docker-Compose und Installationsskripte zeigen auf das eigene Repo; kein
  Fehlerbericht-Relay, kein Ankündigungs-Feed, keine Spendenhinweise des Upstream; PrintLab-Version getrennt
  vom Upstream-Basisstand; neue Screenshots.

## v1.2.0 (27.10.2026)

- Spaghetti-/Abbruch-Erkennung ab ca. 75 % der Schichten (nur Warnung).
- Bauteil-Wächter pro Auftrag: Regeln „Namensfragment → Schwelle/an/aus“.
- Angebot pro Warteschlangen-Auftrag (Hover) und Preisliste je Material.
- Automatischer Plattenwechsel: „Nur wenn Auftrag wartet“ wird jetzt wirklich gespeichert,
  Abbruch während der Abkühlwartezeit (Not-Halt, neuer Druck, `POST .../auto-plate-change/cancel`),
  Füllstand-Warnung bei wenig frischen Platten oder freien Ablagefächern.
- PC-Slicer: Zugriffsschutz (Loopback immer, andere Rechner nur über `PC_SLICER_ALLOWED_IPS`
  und/oder `PC_SLICER_TOKEN`, sonst 403).
- Tests: Wartungskarte (Frontend) und Zugriffsschutz/Automatik (Backend); 102 Fork-Backend-Tests.

## Enthalten (v1.0.0)

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
