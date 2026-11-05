# TODO — PrintLab

**Stand:** 04.11.2026, Version 2.0.10 · **Basis:** Bambuddy 1.2.5.7 (AGPL-3.0, Herkunft: `NOTICE`) · **Branch:** `bambu-monitor-port`

Was fertig ist, steht mit Datum im `CHANGELOG.md`. Die ausführliche Bewertung (Risiken R1–R16, Verbesserungen, Erweiterungen)
steht in `docs/ANALYSE-2026-10-28.md`, die Abnahme in `docs/ABNAHME.md`.

## Läuft auf dem Pi (bestätigt)

PrintLab (Pi 5, nativ, systemd-Benutzerdienst), Fernzugriff über Tailscale, Updates aus der Oberfläche, Sicherung vor dem
Update mit Rückbau, Überwachung mit Meldung, Angebote mit PDF, Kamera-Einmessung, Zustand des Geräts, Anmeldung vorgeschrieben.

## Zuletzt erledigt (03.11.2026, Code-Review auf v2.0.1)

**Review-Härtung nach v2.0.1 → Release v2.0.2 (15 Bugfixes + Tests, Details im CHANGELOG-Abschnitt v2.0.2):**

- **Webhooks:** DNS-Prüfung zur Zustellzeit (SSRF-Rebinding), Zahlenkodierung-Hosts abgedichtet, Geheimnisse maskiert in
  Antworten, Event-Validierung (keine toten Hooks), `follow_redirects=False`, 200–299 = Erfolg, Persistenzfehler → 503,
  Registry-Deckel 200, Backpressure-Semaphor (32), Backoff-Retry (Netz/5xx/429; 4xx dauerhaft) mit Zustellhistorie pro Hook
  und Dead-Letter-Deaktivierung nach 5 Fehlern in Folge.
- **Kundenportal:** Checkout rechnet nur serverseitig registrierte Kalkulationen ab (Quote-Registry, jetzt SQLite-Tabelle
  `portal_quotes` — überlebt Neustarts), Betrag nie aus dem Request, URL-Validierung (400 vor 404),
  Stripe-Mindestbetrag, Rate-Limit (20/min Kalkulation, 6/min Checkout, per IP), Positions-Argument-Bug der
  v1.29-Route behoben (`success_url`/`customer_email`-Vertauscher).
- **Fleet:** `_gather_fleet_state` liest echte Telemetrie und Wear-Daten statt Platzhalter; Load Balancer toleriert
  kaputte Payloads; Düsentyp und Betriebsstunden aus `wear_tracker` statt `True`/`120.0`; Dispatch-/Fitness-Body über
  Pydantic-Modell `DispatchJobRequest` validiert.
- **Archiv:** Abschluss-Hooks (Verschleiß + Webhook) in einem Helfer, Feuer nur bei echtem Statuswechsel — keine doppelten
  Stundebuchungen mehr bei wiederholten `update_archive_status`-Aufrufen; Hook-Fehler sichtbar auf Warnstufe.
- **Wear-Alarm: `maintenance.wear_alert` wird jetzt wirklich gesendet** — bei Übergang OK → WARN/CRITICAL durch
  Druckbetrieb, genau einmal je Wechsel (Vorher/Nachher-Vergleich ohne Reentrant-Deadlock).
- **Not-Halt der KI:** meldet ehrlich „kein Hardware-Kanal", statt eine nutzlose Instanz zu erschaffen und Erfolg zu vortäuschen.
- **Plattenwechsel:** Betttemperatur aus der echten Quelle (`state.temperatures["bed"]`), `DEFAULT_MAX_SWAP_TEMP` statt Magiezahl.
- **Routen-Integrationstests** für alle fünf Enterprise-Router (Auth-Pfade, 400/404/429-Mapping, Maskierung,
  Body-Validierung) in `tests/integration/test_fork_routers_api.py`.

## Zuletzt erledigt (01.11.2026, in v1.21.0)

**Nachtrag v1.22.0:** Der Weg endet nicht mehr im Slicedialog: Die Fertigmeldung bietet **„Jetzt drucken“** und öffnet
den normalen Druckdialog mit dem Ergebnis. Ein nicht erreichbares Sidecar steht als gelber Hinweis auf jeder Seite, und
ein im Hintergrund gescheiterter Slice kommt als Browser-Meldung. Dazu die Leiste der Druckerliste
(`PrinterToolbar.tsx`) und die beiden Planer-Auswahlzweige (`scheduler/selection.py`) ausgelagert.

**Nachtrag v1.21.3:** Der Verbindungstest sitzt jetzt bei den Slicer-Einstellungen und nennt Adresse, Version oder
Fehlergrund — dieselbe Abfrage, die die Slice-Maske vor dem Slicen macht.

**Nachtrag v1.21.2:** Drei Meldungen aus dem Betrieb („Slicer-Standardwerte“, „Slicen fehlgeschlagen“, „nur .gcode
…“) hatten dieselbe Wurzel: Das Sidecar antwortete nicht, die Maske bot das Slicen trotzdem an, und ein 3MF-Projekt
wurde nur abgewiesen. Jetzt prüft `GET /slicer/status` vorab, nennt die Adresse und sperrt den Knopf; Fehlschläge
tragen eine übersetzte Handlungsanweisung; ein 3MF-Drop lädt hoch und öffnet den Slicedialog.

**Nachtrag v1.21.1:** Die CI meldete in der Pfadprüfung die neuen Stellen in `services/factory_reset.py`. Sie tragen
jetzt eine Begründung (`# SEC-PATH-OK:`), und der Zielordner aus der Auftragsdatei wird per `RESET_NAME_RX` geprüft,
bevor Daten dorthin wandern. Der Test selbst las die Quellen unter Windows mit cp1252 und stand deshalb auf der
Skip-Liste — er liest jetzt UTF-8 und läuft auch dort, damit solche Stellen künftig vor dem Push auffallen.

Runde „Suche, Push und Wartung“:

- **Browser-Meldungen:** `services/web_push.py` erzeugt VAPID-Schlüssel (in `settings`), verschlüsselt nach RFC 8291
  (aes128gcm, ohne Zusatzpaket) und stellt im Hintergrund zu; `routes/push.py` bietet Schlüssel, Abo, Abmelden,
  Status und Testversand. Die Karte in **Einstellungen → Benachrichtigungen** schaltet das Abo dieses Browsers;
  `public/sw.js` zeigt die Meldung und fokussiert beim Klick den passenden Tab. 7 Backend-Tests.
- **Meldungssprache wirkt:** `services/notification_texts.py` übersetzt die unveränderten Standardvorlagen der fünf
  häufigsten Druck-Ereignisse nach Deutsch, Spanisch, Französisch, Italienisch, Japanisch und Chinesisch; eigene
  Formulierungen bleiben unangetastet. 3 Tests. (Bisher nahm die Einstellung „Meldungssprache“ nur den Wert an.)
- **Globale Suche:** `GET /search` (Drucker, Bibliothek, Archiv, Warteschlange, Rechte wie die Listen) und die
  Befehlspalette `CommandPalette.tsx` mit Strg+K; Treffer öffnen die Liste mit `?search=…` (Archiv und Dateien).
  3 Integrationstests, 3 Frontend-Tests.
- **Reset zurückholen:** `factory_reset.restore` tauscht einen Reset-Ordner gegen den aktuellen Stand
  (`before-restore-…`); Routen `GET /system/factory-reset/archives` und `POST /system/factory-reset/restore`, Karte
  mit Bestätigungswort.
- **Datenbank-Wartung:** `services/db_maintenance.py`, Routen unter `/system/database` und Karte in der Wartung.
- **gzip für die Oberfläche:** `api/frontend_routes.py` komprimiert große Textdateien mit Cache und `Vary`.

Runde „Auslieferung und Karten-Dialoge“:

- **`main.py` von 11 071 auf 10 961 Zeilen:** Die Auslieferung der Oberfläche (Datei-Mounts, `manifest.json`,
  `sw.js`, `sw-register.js`, `index.html` und der Router-Catch-all) liegt in `backend/app/api/frontend_routes.py`;
  `register_frontend(app)` wird an derselben Stelle aufgerufen wie vorher, der Catch-all bleibt zuletzt. Die Grenze
  im Größenbudget ist von 11 075 auf 11 000 gesenkt.
- **Gehashte Build-Dateien bleiben im Browser:** `/assets/*` trägt jetzt `Cache-Control: public, max-age=31536000,
  immutable` — der Inhalts-Hash steht im Dateinamen, ein anderer Inhalt bekommt einen anderen Namen. Bilder, Symbole
  und Schriften (ohne Hash im Namen) bekommen einen Tag, `index.html` bleibt bei `no-cache, must-revalidate`.
  Damit entfallen beim zweiten Aufruf über Tailscale die Rückfragen für jeden Baustein. Neuer Test:
  `backend/tests/integration/test_static_asset_cache_headers.py` (Kopfzeile, 404, Mount der echten App).
- **`PrinterCard.tsx` von 6 255 auf 5 711 Zeilen:** Firmware- und Bearbeiten-Dialog liegen in
  `frontend/src/pages/PrinterCardModals.tsx` (569 Zeilen); die Karte importiert sie unverändert. Grenze im
  Größenbudget von 6 300 auf 5 750 gesenkt. Importe, die nur die Dialoge brauchten, sind mitgewandert.
- **Werkseinstellungen mit Sicherung:** `backend/app/services/factory_reset.py` sichert Datenbank und Konfiguration
  in eine ZIP-Datei, verschiebt alle Daten nach `data/reset-<Zeitstempel>/` (nichts wird gelöscht) und legt ein leeres
  Schema an; ein unterbrochener Lauf wird beim Start vor `init_db` zu Ende geführt. Neue Routen
  `GET/POST /system/factory-reset` (nur mit eingeschalteter Anmeldung, Bestätigung durch getipptes
  `ZURÜCKSETZEN`), Karte in **Einrichtung** und **Wartung → System**, 8 Backend- und 4 Frontend-Tests.
- **Einrichtung an einer Stelle:** neue Seite **/einrichtung** in der Seitenleiste („Einrichtungsassistent“) mit
  Assistent, Checkliste und Werkseinstellungen; vorher war das nur im Status-Reiter der Wartung zu finden.
- **Anleitung Punkt für Punkt:** `docs/ERSTEINRICHTUNG.md` führt von der Installation über Anmeldung, Drucker,
  Material, Meldungen, Sicherung, Updates und Fernzugriff bis zum ersten Druck — je Schritt mit Ziel, Handlung,
  Erwartung und Abbruchkriterium; dazu der Reset mit Zurückholen.
- **13 neue Texte in allen 15 Sprachen** (`factoryReset.*`); die Übersetzungsprüfung erkennt jetzt auch
  Großbuchstaben-Token außerhalb von A–Z (die Bestätigungsphrase `ZURÜCKSETZEN`).
- **Zwei veraltete TODO-Kommentare entfernt:** „TODO: translate encryption keys“ stand noch in sechs
  Sprachdateien, obwohl die Schlüssel längst übersetzt sind; der Fortschrittsbalken in `QueuePage.tsx` trägt kein
  „TODO: integrate with WebSocket“ mehr (die Werte kommen dort schon live aus der Druckerabfrage).

## Erledigt am 30.10.2026 (in v1.19.0 und v1.20.0 veröffentlicht)

Alle Befunde F1–F10 aus `docs/ANALYSE-2026-10-30.md` sind behoben (Plattenwechsel fail-closed bei Temperatur und
Tür, Aufräumen der Fehlerbilder, Magazin-Änderung ohne Teilwirkung, Einstellungen je Drucker, KI-Haushalt,
Geldrechnung in Cent) und die Verbesserungen 1–12 umgesetzt (u. a. `requirements.lock`, KI-Trefferquote je
Fehlerbild, Abbrechen im Assistenten, Filter der Fehlerbild-Sammlung). **Alle acht Erweiterungen sind umgesetzt:**
Trainingsset-Export, KI-Hinweis als eigene Meldung, öffentlicher Angebots-Link mit Zusage/Ablehnung, Zeitraffer-MP4
aus aufbewahrten Schichtbildern, automatische Umverteilung, XRechnung-XML, Nachbestellvorschlag und der
Einmess-Assistent für den Plattenwechsel. Details und Grenzen im `CHANGELOG.md`.

**Aufräumrunde danach (in v1.19.0 enthalten):**

- `_select` im Druckplaner ist nur noch eine Schleife; die beiden Zweige liegen als `_select_pinned` und
  `_select_for_model` daneben, die `continue` der Auftragsschleife sind `return` geworden.
- Alle 43 stillen `except Exception: pass` protokollieren jetzt mit `logger.debug(..., exc_info=True)`;
  das Budget in `test_error_handling_budget.py` steht auf **0**.
- Fehlerhilfe: Abstand und Höchstzahl je Druck sind in der Karte einstellbar; der Server lehnt
  „zu warm“ ≥ „zu kalt“ ab (geprüft auf der zusammengeführten Konfiguration, weil die Karte immer nur
  ein Feld schickt). Zwei neue Schlüssel in allen 15 Sprachen.
- `PrintersPage.tsx` von 9 656 auf 1 985 Zeilen: `PrinterCard.tsx` (6 255), `PrinterCardParts.tsx`
  (1 134, nur Komponenten) und `printerCardHelpers.ts` (290, Konstanten/Typen/reine Funktionen).
- `client.ts` von 9 699 auf 1 009 Zeilen: `core.ts` (270), `types.ts` (4 754), `endpoints.ts` (4 017);
  `client.ts` exportiert alles weiter, kein Import in der Oberfläche musste geändert werden.
- `Dockerfile` installiert jetzt mit `-c requirements.lock` — das Image war der letzte Ort ohne feste
  Versionen. Bauen ließ es sich hier nicht (kein Docker auf dem Rechner).
- Neues Glossar für die Gegenleser: `docs/UEBERSETZUNG-GLOSSAR.md` (Begriffe, Satzvorlagen, Prüfliste).

## Festgelegt (02.11.2026)

Releases werden gebündelt (höchstens ein Minor-Release pro Woche, davor Abnahme am Pi); Version, Tag und Release macht
genau eine Sitzung nach ausdrücklichem OK und grüner CI (`docs/VERSIONING.md`). Nächste Entwicklungsrichtung nach der
Abnahme: technische Schulden (siehe „Technisch offen“), dann KI und Fehlerhilfe am Gerät.

## Offen, nur mit deiner Hand oder echter Hardware

Am Gerät in einer Sitzung abarbeiten: [`docs/ABNAHME-PI.md`](docs/ABNAHME-PI.md) — Update, Angebots-Link, Hardware in
dieser Reihenfolge, mit Erwartungen, Abbruchkriterien und Protokoll.

- [x] **Signaturschlüssel erzeugen** und Tags signieren (`~/.ssh/printlab_signing.pub`, `data/update_allowed_signers`, Tag `v1.23.0` signiert).
- [ ] **GitHub-Konto absichern:** Passkey/2FA, alte Tokens widerrufen, Regelsatz für Branch und Tags.
- [ ] **Sicherung nach außen:** USB-Stick oder NAS als `PRINTLAB_BACKUP_TARGET` eintragen (`docs/INSTALLATION-PI.md`).
- [ ] **Meldeweg** für Ausfälle (Telegram oder ntfy) in `~/.config/printlab.env` eintragen.
- [ ] **HTTPS-Zertifikate** in der Tailscale-Verwaltung einschalten, dann „HTTPS einschalten" in PrintLab.
- [ ] **SSD** statt SD-Karte für den Pi (Warnung erscheint unter Wartung → Zustand des Geräts).
- [ ] **Hardware abnehmen:** Tür-Servo mit Endschaltern, Not-Halt, Slicer über Tailscale, Kamera-Einmessung an echten
      Fotos (Checkliste in `docs/ABNAHME-PI.md` Abschnitt 3, Mechanik in `docs/ABNAHME.md`).
- [ ] **Plattenwechsel:** Mit dem Einmess-Assistenten die Positionen an der echten Mechanik aufnehmen und daraus
      die Bewegungsfolge ableiten; erst nach Probelauf `swap` freigeben. Eine begonnene, nicht abgeschlossene
      Einmessung sperrt den Wechsel bereits (auch die Automatik). Ablauf: `docs/ABNAHME-PI.md` Abschnitte 3.2–3.5.
- [x] **E-Rechnung (XRechnung 3.0 & ZUGFeRD-Hybrid-PDF):** Pflichtfelder `BT-49`, `BT-72`, `BT-146` sowie `embed_zugferd_xml()` (`/zugferd.pdf`) implementiert und im Durchstich geprüft; vor Erstversand noch mit Steuerberatung gegenprüfen.
- [ ] **Angebots-Link und Nachbestellvorschlag erproben:** Link auf dem Mobilgerät öffnen und beantworten
      (`docs/ABNAHME-PI.md` Abschnitt 2); Lieferantenpreise pflegen und den Vorschlag gegen den tatsächlichen Verbrauch
      prüfen (auch im Spoolman-Betrieb).
- [ ] Übersetzungen der 13 Nebensprachen von Muttersprachlern gegenlesen lassen.

## Technisch offen

- [ ] Große Dateien weiter zerlegen; der Test `test_file_size_budget.py` verhindert nur das Wachsen. Stand
      05.11.2026: `main.py` 4 153 Zeilen (Grenze 4 175; die Abflüsse liegen in neun Dienstmodulen: timelapse,
      spool_linkage, history_runtime, background_services, expected_prints, mqtt_status_flow, print_start_flow,
      completion_photo_plate, print_complete_flow), `print_scheduler.py` 3 928 Zeilen (Grenze 3 950;
      Verfügbarkeit- und Wecker-Logik in `scheduler/availability.py`), `queue_pass.py` 582 (Vorgabe 2 600,
      Auswahl in `selection.py`, 483), `PrintersPage.tsx` 1 614 (Grenze 1 650, Leiste in `PrinterToolbar.tsx`, 497),
      `PrinterCard.tsx` 5 232 (Grenze 5 300, Dialoge in `PrinterCardModals.tsx`, 1 225, Bausteine in
      `PrinterCardParts.tsx`, 1 134, Grenze 1 150), `client.ts` 1 016 (Grenze 1 050),
      `types.ts` 19 Zeilen (Grenze 400; die API-Typen liegen nach Bereichen in `types_*.ts`),
      `endpoints.ts` 4 005 (Grenze 4 050).
      **Nächster Schnitt:** (1) `main.py`-Rest: `on_print_complete` (1 560) und `on_print_start` (1 429) sind die
      letzten Riesen; ihre Hintergrund-Aufgaben sind Nestlinge (Closures) und wandern mit dem Abschluss-Kontext —
      vor dem Auslagern gehört eine Zustandsübergabe-Reinigung. `calibrate_snapshot` und `on_tray_change` sind
      Nestlinge in `lifespan` (695).
- [ ] ArchivesPage.tsx: 4 937 Zeilen, Grenze 4 950 (der Bruch von 4 925 war schon auf HEAD da); F1d senkt sie
      wieder — Kartenauswahl auslagern wie `PageHeader`/`PrinterCardModals`.
- [ ] Volle E2E-Prüfung MakerWorld → PC-Slicer → Warteschlange. Die inneren Glieder sind abgesichert
      (566 Integrationstests zu MakerWorld, Bibliothek und Warteschlange, alle grün); der Slicer-Upload und der
druckende Drucker brauchen Gerät und Slicer.
- [x] Komplette Backend-Suite in der CI — `ci.yml` fährt `pytest tests/` in vier Shards (`pytest-split`),
      zusätzlich noch einmal im Docker-Testabbild. `requirements.lock` wird beim Docker-Bau benutzt und ist damit
      geprüft.
- [x] Stille `except Exception: pass`-Handler abbauen — erledigt, Budget steht auf 0.
- [ ] Docker-/ARM-Image auf einem Pi 4/5 starten und prüfen. Das `Dockerfile` ist statisch geprüft und
      installiert jetzt mit `-c requirements.lock`; auf diesem Rechner gibt es kein Docker, deshalb ungetestet.
- [ ] Fehlerhilfe: die zwölf Fließtexte der Fehlerbilder von Muttersprachlern übersetzen lassen (Titel und Kurzfassungen
      sind englisch hinterlegt). Glossar und Prüfliste: `docs/UEBERSETZUNG-GLOSSAR.md`. Die Schwellen **und** die
      Grenzen (Abstand, Höchstzahl je Druck) sind in der Oberfläche einstellbar; der Server prüft, dass „zu warm“
      unter „zu kalt“ liegt.
- [ ] Fehlerhilfe am Gerät erproben: die beiden Bauraum-Regeln im Trockenlauf gegen einen echten PLA- und ABS-Druck
      laufen lassen, bevor der Trockenlauf abgeschaltet wird.
- [ ] KI-Fehlererkennung am Gerät erproben (Bildmodell auf dem Pi, Latenz messen) und ein kleines Vision-Modell
      empfehlen; Treffer mit echten Fehlerbildern gegenprüfen, bevor die automatische Prüfung eingeschaltet wird.

## Bewusst nicht im Fokus

- Cloud-Steuerung der Drucker und Kopplung der Bambu-Handy-App: deren QR-Code und PIN laufen über die Bambu-Cloud und
  lassen sich nicht nachbauen. Von unterwegs nutzt man PrintLab im Browser über Tailscale.
- PV-/Tarifsteuerung, Kiosk, Drucker-Simulator, verschlüsselte Sicherung.

## Start (Windows-Entwicklung)

```powershell
cd C:\Users\lukas\OneDrive\Desktop\Bambuddy-Fork
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --loop asyncio
.venv\Scripts\python.exe werkzeuge\lokal_pruefen.py        # alles prüfen, was die CI prüft
```
