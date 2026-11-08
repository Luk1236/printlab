# Changelog

Alle nennenswerten Änderungen an PrintLab. Versionsschema: siehe `docs/VERSIONING.md`.
PrintLab baut auf Bambuddy 1.2.5.7 auf (Herkunft und Lizenz: `NOTICE`).

## v2.0.48 (08.11.2026) — Spülmengen-Minimierer & Druckbett-Schadenszonen-Sperre (Phase 19)

- **Spülmengen-Minimierer & G-Code Farbwechsel-Optimierer (`backend/app/services/purge_optimizer.py`, `POST /api/v1/fleet/purge-optimize`):**
  - Analysiert Werkzeug- und Farbwechsel (T0, T1...) im G-Code und berechnet dynamische Spülmengen-Reduktion (Flush-Multiplikator von 1.0 auf 0.65).
  - Purge-to-Infill Filter: Leitet bis zu 40% des verbleibenden Farbwechsels in das Bauteil-Infill um, spart bis zu 60% Spülmüll und mehrere Euro Filament pro Mehrfarb-Auftrag.
- **Druckbett-Schadenszonen-Sperre & PEI Exclusion Zones (`backend/app/services/auto_nesting.py`, `POST /api/v1/fleet/auto-nest`):**
  - Guillotine-Bin-Packer mit Sperrzonen-Ausschnitt (`_carve_exclusion_zones`): Verhindert die Platzierung von Bauteilen auf beschädigten, zerkratzten oder abgelösten PEI-Druckbettbereichen.
  - Mathematische Kollisions- und Sperrzonen-Verifikation (`verify_no_exclusion_collisions`).

## v2.0.47 (08.11.2026) — Abrasive Filament Wear Predictor & AMS Taupunkt-Trocknungswächter (Phase 18)

- **Abrasive Filament Wear Predictor (`backend/app/services/wear_predictor.py`, `POST /api/v1/maintenance/wear/forecast`):**
  - Präzise Vorausberechnung der beschleunigten Abnutzung von Druckdüsen, Extruder-Zahnrädern und PTFE-Führungsschläuchen durch abrasive Füllstoffe (PA-CF 6x, PETG-CF 5x, PLA-CF/GF 5x, Glow 4x, Holz 2x).
  - Früherkennung vor Druckauftragsstart: Verhindert Düsenverschleiß-Abbrüche bei langen Druckaufträgen und sperrt unzulässige Messingdüsen bei abrasivem Filament.
- **AMS Taupunkt- & Feuchtigkeitswächter (`backend/app/services/humidity_guard.py`, `POST /api/v1/maintenance/ams/drying-guard`):**
  - Psychrometrische Taupunkt- und Kondensationsrisikoberechnung nach der Magnus-Formel aus AMS-Temperatur und relativer Feuchte.
  - Materialspezifische Feuchtigkeitsüberwachung für hygroskopische Filamente (PA max. 20 %, TPU max. 25 %, PVA/BVOH max. 15 %, PETG max. 35 %) mit gezielten Trocknungsempfehlungen (Temperatur in °C und Dauer in Stunden).
- **Integrierter Druckauftrag-Preflight-Check (`POST /api/v1/maintenance/preflight-check`):**
  - Kombinierte Vorab-Prüfung vor dem Absenden an die Druckfarm: Stellt sicher, dass das geladene Material ausreichend trocken ist und die Düse über die gesamte geplante Druckzeit standhält.

## v2.0.46 (08.11.2026) — Raspberry Pi 7" Touch-Kiosk Modus & SD-Card Wear Guard (Phase 17)

- **Raspberry Pi 7" Touch-Kiosk-Modus (`backend/app/api/routes/kiosk.py`, `frontend/src/pages/KioskModePage.tsx`):**
  - Große, handschuh- und touchscreen-optimierte Bedienoberfläche für Werkstatt- und Standalone-Displays.
  - Not-Halt (E-Stop) mit zweistufiger Bestätigungssperre (`POST /api/v1/kiosk/printers/{id}/quick-action?action=e_stop`).
  - Ein-Klick-Aktionen: Druckbettfreigabe (`plate_clear`), Kammerlicht umschalten (`toggle_light`), Vorheiz-Presets (PLA, PETG, ABS, ASA, TPU, Cooldown) und AMS-Spulenrescan (`ams_sync`).
- **SD-Card Wear Guard & /dev/shm RAM-Disk Pufferung (`backend/app/services/pi_sd_wear_guard.py`):**
  - Automatische Verlagerung flüchtiger I/O-Schreiblasten (Live-Webcam Einzelbilder, Zeitraffer-Renderframes, Slicer-Uploads) in den Linux tmpfs Arbeitsspeicher (`/dev/shm/printlab`).
  - Schont die MicroSD-Karte des Raspberry Pi vor Speicherzellen-Verschleiß und verhindert I/O-bedingte System-Hänger.
  - Statistiken und RAM-Disk Überwachung über `GET /api/v1/kiosk/sd-guard/stats`.

## v2.0.45 (08.11.2026) — ZUGFeRD 2.2 / Factur-X Hybrid PDF & DATEV EXTF Buchungsstapel-Export (Phase 16)

- **Amtlicher DATEV EXTF Buchungsstapel (CSV) Export (ackend/app/services/accounting_export.py, ackend/app/api/routes/accounting.py):**
  - Vollständige Unterstützung der amtlichen DATEV-Schnittstellendefinition (Format 700 / Version 12) für Steuerkanzleien und DATEV Unternehmen online.
  - Vorkonfigurierte Kontenrahmen SKR03 (Erlöskonten 8400, 8300, 8100, Forderungen 10000) und SKR04 (Erlöskonten 4400, 4300, 4100, Debitoren 10000).
  - Automatische Ermittlung von Bruttoumsatz, Soll/Haben-Kennzeichen, Belegdatum (TTMM), Belegfeld 1 (Rechnungsnummer) und Buchungstext sowie Vorab-Summenkontrolle (GET /api/v1/accounting/datev-preview).
- **Hybride E-Rechnung ZUGFeRD 2.2 / Factur-X (PDF/A-3):**
  - Generierung von maschinenlesbaren Hybrid-PDFs mit eingebettetem actur-x.xml (Profil EN 16931 / Comfort) im PDF/A-3 Dateistrom (GET /api/v1/accounting/invoices/{id}/zugferd-pdf).
  - Vollständige Gesetzeskonformität zur E-Rechnungspflicht ab 01.01.2025 im deutschen B2B-Geschäftsverkehr.

## v2.0.44 (08.11.2026) — Live Customer Tracking Portal & Volume Tier Pricing (Phase 15)

- **Echtzeit-Tracking-Portal für Kunden (`backend/app/services/customer_tracking.py`, `backend/app/api/routes/customer_tracking_route.py`):**
  - Öffentliche Auftragsverfolgung über fälschungssichere HMAC-SHA256 Tracking-Tokens (`GET /api/v1/portal/tracking/{token}`) ohne Benutzer-Login.
  - Mehrstufige visuelle Fortschrittsanzeige (`RECEIVED`, `QUEUED`, `PRINTING`, `POST_PROCESSING`, `QUALITY_CHECK`, `DISPATCHED`) mit Live-Schicht, Restzeit, Druckermodell und Sendungsverfolgungsnummer (DHL / DPD / UPS).
- **Dynamische Mengenstaffel-Berechnung (Volume Tier Pricing):**
  - 5-Stufen-Rabattmatrix für B2B- und Serienfertigung (1–9: 0 %, 10–49: 10 %, 50–99: 18 %, 100–249: 25 %, 250+: 32 %).
  - Transparente Ersparnisanzeige (`savings_eur`) und Staffelübersicht (`tiers_overview`) für Kunden im Sofortkalkulator.
- **Nachbearbeitungs-Optionen & 24h-Expressfertigung:**
  - Konfigurierbarer Katalog für Stützstrukturentfernung, thermische Gewindeeinsätze (M2–M6), Oberflächenfeinschliff und Ofen-Tempern.
  - 24h-Expressfertigung mit Prio-Warteschlange an der Spitze der Druckfarm (`express_24h`).
  - Endpunkte: `GET /api/v1/portal/pricing/options`, `POST /api/v1/portal/pricing/calculate-tiers`, `POST /api/v1/portal/tracking/token`.

## v2.0.43 (08.11.2026) — B2B & ISO-9001 Qualitätszertifikat PDF & Auto-Skip Defekt-Ausschluss (Phase 14)

- **DIN A4 ISO-9001 Werks- und Qualitätsprüfzertifikat (`backend/app/services/quality_certificate.py`, `backend/app/api/routes/quality.py`):**
  - Automatisierte PDF-Generierung für Industrie- und B2B-Kunden nach DIN EN 10204 2.1 / ISO-9001.
  - Enthält Druckparameter (Druckzeit, Schichtdicke, Filamentcharge, Nozzle-Ø, Betttemperatur), Qualitätsindex-Score (0–100), Güteklasse (A+, A, B, C), First-Layer-Score, Temperaturabweichung, kryptografischen SHA-256 Prüfhash und QR-Code zur Verifizierung.
  - Endpunkte: `POST /api/v1/quality/certificate/preview`, `POST /api/v1/quality/certificate/pdf`, `GET /api/v1/quality/certificate/{archive_id}/pdf`.
- **Echtzeit-Ausschluss defekter Einzelteile auf dem Druckbett (`backend/app/services/auto_skip_objects.py`):**
  - 2D-Objekt-Mapping von optisch oder per Sensor erkannten Fehlerkoordinaten (`defect_x_mm`, `defect_y_mm`) auf die Bounding-Boxen der platzierten Druckobjekte.
  - Bambu Lab MQTT-Befehlsinjektion (`skip_objects([id])`) zur selektiven Fortsetzung des Restdrucks ohne Abbruch der gesamten Bauplatte.
  - Endpunkte: `POST /api/v1/quality/printers/{printer_id}/skip-objects`, `POST /api/v1/quality/printers/{printer_id}/detect-and-skip`.

## v2.0.42 (08.11.2026) — Raspberry Pi Boot-Crash-Fix (Ollama LLM-Warmup-Sperre & Tailscale-Persistenz)

- **Kein automatisches Ollama-LLM-Warmup mehr beim Systemstart (`backend/app/services/assistant_autoconfig.py`):**
  - `ensure_on_startup()` hat bisher bei jedem Start von PrintLab automatisch `await warmup()` (`POST /api/generate`) an Ollama gesendet und dadurch ein 3B–8B-Sprachmodell (2,5–4,5 GB RAM + 100 % Last auf allen 4 CPU-Kernen) sofort nach dem Booten in den Arbeitsspeicher geladen. Das führte wenige Sekunden nach dem Start von `printlab.service` zum sofortigen OOM-/Spannungs-Absturz des Raspberry Pi.
  - Das automatische Vorladen beim Booten ist jetzt standardmäßig deaktiviert (nur noch auf explizite Anforderung über `PRINTLAB_ASSISTANT_WARMUP=1`).
- **Halbierung der Slicer-Sidecar-Threads beim Start (`backend/app/services/builtin_slicer.py`):**
  - `ensure_builtin_slicer_running()` startet standardmäßig nur noch eine Sidecar-Instanz (`Port 3001`) statt zwei redundanter Uvicorn-Server (`3001` und `3003`).
- **Tailscale bleibt bei Dienst-Neustarts online (`backend/app/services/lifespan_flow.py`, `werkzeuge/pi_neu_installieren.sh`, `werkzeuge/pi_absturzschutz.sh`):**
  - `stop_background_services()` beendet das abgekoppelte `tailscaled` (`start_new_session=True`) beim Neustart von PrintLab nicht mehr, und `KillMode=process` in `printlab.service` verhindert, dass systemd den Tailscale-Daemon beim Neustart von PrintLab mitbeendet.
  - `pi_absturzschutz.sh` begrenzt zudem eine eventuell installierte `ollama.service`-Instanz (`OLLAMA_KEEP_ALIVE=2m`, `OOMScoreAdjust=500`).

## v2.0.41 (08.11.2026) — 2D Auto-Nesting, 3D-Orientierungs-Analyse, M486-Injektor & Farm-Seriensplit (Phase 13)

- **Kollisionsfreies 2D-Multi-Plate-Bin-Packing (`backend/app/services/auto_nesting.py`, `POST /api/v1/fleet/auto-nest`):**
  - Guillotine-Bin-Packer (Best-Short-Side-Fit) mit automatischer $90^\circ$-Rotationsoptimierung für beliebige Stückzahlen und Bauteiltypen auf eine oder mehrere Bauplatten ($256 \times 256\,\text{mm}$).
  - Mathematische Kollisionsfreiheits-Garantie (`verify_no_collisions`), Plattenauslastung in Prozent, Filamentbedarf und Druckzeit pro Platte sowie automatische Erkennung übergroßer Bauteile (`oversized_parts`).
- **Paralleler Farm-Seriensplit (`split_batch_across_fleet`, `POST /api/v1/fleet/batch-split`):**
  - Verteilt die gepackten Bauplatten einer Großserie automatisch per Longest-Processing-Time-First (LPT) auf alle geeigneten, freien Farm-Drucker (passendes Material, Farbe, Düsendurchmesser) und berechnet den realen Speedup-Faktor (`speedup_factor`).
- **Optimale 3D-Druckausrichtung (`suggest_optimal_orientation`, `POST /api/v1/fleet/orientation-check`):**
  - Bewertet alle 6 orthogonalen Ausrichtungen anhand von Betthaftungsfläche, Kippsicherheit (Schwerpunkthöhe) und Überhanganteil.
- **G-Code `M486` Object-Exclusion-Injektor (`inject_m486_object_markers`, `POST /api/v1/fleet/gcode-m486`):**
  - Analysiert Slicer-G-Code und injiziert fehlende `M486 T<count>` / `M486 S<idx>` / `M486 S-1` Marker für das gezielte Überspringen einzelner fehlerhafter Bauteile während des Drucks.

## v2.0.40 (08.11.2026) — Raspberry Pi OOM-Absturzschutz beim Update & systemd Auto-Restart-Härtung

- **Vermeidung von OOM-Kernel-Freezes bei In-App-Updates (`backend/app/api/routes/updates.py`):**
  - `_perform_update` überspringt `npm install` und `npm run build` (`vite build`) auf dem Zielgerät automatisch, sobald das vorab gebaute Frontend (`static/index.html`) bereits im Repository liegt (optional erzwingbar über `PRINTLAB_FORCE_FRONTEND_BUILD=1`).
  - Verhindert den >2,5-GB-RAM-Peak beim Kompilieren von >3.000 Vite-Modulen auf dem Raspberry Pi sowie das Löschen von `static/` (`emptyOutDir`) bei einem Abbruch mitten im Build.
- **Zuverlässiger Git-Tag-Fallback bei Updates (`backend/app/api/routes/updates.py`):**
  - Doppeltes `return None` im `HTTPError`-Fallback von `_discover_target_release` entfernt und automatischen Fallback auf `_git_tag_releases()` ergänzt, wenn GitHub `/releases` eine leere Liste oder `404` liefert.
- **Automatischer Neustart nach Boot & Absturz (`werkzeuge/pi_neu_installieren.sh`, `werkzeuge/pi_absturzschutz.sh`, `werkzeuge/ueberwachung.py`):**
  - `loginctl enable-linger` wird sowohl bei der Installation als auch im Absturzschutz-Skript aktiviert, damit `systemd --user` den Dienst `printlab.service` und `printlab-watch.timer` beim Booten ohne offene SSH-Sitzung startet.
  - `StartLimitIntervalSec=0` und `OOMScoreAdjust=-200` in `printlab.service` sowie Drop-In `restart.conf` für User- und System-Units eingetragen, damit systemd nach mehreren Startfehlern nicht dauerhaft in `start-limit-hit` stehen bleibt.
  - `systemctl --user reset-failed printlab.service` vor jedem Neustart in `werkzeuge/ueberwachung.py` ergänzt.
  - Kernel-Sysctl (`vm.oom_kill_allocating_task=1`, `kernel.softlockup_panic=1`, `kernel.hung_task_panic=1`) in `werkzeuge/pi_absturzschutz.sh` verschärft, damit der Pi bei Speicherknappheit nicht im SD-Swap-Thrashing einfriert.

## v2.0.39 (08.11.2026) — Finaler Gesamttest & Exzellenz-Zertifizierung aller 10 Domänen (Phase 12)

- **Vollständige Verifikation aller 12 Ausbauphasen (v2.0.28 bis v2.0.39):**
  - **Backend-Zertifizierung:** 82/82 Phasen-Tests (Slicer-Cache, Presets, AMS Spool Auto-Fallback, GPIO-Hardware/Not-Halt, KI-Schichtanalyse, Kundenportal 2.0, Flottenmanagement, E2E-Benchmarks, Dateigrößen-Budgets) in 13,9s grün.
  - **Frontend- & WCAG 2.1 AA-Zertifizierung:** 43/43 Vitest-Assertions (useFocusTrap, ConfirmModal, AlertModal, PreviewModalShell, PrinterMovementPopover) in 2,87s grün; 199 Produktions-Bundles Safari-16.0-Baseline-konform.
  - **Durchstich-Abnahme (bnahme.py --nur-durchstich):** Alle 5 End-to-End-Stufen (Angebots-Link & XRechnung, Hardware-Trockenlauf & Not-Halt, Einmess-Assistent & Plattenwechsel, Kamera-Einmessung & Leerbett-Erkennung, Integrierter Slicer STL/3MF -> G-Code) mit 0 Fehlern und 0 Hinweisen bestanden.
  - **Statische Build-Hash-Synchronisation:** static/BUILD_SOURCE_SHA nach CRLF-Normalisierung festgeschrieben.

## v2.0.38 (08.11.2026) — E2E Integration, WebSocket-Parallelauslieferung & Performance-Benchmarks (Phase 11)

- **Paralleler WebSocket-Fanout & Slow-Client-Isolierung (`backend/app/core/websocket.py`):**
  - Umstellung von `ConnectionManager.broadcast()` und `broadcast_to_user()` von sequenzieller Auslieferung unter `self._lock` auf paralleles `asyncio.gather()` außerhalb des Verbindungs-Locks.
  - Pro-Client Sende-Timeout (`send_timeout=2.0s` via `asyncio.wait_for`), sodass langsame oder hängende TCP-Clients weder den Broadcast noch neue `connect`/`disconnect`-Vorgänge blockieren.
  - Automatische Bereinigung abgebrochener oder in ein Timeout gelaufener Sockets sowie Echtzeit-Latenzmessung (`last_broadcast_ms`, `avg_broadcast_ms`, `max_broadcast_ms`, `dropped_connections`).
- **Echtzeit-Telemetrie-Endpunkt (`GET /api/v1/fleet/metrics`):**
  - Neues Schema `FleetMetricsResponse` (`backend/app/schemas/fleet.py`) und Route in `backend/app/api/routes/fleet.py` sowie Frontend-Client `getFleetMetrics()` in `frontend/src/api/hardware_endpoints.ts`.
- **Präziseres Farb-Matching im Flotten-Load-Balancer (`backend/app/services/fleet_load_balancer.py`):**
  - Differenzierung zwischen exaktem Material- + Farb-Treffer (`+25.0` Punkte) und reinem Material-Treffer bei abweichender Spulenfarbe (`+15.0` Punkte).
- **E2E-Integrations- & Performance-Benchmark-Suite (`backend/tests/unit/test_e2e_and_performance_benchmarks.py`):**
  - **WebSocket-Stresstest:** 100 parallele Clients + 2 fehlerhafte/hängende Clients in <250ms inkl. automatischer Eviction.
  - **Load-Balancer-Benchmark:** Vollständiges Fitness-Scoring und Dispatching über 50 Farm-Drucker in <50ms.
  - **E2E-Dokumentenpipeline:** Binäres STL -> 3D-Mesh-Analyse -> Sofort-Kalkulation -> DIN A4 Lieferschein-PDF + 2 Thermo-Versandetiketten (`100x150` & `62x29`) in <1.5s.
  - **E2E-Flotten-API-Workflow:** WebSocket-Broadcast -> Fleet Overview -> Batch-Pause nach Standort -> Metrik-Verifikation.

## v2.0.37 (08.11.2026) — Erweitertes Drucker-Flottenmanagement & Batch-Steuerung (Phase 10)

- **Echtzeit-Flottenübersicht (`GET /api/v1/fleet/overview`):**
  - Aggregierte Live-Kennzahlen über alle aktiven Drucker (`total_printers`, `online_printers`, `printing_count`, `paused_count`, `idle_count`, `maintenance_count`, `hms_error_count`).
  - Detaillierte Job-Zusammenfassung (`FleetJobSummary`) für alle laufenden Druckaufträge inklusive Fortschritt, verbleibender Druckzeit, aktuellem Layer und Standort-Gruppierung (`locations`).
- **Batch-Kommandosteuerung über die gesamte Flotte (`POST /api/v1/fleet/command`):**
  - Unterstützung für flottenweite Sammelaktionen: `pause`, `resume`, `stop`, `emergency_stop` (inkl. `M112`), `chamber_light_on`, `chamber_light_off`, `maintenance_enter` und `maintenance_exit`.
  - Flexible Zielauswahl über explizite `printer_ids` oder Standortfilter (`location`), mit detaillierter Ergebnisrückmeldung (`succeeded`, `failed`, `skipped`).
- **Synchrone Flotten-Telemetrie-Aktualisierung (`POST /api/v1/fleet/sync`):**
  - Erzwingt sofortige Status-Updates über `printer_manager.request_status_update` für alle aktiven Drucker der Farm.
- **Pydantic-Schemas & Frontend-API-Anbindung:**
  - Neues Schema-Modul `backend/app/schemas/fleet.py` (`FleetCommandRequest`, `FleetCommandResponse`, `FleetCommandResultItem`, `FleetJobSummary`, `FleetOverviewResponse`).
  - Frontend-Integration in `frontend/src/api/hardware_endpoints.ts` (`getFleetOverview`, `executeFleetCommand`, `syncFleetTelemetry`).
- **Tests & Qualitätssicherung:**
  - Neue Unit-Test-Suite `backend/tests/unit/test_fleet_routes.py` für Flottenübersicht, Pause/Resume-Batch, Not-Halt (`M112`), Bauraumlicht, Wartungsmodus und Telemetrie-Sync (100% grün).

## v2.0.36 (08.11.2026) — Vollständige Barrierefreiheit & WCAG 2.1 AA Audits (Phase 9)

- **Zentraler Focus-Trap & Keyboard-Management Hook (`useFocusTrap.ts`):**
  - **Fokus-Einschluss (Focus Trap):** Verhindert das Ausbrechen von Tab und Shift-Tab Navigation in den Hintergrundbereich während geöffnete Dialoge aktiv sind (WCAG 2.1.2 No Keyboard Trap).
  - **Escape-Key Handler:** Globales und kontextsensitives Schließen von Modals über Escape mit vollständiger Scroll-Verriegelung des `body`-Elements (`overflow: hidden`).
  - **Automatischer Fokus & Rücksprung:** Automatisches Fokussieren des ersten interaktiven Elements beim Öffnen und zuverlässige Rückführung des Tastaturfokus auf das auslösende Element beim Schließen (WCAG 2.4.3 Focus Order).
- **Semantische ARIA-Überarbeitung aller Kern-Modals:**
  - **`ConfirmModal.tsx`:** Dynamische Rollenvergabe (`role="alertdialog"` für Warnungen/Gefahren, `role="dialog"` für Standard), `aria-modal="true"`, `aria-labelledby="confirm-modal-title"` und `aria-describedby="confirm-modal-description"`.
  - **`AlertModal.tsx`:** Barrierefreier Hinweisdialog mit `role="alertdialog"`, `aria-modal="true"`, dedizierten Titel- und Beschreibungs-IDs sowie automatischer Fokusführung.
  - **`PreviewModalShell.tsx`:** Vollständige Barrierefreiheit für alle Datei- und 3D-Viewer (3D-Model, G-Code, PDF, Spreadsheet, Image) inklusive Screen-Reader-Titel und Vollbild-Tastaturbehandlung.
- **Barrierefreiheit im Kundenportal (`CustomerPortalPage.tsx`):**
  - **Barrierefreie Dropzone:** Umwandlung der 3D-Upload-Zone in ein vollwertiges Tastatur-Bedienelement mit `role="button"`, `tabIndex={0}`, `aria-label` und Enter/Leertaste-Aktivierung.
  - **Screen-Reader-Unterstützung für Regler und Auswahlen:** Infill-Slider mit `aria-valuemin`, `aria-valuemax`, `aria-valuenow`, `aria-label`; Material- und Mengenstaffelknöpfe mit dynamischem `aria-pressed`.
- **Barrierefreiheit der Drucker-Achsensteuerung (`PrinterMovementPopover.tsx`):**
  - Jog-Popover als eigenständiger Dialog mit `role="dialog"`, `aria-haspopup="dialog"`, `aria-expanded` und `aria-pressed` für Schrittweiten-Buttons (1/10/50mm).
- **Test-Suite & Qualitätssicherung:**
  - Neuer Test-Satz `useFocusTrap.test.tsx`: 7 Unit-Tests zur Verifizierung von Fokus-Einschluss, Tab-Wrapping, Shift-Tab, Escape, Scroll-Lock und Fokus-Wiederherstellung.
  - Erweiterung von `ConfirmModal.test.tsx`: 20/20 Tests zur Verifizierung von ARIA-Attributen und Tastatur-Navigation.
  - 6/6 Tests für `PrinterMovementPopover.test.tsx` und 4/4 Tests für `AlertModal.test.tsx`.

## v2.0.35 (08.11.2026) — Code-Modularisierung der Monolithen & Dateigrößen-Budgets (Phase 8)

- **Modularisierung von library.py (Backend-Bibliotheksverwaltung):**
  - Reduzierung des Monolithen von 6.094 Zeilen auf 3.975 Zeilen (-2.119 Zeilen, -35%).
  - **library_helpers.py (854 Zeilen):** Saubere Kapselung von 3MF-Metadaten-Bereinigung, Pfadvalidierungen, STL/PDF-Thumbnail-Generierung und Sichtbarkeitsprüfungen.
  - **library_slicing.py (1.465 Zeilen):** Vollständige Auslagerung der Slicing-Workflows, Preset-Auflösung, G-Code-Extraktion, Cross-Class-Multi-Plate-Schleifen und Slicing-Jobs.
  - Rückwärtskompatible Re-Exporte aller Funktionen in library.py, sodass bestehende Integrationen unberührt bleiben.
- **Modularisierung von ambu_mqtt.py (MQTT-Druckerkommunikation):**
  - Reduzierung des Monolithen von 8.249 Zeilen auf 7.660 Zeilen (-589 Zeilen).
  - **ambu_mapping.py (627 Zeilen):** Saubere Kapselung aller AMS- und Nozzle-Rack-Mapping-Logiken, A2L Lite Einheiten-Normalisierung, 	ray_exist_bits-Bitmaskenberechnung und Rack-Positionierungs-Algorithmen.
- **Modularisierung von PrinterCard.tsx (Frontend-Druckersteuerung):**
  - Reduzierung der Hauptkarte von 5.232 Zeilen auf 4.981 Zeilen (-251 Zeilen).
  - **PrinterMovementPopover.tsx (215 Zeilen):** Auslagerung der interaktiven Achsensteuerung (XY, Z, Extruder, Homing, Schrittweitenauswahl 1/10/50mm) mit integrierter Bauraum-Kollisionswarnung (#2579).
  - **PrinterConfirmModals.tsx (190 Zeilen):** Zentrale Kapselung aller Betriebs- und Sicherheitsdialoge (Strom An/Aus, Wartungsmodus bei aktivem Druck, Abbruch, Pause, Fortsetzen, HA-Schalter).
- **Verschärfung der Dateigrößen-Budgets (	est_file_size_budget.py):**
  - ackend/app/api/routes/library.py: Budget gesenkt von 6.100 auf 4.200 Zeilen.
  - ackend/app/services/bambu_mqtt.py: Budget gesenkt von 8.275 auf 7.700 Zeilen.
  - rontend/src/pages/PrinterCard.tsx: Budget gesenkt von 5.300 auf 5.000 Zeilen.
- **Qualitätssicherung & Tests:**
  - 100% Pass auf allen 106 Bibliotheks- und Slicing-Tests.
  - 100% Pass auf allen 675 MQTT- und Hardware-Tests.
  - Vollständiger 5/5 Durchstich-Test bestanden (bnahme.py --nur-durchstich).

## v2.0.34 (08.11.2026) — Kundenportal 2.0 & Sofort-Kalkulator mit 3D-Upload, Lieferschein & Thermo-Labels (Phase 7)

- **3D-Mesh- und Geometrieanalyse (`mesh_analysis.py`):**
  - **STL, 3MF & OBJ Geometrieextraktion:** Automatisches Auslesen von Nettovolumen (cm³), Bounding-Box-Abmessungen (X × Y × Z in mm), Oberfläche (cm²), Dreiecksanzahl und Wasserdichtigkeit via `trimesh`.
  - **Bambu Lab Bauraum-Prüfung:** Automatischer Abgleich gegen den 256 × 256 × 256 mm Druckbereich mit visueller Warnung bei Übergröße.
  - **3D-Thumbnail-Vorschau:** Generierung eines 2D-Isometrie-Renderings direkt aus den Mesh-Daten für Kundenportal und Auftragsübersicht.
- **Lieferschein- & Thermo-Versandetiketten-Dienst (`delivery_note_service.py`):**
  - **DIN A4 Lieferschein (PDF):** Druckfertiges Warenbegleitdokument mit Firmenkopf, Kundendaten, detaillierter Positionstabelle, Material-/Gewichtsdaten und rechtssicherem Empfangsbestätigungsfeld.
  - **Thermo-Versandetiketten (PDF):** Vorkonfektioniert für Standard-Thermo-Versandaufkleber (100 × 150 mm / DHL/UPS) sowie Brother QL / Dymo Kompakt-Etiketten (62 × 29 mm).
  - **Dynamischer Tracking-QR-Code:** Auf allen Begleitdokumenten eingebettet; führt direkt zum hinterlegten Auftrag im Kundenportal.
- **Erweiterte Kundenportal-API (`customer_portal_route.py`):**
  - `POST /api/v1/portal/analyze-model`: Analysiert hochgeladene 3D-Modelle ohne vorheriges Speichern.
  - `POST /api/v1/portal/quote-from-model`: Erzeugt aus 3D-Modell und Parametern ein verbindliches Sofort-Angebot (`SQ-XXXXXXXX`).
  - `GET /api/v1/portal/quote/{quote_id}`: Ruft gespeicherte Kalkulationen ab.
  - `GET /api/v1/portal/delivery-note/{quote_id}/pdf`: Generiert und liefert den Lieferschein als PDF.
  - `GET /api/v1/portal/shipping-label/{quote_id}/pdf`: Liefert das passende Thermo-Versandetikett als PDF.
- **Web-Frontend Kundenportal 2.0 (`CustomerPortalPage.tsx`):**
  - **Drag-and-Drop 3D-Upload:** Barrierefreie Dateiauswahl mit Live-Statistiken (Volumen, Maße, Bauraum-Check).
  - **Interaktiver Konfigurator:** Materialprofile (PLA, PETG, ABS, ASA, TPU, PLA-CF), Infill-Schieberegler (5–100%), Schichthöhen (0.12–0.28 mm) und Mengenstaffel mit Rabatten (5% ab 5 Stk., 10% ab 10 Stk., 15% ab 25 Stk.).
  - **Transparente Preiskalkulation:** Live-Aufschlüsselung von Material-, Maschinenlaufzeit- und Rüstkosten sowie MwSt. und Gesamtsumme.
  - **Bestellabschluss & Dokumente:** Integrierter Stripe Checkout sowie direkte 1-Klick-Downloads für Lieferschein und Thermo-Labels.
  - Öffentliche Zugänglichkeit unter `/portal` und `/kalkulation` sowie Direktlink auf `FinancePage.tsx`.
- **Test-Suite:**
  - `test_mesh_analysis.py`: 4 Unit-Tests für Volumen, Bauraumgrenzen, fehlerhafte und leere Dateien.
  - `test_delivery_note_service.py`: 3 Unit-Tests für DIN A4 Lieferschein und Thermo-Labels (100x150 mm & 62x29 mm).
  - `test_customer_portal_v2_api.py`: 4 Integrationstests für Analyse, Sofortkalkulation, Lieferschein- und Label-PDF-Routen.

## v2.0.33 (07.11.2026) — KI & Kamera: Kontinuierliche Schichtanalyse & Edge-Spaghetti-Detektor (Phase 6)

- **Schneller lokaler Edge-Spaghetti-Detektor (`spaghetti_detector.py`):**
  - **OpenCV CLAHE-Beleuchtungskompensation:** Normalisiert Helligkeit und Kontrastschwankungen im LAB-Farbraum (Chamber-LED an/aus, Tag/Nacht, Reflexionen) vor der Merkmalsextraktion.
  - **Sobel-Orientierungsentropie:** Mathematische Trennung zwischen geordneten Druckbahnen (Wände, Gitter, Infill mit 0°/45°/90° Orientierungsspitzen) und chaotischem Filament-Salat (isotrope Winkeldistribution mit hoher Shannon-Entropie > 0.70).
  - **Kantendichte & Kontur-Clusterung:** Findet Spaghetti-Fäden mittels Canny-Kantendichte und gruppiert morphologische Filament-Nester zu einer exakten Fehler-Bounding-Box.
  - **Ultra-performant:** Läuft in unter 25 ms auf Raspberry Pi 5 / CPU ohne Cloud- oder LLM-Latenz.
- **Kontinuierlicher Schichtanalyse-Dienst (`layer_inspection.py`):**
  - Hook in `on_layer_change` in `printer_telemetry_flow.py`: Prüft das Druckbett im einstellbaren Takt (z. B. alle 2–3 Schichten).
  - **Schwellwert- & Bestätigungsfilter:** Verhindert Fehlalarme durch vorübergehende Verdeckungen (z. B. durch den Druckkopf) via Konfigurationsparameter `consecutive_alerts` (Standard: 2 bestätigte Prüfungen in Folge).
  - **Automatischer Not-Stopp (Auto-Pause):** Sendet bei bestätigtem Fehldruck sofort `pause_print()` an den Drucker, archiviert ein annotiertes Beweisfoto in der Fehlerbild-Sammlung und löst die AI-Alarmierungs-Pipeline aus.
  - Ringpuffer für die letzten 50 Schichtprüfungen mit Schichtnummer, Entropie, Kantendichte und Status.
- **API-Endpunkte (`layer_inspection.py`):**
  - `GET /api/v1/printers/{id}/layer-inspection`: Status, Konfiguration und Historie.
  - `PUT /api/v1/printers/{id}/layer-inspection`: Konfiguration aktualisieren.
  - `POST /api/v1/printers/{id}/layer-inspection/reset`: Laufenden Fehlerzähler zurücksetzen.
  - `POST /api/v1/printers/{id}/layer-inspection/test`: Sofortige Einzelprüfung mit Live-Kamerabild oder Test-Upload inklusive Base64-Vorschau.
- **Web-Frontend (`LayerInspectionCard.tsx`):**
  - Neues Diagnose- und Überwachungs-Panel auf der Wartungsseite mit Live-Statusanzeige, Sensitivitäts-Schieberegler, Prüfintervall, Auto-Pause-Schalter, Test-Upload mit annotierter Bildvorschau und Verlaufstabelle.
  - Direkte Schalter-Integration in der zentralen Karte `AiChecksCard.tsx`.
- **Test-Suite:**
  - `test_spaghetti_detector.py` (5 Unit-Tests für Normalisierung, Entropie, Gitter vs. Spaghetti, Bildformate).
  - `test_layer_inspection.py` (6 Unit-Tests für Konfiguration, Intervallfilter, Notpause-Ablauf, Sofort-Test).
  - `test_layer_inspection_api.py` (3 Integrationstests für REST-Endpunkte).

## v2.0.32 (07.11.2026) — GPIO Hardware-Taster, Not-Halt-Dienst & Servo-Justierung (Phase 5)

- **GPIO Not-Halt & Taster-Dienst (`gpio_hardware.py`):**
  - **Physischer Not-Halt (E-Stop):** Überwachung von GPIO 26 mit Software-Entprellung (50 ms) im Öffner- (NC) oder Schließer-Modus (NO). Bei Unterbrechung werden sofort alle Schrittmotoren stromlos geschaltet, aktive Drucke gestoppt und neue Warteschlangen-Aufträge verriegelt.
  - **Sicherheits-Verriegelung:** Der Not-Halt kann erst quittiert werden, wenn der physische Pilztaster mechanisch entriegelt ist.
  - **Quittier- & Pausetaster:** Physischer Quittiertaster (GPIO 16) zum Rücksetzen des Not-Halts oder Bestätigen von Plattenwechseln; Pausetaster (GPIO 20) zum Anhalten/Fortsetzen des Drucks.
  - **Status-LED-Ansteuerung:** GPIO 21 signalisiert den Betriebszustand (Bereit, Druckt, Not-Halt).
- **Servo-Winkel-Justierassistent:**
  - Kalibrierung der Endlagen für Türschließer-Servos (`zu_grad`, `offen_grad`) direkt über Schieberegler im Web-Interface mit Live-Testfahrt ohne manuelle JSON-Edits.
- **Web-Frontend (`GpioHardwareCard.tsx`):**
  - Neues Hardware-Bedienfeld auf der Wartungsseite mit Not-Halt-Statusbanner, rotem Not-Aus-Schalter, Quittierungs-Button, Live-Pinanzeige und Servo-Kalibrierung.
- **Unit-Tests:**
  - `backend/tests/unit/test_gpio_hardware.py` (4 Tests) deckt Status, Entprellung, E-Stop-Auslösung, Reset und Kalibrier-Endpunkte vollständig ab.

## v2.0.31 (07.11.2026) — Intelligenter Rollentausch & AMS Spool Auto-Fallback (Phase 4)

- **Intelligenter AMS Rollentausch & Spool-Auto-Fallback (`spool_auto_fallback.py`):**
  - **Automatische Backup-Erkennung:** Identifiziert kompatible Rollenpaare in allen AMS-Einheiten des Druckers basierend auf Materialtyp (PLA, PETG etc.), Farb-Kompatibilität (exakter Hex-Code oder Delta-E Schwellenwert) und Düsendurchmesser.
  - **Proaktive Auto-Refill-Aktivierung:** Beim Druckstart in `print_scheduler.py` und bei der Filament-Defizit-Prüfung in `filament_deficit.py` wird Bambus natives `ams_filament_backup` automatisch auf dem Drucker aktiviert, wenn kompatible Spulen geladen sind. Dies verhindert Druckabbrüche und Wartepausen bei leerlaufenden Spulen.
  - **Material-Pooling bei Defiziten:** Bei aktiviertem Auto-Fallback poolt PrintLab das Restfilament aller kompatiblen Schächte, sodass Aufträge ohne Fehlalarm starten können, wenn die Summe des Filaments ausreicht.
- **Neue API-Endpunkte für AMS-Fallback:**
  - `GET /api/v1/printers/{id}/ams-backup-pairs`: Liefert die aktiven und redundanten Spulenpaarungen pro AMS-Einheit mit Schacht-Nummern und Restmengen.
  - `POST /api/v1/printers/{id}/ams-auto-fallback/apply`: Erzwingt die proaktive Aktivierung des nativen AMS-Backups für kompatible Rollen.
- **Slicer & Slicing-Stabilität:**
  - `tree_support_wall_count` wird bei allen Prozesskonfigurationen standardmäßig auf `"0"` vorgegeben, wodurch der OrcaSlicer CLI Returncode 238 (-1 out of range) vollständig verhindert wird.
  - Linux-Paket-Abhängigkeiten (`libwebkit2gtk-4.1-0`, `xvfb`) und Multi-User-Service-Neustart in `werkzeuge/pi_slicer_installieren.sh` verbessert.

## v2.0.30 (07.11.2026) — Slicer-Preset-Manager UI & Profil-Verwaltung (Phase 3)

- **Slicer-Preset-Manager im Web-Frontend (`LocalProfilesView.tsx`):**
  - **Neues Profil erstellen:** Dialog zur Erstellung benutzerdefinierter Filament- und Prozess-Profile mit Auswahl vorgefertigter Basis-Vorlagen (Generic PLA, PETG, ABS, TPU sowie 0.20mm Standard, 0.12mm Fein, 0.28mm Schnell, 0.20mm Stabil).
  - **Profil bearbeiten:** Umfassender Editor mit Formular-Modus (Drucktemperaturen, Bett-Temperatur, Volumengeschwindigkeit, Schichthöhe, Wandlinien, Infill-Muster, Stützen etc.) und Experten-Modus (Live-JSON-Editor mit Syntax-Validierung).
  - **Profil klonen:** 1-Klick-Duplizierung bestehender Presets mit automatischer fortlaufender Namensgebung (`(Kopie)`).
  - **Profil exportieren:** Direkter Download als Bambu Studio / OrcaSlicer kompatibles `.json`.
  - **Kategorie-Filter:** Tab-Leiste zur schnellen Umschaltung zwischen allen Profilen, Filamenten, Prozessen und Druckern mit Mengenzählern.
- **Backend-Erweiterungen für Profile (`local_presets.py`):**
  - Neuer Endpunkt `GET /api/v1/local-presets/templates` für Standardvorlagen.
  - Neuer Endpunkt `POST /api/v1/local-presets/{id}/clone` zum Klonen.
  - Automatische Sanitisierung von Prozess-Parametern beim Anlegen und Aktualisieren zur Verhinderung von OrcaSlicer-Range-Fehlern.
  - Unit-Tests in `backend/tests/unit/test_local_presets_api.py`.

## v2.0.29 (07.11.2026) — Slicer-Cache-Hygiene & 3D-Toolpath-Direktvorschau

- **Slicer-Cache-Bereinigung & Speicher-Hygiene (`slicer_cache.py`):**
  - Automatischer Hintergrund-Watchdog bereinigt verwaiste temporäre Slicing-Ordner (`bambu_slice_*`) im System-Temp-Verzeichnis periodisch.
  - Begrenzt überdimensionierte Slicer-Logdateien (`*.log` > 5 MB) durch automatische Rotation/Kürzung.
  - Neue System-Endpunkte `GET /api/v1/system/slicer-cache` und `POST /api/v1/system/slicer-cache/clean` für Monitoring und manuelle Bereinigung.
  - Unit-Tests in `backend/tests/unit/test_slicer_cache.py`.
- **3D G-Code / Toolpath Direktzugriff nach Slicen:**
  - `ToastContext` um sekundäre Aktionen (`secondaryAction`) erweitert.
  - Slice-Fertigstellungs-Meldung bietet neben `[Jetzt drucken]` nun auch direkt `[3D-Vorschau]` an, um die visualisierten Werkzeugbahnen und Schichten ohne Umwege im Three.js G-Code-Viewer zu betrachten.
  - Frontend-Produktions-Build aktualisiert.

## v2.0.28 (07.11.2026) — OrcaSlicer Parameter-Validierung & Auto-Korrektur (tree_support_wall_count)

- **OrcaSlicer CLI Range-Validierungsfehler behoben (Returncode 238):**
  - **Tree-Support-Wandanzahl sanitisiert:** Bambu Studio / Bambu Cloud Profile setzen `tree_support_wall_count: -1` als Sentinel für "Auto". OrcaSlicer v2.4.2 validiert diesen Wert strikt gegen den Wertebereich `[0.0, 2.0]` und bricht mit Returncode 238 ab (`tree_support_wall_count: -1 not in range [0.000000,2.000000]`).
  - `slicer_cli.py`, `preset_resolver.py` und `library.py` sanitieren negative Sentinel-Werte nun proaktiv und setzen `tree_support_wall_count` auf den gültigen Standardwert `"0"`.
  - Zusätzliche Absicherung für weitere Bambu Studio Sentinel-Werte wie `raft_first_layer_expansion`, `prime_tower_brim_width` und `support_bottom_interface_spacing` (auf `0` geclampt).
  - Chirurgische Bereinigung eingebetteter Sentinels aus `.3mf`-Dateien (`project_settings.config`) auch beim direkten Slicing via Sidecar.
- **Resiliente automatische Fehler-Selbstheilung bei Slicer-Validierungsfehlern:**
  - Erkennt `slicer_cli.py` in der Slicer-CLI-Ausgabe einen Wertebereichs-Fehler (`<param>: <val> not in range [<min>, <max>]`), wird der betreffende Parameter automatisch auf den erlaubten Grenzwert geclampt und der Slice-Auftrag transparent wiederholt, ohne dass der Benutzer mit einem Fehlerdialog abbricht.

## v2.0.27 (07.11.2026) — SliceModal Stabilität & Slicer-Fehlerbehebung

- **SliceModal UI-Crash behoben (`(intermediate value).trim is not a function`):**
  - Robuste Typ-Normalisierung (`normalizeTypeString`) in `slicePresetPicker.ts` verhindert Abstuerze beim Oeffnen des Slicer-Fensters, wenn `filament_type` als Array (`["PLA"]`) oder `null`/`undefined` geliefert wird.
  - Backend-Bereinigung in `builtin_slicer.py` und `slicer_presets.py`: `filament_type` wird strikt zu einem standardkonformen String (`str`) normalisiert.
  - Automatischer Pydantic-Validator in `UnifiedPreset` garantiert typsichere Serialisierung der Preset-Daten.
  - Neu gebautes Produktions-Frontend in `static/` mit validiertem Quell-Hash.
- **Linux / Raspberry Pi WebKitGTK 4.1 Laufzeitumgebung & Fehlerbehandlung:**
  - `werkzeuge/pi_slicer_installieren.sh` installiert gezielt `libwebkit2gtk-4.1-0` und `libjavascriptcoregtk-4.1-0` fuer Raspberry Pi OS 12 (Bookworm) und neuere Debian/Ubuntu-Systeme.
  - Automatischer Installationsversuch im Slicer-Wrapper `run_slicer.sh` bei fehlenden Bibliotheken.
  - Verstaendliche, praezise Handlungsanweisung im Slice-Fehlerdialog mit dem exakten Terminalbefehl statt kryptischem Returncode 1.

## v2.0.26 (06.11.2026) — Offizielle OrcaSlicer-Engine integriert (GitHub Auto-Download & Headless-Slicing)

- **Echter GitHub-Slicer statt fehlerhaftem Python-Code (`builtin_slicer.py` & `slicer_manager.py`):**
  - Vollstaendige Abloesung des frueheren Polygon-basierten Python-Slicers durch die offizielle **OrcaSlicer v2.4.2 CLI-Engine** direkt von GitHub (`SoftFever/OrcaSlicer` sowie `kldzj/orca-slicer-arm64`).
  - Komplexe Geometrien, Handyhalter, Loecher, Waende, Infill und Ueberhaenge werden 1:1 exakt in echten Bambu Lab G-Code geslict – keine massiven Kloetze oder fehlerhaften Gitterstrukturen mehr.
  - Automatischer Download und Entpacken der passenden Binaerdatei fuer Windows (x64 / ARM64) und Linux / Raspberry Pi (x86_64 / aarch64 mit Xvfb-Headless-Unterstuetzung).
- **Robuste Profil- & Druckervalidierung (`slicer_cli.py`):**
  - Automatische Injektion von `compatible_printers` in Prozessprofile, sodass alle Druckerprofile (Bambu Lab P2S, P1S, X1 Carbon, A1, A1 mini, H2D) ohne OrcaSlicer-Preset-Fehler sauber geslict werden.
  - Automatische Zentrierung (`--arrange 1`) und Vermeidung der Bambu Lab Bett-Ausschlusszone (Cutter/Wiper) fuer STL-Modelle.
  - Automatischer Layer-Reset (`layer_gcode: ";AFTER_LAYER_CHANGE\nG92 E0"`) zur Verhinderung von Rundungsfehlern bei relativer Extrusion.
  - Praezise Rueckgabe von Druckzeit (`seconds`) und Filamentgewicht (`grams`) aus den erzeugten G-Code-Dateien und `slice_info.config`.
- **System-Verwaltung (`/api/v1/system/slicer-engine`):**
  - Neue API-Endpunkte zur Abfrage des Slicer-Zustands (`GET /slicer-engine`) und zur Hintergrund-Installation von GitHub (`POST /slicer-engine/install`).
  - Standalone-Installer `werkzeuge/pi_slicer_installieren.sh` fuer unkomplizierte Einrichtung auf Raspberry Pi OS.
- **SliceModal UI-Crash behoben (`(intermediate value).trim is not a function`):**
  - Robuste Typ-Normalisierung (`normalizeTypeString`) in `slicePresetPicker.ts` verhindert Abstuerze, wenn `filament_type` als Array (`["PLA"]`) oder `null`/`undefined` geliefert wird.
  - Backend-Bereinigung in `builtin_slicer.py` und `slicer_presets.py`: `filament_type` wird strikt zu einem standardkonformen String normalisiert.

## v2.0.25 (06.11.2026) — Vollwertige Solid-Skin & Mehrfach-Wand-Slicing, Pi OrcaSlicer-Installer

- **Vollstaendige Solid-Skin- & Mehrfach-Wand-Engine (`builtin_slicer.py`):**
  - **Dichte Decken & Boeden (Solid Shells):** Die ersten 4 Schichten am Druckbett und die obersten 4 Schichten werden zu 100% vollflaechig mit 0.42 mm Strangabstand gedruckt.
  - **Automatische Solid-Skin fuer Schraegflaechen & Ueberhaenge:** Schraeg abfallende Flaechen und Rampen (z. B. Handyhalterungen) werden schichtuebergreifend erkannt und dicht geschlossen statt als offenes Gitter gedruckt.
  - **Mehrfach-Waende (Inner & Outer Perimeters):** Exakte Umsetzung von `wall_loops` (2, 3 oder mehr Waende) durch geometrisches Polygon-Insetting (0.40 mm Versatz) mit automatischer Singularitaets- und Invertierungspruefung.
  - **45°/-45° Wechselschraffur:** Das Infill wechselt schichtweise den Winkel (+45° / -45°), sodass ein stabiles, tragendes Kreuzgitter entsteht.
  - **Bambu-Feature-Tags & Faden-Vermeidung:** Ausgabe von `; FEATURE: Outer wall`, `; FEATURE: Inner wall`, `; FEATURE: Top surface`, `; FEATURE: Sparse infill` zur korrekten Farbdarstellung im Bambu-Studio-Vorschaufenster sowie 0.8 mm Retraktion vor laengeren Travel-Fahrten.
- **OrcaSlicer CLI Installer fuer Raspberry Pi (`werkzeuge/pi_slicer_installieren.sh`):**
  - Ein-Klick-Installation des offiziellen OrcaSlicer ARM64 Linux AppImages inklusive Xvfb-Headless-Wrapper auf dem Raspberry Pi 4 / 5.
  - Ermoeglicht bei Bedarf vollwertiges Desktop-Slicing (inkl. Baum-Supports, adaptiver Schichthoehe, Nahtplatzierung) direkt auf dem Pi.
  - Automatische Erkennung in `slicer_cli.py` unter `/usr/local/bin/orca-slicer` und `/opt/orca-slicer/`.

## v2.0.24 (06.11.2026) — Raspberry Pi Absturzschutz, Watchdog-Auto-Reboot, Planarer Python-Slicer & MakerWorld-Download

- **Raspberry Pi Absturzschutz & Watchdog-Automatisierung (`werkzeuge/pi_absturzschutz.sh`):**
  - Automatisches sauberes Rebooten bei Freezes/Hangs durch Aktivierung des Hardware-Watchdogs (`bcm2835_wdt`, `RuntimeWatchdogSec=15s`, `RebootWatchdogSec=2min`).
  - Automatischer Kernel-Reboot nach 10 Sekunden bei Kernel-Panic (`kernel.panic = 10`, `kernel.panic_on_oops = 1`, `vm.panic_on_oom = 0`).
  - Persistenter systemd-Journal-Speicher (`Storage=persistent`, 100 MB MaxUse) zur Erhaltung von Log-Eintraegen ueber Reboots und Abstuerze hinweg.
  - 2 GB Swap-Speicher zur Vermeidung ploetzlicher Out-Of-Memory-Kernel-Crashes bei grossen Slices.
  - Systemd Service Auto-Restart mit 3-Sekunden-Backoff (`Restart=always`).
- **Absturz-Diagnose & Ursachen-Analyse (`crash_diagnostics.py`):**
  - Erkennt unsaubere Reboots und analysiert die Ursache: Unterspannung / Brownout via `vcgencmd get_throttled` (Bit 0/16), Out-Of-Memory (OOM-Killer), thermische Notabschaltung, Kernel-Panic, Watchdog-Reset oder Stromausfall.
  - Prominente Diagnose-Warnung in `PiHealthCard` mit verstaendlichen Erklaerungen, konkreten Loesungsschritten (z. B. 27W USB-C Netzteil, aktiver USB-Hub) und ausklappbarem Log-Auszug des vorherigen Boots.
  - Neue Endpunkte `GET /api/v1/system/crash-report` und `POST /api/v1/system/crash-report/dismiss`.
- **Echter planarer Python-Slicer (`builtin_slicer.py`):**
  - Ersetzt die fruehere Bounding-Box-Generierung durch echte geometrische 2D-Ebenenschnitte (`trimesh.intersections.mesh_plane`).
  - Rekonstruiert echte Aussenkonturen und Hohlraeume/Aussparungen (`_chain_segments`) und platziert Infill nur innerhalb der realen Polygonpfade (`_scanline_infill`).
  - Das geslicte Modell entspricht zu 100% der Geometrie des 3D-Modells – keine massiven Kloetze / Kastenleisten mehr.
- **MakerWorld-Download-Fix & Upstream-Fehler-Transparenz:**
  - Praezise Extraktion von Upstream-Fehlergruenden (`msg`, `error_msg`, `description`, `code`) statt eines undurchsichtigen HTTP 400.
  - Robuster Multi-Parameter-Fallback (`model_id`, `design_id`, `profile_id`, Fallback-User-Agent) fuer die Bambu Lab IoT API.

## v2.0.23 (06.11.2026) — Einstellungsfenster: Saubere Unterpunkte & Beseitigung redundanter Karten

- **Strukturierte Unterpunkte im Allgemein-Menü:**
  - Das Einstellungsfenster wurde modularisiert und in übersichtliche Unterbereiche (Pills-Navigation) unterteilt:
    - **Grundeinstellungen:** Sprache, Standard-Startseite, Datums- und Zeitformate sowie Standarddrucker.
    - **Erscheinungsbild:** Theme-Umschaltung (Dunkel / Hell / System), Farbpaletten, Akzente, Druckfortschritt im Browsertab sowie Menüleisten-/Seitenleisten-Quicklinks.
    - **Kosten & Abrechnung:** Währung, Filament- und Strompreise, Verbrauchsmodi, Abrechnung/Kostenstellen, Schutz vor unbefugtem Druck und monatlicher Budget-Reset.
    - **Kamera & Medien:** Externe Videostreams und Snapshots pro Drucker (MJPEG, RTSP, Snapshot, USB V4L2) mit Verbindungstest, Abschlussfotos bei Druckende und Druckbett-Parkposition.
    - **Dateien & Speicher:** Bibliotheks-Archivregeln, Speicherwarnschwelle, automatische Papierkorb- und Verlaufsbereinigung, visuelle Speicherplatz-Nutzungsanalyse und Wartungsfunktionen.
    - **Alle anzeigen:** Vollständige Übersicht aller Karten für schnellen Gesamteinblick.
- **Beseitigung von Duplikaten & Redundanzen:**
  - Die redundante Karte *Aktualisierungen* wurde aus dem *Allgemein*-Tab entfernt – sämtliche Update-, Firmware- und Versionsprüfungen befinden sich nun exklusiv im dafür vorgesehenen Hauptmenüpunkt *Updates & Version*.
  - Vermeidung unübersichtlicher 3-Spalten-Wände zugunsten strukturierter, responsiver Unterkarten mit Deep-Link- und Suchunterstützung.

## v2.0.22 (06.11.2026) — Slicer-Geometrie (Echte Werkzeugbahnen statt Kasten) & MakerWorld-Download-Fix

- **Echte Slicer-Geometrie statt Dummy-Kasten (Bambu Studio CLI G-Code Paketierung):**
  - Bambu Studio CLI erzeugt bei `--outputdir` standardmäßig `plate_1.gcode` und `result.json` statt einer direkten 3MF-Datei. Der fehlerhafte Parameter `--export-3mf <name>` (der zum Abbruch und Bounding-Box-Fallback führte) wurde korrigiert.
  - Neue Paketierungsfunktion `_package_gcode_3mf` führt die echten G-Code-Werkzeugbahnen, Schichten, Infill und Dauern mit der 3D-Geometrie und `Metadata/slice_info.config` zusammen.
  - Modelle werden nun mit 100% originalgetreuen Konturen, Aussparungen und Rundungen geslict – kein massiver rechteckiger Dummy-Kasten mehr.
- **MakerWorld / Bambu Lab API Download-Fix (Status 400 Fallback):**
  - `get_profile_download` fängt HTTP 400 von der Bambu Lab IoT-API ab und versucht automatisch alternative Parameter (`model_id` als Design-ID sowie ohne `model_id`-Filter).
  - Klare deutsche Fehlermeldung mit Extraktion des Upstream-Fehlers (`_extract_upstream_error`), wenn ein Profil nicht mehr verfügbar oder geschützt ist, statt eines kryptischen Status 400.

## v2.0.21 (06.11.2026) — Modell-Hub: Thangs 3D Benutzerführung, Yeggi-Metasuche & zuverlässige Links

- **Thangs 3D Benutzerführung & Aufklärung:**
  - Da Thangs eine Metasuchmaschine ist, die eigene Logins und Cloudflare verlangt, zeigt PrintLab bei Eingabe von `thangs.com`-Links nun sofort einen verständlichen Hilfekasten mit Schritt-für-Schritt-Anleitung an (Original-Quelle auf Thangs anklicken oder Datei per Drag & Drop importieren).
  - Backend liefert bei `thangs.com`-Links eine hilfreiche deutsche Handlungsanweisung statt eines technischen 400-Fehlers.
- **Yeggi 3D-Metasuche hinzugefügt:**
  - Yeggi (`yeggi.com`) als schlanke und unkomplizierte Suchmaschine direkt neben Thangs in der Schnellsuche integriert.
- **Zuverlässige Portal-Links:**
  - Alle Portal-Schaltflächen (MakerWorld, Printables, Thingiverse, Thangs) als echte Hyperlinks umgestellt, sodass sie nie wieder von Browser-Popup-Blockern verhindert werden.

## v2.0.20 (06.11.2026) — PC-Slicer Netzwerkanbindung (LAN & Tailscale), Auto-Erkennung OrcaSlicer & Update-SSL-Fallback

- **PC-Slicer Netzwerkanbindung für Raspberry Pi:**
  - `starte_pc_slicer.bat` lauscht auf allen Netzwerk-Schnittstellen (`0.0.0.0:3001`) und schaltet LAN- und Tailscale-Netzwerke (`100.64.0.0/10`, `192.168.0.0/16`, `172.16.0.0/12`, `10.0.0.0/8`) frei.
  - Zeigt beim Start im Konsolenfenster automatisch die genauen Adressen an (z. B. `http://<PC-IP>:3001`), die in PrintLab auf dem Raspberry Pi eingetragen werden müssen.
- **Automatische Slicer-Erkennung:**
  - `slicer_cli.py` erkennt neben Bambu Studio nun auch automatisch OrcaSlicer in Standardpfaden oder Umgebungsvariablen.
- **Update-Prüfung SSL-Fallback:**
  - Automatischer Fallback auf Git-Tags, wenn die GitHub-API durch Schul-/Unternehmens-Proxys oder Zertifikatsfehler (`[SSL: CERTIFICATE_VERIFY_FAILED]`) blockiert wird.

## v2.0.19 (06.11.2026) — Integrierter Slicer: Bambu Studio CLI Fix & echte Werkzeugbahnen für 3MF/STL

- **Bambu Studio CLI Plattenauswahl korrigiert:** Der ungültige Parameter `--export-plate <N>` wurde durch das offizielle `--slice <N>` ersetzt. Bambu Studio bricht nicht mehr mit Fehler `-2` ab.
- **Profil-Stubs & Fallback für 3MF behoben:** Rumpf-Profile (`{"inherits": ...}`) werden nicht mehr ungeprüft über `--load-settings` übergeben, was Bambu Studio zum Absturz brachte. 3MF-Dateien nutzen direkt ihre eingebetteten Original-Einstellungen mit automatischem Retry.
- **Keine Dummy-Kästen mehr:** Der fehlerhafte Notfall-Fallback in `pc_slicer.py` wurde behoben, sodass installierte Bambu-Studio-Installationen echte Werkzeugbahnen und G-Code erzeugen statt einer massiven rechteckigen Bounding-Box.
- **Signiertes Release:** Release-Tag wird mit SSH-Schlüssel signiert, um die Signaturprüfung auf Raspberry Pi und Zielsystemen zu bestehen.

## v2.0.18 (06.11.2026) — 3D-Modell-Hub (6 Plattformen & Quellen), Telegram-Aktionen & Auto-Druckbett-Prüfung

- **3D-Modell-Hub mit 6 Plattformen & Quellen:**
  - **🟢 MakerWorld (`makerworld.com`):** Direkte Auflösung von Bambu Lab 3MFs, Platten, Druckern und AMS-Farbzuweisungen.
  - **🟠 Printables (`printables.com`):** Prusa Research Modelle (3MF & STL) direkt per Link laden.
  - **🔵 Thingiverse (`thingiverse.com`):** Ultimaker Community-Modelle direkt per Link (z. B. `thing:763622`) abrufen und Platten/Dateien einzeln importieren.
  - **🟣 Thangs 3D (`thangs.com`):** Schnellzugriff auf die weltweit größte Metasuchmaschine für 3D-Druckmodelle.
  - **🔗 Direkt-Download:** Beliebige direkte Web-Links zu `.3mf`-, `.stl`- oder `.step`-Dateien werden sofort erkannt und geladen.
  - **📁 Eigener Datei-Upload:** `.3mf`-, `.stl`- und `.step`-Dateien können direkt per Klick auf „Modell hochladen“ oder via Drag & Drop ins Browserfenster importiert werden.
  - **Modell-Hub Navigation:** Untermenüpunkt in der Seitenleiste umbenannt zu *Modell-Hub (MakerWorld & 3D)*.
- **MakerWorld Download-Korrektur ("Did not return a download URL"):**
  - Kandidatenauflösung für Modelle mit vielen Platten (wie Mystic Dragon mit 23 Profilen) erweitert: dynamischer Abruf aller Platten über `get_design_instances` (`hits`), wenn eine Profil-ID außerhalb der ersten 4 Standardinstanzen liegt.
  - Robuste rekursive Fallback-Suche nach signierten 3MF/STL-URLs (`bblmw.com`) in verschachtelten Manifest-Antworten.
- **Interaktive Telegram-Bot-Steuerung:**
  - Neue Chat-Befehle `/pause`, `/resume`, `/licht`, `/stop` sowie interaktive Inline-Keyboard-Buttons (`cmd:live`, `cmd:light`, `cmd:pause`, `cmd:resume`, `cmd:stop`, `cmd:stop_confirm`) mit Sicherheitsabfrage vor Abbruch.
- **Automatische Druckbett-Leerkontrolle in der Warteschlange:**
  - Automatischer Bed-Check vor Vorheizen und Druckjob-Upload in `print_scheduler.py` via `queue_plate_check.py`.
  - Blockiert automatisches Drucken und sendet Warnungen, wenn das Druckbett noch nicht geräumt ist.
- **Home Assistant MQTT Discovery & Telemetrie-Erweiterung:**
  - Neue Sensoren für Bauraumtemperatur (`chamber_temperature`), aktiven Druckauftrag (`current_print`), Bauteillüfter-Geschwindigkeit (`cooling_fan_speed`) und Schalter für Druck-Pause/Fortsetzen via MQTT-Discovery.

## v2.0.17 (05.11.2026) — Thingiverse-Integration & Direkter 3D-Modell-Upload

- **Thingiverse-Integration (`thingiverse.com`):**
  - Direkte Eingabe von Thingiverse-Modell-URLs (`thingiverse.com/thing:ID`, `thingiverse.com/thing/ID`, Dateilinks und Fragmente) im Modell-Hub.
  - Abfrage von Modell-Details, Metadaten, Beschreibungen, Bildern und Dateilisten (STL, 3MF, etc.) über die Thingiverse-API mit Fallback-Token-Extraktion.
  - Direkter und anonymer Download von Modell-Dateien über `cdn.thingiverse.com` ohne Cloud-Konto-Zwang.
  - Unterstützung von Thingiverse-Bildern (`cdn.thingiverse.com`, `resize.thingiverse.com`) im internen Thumbnail-Proxy unter Einhaltung der CSP.
  - Plattform-Badge (*Thingiverse*) und direkter Link („Auf Thingiverse öffnen“).
- **Direkter 3D-Modell-Upload im Modell-Hub:**
  - Neue Upload-Schaltfläche („Modell hochladen“) direkt im Kopfbereich des Import-Kartenfelds.
  - Nahtloses Drag & Drop von Modelldateien (`.3mf`, `.stl`, `.step`, `.stp`, `.zip`) direkt auf das Import-Kartenfeld mit visueller Hervorhebung.
  - Vollständige Integration des `FileUploadModal` inklusive Fortschrittsanzeige, STL-Vorschaubild-Generierung und automatischer Aktualisierung der Bibliothekslisten.

## v2.0.16 (05.11.2026) — Multihost-Modell-Hub (MakerWorld Fix, Printables & Direkt-Download)

- **MakerWorld Download-Korrektur ("Did not return a download URL"):**
  - Behebung des Download-Fehlers bei Platten-URLs mit abweichender Instanz- und Profil-ID (z. B. Mystic Dragon `#profileId-3884112`).
  - Duale Kandidatenauflösung gleicht IDs gegen `id` und `profileId` ab und wählt bei Fehlern automatisch den passenden Fallback.
  - Robuste Manifest-URL-Extraktion (`_extract_manifest_url_and_name`) für verschachtelte IoT-Antwortformate (`data.url`, `downloadUrl`, `files[]`).
  - System-Trust-Store Initialisierung (`load_default_certs(ssl.Purpose.SERVER_AUTH)`) für fehlerfreie TLS-Verbindungen unter Windows.
- **Integration von Printables (`printables.com`):**
  - Direkte Eingabe von Printables-Modell-URLs im Modell-Hub.
  - GraphQL-Integration zur automatischen Abfrage von Metadaten, Beschreibungen, Bildern und Dateilisten (STL, 3MF, etc.).
  - Kostenloser und anonymer Download über signierte Printables-Links ohne Notwendigkeit eines Bambu-Cloud-Kontos.
- **Integration von direkten 3D-Modell-Links (Direct URLs):**
  - Direkte Eingabe beliebiger Weblinks zu `.3mf`-, `.stl`-, `.step`- und `.stp`-Dateien (z. B. GitHub Releases, Thingiverse-Direktdownloads).
  - Automatisches Herunterladen und Speichern mit korrekter Dateiendung und Größenangabe in der Bibliothek.
- **Modell-Hub Oberfläche & Provider-Erweiterungen:**
  - Automatische Provider-Erkennung in der Eingabezeile mit Plattform-Badges (*MakerWorld*, *Printables*, *Direkt-Download*).
  - Proxying von Printables-Bildern (`media.printables.com`) über den internen Thumbnail-Proxy zur Einhaltung der Browser-CSP.
  - Provider-spezifische externe Links und angepasste Download-Hinweise (Bambu-Cloud-Warnung erscheint nur bei MakerWorld-Modellen).

## v2.0.15 (05.11.2026) — Fester KI-Assistent-Chat in der Seitenleiste & Schnellsuche entfernt

- **Seitenleiste optimiert:**
  - Die Suchzeile („Schnellsuche... Ctrl K“) oben links in der Seitenleiste wurde entfernt (Tastaturkürzel Ctrl+K bleibt weiterhin aktiv).
  - Neuer fester Menüpunkt **KI-Assistent** (`/assistant`) unter *Betrieb* direkt in der linken Navigation.
- **Reine Chat-Oberfläche für den KI-Assistenten (`/assistant`):**
  - Direkter Chat ohne technische Einstellungsformulare (keine Base-URL, kein Modell-Dropdown, keine Timeout-Felder, keine Auto-Setup-Karten).
  - Automatisches Aktivieren im Hintergrund, Live-Statusindikator (Bereit / Verbindung prüfen), Willkommens-Karten und Vorschlags-Chips.

## v2.0.14 (05.11.2026) — Vollständige Integration von Einrichtung & Systemzustand in die Einstellungen, Seitenleiste bereinigt

- **Vollständige Integration in die Einstellungen (`/settings`):**
  - **Einrichtungsassistent (`/settings?tab=setup`):** Alle Funktionen und Karten des bisherigen Einrichtungsassistenten (`/einrichtung`) sind vollständig in den Einstellungsbereich gewandert, sauber gegliedert in 4 logische Unterbereiche (*Checkliste & Kompass*, *KI & Schnellstart*, *Verbindungen & Slicer*, *Diagnose & Wartung*) sowie *Alle Bereiche*. Direkte Deep-Links und Anker (`#setup-alerts`, `#setup-remote`, `#setup-selftest`, etc.) schalten automatisch auf den passenden Unterbereich um.
  - **Systemzustand & Diagnose (`/settings?tab=system`):** Vollständige Übernahme aller System- und Ressourcen-Dashboards des bisherigen `/system`-Endpunkts in die Einstellungen. Aufgeteilt in Unterbereiche für *Hardware & Ressourcen* (CPU, RAM, Speicherplatz mit visuellen Fortschrittsbalken, Uptime, Hostname, Datenbank-Statistiken, verbundene Drucker), *Systemprüfung & Tests* (Live-Systemgesundheit mit Rescan, Drucker-Verbindungsdiagnose für alle konfigurierten Drucker) und *Support & Protokolle* (Debug-Logging mit Live-Laufzeit-Timer, Support-Bundle-Download mit Fortschrittsanzeige, integrierter Live-Logviewer).
  - **Automatische Weiterleitung:** Frühere Routen `/einrichtung` und `/system` leiten nahtlos auf die entsprechenden Einstellungs-Tabs um.
- **Bereinigte Seitenleiste (Keine Doppelungen):**
  - Unter dem Menüpunkt **VERWALTUNG** befindet sich jetzt exklusiv **Einstellungen**, womit alle Verwaltungs- und Systemfunktionen zentral an einem einzigen Ort gebündelt sind.
  - Veraltete, doppelte Navigationspunkte für Einrichtungsassistent und Systemzustand wurden aus der Haupt-Seitenleiste entfernt.
- **Frontend Cache-Robustheit:**
  - Automatisches Neuladen bei veralteten Dynamic-Import-Chunks (`vite:preloadError`), um Client-Fehlermeldungen („error loading dynamically imported module“) nach Version-Updates auf dem Raspberry Pi zu verhindern.

## v2.0.13 (05.11.2026) — Modulares Einstellungsmenü, Layout-Modernisierung & Schnellsuche

- **Modulares & aufgeräumtes Einstellungsmenü:**
  - Kategorisierte Navigationsleiste (`SettingsNavRail.tsx`) mit 5 Themenbereichen: *System & Allgemein*, *Geräte & Hardware*, *Workflow & Druck*, *Netzwerk & Schnittstellen* und *Sicherheit & Zugriff*.
  - Live-Indikatoren, Badge-Zähler und integrierte Echtzeit-Suchfilterung über alle Unterpunkte.
  - Auslagerung und Entrümpelung von `SettingsPage.tsx`:
    - `SetupSettingsSection.tsx`: Zentraler Einrichtungs-Hub (Quick-Setup, Checkliste, Selbsttest, Slicer-Verbindungscheck).
    - `SystemSettingsSection.tsx`: Systemdiagnose mit Live-Logviewer, Verbindungsdiagnose und Support-Bundle-Download.
    - `UpdatesSettingsSection.tsx`: Vollständige Versionsverwaltung, Update-Prüfung, Docker-/Windows-Befehle und GitHub-Release-Hinweise.
  - `SettingsPage.tsx` um fast 400 Zeilen verkleinert und Dateigrößen-Budgetierung abgesenkt.
- **Modernisiertes Layout & optimierte Seitenleiste:**
  - **Logo & Kopfbereich:** Schlankeres Logo (36 px statt 64 px), spart vertikalen Platz und führt per Klick direkt zur Startseite.
  - **Schnellsuche (Command Palette):** Zentral platziert im Hauptmenü (*„Schnellsuche... Ctrl K“*) und als Icon im mobilen Header.
  - **Vertikale Dichte & Scrollbar:** Schlankere Abstände (`py-1.5`) und neue `.sidebar-scroll`-Klasse (kein klobiger Windows-Scrollbalken mehr). Alle Menüpunkte passen ohne Scrollen auf Standard-Displays.
  - **Neugestaltete Collapse-Leiste:** Volle Aktionsleiste mit `Seitenleiste einklappen [` statt alleingestelltem Chevron.
  - **Aufgeräumter Footer:** Redundantes Info-Icon entfernt; eigene Benutzerprofil-Karte für Authentifizierung mit Direktzugriff auf Passwort-Änderung und Abmeldung.
  - **Direktverlinkung:** Update-Button leitet direkt auf den Unterpunkt `Updates` (`/settings?tab=updates`).

## v2.0.12 (05.11.2026) — Telegram-/ntfy-Erweiterungen & aufgeräumte Seitenleiste

- **Telegram Zwei-Wege-Bot:**
  - Live-Kamerafoto auf Abruf über Chat-Befehle (`/live`, `/foto`, `/snap`) sowie per Klick auf den Inline-Button `[📷 Live-Foto]`.
  - Detaillierte Status-Abfrage (`/status`) mit aktuellem Druckstatus, Dateiname, Fortschritt %, Restzeit (ETA), Schichten und Temperaturen.
  - Befehlsführung mit `/help` und Chat-Autorisierungsprüfung gegen konfigurierte Telegram-Provider.
  - Nahtlos über bestehendes Long-Polling (`getUpdates`) ohne externe Webhook-Freigabe.
- **ntfy Aktionsbuttons & Direktnavigation:**
  - Sofort-Navigation via `Click`-Header direkt auf die Detailseite des Druckers (`/printers/<id>`).
  - Schnellauswahl-Aktionen (`Actions`-Header) mit `[📷 Live-Kamera]` (`/cameras`) und `[🖨️ Drucker öffnen]`.
  - Vollautomatisches Abschlussbild bei Druckende an Telegram und ntfy.
- **Seitenleiste aufgeräumt & strukturiert:**
  - Logische Aufteilung: Neue Gruppe „Dateien & Modelle“ trennt den Druck-Workflow von der Modellbibliothek.
  - Einklappbare Kategorien (Akkordeon): Jede Kategorie per Klick auf- und zuklappbar; Zustand bleibt in `localStorage` erhalten.
  - Schlankere Abstände (`py-2`, `space-y-0.5`): Über 180 px Platzersparnis, kein vertikaler Scrollbalken mehr.
  - Mehrsprachige Übersetzungen für `nav.groupLibrary` in 15 Sprachen.

## v2.0.11 (05.11.2026) — Aufräumen: Lifespan-Orchestrierung und Queue-Ausdünnung

Reines Aufräumen und Modularisieren — Technik-Schulden aus `docs/ANALYSE-2026-10-28.md` und Dateigrößen-Budgetierung:

- **main.py unter 2.000 Zeilen:** Auslagerung der verbleibenden Lifespan-Orchestrierung
  (Cloud-HTTP-Clients, Startup-Fixups, Printer-Manager-Callbacks, MQTT-Setup,
  Starten und Stoppen der Hintergrunddienste) in `lifespan_flow.py` (373 Zeilen). `main.py`
  sinkt von 2.282 auf 1.985 Zeilen (Welle 11) und bleibt weit unter der 2.600-Fallgrenze.
- **QueuePage ausgedünnt:** Auslagerung von `GroupBatchModal` (64 Zeilen) und
  `QueueHistorySection` (242 Zeilen). `QueuePage.tsx` schrumpft von 3.091 auf 2.814 Zeilen;
  die Budget-Grenze im Dateigrößen-Wächter wurde von 3.091 auf 2.825 Zeilen gesenkt.
- **Frontend & Tests:** Vollständig grün (`tsc -b`, ESLint, Vitest 61/61 in QueuePage,
  `test_file_size_budget.py`).

## v2.0.10 (04.11.2026) — Aufräumen: Verfügbarkeit ausgelagert, API-Typen geteilt

Reines Aufräumen ohne Funktionsänderung — Technik-Schulden aus `docs/ANALYSE-2026-10-28.md`, damit neue
Anpassungen wieder Platz haben:

- **Druckplaner schrumpft:** Die Verfügbarkeits- und Wecker-Logik (Modell-Suche mit Filament-Matching,
  Aufwecken über Smart Plugs, Idle-Prüfung, Prüfung des vorherigen Auftrags, Blockade bei
  Filament-Knappheit) liegt jetzt als `scheduler/availability.py` (623 Zeilen). `print_scheduler.py`
  von 4 509 auf 3 928 Zeilen, Budget-Grenze 4 550 → 3 950. Gepatchte Namen greifen weiter über die
  `_rt()`-Fassade — 1 055 Planer-Tests und die volle Suite (7 084) laufen unverändert grün.
- **API-Typen geteilt:** `frontend/src/api/types.ts` von 4 221 auf 19 Zeilen reiner Wiederausgabe; die
  Typen liegen in zehn Bereichsdateien (`types_printer`, `types_archive`, `types_slicer`, `types_queue`,
  `types_messaging`, `types_spool`, `types_maintenance`, `types_finance`, `types_user`, `types_system`).
  Importstellen bleiben unverändert; tsc, ESLint und alle 4 411 Oberflächen-Tests grün.
- **Hausrat:** Die toten `spaghetti_check.json` (Feature seit v2.0.8 gelöscht) ist weg; das Signieren der
  Release-Tags lässt sich jetzt auch lokal verifizieren (`docs/VERSIONING.md`).
- **Neue Anleitung:** `docs/GITHUB-ABSICHERUNG.md` führt Schritt für Schritt durch 2FA/Passkey,
  Token-Inventur, Actions-Berechtigungen und die Branch-/Tag-Regelsätze für das öffentliche Repo.

## v2.0.9 (04.11.2026) — Barrierefreiheit: Skip-Link, Live-Region und Sprachmarkierung

- **Skip-Link:** Der erste Tab-Druck bietet „Zum Hauptinhalt springen“; der Sprung landet im
  Inhaltsbereich (`#main-content`) und übernimmt dort den Tastaturfokus — Tastatur- und
  Screenreader-Nutzende überspringen die Seitenleiste. Der Text steht in allen 15 Oberflächensprachen
  (Paritätsprüfung und Vitest 4411/4411 grün).
- **Meldungen für Screenreader:** Der Toast-Bereich ist jetzt eine Live-Region („polite“): neue
  Meldungen werden ohne Tastaturfokus vorgelesen, das Schließen bleibt stumm (kein doppeltes Vorlesen).
- **Sprachmarkierung:** `<html lang>` folgt der in den Einstellungen gewählten Sprache, damit
  Screenreader (NVDA/VoiceOver) Aussprache und Satzregeln der gewählten Sprache verwenden — vorher
  lasen sie z. B. japanische Oberfläche mit deutscher Aussprache vor.

## v2.0.8 (03.11.2026) — KI- und Kameraprüfungen zusammengeführt und korrigiert

- **Eine Übersicht:** Neue Karte „KI & Kameraprüfungen“ unter Einstellungen → Fehlererkennung mit den Schaltern aller
  Erkennungen. Obico und die Erkennung des Druckers werden dort nur angezeigt, Feineinstellungen bleiben verlinkt.
- **Entfernt:** Spaghetti-Prüfung und Leerbett-Prüfung. Die Platte beim Start prüft jetzt nur die Platten-Erkennung, die
  **nach dem Update ausgeschaltet ist** und bei einem Treffer den Druck anhält. Den laufenden Druck überwachen die
  KI-Überwachung und die Erkennung des Druckers. Die ungenutzten Module `spaghetti_detector` und `assistant_tools` sind weg.
- **Assistent:** Eine an den letzten Satz angehängte Aktionsliste bleibt nicht mehr im Antworttext stehen und wird ausgewertet.
- **Bildanalyse:** Sie wartet auf eine laufende Assistenten-Antwort und hat mindestens 300 Sekunden Zeit. Am Pi 5 dauert ein
  neues Bild knapp 3 Minuten, der Kaltstart mehr als 3 Minuten. Während einer Bildanalyse antwortet der Assistent mit „bitte warten“.
- **Bauteil-Wächter:** Umschalten setzt die gespeicherte Schwelle nicht mehr auf 1,0 zurück.
- **Obico:** Der Punkt am Reiter leuchtet nur noch mit eingetragener Server-Adresse.
- **Bekannte Grenzen:** Auf einer gemusterten Platte erkennt die Erste-Schicht-Prüfung fehlendes Material nicht, und der
  Bauteil-Wächter warnt mit der Vorgabe kaum. Das steht jetzt auch an den Schaltern und in `docs/KI-EINRICHTUNG.md`.

## v2.0.7 (03.11.2026) — Spaghetti-Prüfung lässt sich wieder einstellen

- **Spaghetti-Prüfung:** Lesen und Speichern der Einstellung endeten mit Fehler 500, weil die Schnittstelle die Funktionen
  am falschen Objekt aufrief. Zum Prüfen braucht sie weiter die 4-Ecken-Einmessung und eine Leerbett-Referenz; ohne sie
  überspringt sie den Druck.

## v2.0.6 (03.11.2026) — Absturz-Bildschirm: Seite lädt wirklich neu

- **Retry lädt die ganze Seite neu:** Der Knopf auf dem Bildschirm „UI Crash“ zeichnete die Seite nur neu. `React.lazy`
  merkt sich einen gescheiterten Import, deshalb lief das immer wieder in denselben Fehler, bis jemand von Hand mit
  `Strg + F5` neu lud.
- **Nicht ladbare Seitendatei heilt sich einmal selbst:** Scheitert das Laden einer Seitendatei („error loading
  dynamically imported module“, etwa während eines Neustarts nach dem Update oder bei einem Aussetzer im Netz), lädt die
  Seite einmal von selbst neu. Scheitert es innerhalb einer Minute wieder, bleibt der Fehlerbildschirm stehen, damit ein
  ausgefallener Server keine Endlosschleife auslöst.

## v2.0.5 (03.11.2026) — Oberfläche aufgeräumt: einheitliche Seitenköpfe, Systemzustand übersetzt

- **Einheitlicher Seitenkopf:** Neue Komponente `PageHeader` (Titel mit Symbol und Untertitel links, Hauptaktionen
  rechts, Nebenaktionen im Menü „Aktionen“) in Filament, Dateimanager, Statistik und Systemzustand. Filament zeigt
  statt 7 Knöpfen noch 3; CSV-Import/-Export, Lagerorte, Lieferanten und Etiketten liegen im Menü. Im Dateimanager
  liegen Vorschaubilder, Extern verknüpfen, Tags, Papierkorb und Aufräumen im Menü.
- **Einstellungs-Kompass eingeklappt:** In den Einstellungen ist die Karte standardmäßig zu und merkt sich die Wahl,
  die eigentlichen Einstellungen stehen sofort sichtbar. Auf der Seite Einrichtung bleibt sie offen.
- **Systemzustand übersetzt:** 66 Texte der Seite standen in keiner Sprachdatei, dort erschien immer Englisch. Sie
  stehen jetzt in allen 15 Sprachen (von Hand übersetzt, nicht muttersprachlich gegengelesen).
- **Statistik ohne Drucke:** Statt acht leerer Widgets steht eine einzige Hinweiskarte; die Widgets Lieferanten und
  Materialnummern bleiben, weil sie aus dem Bestand rechnen.

## v2.0.4 (03.11.2026) — CI-Härtung: Contract-Fixes, Test-Isolation & Requirements-Paarung

- **Contract-Fixes:** URL-Klassifizierung (`GUARDED_BODY_URLS`: Outbound-Webhook-URL; `NOT_A_FETCH_TARGET`: 
  Stripe-Rückleitungen) und Auth-Allowlist für die bewusst öffentlichen Kundenportal-Routen; `werkzeuge/` wird 
  jetzt ins Test-Image kopiert (API-Doc-Doktest in CI lauffähig, war vormals `ModuleNotFoundError: werkzeuge`).
- **Test-Isolation:** `services/test_plate_detection.py` neu — der alte Rebase-unter-Mocks-Kurs vergiftete das 
  geteilte Modul dauerhaft (`OPENCV_AVAILABLE=False` ohne Restore) und stürzte alles danach im selben Prozess ab 
  (maskierte in CI als "OpenCV not installed" in shard 4/4). Jetzt: normaler Import + Monkeypatch-Fixtures mit 
  Auto-Restore; läuft in beiden Umgebungen (mit und ohne echtem OpenCV).
- **Requirements:** opencv↔numpy-Paarung nach Python-Version gestrickt — Python 3.11 (CI) bleibt bei der 
  ABI-kompatiblen opencv-4.x/NumPy-2.4-Kombination, 3.12+ (Lock/Docker/PC) bei opencv-5.x/NumPy-2.5+.
- **Diagnose-Canary (manuell):** CI-Probe-Job "Backend Probe (cancel-soak)" (Actions → Run workflow) — läuft nur 
  auf Bedarf; der zweimal betroffene shard-4-Lauf ist im Rerun bestätigt grün (Runner-Auslastungs-Rauschen).

## v2.0.3 (03.11.2026) — Update-Selbstheilung: Konflikt-Zustände am Gerät aufräumen

- **Update-Fluss (`updates.py`):** Vor dem Einspielen einer Version bricht der Updater offene Git-Operationen am Gerät
  explizit ab (`rebase`/`merge`/`cherry-pick`/`am --abort`) und macht erst danach den `reset --hard` auf den geprüften,
  signierten Tag. Hintergrund: ein hängender Rebase (z. B. nach einer händischen Git-Aktion auf dem Pi) hinterließ
  Konfliktmarker (`<<<<<<< HEAD`) in ausgelieferten Dateien — die Oberfläche stürzte mit `Unexpected token '<<'` ab,
  weil `reset --hard` allein den Sequencer-Zustand nicht entfernte. Update-Testsuite geprüft (255 grün).
- **Release-Werkzeug (`werkzeuge/release.py`):** `--force` löscht jetzt auch den Remote-Tag, bevor das `git fetch`
  den Verweis zurückholt; ein Tag, der nur auf origin existiert, wird erkannt und nur mit `--force` ersetzt.
  Behebt die „tag already exists"-Falle beim Neutaggen eines Releases.
- **`.gitignore`:** Laufzeit-Dateien am Projektstamm (`assistant.json` und die vorhandenen `service_secrets.key`,
  `wear_tracking.json`, `outbound_webhooks.json`) sind ignoriert, damit die Release-Prüfung am PC nicht an
  Entwickler-Laufzeitdaten hängt.

## v2.0.2 (03.11.2026) — Code-Review-Härtung: Webhook-Zustell-Lifecycle, Quote-Registry in SQLite & echte Flotten-Daten

Aus einem tiefen Review der v2.0-Erweiterungen (SSRF, Fleet, Portal, Verschleiß-Hooks): 15 Fehler behoben, die
Betriebslogik verfälscht oder Angriffsflächen offen gelassen haben. Details und die Testabdeckung stehen hinter dem
Verweis auf die Review-Tests (`tests/unit/test_v2_0_1_hardening.py`, `tests/integration/test_fork_routers_api.py`).

- **Outbound-Webhooks (`outbound_webhooks.py`) — SSRF, Zustell-Lifecycle & Geheimnisse:**
  - Zustellungszeit-DNS-Prüfung: vor jedem Versand wird der Host per `socket.getaddrinfo` aufgelöst und jede resultierende
    Adresse erneut validiert — Domains, die erst während der Zustellung auf private Adressen/Metadatendienste auflösen
    (DNS-Rebinding), laufen in die Sperre. Zahlenkodierungen (`http://2130706433/`, `http://0x7f000001/`, `127.1`)
    werden bei der Registrierung abgelehnt.
  - Zustell-Lifecycle: Backoff-Retry für transiente Fehler (Netzwerk, 5xx, 429 — mit steigender Pause, zweimal), 4xx gilt als
    dauerhaft; `follow_redirects=False` (keine Umleitungen ohne erneute SSRF-Prüfung); nur `200–299` zählt als ausgeliefert.
  - Zustellhistorie & Dead-Letter: jeder Hook führt `failure_streak`, `last_delivery_status/detail/at`; nach 5 Fehlern in
    Folge schaltet die Engine den Hook still (`dead_lettered`, `enabled=false`) — sichtbar in der Verwaltung, von Hand
    reaktivierbar. Backpressure (Semaphore 32) und Registrierungsdeckel (200) bleiben.
  - Geheimnisse: verschlüsselt persistiert über `secret_codec.py` (Fernet; Schlüssel in `service_secrets.key`, POSIX 0600,
    erstes Nutzen erzeugt ihn; Verlust deaktiviert Zustellungen mit klarer Meldung statt unsigniert zu senden). API/Liste
    liefert nur noch maskiertes `secret` + `secret_configured`. Event-Abos werden gegen `ALL_EVENTS` validiert
    (Tippfehler → klare 400 statt still toter Hooks); Persistenzfehler melden `503`.
- **Kunden-Selfservice-Portal (`portal_quote_store.py`):**
  - **Quote-Registry in SQLite:** neue Tabelle `portal_quotes`; `/portal/quote` speichert serverseitig kalkulierte Angebote,
    `/portal/checkout` rechnet ausschließlich registrierte ab (`404` bei unbekannt/abgelaufen) — der Zahlbetrag kommt nie
    aus dem Request, und Neustarts verlieren laufende Stripe-Angebote nicht. TTL 60 Minuten, `purge_expired` räumt auf.
  - **Rate-Limit** (Muster aus `quote_share.py`): pro IP und Endpunktart, 20 Kalkulationen und 6 Checkouts pro Minute (`429`).
  - **URL-Validierung vor der Suche:** ungültige Rückleitungen antworten `400`, bevor der Angebotszustand geprüft wird;
    Stripe-Mindestbetrag 0,50 € geprüft.
  - **Fix des v1.29-Verdrahtungsfehlers:** `success_url` landete im Parameter `customer_email`, `cancel_url` ging verloren —
    Checkout nutzt jetzt Keyword-Argumente.
- **Fleet (`fleet.py`, `fleet_load_balancer.py`):**
  `_gather_fleet_state` liest echte Daten statt Platzhalter: Betttemperatur aus `state.temperatures`, AMS-Trays aus
  `state.raw_data["ams"]` (dict- und list-Form, leere Slots übersprungen, `remain` ist Prozent → Umrechnung mit
  `ASSUMED_SPOOL_CAPACITY_G`), Düsentyp und Betriebsstunden aus dem Wear-Tracker, `plate_clear` als ehrliche Heuristik aus
  dem Druckerstatus. Der Balancer toleriert kaputte Payload-Werte (`_as_float`); `POST /fleet/dispatch` und
  `/fleet/fitness` validieren den Body über `DispatchJobRequest` (Pydantic).
- **Archiv-Hooks & Wear-Alarm (`archive.py`, `wear_tracker.py`):**
  Abschluss-Hooks (Verschleißbuchung + Webhook) laufen in `_emit_lifecycle_hooks()`; `update_archive_status` feuert nur bei
  echtem Statuswechsel — keine doppelten Stundebuchungen oder Webhooks mehr bei wiederholten Aufrufen; Fehler laufen auf
  Warnstufe statt unsichtbar. `maintenance.wear_alert` wird jetzt wirklich gesendet: `record_print_usage` vergleicht den
  Status vor/nach der Buchung (reine Funktion `_overview_from_data`, Reentrant-frei) und verteilt beim Übergang
  `OK → WARN/CRITICAL` genau einmal das Event mit betroffenen Bauteilen. Abrasivkennzeichnung ≠ CF-Filament
  (`DEFAULT_ABRASIVE_MULTIPLIER` 3.0), NaN/inf-Zeiten werden abgewiesen.
- **Plattenwechsel & Assistent (`hardware.py`, `hardware_extension.py`, `assistant_tools.py`):**
  Betttemperatur aus der echten Quelle `state.temperatures["bed"]`, `DEFAULT_MAX_SWAP_TEMP` statt Magiezahl;
  der KI-Not-Halt meldet ehrlich „kein Hardware-Kanal", statt eine nutzlose Instanz zu erschaffen und Erfolg vorzutäuschen.

## v2.0.1 (02.11.2026) — Production Hardening, SSRF Protection, Service Wiring & Wear Hooks

- **SSRF-Schutz & ThreadPool-Sicherheit für Outbound-Webhooks (`outbound_webhooks.py`):**
  Strikte Validierung aller Ziel-URLs gegen Server-Side Request Forgery (SSRF). Blockiert Cloud-Metadatendienste (AWS/GCP/Azure `169.254.169.254`, `metadata.google.internal`) und unberechtigte Loopback-/Privatnetz-Adressen. Ersetzt unbegrenzte Threads durch einen kontrollierten `ThreadPoolExecutor(max_workers=4)`.
- **Thermischer Cooldown-Interlock in Plattenwechsler integriert (`hardware_extension.py`, `hardware.py`):**
  Direkte Kopplung von `cooldown_guard.py` an `HardwareExtension.change_plate()`. Blockiert mechanische Wechselversuche bei Druckbett-Temperaturen über 36,0 °C zur Vermeidung von Verzug und PEI-Beschädigungen (mit explizitem `force`-Override für Notfälle).
- **Automatisches Verschleiß-Tracking bei Druckende (`archive.py`):**
  Erfolgreich beendete Druckaufträge buchen ihre Laufzeit und den Filament-Abrasivitätsfaktor automatisch in `wear_tracker.py` ein und triggern `print.completed` / `print.failed` Webhook-Events.
- **FastAPI-Routen für alle Kern-Dienste (`fork_routers.py`):**
  Neue modulare Endpunkte für Flottenmanagement (`/api/v1/fleet`), Verschleißüberwachung (`/api/v1/maintenance/wear`), Home Assistant Discovery (`/api/v1/discovery/homeassistant`), Kunden-Portal (`/api/v1/portal`) und Webhook-Administration (`/api/v1/webhooks/outbound`).
- **Touchscreen-Kiosk Route (`App.tsx`):**
  Einbindung der `/kiosk`-Route in das React-Frontend für Standalone-Touchdisplays am Raspberry Pi 5.

## v2.0.0 (02.11.2026) — Enterprise Flottenmanagement, Touchscreen-Kiosk & Granulare Rollen (RBAC)

- **Enterprise Flottenmanagement & Dynamisches Load Balancing (`fleet_load_balancer.py`):**
  Intelligente Zuweisung von Druckaufträgen an die optimale Maschine in einer Druckerflotte (P2S, P1S, X1C, A1). Bewertet Betriebsbereitschaft, Düsenkompatibilität (Größe und gehärteter Stahl), AMS-Material/Farb-Matching mit Restmengenprüfung und gleicht die Betriebsstunden der Maschinen gleichmäßig ab.
- **Raspberry Pi 5 Touchscreen-Kiosk-Modus (`KioskModePage.tsx`):**
  Speziell für 7-Zoll und 10-Zoll Pi-Displays am Druckergehäuse optimierte Vollbild-Touchoberfläche mit großen Bedienfeldern: 1-Touch Not-Aus-Schalter mit Quittierungs-Freigabe, Bauplatten-Bereitschaftsbestätigung, Live-Kamerastream, AMS-Slot-Übersicht und extragroße Temperatur- und Fortschrittsanzeige.
- **Rollenbasierte Zugriffskontrolle / RBAC (`rbac_engine.py`):**
  Unterscheidung von 4 strikten Benutzerrollen (`admin`, `operator`, `accounting`, `client_guest`). Schützt sensible Systemeinstellungen, Buchhaltungsdaten und Hardwaresteuerungen nach dem Least-Privilege-Prinzip mit automatischer Menüfilterung und Berechtigungsvalidierung.

## v1.29.0 (02.11.2026) — Live-Spaghetti-Erkennung, Kunden-Selfservice mit Stripe & Abkühl-Schutz

- **In-Print Spaghetti- & Fehldruck-Erkennung (`spaghetti_detector.py`):**
  Echtzeit-Überwachung laufender Druckaufträge über die P2S-Gehäusekamera mittels Kantenchaos-Entropie (Laplace-Varianz & Canny-Ratio). Rolling-Window-Mechanismus verhindert Fehlalarme und empfiehlt nach 3 auffälligen Schichten in Folge den automatischen Druck-Stopp.
- **Kunden-Selfservice-Portal & Sofortkalkulation (`customer_portal.py`):**
  Verbindliche Sofort-Preiskalkulation basierend auf Modellvolumen, Materialdichten (PLA, PETG, ABS, ASA, TPU, PLA-CF), Schichthöhe und Infill mit automatischer Mengenstaffel. Beinhaltet Stripe Checkout Session Generierung und sofortige Druckfreigabe nach Zahlungseingang.
- **Thermische Abkühlüberwachung vor Plattenwechsel (`cooldown_guard.py`):**
  Sicherheits-Interlock für den Plattenwechsler: Mechanische Fahrten und Plattenauswürfe werden blockiert, solange das Druckbett über 36 °C warm ist. Berechnet die verbleibende Abkühlzeit nach Newtons Abkühlungsgesetz und schützt PEI-Platte und Bauteile vor Verzug und Schäden.

## v1.28.0 (02.11.2026) — Agentic Tool-Calling, RAG-Wissensbasis, Verschleiß-Tracker & Webhooks

- **Agentic Tool-Calling Engine für KI-Assistenten (`assistant_tools.py`):**
  Der KI-Assistent kann strukturierte Aktionen und Funktionsaufrufe vorschlagen und ausführen: Not-Halt anfordern, Telemetriedaten auslesen, Druckbett- und Düsentemperatur setzen, HMS-Fehlerdatenbank durchsuchen, Verschleißstatus abfragen und Sofortkalkulationen erstellen.
- **RAG-Wissensbasis über Bambu Lab P2S & HMS-Fehlercodes (`hms_knowledge.py`):**
  Strukturierte Datenbank offizieller Reparatur- und Wartungsanleitungen (z. B. 0300-0100 Nozzle Malfunction, 0500-0300 AMS Overload, 0700-2000 Bed Leveling Fail, Z-Spindelschmierung) mit Schritt-für-Schritt-Anleitungen, benötigten Werkzeugen und Wiki-Referenzen.
- **Verschleißteil- & Predictive-Maintenance-Tracker (`wear_tracker.py`):**
  Präzise Erfassung von Druckstunden für Düsen (getrennt nach Messing und gehärtetem Stahl mit Abrasivitäts-Multiplikatoren für CF/Glow-Filamente), PTFE-Schläuche, Z-Gewindespindeln, Führungsstangen und Aktivkohlefilter mit Health-Status (`OK`, `WARN`, `CRITICAL`).
- **Outbound Webhooks Engine (`outbound_webhooks.py`):**
  Ereignisverteilung an externe Endpunkte (Discord, Slack, Make, Zapier, Home Assistant) bei Druckstart, Fertigstellung, Fehldruck, Plattenwechsel, Not-Aus und Wartungswarnungen mit kryptografischer HMAC-SHA256-Signaturprüfung (`X-PrintLab-Signature`).

## v1.27.0 (02.11.2026) — GiroCode (EPC-QR), G-Code-Viewer, Home Assistant MQTT Discovery & CLAHE

- **EPC-QR-Code (GiroCode) für E-Rechnungen & Angebote (`girocode.py`, `einvoice.py`):**
  Normkonforme Generierung von SEPA EPC-QR-Codes (EPC069-12 v002) als SVG und Base64-PNG für PrintLab-Rechnungen und -Angebote. Ermöglicht Kunden die sekundenschnelle Bezahlung per Banking-App ohne manuelles Eintippen von IBAN, Betrag und Rechnungsnummer.
- **Clientseitiger G-Code-Parser & Datei-Upload im 3D-Canvas (`GCode3DPreview.tsx`):**
  Die 3D-Vorschau unterstützt jetzt das Laden und Parsen beliebiger eigener `.gcode`- und `.3mf`-Dateien per Datei-Upload. Extrahiert Werkzeugbahnen, Schichthöhen, Verfahrwege und berechnet die realen Modellabmessungen in Millimetern.
- **Home Assistant MQTT Discovery Engine (`ha_discovery.py`):**
  Automatische Generierung und Bereitstellung aller Home Assistant MQTT Discovery Entitäten für Druckstatus, Düsen- und Betttemperatur, Fortschritt, Restzeit, Schichtzähler, Not-Halt-Schalter und Gehäusebeleuchtung nach dem `homeassistant/<component>/printlab_<id>/<sensor>/config` Standard.
- **CLAHE-Beleuchtungsfilter für optische Betterkennung (`plate_detection.py`):**
  Integration von Contrast Limited Adaptive Histogram Equalization im LAB-Farbraum vor der Bilddifferenz-Berechnung. Normalisiert schwankende Werkstattbeleuchtung, Schattenwurf und Sonnenlichteinfall zuverlässig.

## v1.26.0 (02.11.2026) — 3D-G-Code-Vorschau, OpenAPI/Postman-Export & Modularisierung der Druckerkarte

- **Interaktiver 3D-G-Code- & Layer-Visualisierer (`GCode3DPreview.tsx`):**
  Neuer interaktiver Canvas-3D-Viewer mit Bambu P2S Druckbett-Simulation (256x256 mm Federstahlplatte), Orbit-Kamera, Schichten-Scrubber, Düsen-Verfahrwegen und Filamentfarb-Umschaltung für geslicte Druckdateien. Direkt integriert auf der Einrichtungs-Seite (`/einrichtung` im Reiter Slicer & Verbindungen).
- **Automatischer OpenAPI 3.1 & Postman-Collection Export (`werkzeuge/export_api_docs.py`):**
  Exportiert die vollständige API-Spezifikation nach `docs/openapi.json`, `postman/schemas/printlab.openapi.json`, `postman/PrintLab.postman_collection.json` und `.postman/resources.yaml`. Getestet durch `test_api_docs_export.py`.
- **Modularisierung der Druckerkarte (`PrinterCard.tsx` -> `PrinterCardModals.tsx`):**
  Druckbett-Prüfungs-Dialog (`PlateCheckResultModal`) und AMS-Trocknungs-Popover (`AmsDryingPopover`) wurden in eigene wiederverwendbare Komponenten ausgelagert. Senkt die Dateigröße der Druckerkarte von 5.737 Zeilen auf unter 5.200 Zeilen und hält das Dateigrößen-Budget dauerhaft ein.

## v1.25.0 (02.11.2026) — KI-Einrichtungs-Assistent & 1-Klick-Autokonfiguration

- **Automatischer KI-Einrichtungs-Assistent (`assistant_autoconfig.py`, `fork_startup.py`):**
  Lokale Modell-Server (Ollama auf `127.0.0.1:11434` oder Host-PC) werden beim Start und in der Inbetriebnahme automatisch erkannt. Wählt das ressourcenschonendste und schnellste Chat-Modell (z. B. `qwen3.5:4b`, `qwen2.5:3b`, `llama3.2:3b`) sowie optionale Bild-Modelle (`qwen2.5vl:3b`) ohne manuelle Konfiguration aus und heizt das Modell im RAM vor (`keep_alive="30m"`), sodass Antworten sofort und ohne Wartezeit generiert werden.
- **Inbetriebnahme-Integration (`/einrichtung` SetupGuidePage & `AssistantPanel.tsx`):**
  Direkte Einbettung des KI-Assistenten in die Einrichtungsseite `/einrichtung` mit prominentem 1-Klick-Erkennungs-Banner, RAM-Vorheiz-Knopf und vorkonfigurierten Schnellstart-Vorschlägen für Drucker-Inbetriebnahme (Bambu Lab P2S LAN-Modus & Entwicklermodus), Slicer-Sidecar und Tailscale-Fernzugriff.
- **Live-Systemkontext für Setup-Fragen (`assistant_context.py`):**
  Der System-Prompt enthält jetzt einen strukturierten Snapshot über den aktuellen Einrichtungsstand (verbundene Drucker, Slicer-API-Status, Tailscale-Fernzugriff, Spoolman-Anbindung und Finanzen), damit die KI gezielt bei der Fehlersuche und den nächsten Schritten unterstützt.

## v1.24.0 (02.11.2026) — Integrierter Slicer (Auto-Start Port 3001/3003) & 10-Bereiche-Ausbau

- **Integrierter PrintLab-Slicer (`builtin_slicer.py`, `pc_slicer.py`, `fork_startup.py`):**
  Startet beim Start von PrintLab automatisch im Hintergrund auf `127.0.0.1:3001` (Bambu Studio API) und `127.0.0.1:3003` (OrcaSlicer API) und aktiviert `use_slicer_api` standardmäßig. Liefert mitgelieferte Standard-Profile (`BUNDLED_PROFILES`) für Bambu Lab P2S (`0.2`/`0.4`/`0.6` Düse), P1S, X1C, A1, A1 mini und H2D sowie Prozess- (`0.08mm`–`0.24mm`) und Filament-Profile (`PLA`, `PETG`, `ABS`, `ASA`, `TPU`). Unterstützt `/health`, `/profiles/bundled`, `/profiles/resolve`, `/slice/progress/{id}` und `/slice` (inkl. nativem Python-STL/3MF-Slicer als Fallback ohne externes Desktop-Slicer-Programm auf dem Raspberry Pi 5).
- **ZUGFeRD-Hybrid-PDF, Plattenwechsel-Bewegungsfolge, Kamera-Durchstich & Modul-Aufteilung:**
  Hybride ZUGFeRD-/Factur-X-PDF-Ausgabe (`embed_zugferd_xml` / `/zugferd.pdf`), G-Code- & Tür-Bewegungsfolge (`build_motion_sequence` / `/plate-wizard/sequence`), Tailscale-Dual-Port (`8000` + `8080 -> 8000`), Stufe 4.3 (Kamera) & Stufe 4.4 (Integrierter Slicer) im Komplett-Durchstich (`werkzeuge/abnahme.py --durchstich`) sowie Auslagerung von `SettingsUserModals.tsx` und `bambu_hms_dispatch.py`.

## v1.23.0 (02.11.2026) — Auto-Einrichtung, Einstellungs-Kompass, XRechnung 3.0 & Komplett-Abnahme

- **Aufgeräumte Einrichtungs-Zentrale (`/einrichtung`) & Einstellungs-Kompass (`QuickSetupHubCard.tsx`):**
  Alle 6 Hauptbereiche (Drucker/LAN/Zugang, PC-Slicer & Druckablauf, P2S-Mechanik & Kamera, Ausfall-Meldung & Tailscale, Lokale KI Ollama, Angebote/Firma/XRechnung inkl. 1-Klick-Aktivierung in der Seitenleiste) sind auf `/einrichtung` und `/settings` mit Live-Status-Ampeln und Direkt-Buttons gebündelt. Offene Punkte der Einrichtungs-Checkliste (`SetupChecklistCard.tsx`) springen per Klick direkt zur passenden Karte; Ausfall-Meldung, Tailscale-Fernzugriff, Slicer-Prüfung und System-Selbsttest liegen jetzt direkt auf `/einrichtung`. Die Einstellungssuche (`settingsSearch.ts`) findet auch deutsche PrintLab-/P2S-Begriffe seitenübergreifend.
- **XRechnung 3.0 (EN 16931), ZUGFeRD-Hybrid-PDF, Plattenwechsel-Bewegungsfolge & Angebots-Schutz:**
  E-Rechnungen (`einvoice.py`) schreiben vollständig die elektronischen Endpunkt-Adressen (`cbc:EndpointID` BT-34/BT-49), das Lieferdatum (`cac:Delivery/cbc:ActualDeliveryDate` BT-72) sowie den Netto-Einzelpreis (`cac:Price/cbc:PriceAmount` BT-146) und lassen sich als hybrides ZUGFeRD-/Factur-X-PDF (`embed_zugferd_xml` / `/zugferd.pdf`) herunterladen. Der Einmess-Assistent (`plate_wizard.py`) erzeugt nach abgeschlossener 5-Schritt-Kalibrierung die vollständige G-Code- und Tür-Bewegungsfolge (`build_motion_sequence` / `/plate-wizard/sequence`). Öffentliche Angebots-Links (`quote_share.py`) begrenzen Zugriffe pro IP (Rate-Limit).
  E-Rechnungen (`einvoice.py`) schreiben jetzt vollständig die elektronischen Endpunkt-Adressen (`cbc:EndpointID` BT-34/BT-49 mit `@schemeID="EM"`), das Lieferdatum (`cac:Delivery/cbc:ActualDeliveryDate` BT-72) sowie den Netto-Einzelpreis (`cac:Price/cbc:PriceAmount` BT-146). Öffentliche Angebots-Links (`quote_share.py`) begrenzen Zugriffe pro IP (Rate-Limit gegen Token-Scanning).
- **Komplett-Abnahme (`werkzeuge/abnahme.py --durchstich`) & Modul-Aufteilung:**
  `abnahme.py` prüft neben dem Systemzustand auch XRechnung-3.0-Konformität, GPIO-Pin-Konflikte (`gpio_mechanik.beispiel.json`), lokale Ollama-Modelle sowie im Komplett-Durchstich den gesamten Ablauf von Angebots-Freigabe über Hardware-Trockenlauf/Not-Halt bis zum 5-stufigen Einmess-Assistenten. Außerdem wurden `scheduler/watchdog.py` aus `print_scheduler.py` und `types_library_system.ts` aus `types.ts` ausgelagert und `release_pruefen.py` prüft nun auch `pyproject.toml`.

- **Auto-Einrichtung:** Auf der Seite **Einrichtung** steht über dem Assistenten eine Karte, die zeigt, was PrintLab
  ohne Zugangsdaten selbst einrichten kann, und es mit einem Knopf erledigt: Update-Schutz in die systemd-Unit
  eintragen, den lokalen Assistenten einschalten (nur wenn Ollama läuft und das Modell da ist) und den Fernzugriff
  über Tailscale einrichten (nur mit eingeschalteter Anmeldung; den Anmelde-Link öffnet weiter der Benutzer).
  Jeder Schritt ist wiederholbar, ein gescheiterter Schritt stoppt die anderen nicht, und die Meldung nennt nur die
  Fehlerart, nie den Text des Fehlers. Neue Routen `GET/POST /system/auto-setup` (Vorschau ändert nichts; Ausführen
  braucht die Einstellungsberechtigung und läuft nie doppelt). Bewusst nicht automatisch: Anmeldung (Passwort wählt
  der Benutzer), Drucker (Zugangscode), Meldewege (Token), Signaturschlüssel (der private Teil gehört nicht auf den Pi).
  17 Backend- und 4 Frontend-Tests, 13 neue Texte in allen 15 Sprachen (`autoSetup.*`).

## v1.22.0 (01.11.2026) — Nach dem Slicen direkt drucken; Ausfälle früher sichtbar

- **„Jetzt drucken“ nach dem Slicen:** Die Fertigmeldung trägt jetzt einen Knopf. Er öffnet den normalen Druckdialog
  mit dem geslicten `.gcode.3mf` (Bibliotheksdatei oder Archiv) — Druckerauswahl, AMS-Zuordnung und Zeitplan wie im
  Dateimanager. Die Meldung bleibt dafür 15 s stehen; ohne Ergebnis (ältere Aufträge) bleibt sie wie bisher.
- **Slicer-Ausfall in der Kopfzeile:** Antwortet das konfigurierte Sidecar nicht, steht auf jeder Seite ein gelber
  Hinweis mit der Adresse und einem Link zu den Slicer-Einstellungen. Alle 60 s nachgefragt; ein Fehler der Abfrage
  selbst (ältere Installation) zeigt nichts. Solange kein Slicer eingerichtet ist, erscheint nichts.
- **Fehlgeschlagene Slices per Browser-Meldung:** Läuft der Slice im Hintergrund und der Browser ist zu, meldet
  PrintLab den Fehlschlag per Web Push — bei „Sidecar nicht erreichbar“ und „Zeitlimit“ mit der Handlungsanweisung,
  sonst mit dem Dateinamen. Der Klick öffnet die Einstellungen bzw. den Dateimanager.
- **Aufgeräumt:** Die Listen- und Filterleiste der Drucker liegt in `PrinterToolbar.tsx` (497 Zeilen), die beiden
  Auswahlzweige des Planers in `scheduler/selection.py` (Mixin, `QueuePass` erbt). `PrintersPage.tsx` fällt von
  1 985 auf 1 614 Zeilen, `queue_pass.py` von 1 032 auf 582; die Größengrenzen sind nachgezogen.
- **Tests:** ein Frontend-Test für den Druck-Knopf in der Fertigmeldung, ein Backend-Test für die Push-Meldung; dazu
  die bestehenden 50 Layout-/Tracker-Tests und 98 Druckerseiten-Tests. Die 1 060 Planer- und Warteschlangen-Tests
  bleiben grün.
- **Abnahme:** [`docs/ABNAHME-PI.md`](docs/ABNAHME-PI.md) führt jetzt in Abschnitt 1b durch Slicer-Prüfung, 3MF-Drop,
  „Jetzt drucken“ und die Push-Meldung; alle Versionsangaben stehen auf 1.22.0.

## v1.21.3 (01.11.2026) — Slicer-Verbindung dort prüfen, wo man sie einträgt

- **„Verbindung prüfen“ bei den Slicer-Einstellungen:** Der Knopf fragt `/slicer/status` und zeigt die tatsächlich
  benutzte Adresse, die Version des Sidecars oder den Grund des Fehlschlags. Geprüft wird die **gespeicherte** Adresse;
  der Hinweis darunter sagt das. Damit findet man den `localhost`-Fehler auf dem Pi direkt neben dem Eingabefeld,
  statt erst beim Slicen.
- **Texte in allen 15 Sprachen**, drei Frontend-Tests für erreichbar, nicht erreichbar (mit Adresse) und nicht
  eingerichtet.

## v1.21.2 (01.11.2026) — Slicer sagt, was los ist; 3MF führt zum Slicen

- **Slicer wird vor dem Slicen geprüft:** `GET /slicer/status` fragt das Sidecar. Die Slice-Maske nennt die
  tatsächlich benutzte Adresse und sperrt „Slicen“, wenn der Dienst nicht antwortet — statt den Nutzer in einen
  Fehlschlag laufen zu lassen. Der Hinweis sagt auch, dass auf dem Pi die Adresse des PCs stehen muss und nicht
  `localhost`. Ein Fehler der Statusabfrage selbst (ältere Installation) sperrt nichts.
- **Fehlerursache wird übersetzt:** Fehlgeschlagene Slice-Aufträge tragen jetzt ein `error_kind`. Bei „Sidecar nicht
  erreichbar“ und „Zeitlimit“ steht eine Handlungsanweisung über der technischen Meldung, statt nur
  „Slicer sidecar unreachable: All connection attempts failed“ in Englisch (alle 15 Sprachen).
- **3MF-Projekt führt zum Slicen:** Wird eine noch nicht geslicte `.3mf` auf eine Druckerkarte gezogen oder im
  Druck-Dialog ausgewählt, wird sie hochgeladen und der Slicedialog geöffnet. Vorher blieb nur die Meldung „Nur
  .gcode- und .gcode.3mf-Dateien können gedruckt werden“ — eine Sackgasse, weil ein Projekt erst geslict werden muss.
- **Tests:** drei für den Status-Endpunkt, zwei für die Fehlerursache (Einheit und durchgereichter Auftrag), je einer
  für die Sperre der Maske und den 3MF-Drop; die bestehenden 93 Slice-Modal-Tests bleiben grün.

## v1.21.1 (01.11.2026) — Pfadprüfung nachgezogen

- **CI wieder grün:** Die Pfadprüfung (`test_no_unsafe_path_joins`) meldete die neuen Stellen in
  `services/factory_reset.py`. Die Konstanten-Joins sind mit `# SEC-PATH-OK:` und Begründung versehen; der Zielordner
  aus der Auftragsdatei wird jetzt zusätzlich per `RESET_NAME_RX` geprüft, damit ein manipulierter Eintrag keine
  Daten aus dem Datenordner heraus verschieben kann (neuer Test).
- **Pfadprüfung läuft jetzt auch unter Windows:** Der Test las die Quellen ohne Kodierung und brach dort mit cp1252
  ab; deshalb stand er auf der Windows-Skip-Liste und der Fehler fiel erst in der Linux-CI auf. Er liest jetzt UTF-8
  und ist von der Skip-Liste gestrichen.

## v1.21.0 (01.11.2026) — Schnellsuche, Browser-Meldungen, Wartung

- **Meldungssprache wirkt jetzt:** Die eingebauten Texte der fünf häufigsten Druck-Ereignisse (Fertig, Fehler,
  pausiert, abgebrochen, Fortschritt) gibt es in Deutsch, Englisch, Spanisch, Französisch, Italienisch, Japanisch und
  Chinesisch; selbst geschriebene Vorlagen bleiben unverändert. Bisher war die Einstellung ohne Wirkung.
- **Browser-Meldungen (Web Push):** Jedes Gerät schaltet sie in **Einstellungen → Benachrichtigungen** selbst ein;
  dafür ist kein Meldeweg wie Telegram nötig. Der Server verschlüsselt jede Meldung nach RFC 8291 und signiert den
  Versand mit VAPID (RFC 8292) — nur mit `cryptography` und `httpx`, ohne `pywebpush` auf dem Pi. Abos liegen in
  `push_subscriptions`, der Schlüssel in den Einstellungen; ein Abo, das der Browser verwirft (HTTP 404/410), fliegt
  nach dem fünften Fehlschlag raus. Die neue Karte schickt auf Wunsch eine Testmeldung. Voraussetzung ist HTTPS oder
  `localhost` auf demselben Gerät — über Tailscale funktioniert es ebenso.
- **Globale Suche (Strg+K / ⌘K):** Eine Befehlspalette springt zu jeder Seite und durchsucht Drucker, Bibliothek,
  Archiv und Warteschlange. Die Treffer öffnen die passende Liste bereits mit dem Suchbegriff (`?search=…`).
  Neue Route `GET /search`; sie prüft dieselben Besitzrechte wie die Listen (eigene statt aller Archive, Papierkorb
  bleibt draußen) und maskiert `%`/`_` als Literale.
- **Werkseinstellungen lassen sich zurückholen:** Die Karte listet vorhandene Reset-Ordner und stellt einen davon
  wieder her; der aktuelle Stand wandert dabei nach `before-restore-…`, wird also ebenfalls nicht gelöscht.
- **Datenbank-Wartung:** `quick_check` und `VACUUM` als Dienst und Route, mit Karte in **Wartung**.
- **Oberfläche wird komprimiert:** Der Static-Handler liefert große Textdateien als gzip mit `Vary: Accept-Encoding`
  und einem Cache; gehashte Build-Dateien bleiben unverändert ein Jahr im Browser.

## v1.20.0 (31.10.2026) — Sortierte Oberfläche, geübte lokale KI

- **Seitenleiste gegliedert:** Drucken, Material & Kosten, Betrieb und Verwaltung; die eigene Reihenfolge gilt weiter
  innerhalb der Gruppe, externe Links und künftige Einträge stehen sichtbar unter „Mehr“. Tastenkürzel 1–9 folgen der
  angezeigten Reihenfolge.
- **Systemzustand im Menü:** Die bisher nur über die direkte Adresse erreichbare Seite `/system` ist jetzt verlinkt
  (`settings:read`). Die ungenutzte Seite `UsersPage.tsx` ist entfernt.
- **Lokale Überwachung praxistauglicher:** Das Bildmodell bleibt bei Ollama 30 Minuten im Speicher (`keep_alive`), statt
  bei jeder Runde neu zu laden. Pro Prüfung werden 1–3 Bilder aufgenommen (Standard 2) und nach Mehrheit entschieden;
  ein einzelner Ausreißer löst nichts aus. Die Mindest-Sicherheit lässt sich je Fehlerbild festlegen.
- **Treffer führen zur Hilfe:** Jede Trefferzeile hat „Fehlerbild öffnen“ und springt zur passenden Karte mit Erklärung,
  Slicer-Hinweisen und Gegenmaßnahmen.
- **Systemprüfung** meldet zusätzlich die laufende Überwachung: aus, noch nicht gelaufen, letzter Fehler oder „läuft,
  zuletzt …“.

## v1.19.0 (30.10.2026) — Aufgeräumt: stille Fehler, große Dateien, feste Builds

- **Keine stillen Ausnahmen mehr:** Alle 43 `except Exception: pass` in Routen, Planer, virtuellem Drucker und
  Support-Code protokollieren jetzt mit `logger.debug(..., exc_info=True)`; das Budget in
  `test_error_handling_budget.py` steht auf 0. Ein Fehler bleibt sichtbar, ohne das Protokoll im Normalbetrieb
  zu fluten.
- **Fehlerhilfe vollständig einstellbar:** Abstand und Höchstzahl je Druck sind in der KI-Karte einstellbar
  (bisher nur die Schwellen). Der Server prüft die zusammengeführte Konfiguration und lehnt „zu warm“ ≥ „zu kalt“
  mit einer erklärenden Meldung ab — die Karte schickt immer nur ein Feld. Zwei neue Schlüssel in allen 15 Sprachen.
- **Druckplaner weiter geteilt:** `_select` ist nur noch eine Schleife; die Auswahl nach Anheftung und nach Modell
  liegen als `_select_pinned` und `_select_for_model` daneben, die `continue` der Auftragsschleife sind `return`
  geworden. `queue_pass.py` bleibt mit 1 032 Zeilen unter der Vorgabe.
- **Zwei große Frontend-Dateien zerlegt, Importe unverändert:** `PrintersPage.tsx` 9 656 → 1 985 Zeilen
  (`PrinterCard.tsx` 6 255, `PrinterCardParts.tsx` 1 134, `printerCardHelpers.ts` 290); `client.ts` 9 699 → 1 008
  (`core.ts` 270, `types.ts` 4 754, `endpoints.ts` 4 017). `client.ts` bleibt die Fassade, deshalb musste kein
  Import angefasst werden; das Größenbudget nennt die neuen Grenzen.
- **Docker-Image mit festen Versionen:** Der Bau installiert mit `-c requirements.lock`. Damit zieht ein frischer
  Build dieselbe Kombination wie die native Installation, statt jeweils die neuesten Wheels. (Auf diesem Rechner
  ohne Docker nicht gebaut.)
- **Weniger fehlschlagende Tests unter Last:** Die asynchronen Abfragen der Oberfläche warten 5 s statt 1 s;
  einzeln grüne Tests fielen im 334-Dateien-Lauf sonst gelegentlich durch die Standardwartezeit. `lokal_pruefen.py`
  bricht beim Umleiten der Ausgabe nicht mehr an Sonderzeichen der Windows-Konsole ab.
- **Übersetzungs-Glossar:** `docs/UEBERSETZUNG-GLOSSAR.md` sammelt Begriffe, Satzvorlagen und eine Prüfliste für die
  Gegenleser der 13 Nebensprachen.
- **Prüfstand:** 14 518 Backend-Tests bestanden (186 übersprungen), Frontend-Typprüfung, ESLint und alle
  Übersetzungen grün; die Kette MakerWorld → Bibliothek → Warteschlange ist mit 566 Integrationstests abgesichert.
  Slicer-Upload und der druckende Drucker brauchen weiterhin Gerät und Slicer (`docs/ABNAHME-PI.md`).

## v1.18.0 (30.10.2026) — Laufende Überwachung, Modellwahl und aufgeräumter Planer

- **Laufende Fehlerüberwachung auf dem Pi:** Während eines Drucks holt PrintLab im eingestellten Abstand
  (Standard 10 Minuten) ein Kamerabild und prüft es mit dem lokalen Bildmodell. Gehandelt wird erst nach mehreren
  gleichen Treffern in Folge — dann Bild in die Sammlung, Treffer für die Fehlerhilfe, Meldung und optional Pause,
  damit eine einzelne Fehlwarnung keinen Druck abbricht. Standardmäßig aus; Abstand und nötige Bestätigungen sind
  einstellbar. Neue Routen `GET/PUT /error-help/ai-watch` und `POST /error-help/ai-watch/check`; die KI-Karte hat
  Schalter, „Jetzt prüfen“ und den Zustand je Drucker. Abschnitt „Laufende Überwachung (lokal)“ in
  `docs/KI-EINRICHTUNG.md`.
- **Kameraaufnahme nur einmal beschrieben:** Die Obico-Erkennung und die lokale Überwachung teilen sich eine
  Aufnahmefunktion (Buffer bei aktivem Viewer, sonst externe Kamera), damit beide denselben Weg gehen.
- **Bildmodell als Auswahl:** Statt Freitext bietet die KI-Karte die auf dem Server installierten Modelle an und
  zeigt sie an; „Assistenten-Modell“ bleibt als leere Auswahl daneben bestehen.
- **„Hinweis als eigene Meldung“ ist ein sichtbarer Schalter** (`error_scan_notify`, Standard an, gespeichert mit
  den Assistenten-Einstellungen). Der Hinweis nennt den nötigen Kanal-Schalter „Nachrichten verbundener Apps“,
  sonst käme er nirgends an.
- **Angebots-Link ist immer absolut:** Ohne gepflegte Basis-URL bestand der kopierte Link nur aus dem Pfad und
  war damit unbrauchbar; jetzt springt die Adresse der Anfrage ein.
- **Planer aufgeräumt (intern):** `print_scheduler.py` von 8 740 auf 4 846 Zeilen. Filament- und AMS-Abgleich,
  Düsenprüfung, Kammergrenzen, Übertragung, Startbefehl und die Warteschlangen-Runde liegen in eigenen Modulen
  unter `backend/app/services/scheduler/`, Vorheizen und Trocknung als Mixins; alle Namen bleiben über
  `print_scheduler` erreichbar, Verhalten unverändert. Die Dateigrenze im Test wurde nachgezogen.
- `docs/ABNAHME-PI.md`: Arbeitsliste für eine Sitzung am Gerät (Update → Angebots-Link → Hardware) mit
  Erwartungen, Abbruchpunkten und Protokoll; README, Abnahme-Doku und `werkzeuge/abnahme.py` verweisen darauf.

## v1.17.1 (30.10.2026) — Fehlerbehebungen zu 1.17.0

- **Frontend-Typprüfung:** Die neuen API-Typen werden direkt aus `api/forkApi.ts` importiert; `client.ts` gibt sie
  nicht weiter und liegt am Zeilenbudget. `npm run typecheck` (das ist `tsc -b`, nicht `tsc --noEmit`) ist grün.
- **Englische Übersetzung:** Drei deutsche Meldungen aus Hardware und Wartung („Drucker ist nicht verbunden.“,
  „Während eines Drucks gesperrt.“) haben wieder eine Regel in `i18n/fork_messages.py`.
- **Sicherheit der neuen Download-Route:** Das MP4 aus den Schichtbildern verlangt jetzt `archives:read`; die
  Oberfläche lädt es mit Anmeldung statt über einen offenen Link. Die öffentliche Angebotsseite (GET/POST) steht
  mit Begründung in der Routen-Allowlist des Sicherheitstests.

## v1.17.0 (30.10.2026) — Angebots-Link, E-Rechnung, Zeitraffer und Einmess-Assistent

- **Plattenwechsel bricht bei unbekannter Betttemperatur ab.** Bisher lief er dann sofort los — bei getrennter
  MQTT-Verbindung auch auf einer heißen Platte. Jetzt fail-closed mit Eintrag im Audit-Log.
- **Türprüfung liest den Endschalter wirklich.** Mit konfiguriertem `door_status_command` wird vor dem Wechsel
  frisch gelesen; ohne Endschalter steht „ohne Endschalter“ im Ergebnis. Vorher galt der gespeicherte Zustand,
  nach einem Neustart immer „geschlossen“.
- **Plattenwechsel-Einstellungen je Drucker** (`hardware_{id}.json`); ein vorhandener globaler Bestand gilt
  weiter als Vorlage. Änderung an einem Drucker wirkt nicht mehr auf die anderen.
- **Fehlerbild-Aufräumen** rechnet die Obergrenze auf die verbliebenen Bilder: 600 Bilder mit 300 alten ergaben
  vorher 300 statt 500.
- **Magazin-Änderung ohne Teilwirkung:** eine abgelehnte Sammeländerung lässt den Zustand unverändert.
- **KI-Trefferquote je Fehlerbild** in der Fehlerhilfe (richtig/falsch/Quote); Bewertungen werden begrenzt und
  mit gelöschten Treffern entfernt.
- **KI:** Bild wird vor dem Umwandeln verkleinert (Speicher auf dem Pi), Hintergrundaufgaben werden gehalten,
  und die Bildanalyse hat ein Zeitbudget.
- **Geldbeträge** in Angebot und Rechnung werden in Cent (`Decimal`) gerechnet und einmal gerundet.
- **Assistent:** „Abbrechen“ stoppt eine laufende Antwort, „Neues Gespräch“ bricht sie ab.
- Fehlermeldungen der Hardware-, Wartungs-, Kalibrier- und Spaghetti-Routen sind jetzt deutsch.
- **Trainingsset-Export:** Die Fehlerbild-Sammlung lässt sich als ZIP herunterladen (Bilder, `labels.jsonl` mit
  Fehlerbild, Sicherheit, Begründung und eigener Bewertung, `meta.json`, `README.txt`) — direkt in der Fehlerhilfe.
- **KI-Hinweis als eigene Meldung:** Ist die KI-Erkennung eingeschaltet, kommt nach einer Fehlwarnung ein kurzer
  Hinweis mit Fehlerbild, Sicherheit und Begründung. Die Warnung selbst wartet nie auf das Bildmodell.
- **Filter für die Fehlerbild-Sammlung** in der Fehlerhilfe (Name, Anlass, Zeitpunkt) statt nur der letzten 20.
- `requirements.lock` mit festen Versionen; Installation: `pip install -r requirements.txt -c requirements.lock`.
- Neuer Test als Obergrenze für stille `except: pass`-Handler; MakerWorld-Hilfsfunktionen in ein eigenes Modul
  ausgelagert und geprüft.
- **Öffentlicher Angebots-Link:** Ein Angebot lässt sich als Link verschicken, den der Kunde ohne Anmeldung
  öffnet und dort zusagt oder ablehnt. Das Merkmal in der Adresse ist die Berechtigung, der Link läuft nach
  einer Frist ab, ein neuer Link macht den alten ungültig, und zurückziehen geht jederzeit. Die Seite zeigt nur
  Kundenangaben, Positionen und Gesamtpreis — nicht die interne Kalkulation. Antworten sind einmalig; ein
  doppelt abgeschicktes Formular dreht die Entscheidung nicht um.
- **Zeitraffer als MP4 aus den Schichtbildern:** Mit eingeschalteter Aufbewahrung bleiben die Schichtbilder
  nach dem Druck liegen (`data/timelapse_kept/`), und im Zeitraffer-Editor lässt sich daraus mit wählbarer
  Bildrate ein MP4 rendern (`data/timelapse_exports/`). Aufbewahrung mit Tages- und Anzahlgrenzen; auch ein
  fehlgeschlagenes automatisches Stechen kostet die Bilder dann nicht mehr.
- **Automatische Umverteilung:** Scheitert ein Auftrag (nicht: Abbruch durch den Benutzer), wird er einmal als
  neuer Eintrag auf ein anderes Gerät desselben Modells eingereiht. Je Auftragskette eine Merkliste in
  `data/auto_requeue_log.json`, Meldung über `queue_job_added`, Protokoll in der Oberfläche. Standardmäßig aus.
- **E-Rechnung (XRechnung, UBL):** Rechnungen lassen sich als XRechnung-XML herunterladen. Fehlende
  Pflichtangaben (Firma, Anschrift, Steuernummer/USt-IdNr., E-Mail, Kunde, Daten, Steuerhinweis) werden vorher
  als Liste gemeldet und es wird kein XML erzeugt. **Nicht** zertifiziert und nicht gegen den KoSIT-Validator
  geprüft; kein ZUGFeRD. Die rechtliche Prüfung bleibt bei der Steuerberatung.
- **Nachbestellvorschlag:** Auf Basis der vorhandenen Prognose (`stock_forecast`): fällige Materialien mit
  Bestellmenge in ganzen Rollen, günstigstem Lieferanten aus den gepflegten Angeboten und geschätzten Kosten;
  im Spoolman-Betrieb aus dem Spoolman-Bestand (ohne Preise). Zielbestand und Mindestmenge einstellbar.
- **Einmess-Assistent Plattenwechsel:** Referenz-, Aufnahme-, Ablage- und optionale Magazinposition, Tür- und
  Endschalterprüfung, Probelauf, Name der einmessenden Person; Abschluss nur mit allen Pflichtschritten und
  ohne doppelte Positionen. Ein begonnener, nicht abgeschlossener Assistent sperrt den Plattenwechsel — auch
  die Automatik. Protokoll als Textdatei. Der Assistent erzeugt **keine** Bewegungsfolge; die muss am Gerät
  erprobt werden.

## v1.16.0 (30.10.2026) — KI-Erkennung mit Rückmeldung und Anleitung

- **Rückmeldung pro Treffer:** Jeder erkannte Fehler lässt sich als richtig oder falsch bewerten; die letzte Bewertung zählt
  und die Summe steht in der KI-Karte. Damit lässt sich die Trefferquote mit eigenen Bildern messen.
- **Verlauf je Fehlerbild:** Von der Fehlerkarte aus die letzten 50 Treffer mit Datum, Sicherheit, Begründung und Bewertung.
- **Stapelprüfung der Sammlung:** Gesammelte Fehlerbilder im Hintergrund durchprüfen (zehn je Lauf), mit Fortschritt;
  bereits geprüfte Bilder werden übersprungen.
- **Systemprüfung** meldet jetzt auch die KI-Fehlererkennung: ausgeschaltet, Server weg, Bildmodell fehlt (mit
  `ollama pull …`) oder bereit — samt Dauer der letzten Bildprüfung.
- **Anleitung** `docs/KI-EINRICHTUNG.md`: Ollama einrichten, `qwen2.5:3b` als Text-Assistent und **`qwen2.5vl:3b` als
  Bildmodell**. In der Oberfläche steht der Hinweis, dass `qwen2.5:3b` keine Bilder sehen kann.
- Die aufgeklappte Fehlerkarte zeigt die Zeichnung groß statt nur als Miniatur.

## v1.15.0 (30.10.2026) — Fehlererkennung mit lokaler KI

- **KI-Fehlererkennung (lokal):** Ein Kamerabild wird vom lokalen Bildmodell (Ollama oder OpenAI-kompatibler Server,
  z. B. `qwen3.5:4b`) einem der zwölf Fehlerbilder zugeordnet. Treffer ab der eingestellten Mindest-Sicherheit landen in
  `data/ai_error_findings.jsonl`; die Fehlerkarte zeigt „N× erkannt“ samt letzter Begründung und Datum.
- **Prüfen per Klick:** In der Fehlerhilfe ein Bild hochladen oder ein gesammeltes Fehlerbild auswählen und analysieren.
  Die Karte nennt Modellstatus, fehlende Modelle (mit `ollama pull …`), Bildmodell und Mindest-Sicherheit.
- **Automatisch möglich:** Nach AI- und „Platte nicht frei“-Warnungen prüft PrintLab das Bild im Hintergrund — nur wenn die
  Erkennung ausdrücklich eingeschaltet ist. **Standardmäßig aus**; die Erkennung ist ein Hinweis, keine Diagnose.
- Live gegen den lokalen Server geprüft: gültiges JSON, ein Software-Screenshot ergab korrekt „kein Fehlerbild“. Ein
  Bildmodell braucht auf dem Entwicklungs-PC rund 85–150 s pro Bild (erster Aufruf inkl. Modellstart länger); für den Pi
  ist ein kleineres Vision-Modell sinnvoll.
- Intern: `services/ai_error_scan.py`, Endpunkte `/error-help/ai-scan/*`, Erweiterung der Assistenten-Einstellungen
  (`vision_model`, `error_scan_enabled`, `error_scan_min_confidence`).

## v1.14.1 (30.10.2026) — Bilder zur Fehlerhilfe

- **Jedes Fehlerbild hat eine Zeichnung:** zwölf schematische Darstellungen (Heat Creep, Unter-/Überextrusion, Stringing,
  Warping, Curling, Elefantenfuß, Schichtablösung, Layer Shift, Ghosting, Z-Wobble, Bauteil-Verlust) stehen links neben
  dem Titel der Fehlerkarte. Zeichnungen statt Fotos: keine Lizenzfragen, offline auf dem Pi verfügbar und in hellem wie
  dunklem Design lesbar.
- Intern: `CoverImage` (Titelbild mit Vollbild-Overlay) nach `components/printer/CoverImage.tsx` ausgelagert;
  `PrintersPage.tsx` fällt auf 9 656 Zeilen, das Budget sinkt auf 9 675.

## v1.14.0 (30.10.2026) — MakerWorld im MakerWorld-Layout

- **MakerWorld-Seite neu gestaltet:** Kopfleiste mit Logo, großer Suche, Sammlungsauswahl und Konto-Zugang; die Importe stehen
  als bildstarke Karten in einem responsiven Raster (zwei bis fünf Spalten). Beim Darüberfahren erscheinen die Aktionen
  „In der Bibliothek öffnen“, „Im Slicer öffnen/slicen“ und „Original auf MakerWorld öffnen“. Suche und Sammlungen filtern
  den Bestand, Trefferzahl und leerer Zustand sind beschriftet.
- Der Import über einen Modell-Link (URL einfügen → Platten → importieren) bleibt unverändert.
- Ehrliche Grenze: MakerWorlds Such-Schnittstelle liefert auch bei direkter Anfrage leere Ergebnisse (`total: 0`); die Seite
  zeigt deshalb die eigenen MakerWorld-Importe im MakerWorld-Layout, neue Modelle kommen über den Modell-Link.

## v1.13.1 (29.10.2026) — Schneller, aufgeräumt, sicher veröffentlicht

- **Deutlich schnellerer Start:** Jede Seite wird erst beim Aufruf geladen, und eingebündelt sind nur noch Deutsch und Englisch — die
  übrigen zwölf Sprachen kommen beim Umschalten nach. Das Startbündel schrumpft von rund 11 MB auf 1,4 MB; auf dem Pi, über
  Tailscale und am Handy ist die Oberfläche damit spürbar eher da.
- **Fehlerhilfe:** Die beiden Schwellen der Bauraum-Regeln („zu warm ab“, „zu kalt unter“) sind jetzt direkt in der Oberfläche
  einstellbar; gespeichert wird beim Verlassen des Feldes.
- **Release-Skript** (`werkzeuge/release.py`): prüft Version, Changelog und `static/`, verweigert einen unsauberen Arbeitsbaum
  und pusht den signierten Tag erst nach bestandener Prüfung. Der Fall vom Vormittag (Tag auf einer alten Version, kein Release)
  kann so nicht wieder passieren; `docs/VERSIONING.md` beschreibt den Weg.
- Intern: Anzeige-Bausteine der Druckerkarte ins eigene Modul `components/printer/StatusIndicators.tsx` ausgelagert
  (`PrintersPage.tsx` 10 130 → 9 754 Zeilen, Budget mitgesenkt).

## v1.13.0 (29.10.2026) — Fehlerhilfe

- **Fehlerhilfe** (neue Seite im Seitenmenü): zwölf Fehlerbilder aus der Werkstattpraxis in vier Gruppen — Extrusion,
  Thermik/Haftung, Mechanik, Slicer/Geometrie. Jedes nennt Erklärung, typische Ursachen, was im Slicer hilft und was am
  Drucker möglich ist; dazu eine durchsuchbare Liste und Kategoriefilter. Die Oberfläche ist in allen 15 Sprachen
  übersetzt, die Fließtexte liegen auf Deutsch vor (englische Titel und Kurzfassungen).
- **Sofort-Eingriffe am laufenden Druck:** Kammer-/Zusatz-/Bauteillüfter, Bett ±, Düse ±, Fluss ±, Silent-Tempo. Jeder
  Eingriff wird bestätigt, nur während eines Drucks angeboten und landet im Audit-Log. Rechte: `printers:control`.
- **Automatische Gegenmaßnahmen (optional):** zwei Regeln, die sich aus den Daten sicher ableiten lassen — Bauraum zu
  warm bei PLA/PETG/TPU (Lüfter auf, Bett etwas kühler) und Bauraum zu kalt bei ABS/ASA/PC/PA (Lüfter aus). Nur je
  Drucker freigeschaltet, nur mit echtem Bauraumfühler und eindeutigem Filament, höchstens drei Eingriffe je Regel und
  Druck im Abstand von mindestens zehn Minuten, mit Rückkopplung an das Audit-Log. **Standardmäßig Trockenlauf**: PrintLab
  protokolliert nur, was es getan hätte. Start, Pause und Abbruch bleiben immer Sache des Bedieners.
- Intern: Katalog in `services/error_patterns.py`, Regeln in `services/countermeasures.py` (reine Entscheidungsfunktion,
  testbar ohne Drucker), Router `api/routes/error_help.py`; Konfiguration in `data/countermeasures.json`.

## v1.12.1 (29.10.2026) — Meldungen, die ankommen

- **Fälligkeits-Meldung gilt erst als zugestellt, wenn ein Kanal bestätigt.** Bisher markierte sich ein Auftrag als
  gemeldet, sobald die Meldung abgeschickt war — fiel der Kanal in dem Moment aus, blieb der Hinweis aus und kam nie
  wieder. Jetzt zählt die Bestätigung mindestens eines Kanals; scheitert die Zustellung, wird sie wiederholt
  (nach 5 Minuten, danach mit verdoppeltem Abstand bis zu einer Stunde, höchstens fünf Versuche). Danach bleibt es
  ruhig, bis der Auftrag wieder in den Plan passt. Ist gar kein Kanal eingeschaltet, zählt das nicht als Fehlversuch:
  die Meldung geht nach, sobald einer eingerichtet ist.
- **Meldungen und Oberfläche zeigen lokale Zeit**, wenn auf dem Pi `TZ` gesetzt ist (`docs/INSTALLATION-PI.md`).
- Intern: `notification_service.py` wieder unter dem Zeilenbudget, indem die reinen Hilfsfunktionen nach
  `notification_utils.py` wanderten und die Ergebnisvariante des Versands die alte Schleife ersetzt (kein Duplikat
  mehr). Der fehlerhafte Entwurf `setup_firewall_rule.ps1` ist entfallen — `werkzeuge/firewall_regeln.ps1` deckt den
  PC-Slicer-Port bereits ab.

## v1.12.0 (29.10.2026) — Geschäft, Warteschlange und Assistent

- **Monats-Report** (Finanz-Seite → „Monats-Report"): Umsatz je Währung (Rechnungen ausgestellt/bezahlt/überfällig),
  Angebote, Fertigung (Drucke, Stunden, Filament, Material- und Energiekosten, je Drucker) und Gewinn aus der
  Nachkalkulation — als Zahlensammlung und als A4-PDF mit Firmenbriefkopf (de/en). Arbeitszeit zählt, wenn gebucht.
- **Angebot → Warteschlange:** Verhalten → Nachkalkulation kennt „Erneut einreihen" — die verknüpften Druckjobs eines
  Angebots landen wieder in der Warteschlange (Drucker oder „irgendein Modell", Priorität oder später zuweisen, Stückzahl).
  Dieselbe Rechteprüfung und Kostenkalkulation wie jede Einreihung; abgelehnte Archivliste erscheint einzeln.
- **Kunden-Stamm** (Finanz-Seite): Adressbuch für Angebote und Rechnungen (neue Tabelle, Liste/Anlegen/Ändern/Löschen).
  Belege behalten ihre Kopie von Kunde und Anschrift — Löschen ändert frühere Dokumente nicht.
- **Zahlungserinnerung:** überfällige, offene Rechnungen werden einmal je Rechnung gemeldet (neuer
  Meldeweg-Schalter „Zahlungserinnerung", Voreinstellung an; Prüfung alle 6 Stunden). Nach „bezahlt" und Wiederöffnen
  erinnert sie erneut; bezahlte und stornierte Rechnungen bleiben stumm.
- **Zeitbuchung:** die gebuchte Arbeitszeit eines Angebots (Minuten) ersetzt in der Nachkalkulation den Angebotsansatz
  (`labor_rate_per_hour`); der Gewinn wird gemessen statt geschätzt, ungebuchte Angebote bleiben wie bisher.
- **Fehlerbild-Sammlung** (Einstellungen → Fehlererkennung): Kamerabilder fehlgeschlagener Prüfungen (Platte nicht frei,
  erste Schicht, Spaghetti, Bauteil-Wächter) bleiben dauerhaft liegen (90 Tage, höchstens 500), mit Vorschau und Löschen —
  das Rohmaterial, das eine spätere KI-Fehlererkennung brauchte.
- **Assistent antwortet Wort für Wort** (SSE): der Text erscheint, während das Modell noch denkt; Aktionsvorschläge
  kommen weiterhin nur geprüft und bestätigungspflichtig im Abschluss. Hinweis zum Modell im Speicher
  (`OLLAMA_KEEP_ALIVE`) erscheint, sobald der Modell-Server erreichbar ist.
- Intern: eigene Router sind in einer Registry gebündelt (main.py wieder unter dem Zeilenbudget); Bestandswarnungen
  (`low_stock_threshold`) und automatische Trocknung nach AMS-Feuchte erwiesen sich als bereits vorhanden —
  Erprobung am Gerät bleibt offen.

## v1.11.0 (29.10.2026) — Systemprüfung und Sicherheit

- **Systemprüfung** (Wartung → System): Ein Knopf prüft in einem Durchlauf Datenbank, Druckplaner, Termin-Überwachung, Drucker,
  Prognose, Meldekanäle, Sicherungen, Gerätezustand, Anmeldung, Update-Schutz und den Assistenten. Jede Zeile zeigt Ampel,
  Befund und, wenn etwas nicht stimmt, was zu tun ist. Eine Prüfung, die selbst abstürzt, stoppt die anderen nicht.
- **Zwei Proben laufen bewusst mit:** eine **Testmeldung „Termin in Gefahr"** über die Kanäle, die sie wollen (pro Kanal
  einzeln ausgewertet, ein Fehler erscheint mit dem Kanalnamen), und eine **Probefrage an das Modell** des Assistenten mit
  Antwortzeit. So zeigt sich am echten Gerät, ob Meldungen ankommen und das Modell brauchbar antwortet.
- **Termin-Überwachung** merkt sich Start, letzten Durchlauf und letzten Fehler, damit die Prüfung sagen kann, ob sie lebt.
- Die Probefrage teilt sich die Sperre mit dem Chat; läuft gerade eine Antwort, wird die Probe übersprungen.

**Sicherheit** (Härtung aus der Gesamtanalyse, Parallel-Sitzung):

- **Externe-Link-Symbole härter:** Upload mit Größenlimit (2 MB) und Inhaltsprüfung statt nur Dateiname (Magic-Bytes für
  PNG/JPEG/GIF/WEBP/ICO); SVG nur noch ohne Skripte, Ereignis-Handler und Skript-URLs und nur als gültiges XML. Beim
  Ausliefern kommt `nosniff` dazu; ein ungültiger gespeicherter Symbolname wird verweigert.
- **Hardware-Befehle laufen ganz ohne Shell:** String-Befehle werden unter Windows jetzt zitatbewusst in Programm und
  Argumente aufgelöst statt über die Shell geschickt; Shell-Zeichen (`|`, `&`, `<`, `>`, `;`, Klammern) werden beim
  Speichern und beim Ausführen verweigert, mit dem Rat, den Befehl als Liste einzutragen. Umgebungsvariablen und
  Weiterleitungen funktionieren dadurch nicht mehr in String-Befehlen — dafür läuft der Befehl genau wie gespeichert.
- **Externe Sicherung kann die Zugangsdatei mitnehmen:** `PRINTLAB_BACKUP_INCLUDE_SECRETS=1` legt die Zugangsdatei
  `~/.config/printlab.env` als 0600-Kopie in jede externe Sicherung (Standard bleibt ohne; nur bei geschütztem Ziel
  einschalten, `docs/INSTALLATION-PI.md`).
- **Docker-Anmeldung vorgeschrieben:** `docker-compose.yml` setzt `PRINTLAB_REQUIRE_AUTH=1` (ausschaltbar), wie es der
  native Pi-Installer schon tut; eine Docker-Einrichtung startet nicht mehr offen.
- **CodeQL:** der breite Ausschluss von `py/full-ssrf` ist zurückgenommen (Meldungen wieder sichtbar); `py/path-injection`
  bleibt ausgeschlossen, weil der Repo-Test `test_no_unsafe_path_joins` denselben Fall hart abdeckt — beides begründet in
  `.codeql/codeql-config.yml`. Der überholte react-router-Hinweis in der security.yml-Liste ist korrigiert.
- **Dokumente:** `VERSIONING.md` nennt keine „aktuelle“ Version mehr (sie driftete, die Release-Prüfung übernimmt das),
  und kennzeichnet das Repository korrekt als öffentlich; `INSTALLATION-PI.md` dokumentiert die Zugangsdatei-Option und
  die Systemprüfung; `docs/ANALYSE-2026-10-28.md` hat eine Fortschreibung mit diesen Härtungen; die Randnotizen zur
  Fälligkeits-Meldung (Kanal-Ausfall gilt als gemeldet, UTC-Zeiten in der Meldung) stehen im `TODO.md`.

## v1.10.0 (29.10.2026) — Lokaler KI-Assistent

- **Assistent (Wartung → Reiter „Assistent")** mit einem lokalen Sprachmodell, das auf dem Pi (oder einem Rechner im Netz)
  läuft; nichts geht ins Internet. Er beantwortet Fragen zum Betrieb (Drucker, Warteschlange, Prognose), erklärt Fehler und
  Warte-Gründe und entwirft Texte (zum Beispiel Angebotsbeschreibungen).
- **Änderungen nur nach Bestätigung:** Der Assistent schlägt Änderungen vor (Priorität oder Liefertermin eines wartenden
  Auftrags); PrintLab prüft sie streng, beschriftet sie selbst und führt sie erst nach deinem Klick über die normalen
  Warteschlangen-Funktionen mit ihrer Rechteprüfung aus.
- **Einrichtung:** `werkzeuge/ki_einrichten.sh` prüft Ollama und Arbeitsspeicher, lädt das Modell und macht einen Test
  (optional mit `--installieren`). Die Adresse des Modell-Servers, das Modell und die Zeitgrenze sind einstellbar, jeder
  Server mit OpenAI-kompatibler Schnittstelle (Ollama, LM Studio, llama.cpp) geht.

## v1.9.6 (29.10.2026) — Termin-Meldung

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
