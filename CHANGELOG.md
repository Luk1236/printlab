# Changelog

Alle nennenswerten Änderungen an PrintLab. Versionsschema: siehe `docs/VERSIONING.md`.
PrintLab baut auf Bambuddy 1.2.5.7 auf (Herkunft und Lizenz: `NOTICE`).

## v1.3.1 (28.10.2026)

- **Update-Prüfung bei privatem Repo:** die Update-Prüfung schickt jetzt einen GitHub-Token mit
  (Umgebungsvariable `PRINTLAB_GITHUB_TOKEN`); ohne Token antwortet GitHub bei einem privaten
  Repo mit 404 („keine Releases“), obwohl Releases existieren. `starte_printlab.bat` nimmt den
  Token automatisch aus der `gh`-Anmeldung; die Aufrufe haben damit auch ein höheres
  Rate-Limit (5000 statt 60 je Stunde). Dokumentiert in `docs/HILFE.md`.
- **Tests under Windows:** der nur POSIX-konforme Test zum externen Slicer-Ablageort
  (`os.geteuid`/chmod) wird auf Windows gesammelt nicht mehr gesammelt (Sammlungsfehler);
  ein über Socket-Flüchtigkeits-Schwankungen hinweg fehlgeschlagener Probe-Test ist in der
  Windows-Skip-Liste seiner Geschwister beigetreten. Beide laufen in der Linux-CI.
- **Gesamtsuite:** Backend 13.584 bestanden (die in Parallellauf verbleibenden Abbruch
  waren Windows-Timing-Flake — alle einzeln bestätigt grün); Frontend 4.176/4.177
  (ein flackender, bei Wiederholung grün).

## v1.3.0 (28.10.2026)

- **Sicherung repariert:** `werkzeuge\\backup_erstellen.ps1` sicherte seit dem Rebrand nur
  noch die alte `bambuddy.db`. Jetzt laufen `printlab.db` (+ Journal-Dateien), alle
  Hardware-/Magazin-Konfigurationen, `audit_log.jsonl`, Preisliste, Angebotsverlauf,
  Prüfungs-Konfigurationen sowie die Geheimnisse `data/.jwt_secret` und
  `data/.mfa_encryption_key` mit.
- **Tür-Status:** der bislang nur konfigurierbare `door_status_command` wird jetzt
  ausgeführt — neuer Endpunkt `POST /printers/{id}/hardware/door/status` und Button
  „Türstatus abfragen“ in der Wartungskarte; das Ergebnis setzt den Türzustand.
- **PC-Slicer-Token im Client:** der Slicer-Client im Backend schickt
  `Authorization: Bearer <PC_SLICER_TOKEN>` mit, wenn die Variable gesetzt ist —
  der Zugriffsschutz des PC-Slicers kann dann per Token statt nur per IP-Liste erfolgen
  (Doku in `docs/INSTALLATION-PI.md` und der Slicer-Hinweistext).
- **Audit-Log:** hängt Einträge jetzt an (O(1)) und kappt alle 250 Zeilen auf die
  letzten 2000; die Datei liegt einheitlich unter `data/` (bzw. DATA_DIR), eine
  bestehende Datei aus dem Projekt-Root wird beim ersten Schreiben mitgenommen.
- **Automatik:** der Tür-Check ist auf „ geschlossen bestätigt oder Abbruch“ vereinfacht;
  wenn die Warteschlangen-Prüfung wegen Datenbankfehlern nicht möglich ist, läuft der
  Wechsel weiterhin (fail-open, unverändert), aber das Ergebnis wird sichtbar
  protokolliert statt stillschweigend.
- **Kamera-Einmessung:** scheitert das Verzerren eines neuen Bildes, während eine
  Einmessung vorliegt, überspringen Bauteil-Wächter, Erste-Schicht-Inspektor und
  Spaghetti-Check die Prüfung, statt ein ungewarptes Bild gegen gewarpte Referenzen
  zu vergleichen (Fehlwarnquelle beseitigt).
- **Sicherheit/Start:** Warnung im Protokoll, wenn die Anmeldung aus ist und das Backend
  nicht nur am Loopback lauscht (Docker/systemd binden standardmäßig an 0.0.0.0).
- **Windows-Aufgabe:** die Anmeldeaufgabe heißt „PrintLab PC Slicer“ und entfernt eine
  alte Aufgabe namens „Bambuddy PC Slicer“ (einmalig, beim Einrichten).
- **CI:** Sicherheits-Aufträge (pip-audit, npm-audit) sind wieder harte Schwelle
  (kein `continue-on-error`); CodeQL scannt auch den Arbeitsbranch.
- **Aufräumen:** Installations-README beschreibt den Windows-Installer aus den Releases
  statt eines nicht vorhandenen Skripts; Postgres-Beispiel im compose warnt vor
  „changeme“; `TODO.md` bereinigt.
- **Oberfläche:** Abbruch der Automatik fragt mit Warnhinweis nach (laufende
  Hardware-Schritte stoppt nur der Not-Halt); die Konfigurations-Hilfe empfiehlt
  Befehle als Liste (ohne Shell). Zwei neue UI-Texte in allen 15 Sprachen.
- **Tests:** neue Backend-Tests für Tür-Status und chronologisches Audit-Log;
  Frontend-Tests für die Tür-Status- und Abbruch-Schaltflächen.

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
