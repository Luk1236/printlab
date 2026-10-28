# TODO — PrintLab

**Stand:** 28.10.2026, Version 1.9.3 · **Basis:** Bambuddy 1.2.5.7 (AGPL-3.0, Herkunft: `NOTICE`) · **Branch:** `bambu-monitor-port`

Was fertig ist, steht mit Datum im `CHANGELOG.md`. Die ausführliche Bewertung (Risiken R1–R16, Verbesserungen, Erweiterungen)
steht in `docs/ANALYSE-2026-10-28.md`, die Abnahme in `docs/ABNAHME.md`.

## Läuft auf dem Pi (bestätigt)

PrintLab (Pi 5, nativ, systemd-Benutzerdienst), Fernzugriff über Tailscale, Updates aus der Oberfläche, Sicherung vor dem
Update mit Rückbau, Überwachung mit Meldung, Angebote mit PDF, Kamera-Einmessung, Zustand des Geräts, Anmeldung vorgeschrieben.

## Offen, nur mit deiner Hand oder echter Hardware

- [ ] **Signaturschlüssel erzeugen** und Tags signieren, Schlüssel auf dem Pi hinterlegen (`docs/UPDATE-SIGNATUR.md`).
- [ ] **GitHub-Konto absichern:** Passkey/2FA, alte Tokens widerrufen, Regelsatz für Branch und Tags.
- [ ] **Sicherung nach außen:** USB-Stick oder NAS als `PRINTLAB_BACKUP_TARGET` eintragen (`docs/INSTALLATION-PI.md`).
- [ ] **Meldeweg** für Ausfälle (Telegram oder ntfy) in `~/.config/printlab.env` eintragen.
- [ ] **HTTPS-Zertifikate** in der Tailscale-Verwaltung einschalten, dann „HTTPS einschalten" in PrintLab.
- [ ] **SSD** statt SD-Karte für den Pi (Warnung erscheint unter Wartung → Zustand des Geräts).
- [ ] **Hardware abnehmen:** Tür-Servo mit Endschaltern, Not-Halt, Slicer über Tailscale, Kamera-Einmessung an echten
      Fotos (Checkliste in `docs/ABNAHME.md`).
- [ ] **Plattenwechsel:** Bewegungsfolge vermessen und umsetzen; bis dahin bleibt `swap` gesperrt.
- [ ] Übersetzungen der 13 Nebensprachen von Muttersprachlern gegenlesen lassen.

## Technisch offen

- [ ] Große Dateien schrittweise zerlegen (`main.py`, `PrintersPage.tsx`, `client.ts`, …); der Test
      `test_file_size_budget.py` verhindert nur das Wachsen.
- [ ] Volle E2E-Prüfung MakerWorld → PC-Slicer → Warteschlange.
- [ ] Windows-Firewallregel für den PC-Slicer-Port 3001 beim Wechsel auf `0.0.0.0`.
- [ ] Docker-/ARM-Image auf einem Pi 4/5 starten und prüfen.
- [x] Wartungsseite in Reiter aufgeteilt (Status, Hardware & Optik, System & Betrieb, Einstellungen); Mobilansicht am Gerät noch ansehen.

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
