# Prüfbericht PrintLab — 27.10.2026

Stand: Branch `bambu-monitor-port`. Der Tag `v1.2.0` zeigt auf `a9ea6545`. Alle Änderungen dieses Berichts sind
**noch nicht committet** und gehören in ein Release **v1.2.1** (`PRINTLAB_VERSION = "1.2.1"` steht bereits in
`backend/app/core/config.py`).

## 1. Ergebnis in Kürze

- Alle Fehler und Risiken aus dem ersten Bericht sind behoben. Ausnahme: **die Anmeldung einschalten** kann nur
  du (Passwort selbst eingeben).
- Die Verbesserungs- und Erweiterungsvorschläge sind umgesetzt, außer zwei begründeten Ausnahmen (Abschnitt 4).
- Das Branding ist auch nach innen umgestellt (Abschnitt 5). Nur das, was die Lizenz verlangt, bleibt.

## 2. Fehler und Risiken: Stand

| Fund | Lösung |
|---|---|
| Hardware-Befehle ohne Anmeldung änderbar (Shell-Befehle) | nur mit eingeschalteter Anmeldung und Recht „Einstellungen ändern“; Befehle auch als Liste ohne Shell |
| Update-Prüfung, Docker-Compose und Installationsskripte zeigten auf den Upstream | zeigen auf `Luk1236/printlab`; Compose baut lokal |
| Fehlerbericht-Relay und Ankündigungs-Feed beim Upstream | aus, bis du selbst eine Adresse einträgst |
| `only_with_queue` ging verloren, ungültige Zahlen setzten die Automatik zurück, PostgreSQL-Probe legte Datei an | behoben |
| Wechsel unvollständig → falsches Magazin | Zustand „unvollständig“, Magazin nachgeführt, nächster Wechsel gesperrt bis bestätigt |
| Not-Halt setzte die Sperre sofort zurück | beendet den laufenden Befehl, sperrt bis zur Freigabe |
| Automatik-Ergebnis nur im Arbeitsspeicher | im Audit-Log, nach Neustart sichtbar |
| `NameError` in Kamerabild-Route und Leerbett-Prüfung | Importe ergänzt |
| Rohe Übersetzungsschlüssel in Hardware-Karte und Kalkulator, fehlende „Einmessung löschen“-Schaltfläche | behoben |
| Hilfe-Link der Systemprüfung hängte zwei Anker aneinander | behoben (gefunden durch den Gesamttest) |
| Ruff-Altlasten | `ruff check backend` ist sauber |

**Offen, nur du:** Anmeldung einschalten (`werkzeuge\admin_passwort_setzen.py`). Bis dahin sind Hardware-Befehle
gesperrt, aber Drucker, Not-Halt und Plattenwechsler im Simulationsmodus sind im Netz ohne Anmeldung erreichbar.

## 3. Weitere Verbesserungen dieser Runde

- **Magazin pro Drucker** (`magazine_<id>.json`, `hardware_<id>.json`): eigener Not-Halt, eigener Stand; der
  erste Drucker übernimmt den bisherigen gemeinsamen Stand.
- **Platte frei automatisch** per Kamera (Standard aus, fail-closed).
- **Benachrichtigung** bei Automatik-Fehler und Magazin-Warnung (über „Nachrichten verbundener Apps“).
- **Angebotsverlauf pro Kunde** (speichern, filtern, löschen, Summe je Kunde) und **Angebot als PDF**.
- **Statistik als PDF** (Kennzahlen des gewählten Zeitraums).
- Eigene **Hilfeseite** (`docs/HILFE.md`) statt externem Wiki, **Pi-Anleitung** (`docs/INSTALLATION-PI.md`,
  nicht auf Hardware getestet).

## 4. Nicht umgesetzt

| Vorschlag | Grund |
|---|---|
| Backend-Meldungen in 15 Sprachen übersetzen | du hattest „nicht übersetzen“ entschieden |
| Fertiges ARM-Release-Paket | braucht einen echten Build- und Testlauf auf dem Pi |
| Wartungsintervalle, AMS-Feuchte-Warnung | nicht nötig, die Grundanwendung hat beides |

## 5. Branding

**Jetzt auch nach innen umgestellt** (mit Übergang für Altdaten):

- Datenbank **`printlab.db`**: wird beim Start automatisch aus `bambuddy.db` (samt WAL/SHM) umbenannt.
- Umgebungsvariablen **`PRINTLAB_*`**: die alten `BAMBUDDY_*` gelten weiter und werden abgebildet.
- Protokoll `printlab.log`, Sicherungen `printlab-backup-*` (ältere werden weiter erkannt und gelöscht/gelistet),
  Support-Paket, Etiketten-, Inventar- und Zertifikats-Dateinamen.
- Prometheus-Kennzahlen `printlab_*`, MQTT-Standardpräfix `printlab` (gespeicherte Einstellung bleibt),
  MQTT-Client-IDs, HTTP-Header `X-PrintLab-*`, Standardname des virtuellen Druckers.
- Windows-Installer (`printlab.iss`, Dienst, Ordner, Dateinamen), systemd-Datei `printlab.service`,
  Docker-/Compose-Namen, Installations- und Aktualisierungsskripte, CI-Bezeichnungen.
- Eine einzige Versionsquelle (`PRINTLAB_VERSION`); die Oberfläche zeigt 1.2.1.
- Alle Codekommentare, Docstrings, Tests und Dokumentation (Bambuddy → PrintLab; Verweise auf die Person
  des Upstream-Autors neutralisiert).
- Wiki-Links durch die eigene Hilfeseite ersetzt; `CHANGELOG.md` ist jetzt der PrintLab-Verlauf.
- Entfernt: Spendenaufforderung (Oberfläche, Dienst, Endpunkt), Upstream-Veröffentlichungsskripte und -Workflows,
  Sponsoren-Dateien, Upstream-Screenshots.

**Bleibt (nur das Notwendige):**

- **`LICENSE`, `NOTICE`, Urheberhinweise in Quelldateien.** AGPL-3.0 verlangt, sie zu erhalten und Änderungen als
  solche zu kennzeichnen. Die App als allein selbst geschrieben auszugeben, wäre unwahr; die Angabe lautet
  „PrintLab, basierend auf Bambuddy“ (README, `NOTICE`).
- **Quellcode-Angebot (AGPL §13):** sobald andere PrintLab über das Netzwerk nutzen, haben sie Anspruch auf den
  Quellcode (dann Repo freigeben).
- **Externe Bausteine anderer Projekte**, die PrintLab nutzt: die Slicer-Sidecar-Images
  (`ghcr.io/maziggy/orca-slicer-api`, `.../bambu-studio-api`, nur für den optionalen In-App-Slicer) und
  die Basis-Tags `v1.2.5.x` im Git-Verlauf.
- Protokoll- und Schnittstellennamen, die Dritte erwarten (z. B. Fensternachrichten `bambuddy:theme` für
  eingebettete Fremd-Apps), sowie das Dateiformat der Sicherungen (`bambuddy.db` im ZIP, damit alte
  Sicherungen lesbar bleiben).
- Die Appliance-Pfade `/etc/printlab/local.toml` und `/run/printlab/time-synced` wurden mitgezogen; ein Appliance-Image des Upstream würde sie unter dem alten Namen anlegen.

## 6. Prüfstand

- `ruff check backend`: sauber. TypeScript: sauber. ESLint: sauber. i18n-Parität (15 Sprachen): grün.
- Frontend: 4175 Tests, nach Korrektur alle grün.
- Backend (komplett, ohne `test_slice_external_folder_output.py`, die unter Windows nicht ladbar ist): rund 13 000
  Tests. 111 fehlgeschlagen; **91 davon scheitern ebenso auf dem unveränderten Ausgangsstand** (Windows-Eigenheiten:
  Dateirechte, Symlinks, Pfadtrenner, Zeitzone, Kodierung). **28 gingen auf meine Umbenennungen zurück und sind
  korrigiert** (LDAP-Testdaten, MQTT-Themen, Unit-Dateiname, Etikettenname, Hilfs-Links). Die Tests aus
  `test_bambu_ftp.py` melden im Gesamtlauf Windows-Dateisperren beim Aufräumen, laufen einzeln aber grün; der
  Code dort ist unverändert (nur Kommentare).
- Offen bleibt ein Windows-Pfadtest (`test_erofs_under_systemd…`), der schon vorher an den Backslashes scheiterte.
- **Nicht geprüft:** echter Drucker/Mechanik, Docker- und ARM-Build, Windows-Installer, Linux-Skripte
  (nur Texte/Namen konsistent umbenannt).

## 7. Zum Veröffentlichen

1. Änderungen durchsehen und committen, danach Tag `v1.2.1` setzen. `v1.2.0` nicht verschieben.
2. Erst danach pushen.
3. Vor dem Anschluss der Mechanik im Befehlsmodus: Anmeldung einschalten.
4. Einmalig prüfen: Beim ersten Start mit der neuen Version benennt PrintLab `bambuddy.db` in `printlab.db` um. Vorher
   eine Kopie der Datenbank sichern (der Ordner `backup/` enthält schon eine).

## 8. Nachtrag (Version 1.2.2, noch nicht committet)

Umgesetzt, was nach v1.2.1 offen war:

- **Meldungen auf Englisch:** Die Erweiterungs-Endpunkte übersetzen ihre Meldungen ins Englische, wenn die
  Oberfläche nicht auf Deutsch steht (Antwortfilter `ForkI18nMiddleware`, Katalog in
  `backend/app/i18n/fork_messages.py`, rund 90 Muster). Die Oberfläche schickt ihre Sprache als `Accept-Language`
  mit. Wie in der Grundanwendung kennt der Server nur Deutsch und Englisch; alle anderen Sprachen bekommen Englisch,
  unbekannte Texte bleiben deutsch.
- **Echter Fehler gefunden:** Die Meldung zur gesperrten Befehls-Konfiguration enthielt ein Klingelzeichen statt
  `\admin_passwort_setzen.py` (Backslash-Escape).
- **Relative Pfade in der Datenbank** werden jetzt immer mit `/` gespeichert, damit Datenbank und Sicherungen
  zwischen Windows und Linux/Pi austauschbar sind (vorher Backslashes unter Windows).
- **SpoolBuddy** heißt in der Oberfläche jetzt „PrintLab Spool“ (Logo ersetzt, Texte in 15 Sprachen).
- **Upstream-Tags** (`v1.2.5.x` usw., 77 Stück) aus dem lokalen Repo entfernt; es bleiben `v1.0.0` bis `v1.2.1`.
  Der Remote `upstream` bleibt, damit sich spätere Korrekturen der Grundanwendung holen lassen.
- **Release-Workflow** `.github/workflows/release.yml` (Docker-Image amd64 + arm64 bei Tag `v*`, ungetestet).
- **Windows-Tests:** POSIX-Tests (procfs, Signale, chmod, Symlinks, Zeitzone, Dateisperren) werden unter Windows
  übersprungen (`backend/tests/windows_skips.txt`) und laufen in der Linux-CI weiter; zwei Tests lasen Dateien mit
  falscher Kodierung und sind korrigiert.

**Prüfstand 1.2.2:** Frontend 4175 von 4175 Tests grün. Backend, in fünf Abschnitten: 0 Fehler in den
Integrationstests (1748 + 1915 bestanden), Dienste-Tests 3106 bestanden; die übrigen Unit-Tests ergaben zehn
Fehlschläge durch Windows-Dateisperren bei paralleler Ausführung bzw. falsche Kodierung — alle zehn bestehen
einzeln oder sind korrigiert/übersprungen. `ruff`, TypeScript und die i18n-Parität sind sauber.

**Weiterhin so:** `LICENSE`, `NOTICE` und die Urheberhinweise bleiben (AGPL-3.0). Das entfernt zu wollen, würde dir
die Nutzungserlaubnis nehmen; ehrlich ist „PrintLab, basierend auf Bambuddy“.
