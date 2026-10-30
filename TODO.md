# TODO — PrintLab

**Stand:** 30.10.2026, Version 1.17.1 · **Basis:** Bambuddy 1.2.5.7 (AGPL-3.0, Herkunft: `NOTICE`) · **Branch:** `bambu-monitor-port`

Was fertig ist, steht mit Datum im `CHANGELOG.md`. Die ausführliche Bewertung (Risiken R1–R16, Verbesserungen, Erweiterungen)
steht in `docs/ANALYSE-2026-10-28.md`, die Abnahme in `docs/ABNAHME.md`.

## Läuft auf dem Pi (bestätigt)

PrintLab (Pi 5, nativ, systemd-Benutzerdienst), Fernzugriff über Tailscale, Updates aus der Oberfläche, Sicherung vor dem
Update mit Rückbau, Überwachung mit Meldung, Angebote mit PDF, Kamera-Einmessung, Zustand des Geräts, Anmeldung vorgeschrieben.

## Zuletzt erledigt (30.10.2026, uncommittet)

Alle Befunde F1–F10 aus `docs/ANALYSE-2026-10-30.md` sind behoben (Plattenwechsel fail-closed bei Temperatur und
Tür, Aufräumen der Fehlerbilder, Magazin-Änderung ohne Teilwirkung, Einstellungen je Drucker, KI-Haushalt,
Geldrechnung in Cent) und die Verbesserungen 1–12 umgesetzt (u. a. `requirements.lock`, KI-Trefferquote je
Fehlerbild, Abbrechen im Assistenten, Filter der Fehlerbild-Sammlung). **Alle acht Erweiterungen sind umgesetzt:**
Trainingsset-Export, KI-Hinweis als eigene Meldung, öffentlicher Angebots-Link mit Zusage/Ablehnung, Zeitraffer-MP4
aus aufbewahrten Schichtbildern, automatische Umverteilung, XRechnung-XML, Nachbestellvorschlag und der
Einmess-Assistent für den Plattenwechsel. Details und Grenzen im `CHANGELOG.md`.

## Offen, nur mit deiner Hand oder echter Hardware

Am Gerät in einer Sitzung abarbeiten: [`docs/ABNAHME-PI.md`](docs/ABNAHME-PI.md) — Update, Angebots-Link, Hardware in
dieser Reihenfolge, mit Erwartungen, Abbruchkriterien und Protokoll.

- [ ] **Signaturschlüssel erzeugen** und Tags signieren, Schlüssel auf dem Pi hinterlegen (`docs/UPDATE-SIGNATUR.md`).
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
- [ ] **E-Rechnung abnehmen:** XRechnung mit der Steuerberatung und gegen den KoSIT-Validator prüfen lassen, bevor
      sie an Kunden geht; ZUGFeRD fehlt bewusst (braucht PDF/A-3).
- [ ] **Angebots-Link und Nachbestellvorschlag erproben:** Link auf dem Mobilgerät öffnen und beantworten
      (`docs/ABNAHME-PI.md` Abschnitt 2); Lieferantenpreise pflegen und den Vorschlag gegen den tatsächlichen Verbrauch
      prüfen (auch im Spoolman-Betrieb).
- [ ] Übersetzungen der 13 Nebensprachen von Muttersprachlern gegenlesen lassen.

## Technisch offen

- [ ] Große Dateien weiter zerlegen; der Test `test_file_size_budget.py` verhindert nur das Wachsen. Schnitt am
      30.10.2026: `print_scheduler.py` von 8 740 auf 4 846 Zeilen (−45 %), Grenze auf 4 875 gesenkt. Helfer liegen in
      `backend/app/services/scheduler/` (filament, nozzles, chamber, dispatch, upload, delivery), Vorheizen/Warmhalten
      und Trocknung als Mixins (`preheat.py`, `drying.py`); alles bleibt über `print_scheduler` importierbar. Die
      ausgelagerten Bausteine lösen `printer_manager`, `time`, `datetime`, `notification_service`, `supports_drying`,
      `delete_file_async`, `upload_file_async`, `get_ftp_retry_settings` und `ws_manager` über das Fassadenmodul auf,
      damit die bestehenden Test-Patches unverändert greifen. **Nächster Schritt:** `check_queue` (930 Zeilen) aus der
      Klasse lösen; danach die Druckerkarte (`PrinterCard` in `PrintersPage.tsx`, ~5 600 Zeilen in einer Funktion) und
      `client.ts` (~9 700). `main.py` ist praktisch nur noch Verdrahtung und bleibt an der Grenze (11 069/11 075); neue
      Funktionen gehören in eigene Module bzw. `fork_routers.py`.
- [ ] Volle E2E-Prüfung MakerWorld → PC-Slicer → Warteschlange.
- [ ] Komplette Unit-Suite in der CI (lokal nach 10 Minuten abgebrochen); `requirements.lock` vor der
      Docker-/Pi-Umstellung im Bau prüfen.
- [ ] Stille `except Exception: pass`-Handler abbauen (43, durch `test_error_handling_budget.py` gedeckelt).
- [ ] Docker-/ARM-Image auf einem Pi 4/5 starten und prüfen.
- [ ] Fehlerhilfe: die zwölf Fließtexte der Fehlerbilder von Muttersprachlern übersetzen lassen (Titel und Kurzfassungen
      sind englisch hinterlegt) und die Schwellen der beiden Regeln in der Oberfläche einstellbar machen (derzeit nur
      über `data/countermeasures.json`).
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
