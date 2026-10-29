# Changelog

Alle nennenswerten Änderungen an PrintLab. Versionsschema: siehe `docs/VERSIONING.md`.
PrintLab baut auf Bambuddy 1.2.5.7 auf (Herkunft und Lizenz: `NOTICE`).

## v1.9.6 (in Arbeit) — Termin-Meldung

- **Meldung „Termin in Gefahr":** Rechnet die Prognose damit, dass ein wartender Auftrag nach seinem Liefertermin fertig
  wird (oder ist der Termin schon verstrichen), geht einmal eine Meldung über deine Kanäle (ntfy, Telegram, Pushover, E-Mail
  …). Erst wenn der Auftrag zwischendurch wieder im Plan war, kann dieselbe Meldung erneut kommen. Der Schalter „Termin in
  Gefahr" steht bei jedem Kanal unter den Warteschlangen-Ereignissen und ist überall voreingestellt an; der Text lässt sich
  wie die anderen Vorlagen bearbeiten.
- **Prognose auf dem Server:** Dieselbe Rechnung wie in der Oberfläche (Priorität zuerst, Verteilung auf den zuerst freien
  Drucker), alle fünf Minuten für Aufträge mit Termin. Ohne Kanal, der die Meldung will, wird nichts als „gemeldet" markiert,
  ein später eingerichteter Kanal erfährt also noch von bereits gefährdeten Aufträgen.

## v1.9.5 (29.10.2026) — Sammel-Priorität

- **Priorität und Liefertermin für mehrere Aufträge auf einmal:** In der Warteschlange Aufträge markieren, „Auswahl
  bearbeiten", dort Priorität setzen und den Liefertermin setzen oder entfernen. Nur was du änderst, wird geändert
  (eine reine Prioritätsänderung lässt die Termine stehen). Aufträge, die nicht mehr wartend sind, werden übersprungen.
- **Schnittstelle:** Die Sammel-Änderung (`PATCH /queue/bulk`) kennt `priority` und `due_at`; ein ausdrückliches `null` bei
  `due_at` entfernt den Termin, bei `priority` wird es abgelehnt (422), auch beim Einzel-Update.
- **Intern:** Der Sammel-Dialog liegt jetzt in `QueueBulkEditModal.tsx`; `QueuePage.tsx` ist dadurch gut 230 Zeilen kürzer.

## v1.9.4 (28.10.2026) — Auslastung und Fertigzeit

- **Übersicht „Auslastung und Fertigzeit"** über der Warteschlange: je Drucker der laufende Druck mit Restzeit, „frei ab",
  Auslastung der nächsten 24 Stunden und die Aufträge in der Warteschlange; dazu eine Zeile mit der voraussichtlichen
  Fertigzeit aller Aufträge. Die Prognose folgt der Planer-Reihenfolge (Priorität zuerst) und verteilt Aufträge für „irgendein
  Drucker dieses Modells" auf den Drucker, der zuerst frei wird.
- **Fertigzeit je Auftrag:** Jede Zeile der Warteschlange zeigt „Fertig um …".
- **Termin-Warnung mit Warteschlange:** „Termin wird nicht gehalten" rechnet jetzt mit der Prognose (Aufträge davor
  eingerechnet) statt nur mit der Druckzeit ab jetzt. Die Schnittstelle behält ihre einfache Warnung für andere Programme.

## v1.9.3 (28.10.2026) — Mehrere Drucker

- **Auftrags-Priorität in der Warteschlange:** Stufen *Eilig*, *Standard* und *Niedrig* beim Einreihen (und später im
  Bearbeiten-Dialog). Eine höhere Stufe kommt immer zuerst dran, innerhalb einer Stufe gilt die bisherige Reihenfolge
  (oder „kürzeste zuerst", wenn aktiv). Plakette am Auftrag und Filter „Priorität" in der Warteschlange.
- **Liefertermin (optional):** beim Einreihen setzbar; warnt in der Warteschlange mit „Termin überschritten" oder „Termin
  wird nicht gehalten" (selbst bei sofortigem Start zu spät), ändert die Reihenfolge aber nicht.
- **Gleichmäßige Auslastung:** Passen mehrere freie Drucker („irgendein X1C"), bekommt der mit der geringsten
  Betriebszeit (gezählte Laufzeit plus eingetragener Sockel) den Auftrag; der Aufwecker per Steckdose nimmt ebenfalls den
  am wenigsten genutzten.

## v1.9.2 (28.10.2026) — Virtuelle Drucker und Filament-Profile

- **Virtuelle Drucker:** Beim Anlegen lässt sich der Zieldrucker jetzt für jeden Modus wählen (Archiv, Prüfen,
  Warteschlange; bei Proxy bleibt er Pflicht). So gibt es mehrere virtuelle Drucker mit unterschiedlichen Modi für
  denselben Zieldrucker. Ein Hinweis erklärt, dass jeder im Slicer eine eigene IP-Adresse (Bind-IP) braucht.
- **Filament-Profile den Spulen zuordnen** (Filamentverwaltung → „Profile zuordnen"): sucht für Spulen ohne Slicer-Profil
  das passende Profil aus Bambu Cloud, Orca Cloud, lokalen und eingebauten Profilen (nach Marke, Material und Sorte; bei
  Varianten wie „@BBL X1C" gewinnt das Modell eines vorhandenen Druckers). Vorschlagsliste zum Prüfen, „generisch" ist
  nicht vorangehakt, dann gesammelt übernehmen. Die Zuordnung der Profile braucht eine Anmeldung bei der Bambu Cloud, sonst
  gelten nur die eingebauten Standardprofile.

## v1.9.1 (28.10.2026) — Update-Prüfung

- **Update trotz GitHub-Limit:** Meldet GitHub „rate limit reached" (ohne Anmeldung 60 Abfragen pro Stunde und IP), liest
  PrintLab die Versionen jetzt über `git ls-remote --tags`, das nicht gegen dieses Limit zählt. Prüfen und Einspielen
  funktionieren dann weiter; es fehlen nur die Versionshinweise in der Anzeige. Ohne git oder bei Netzfehler bleibt die
  bisherige Meldung mit der Wartezeit.

## v1.9.0 (28.10.2026) — Angebote und Einrichtung

- **Wartungsseite in vier Reiter** (auch mit Handy bedienbar, waagerecht scrollbar): *Status* (Drucker und Wartung),
  *Hardware & Optik* (Wartungsprogramme, Tür/Wechsler, Kamera-Einmessung), *System & Betrieb* (Checkliste, Zustand des
  Geräts, Meldewege, Fernzugriff) und *Einstellungen*. Der Reiter steht in der Adresse (`?tab=system`).
- **Einrichtungsassistent** (Reiter *System & Betrieb*): führt durch die offenen Punkte der Checkliste, Pflicht zuerst, mit
  Erklärung und Knopf zur passenden Stelle; auf dem Status-Reiter weist ein Hinweis darauf, solange Pflichtpunkte offen sind.

- **Zusätzliche Positionen im Angebot** (Versand, Konstruktion, Nachbearbeitung …): Beschreibung, Menge, Einzelpreis, ohne
  Aufschlag auf die Summe; im Rechner, in der Druckansicht, im Angebots-PDF und in der Rechnung.
- **Nachkalkulation:** Druckjobs aus dem Archiv mit einem Angebot verknüpfen (Verlauf → „Nachkalkulation"); zeigt Ist-Kosten
  für Material und Energie gegen den Angebotspreis, Abweichung und Gewinn. Fehlende Archivkosten werden aus Gramm und
  Druckzeit geschätzt (als „geschätzt" markiert); die Arbeitszeit bleibt wie im Angebot.

## v1.8.0 (28.10.2026) — Verbesserungen im Alltag

- **Sicherungen vor Updates in der Oberfläche** (Einstellungen → System): Liste mit Größe und Dateien, „Wiederherstellen" mit
  Rückfrage. Die Wiederherstellung läuft beim nächsten Start, bevor die App die Datenbank öffnet; der Stand davor wird
  ebenfalls gesichert. Nur mit eingeschalteter Anmeldung und mit dem Update-Schutz im Dienst.
- **Meldewege in der Oberfläche** (Wartung → „Meldung bei Ausfall"): Telegram und ntfy eintragen, Testmeldung senden.
  Token und Adressen werden nur geschrieben und nie zurückgegeben; Überwachung und Sicherung nach außen nutzen sie mit.
  Gefährliche ntfy-Adressen (lokal, Link-Local) werden abgelehnt.
- **Kamera einmessen in der Oberfläche** (Wartung): Fotos mit leerem und belegtem Bett hochladen, Messwerte und Vorschlag
  ansehen, Schwellwert übernehmen oder zurücksetzen; die Bilder werden nicht gespeichert.
- **Angebote:** Kundenanschrift (im PDF), einstellbares Nummernformat (`{prefix}`, `{year}`, `{yy}`, `{seq}`, `{seq4}`,
  `{seq5}`) und Firmenlogo (PNG/JPEG, wird als sauberes PNG abgelegt) im Briefkopf.
- **Rechnungen** (Angebote → „Rechnungen"): aus einem Angebot per „Rechnung" erzeugen, eigene lückenlose Nummer
  (`invoice_prefix`/`invoice_format`), Zahlungsziel, Leistungsdatum, PDF (de/en), als bezahlt markieren, wieder öffnen,
  stornieren (Rechnungen werden nie gelöscht), Summen je Währung und Überfälliges. Keine elektronischen Formate
  (XRechnung, ZUGFeRD); Pflichtangaben klärt die Steuerberatung.
- **Inbetriebnahme-Checkliste** (Einstellungen → System): zeigt, was eingerichtet ist (Anmeldung, Drucker, Meldeweg, Sicherung
  nach außen, Update-Schutz, Signatur, SSD, Fernzugriff, HTTPS) und wie man Offenes erledigt; ändert nichts selbst.
- **Intern:** Erweiterungs-API aus `client.ts` in `forkApi.ts` ausgelagert (Dateigrößen-Budget sinkt).
- **Update ohne Absturz-Eindruck:** nach dem Update zeigt die Oberfläche „startet neu" und lädt sich von selbst neu, sobald
  PrintLab wieder antwortet.
- **Übersetzungen der Fehlermeldungen:** ein Test verlangt für jede deutsche Meldung der Erweiterungen eine englische Regel;
  dabei fehlende Regeln ergänzt, dazu die neuen Update-, Meldeweg- und Logo-Meldungen.

## v1.7.0 (28.10.2026) — Betriebssicherheit

- **Anmeldung vorgeschrieben** (`PRINTLAB_REQUIRE_AUTH=1`, vom Pi-Installer gesetzt): bis der Administrator mit Passwort
  angelegt ist, ist die Schnittstelle gesperrt (403, auch Bilder, Kamera und WebSocket); nur `/setup`, der Anmeldestatus
  und die Versionsabfrage bleiben offen, und die Einrichtung lässt sich nicht ohne Passwort abschließen. Die Oberfläche
  leitet auf `/setup` und sperrt die Wahl „ohne Anmeldung".
- **HTTPS über Tailscale** (Fernzugriff-Karte): verschlüsselter Zugang mit echtem Zertifikat, QR-Code nimmt die HTTPS-Adresse.
- **Zustand des Geräts** (Wartung): Temperatur, Unterspannung, Speicherplatz und -art (SD-Karte-Warnung), Arbeitsspeicher,
  Laufzeit, Sicherungen; Schnittstelle `GET /api/v1/system/pi-health`.
- **Sicherung nach außen** (`werkzeuge/sicherung_extern.py`, Tages-Timer): geprüfte Sicherung auf USB/NAS, legt das Ziel nie
  selbst an, meldet Fehler über den Überwachungs-Meldeweg.
- **Update-Schutz härter:** Sicherungen nur für den Besitzer lesbar (700/600), Rückbau spielt die Pakete des alten Stands neu
  ein, systemd-Startzeit dafür verlängert.
- **Abnahme-Check** (`werkzeuge/abnahme.py`, `docs/ABNAHME.md`): prüft auf dem Pi automatisch Dienst, Anmeldung, Dienst-Datei,
  Signatur, Überwachung, Sicherungen, Gerätezustand und Ports; dazu die Checkliste für alles mit Hardware.
- **Release-Automatik:** „Build static frontend" läuft automatisch bei Änderungen an `frontend/` und schreibt eine
  Quell-Prüfsumme; „Release gate" prüft beim Tag Version, Changelog und `static/` und legt erst dann das GitHub-Release an
  (Text aus dem Changelog). `werkzeuge/release_pruefen.py` macht dasselbe lokal.
- **Wartbarkeit:** Größen-Grenze für die riesigen Dateien (Test), eigene Start- und Torprüfungen aus `main.py` in
  `services/fork_startup.py`.
- **Lokale Prüfung:** `werkzeuge/lokal_pruefen.py` führt alles aus, was die CI prüft, und fängt die bekannten
  Windows-Eigenheiten ab.
- **Fehler behoben:** Die Support-Information (`psutil.open_files()`) konnte unter Windows den ganzen Prozess mit einer
  Zugriffsverletzung abstürzen lassen; dort wird jetzt die Handle-Zahl benutzt.
- **Pakete aktualisiert** (Frontend, innerhalb der erlaubten Versionsbereiche) und die letzten 3 Warnungen von `npm audit`
  behoben (vitest); `i18next` nicht mehr exakt festgenagelt.
- **Branding:** interne Kennungen von Bambuddy auf PrintLab umgestellt (Toast-Ereignis, E-Mail-Bild-Kennungen,
  Zertifikatsname, MQTT-Standardpräfix); Dokumente und Diagramm-Skript angepasst. Der Name `bambuddy.db` in alten
  Sicherungen bleibt für das Zurückspielen erhalten.
- **Übersetzungen:** Test, dass jede Sprache alle `{{Platzhalter}}` des englischen Textes behält.
- **Hardware-Befehle:** deutlicher Hinweis in der Karte, dass Änderungsrecht gleich „Programme auf dem Gerät starten" heißt.
- Einmal-Skripte `i18n_hwadmin.py` und `i18n_pricelist.py` entfernt; `TODO.md` neu geschrieben.

## v1.6.3 (28.10.2026) — Signierte Updates

- **Updates nur von signierten Tags** (optional, aber empfohlen): Liegt auf dem Pi die Datei `update_allowed_signers` im
  Datenordner (öffentlicher SSH-Schlüssel), spielt PrintLab nur Tags ein, die mit diesem Schlüssel signiert sind, und
  setzt genau auf den geprüften Tag zurück. Die Schlüssel liegen bewusst auf dem Pi, nicht im Repo und nicht bei GitHub:
  wer das GitHub-Konto übernimmt, kann dort eigene Schlüssel eintragen, aber nicht diese Datei ändern. Ohne Datei bleibt
  alles wie bisher; die Oberfläche zeigt, ob die Prüfung aktiv ist. Anleitung: `docs/UPDATE-SIGNATUR.md`.
- Release-Namen werden vor dem Update geprüft (nie als Option an git); der Installer nimmt den Schlüssel mit
  `PRINTLAB_UPDATE_PUBKEY` entgegen.
- Aus der Gesamtanalyse: Slicer-Dateiname wird auf den reinen Namen reduziert, Rückbau akzeptiert nur Git-Hashes,
  Überwachung öffnet nur http(s), CI-Korrekturen (siehe `docs/ANALYSE-2026-10-28.md`).

## v1.6.2 (28.10.2026) — Slicer von unterwegs (Versuch)

- **Slicer-Zugriff über Tailscale** (Wartung → Fernzugriff, nur nach der Freigabe der Weboberfläche): gibt die Ports des
  virtuellen Druckers (3000, 3002, 990, 8883 und den FTP-Datenbereich 50000–50029) nur im privaten Tailnet frei. In
  Bambu Studio / OrcaSlicer dann „Drucker per IP hinzufügen" mit der Tailscale-Adresse des Pi und dem 8-stelligen
  Zugangscode des virtuellen Druckers. **Noch nicht an echter Hardware erprobt**; ob der Slicer die Verbindung über
  Tailscale annimmt (Zertifikate, Passiv-Modus des FTP), zeigt erst ein Test.

## v1.6.1 (28.10.2026) — QR-Code für den Handy-Zugriff

- **QR-Code in der Fernzugriff-Karte:** Mit dem Handy scannen, um PrintLab über Tailscale zu öffnen (Tailscale auf dem
  Handy mit demselben Konto anmelden, Seite als Lesezeichen oder zum Home-Bildschirm hinzufügen). Die Bambu-Handy-App
  selbst lässt sich nicht mit PrintLab koppeln: Ihr QR-Code und die PIN laufen über die Bambu-Cloud.

## v1.6.0 (28.10.2026) — Sicherheit beim Update, Überwachung, Hardware, Angebote

- **Update mit Sicherung und Rückbau:** Vor jedem Update in PrintLab werden Datenbank und Einstellungsdateien gesichert
  (Ordner `update-backups` im Datenordner, die letzten 3 bleiben; die Kopie der Datenbank wird auf Integrität geprüft,
  sonst bricht das Update ab, bevor etwas verändert wurde). Startet die neue Version nicht stabil an (viermal ohne
  Bestätigung), baut `werkzeuge/update_guard.py` (systemd `ExecStartPre`) automatisch auf den alten Stand zurück und
  spielt die gesicherte Datenbank wieder ein. Unter „Einstellungen → System“ steht dann ein Hinweis. Ältere Installationen
  bekommen den Schutz beim nächsten Update in die systemd-Unit eingetragen (oder durch erneutes Ausführen des Installers).
- **Überwachung von außen** (`werkzeuge/ueberwachung.py`, systemd-Timer jede Minute, vom Installer eingerichtet): prüft,
  ob PrintLab antwortet, startet es bei Ausfall neu und meldet das per Telegram oder ntfy aufs Handy (auch „läuft wieder“
  und wenig Speicherplatz). Meldeweg über `PRINTLAB_ALERT_TELEGRAM_TOKEN`/`_CHAT` oder `PRINTLAB_ALERT_NTFY_URL` in
  `~/.config/printlab.env`.
- **GPIO-Treiber für Tür und Plattenwechsler** (`werkzeuge/gpio_mechanik.py`): Servo-Tür mit Endschaltern, Not-Halt,
  Selbsttest; meldet `DOOR:OPEN/CLOSED/UNKNOWN` für den Befehlsmodus. Kein stiller Simulationsmodus; der eigentliche
  Plattenwechsel bleibt gesperrt, bis die Mechanik vermessen ist.
- **Kamera einmessen** (`werkzeuge/kamera_kalibrieren.py`): aus Beispielbildern mit leerem und belegtem Bett einen
  Schwellwert und die Mindest-Sicherheit für „Platte frei automatisch bestätigen“ ableiten und speichern.
- **Angebote:** Firmendaten (Briefkopf, Bankverbindung, Umsatzsteuer, Gültigkeit), fortlaufende Angebotsnummer
  (`A-2026-0001`, Zähler fällt nie zurück) und **PDF** je gespeichertem Angebot (Deutsch/Englisch); Leistungstext beim
  Speichern.
- **Sicherungen prüfen:** `werkzeuge/backup_pruefen.py` (Windows, Linux, Pi) prüft Datenbanken und Einstellungsdateien.
- **CI repariert:** Format-Prüfung, unbekanntes Wartungsprogramm, Test-Verschmutzung durch neu geladene Konfiguration,
  Abhängigkeits-Warnung (dompurify); Windows-Installer läuft nur noch von Hand, Code-Scanning-Upload ist optional.

## v1.5.1 (28.10.2026) — Update-Funktion für das private Repo

- **Updates aus der Oberfläche** funktionieren jetzt mit dem privaten Repo: Der Token (`PRINTLAB_GITHUB_TOKEN`) wird
  auch für `git fetch` verwendet (als HTTP-Header über die Umgebung, nirgends gespeichert); vorher scheiterte das
  Holen des neuen Stands ohne hinterlegte Zugangsdaten.
- **Automatischer Neustart** nach dem Update, wenn der Dienst ihn erlaubt (`PRINTLAB_AUTO_RESTART=1`, systemd mit
  `Restart=always`); ohne die Variable bleibt es bei „bitte neu starten“.
- **Klarer Hinweis**, wenn das Repo privat ist und kein Token gesetzt ist (statt „keine Releases gefunden“).
- `werkzeuge/pi_neu_installieren.sh` richtet den Dienst dafür ein (`Restart=always`, optional gespeicherter Token).

## v1.5.0 (28.10.2026) — Fernzugriff

- **Fernzugriff über Tailscale** (Seite „Wartung“): Einrichten ohne Root, Anmelde-Link, Freigabe nur im privaten
  Tailnet, Abschalten; nur mit eingeschalteter Anmeldung. Meldungen auf Deutsch und Englisch, Oberfläche in 15 Sprachen.
- **`werkzeuge/pi_neu_installieren.sh`:** alte Versionen auf dem Pi entfernen, Daten sichern und neu aufspielen.

## v1.4.0 (28.10.2026) — Welle 1 der Erweiterungen

- **Erste-Schicht-Gate:** optionale Automatik „Bei Warnung drucken anhalten“ — pausiert den
  Druck einmalig nach der Inspektor-Warnung (Standard aus); Neuer Schalter in der
  Wartungskarte, Schlüssel `pause_on_warning` je Drucker.
- **Eigene Wartungsprogramme:** Ablaufpläne (home/z/xy/pause) frei definiert in
  `data/maintenance_plans.json` — API `GET/PUT /api/v1/printers/maintenance-plans`, Start
  über dieselbe Start-Route wie eingebaute Programme; harte Validierung (P2S-Grenzen
  20–236 mm, Pausen 1–600 s, max. 200 Schritte, Audit-Log). UI-Editor folgt in Welle 2.
- **Windows-Firewallregeln:** `werkzeuge/firewall_regeln.ps1` legt Portfreigaben für Web
  (8000) und PC-Slicer (3001) mit automatischer Subnetz-Ermittlung oder Geräteliste an
  (`-AllowedIps`), gilt nur für Private-/Domänennetzwerke; `-Remove` entfernt sie.
- **Backup-Integritätsprüfung:** `werkzeuge/backup_pruefen.ps1` prüft die neueste
  Sicherung (Datenbank in Temp kopieren, `PRAGMA integrity_check`); die
  Sicherungsroutine ruft die Prüfung nach jedem Backup automatisch auf.
- **Powershell-Skripte als UTF-8 mit BOM** (PowerShell 5.1 liest ohne BOM als ANSI und
  verliert Umlaute — drei Skripte korrigiert).
- **Tests:** Erste-Schicht-Gate (Konfig + Persistenz), eigene Programme (Validierung,
  Plan-Bau, Startpfad); Update-/Integration-Kontexte unverändert grün.

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
