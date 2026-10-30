# TODO — PrintLab

**Stand:** 30.10.2026, Version 1.19.0 · **Basis:** Bambuddy 1.2.5.7 (AGPL-3.0, Herkunft: `NOTICE`) · **Branch:** `bambu-monitor-port`

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

**Aufräumrunde danach (ebenfalls uncommittet):**

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

- [ ] Große Dateien weiter zerlegen; der Test `test_file_size_budget.py` verhindert nur das Wachsen. Stand
      30.10.2026: `print_scheduler.py` 4 846 Zeilen (Grenze 4 850), `queue_pass.py` 1 032 (Vorgabe 2 600),
      `PrintersPage.tsx` 1 985 (Grenze 2 000), `PrinterCard.tsx` 6 255 (Grenze 6 300), `PrinterCardParts.tsx`
      1 134 (Grenze 1 150), `client.ts` 1 009 (Grenze 1 050), `types.ts` 4 754 (Grenze 4 800), `endpoints.ts`
      4 017 (Grenze 4 050). **Nächste Schnitte:** (1) die beiden Zweige in `queue_pass.py` weiter teilen —
      `_select_pinned` und `_select_for_model` sind je ~300/200 Zeilen, die Verfügbarkeitsprüfungen lassen sich
      als eigene Methoden herausziehen. (2) `PrinterCard.tsx` in Karte, AMS-Bereich und Kamera/Steuerung teilen.
      (3) `endpoints.ts` nach Bereichen (Drucker, Archive, Warteschlange, Verwaltung) mit Spreading wie in
      `createForkApi`. `main.py` ist praktisch nur noch Verdrahtung und bleibt an der Grenze (11 069/11 075);
      neue Funktionen gehören in eigene Module bzw. `fork_routers.py`.
- [ ] Volle E2E-Prüfung MakerWorld → PC-Slicer → Warteschlange. Die inneren Glieder sind abgesichert
      (566 Integrationstests zu MakerWorld, Bibliothek und Warteschlange, alle grün); der Slicer-Upload und der
druckende Drucker brauchen Gerät und Slicer.
- [ ] Komplette Unit-Suite in der CI (lokal nach 10 Minuten abgebrochen); `requirements.lock` vor der
      Docker-/Pi-Umstellung im Bau prüfen.
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
