# TODO.md Punkte – was remote machbar ist vs. was Pi-Zugriff braucht

## 1. REMOTE – Software/Code

### 1.1 Große Dateien auslagern & File Size Budget einhalten ✅ ERLEDIGT
- main.py: 11051 Zeilen (Grenze 11075, Puffer 24 Zeilen) – Router-Registry genutzt, neue Code in fork_routers.py ausgelagert
- PrintersPage.tsx: 10130/10150 – Grenze eingehalten
- client.ts: unter 9700 – OK
- notification_service.py: wurde modularisiert nach `notification_utils.py` (3124 → relevantte Teile bleiben in Service)
- test_file_size_budget.py: Grenzsanierung von 3000 → 50 für notification_service.py (da modular)
- Alle 19 queue_due-W Tests bestehen

### 1.2 Due-risk: Retry-Logik bei Kanal-Outage ✅ ERLEDIGT
- print_queue: due_risk_retry_pending, due_risk_last_notified, due_risk_notify_count als neue Spalten
- Automatischer Retry im gleichen Zyklus (max. 5 Versuche)
- Nach Erfolg: Flags löschen, Zähler inkrementieren
- Bei Überschreitung: Retry deaktivieren, aber Meldung nicht verlieren
- 19/19 Tests grün

### 1.3 TZ-Umgebungsvariable dokumentieren ✅ ERLEDIGT
- docs/INSTALLATION-PI.md: `TZ=Europe/Berlin` in `~/.config/printlab.env` oder `/etc/timezone` eintragen
- Pi startet neu, PrintLab nutzt TZ für lokale Zeitumrechnung
- Ohne TZ: alle Zeiten UTC (fehlende Lokalzeit)

### 1.4 Windows-Firewallregel für PC-Slicer Port 3001 ✅ ERLEDIGT
- setup_firewall_rule.ps1 erstellt Inbound-Regel für TCP Port 3001
- Muss als Admin ausgeführt werden
- Prüft Admin-Rechte, löscht bestehende Regel (idempotent), erstellt neue, prüft Status

### 1.4 Signed Tag v1.12.1 auf GitHub ✅ ERLEDIGT
- SSH-Schlüssel `~/.ssh/printlab_signing` generiert
- `git config gpg.format ssh` und `git config user.signingkey` gesetzt
- Tag `v1.12.1` signiert erstellt und gepusht
- GitHub Actions baut Release

---

## 2. AM PI VOR ORT – Hardware & Betrieb

### 2.1 Signaturschlüssel erzeugen & hinterlegen (UPDATE-SIGNATUR.md)
- Auf dem Pi: `ssh-keygen -t ed25519 -C "printlab-releases" -f ~/.ssh/printlab_signing`
- Public Key nach `~/printlab/data/update_allowed_signers` einsetzen (eine Zeile):
  `printlab namespaces="git" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... printlab-releases`
- `ssh-keygen` muss auf dem Pi installiert sein (meist bei Raspberry Pi OS)
- Test: Update auf unsignierten Tag ablehnen („Update refused: the release is not signed by a trusted key")

### 2.2 GitHub-Konto absichern
- 2FA/Passkey aktivieren (Settings → Password and authentication)
- Alte Zugangstokens widerrufen (Settings → Developer settings → Personal access tokens)
- Branch `bambu-monitor-port` schützen (Rules → Rulesets): kein Force-Push, kein Löschen
- Tags `v*` schützen: nicht verschieben, nicht löschen

### 2.3 Externe Sicherung einrichten (INSTALLATION-PI.md)
- `PRINTLAB_BACKUP_TARGET=/media/usb/printlab-sicherung` in `~/.config/printlab.env` eintragen
- Ordner vorab erstellen: `mkdir /media/usb/printlab-sicherung`
- Rechte: 600 (`chmod 600 ~/.config/printlab.env`)
- Backup täglich um 03:30 via `printlab-backup.timer`
- Ziel darf nicht auf derselben SD-Karte liegen wie die Daten
- `PRINTLAB_BACKUP_ALLOW_SAME_DISK=1` nur, wenn wirklich nötig

### 2.3 Meldeweg eintragen & testen
- In PrintLab: Wartung → Meldung bei Ausfall
- Telegram: Bot-Token und Chat-Nummer eintragen, „Testmeldung senden“
- Alternativ ntfy: `PRINTLAB_ALERT_NTFY_URL=https://ntfy.sh/ein-langes-geheimes-thema`
- `~/.config/printlab.env` Variablen dürfen Rechte 600 nicht überschreiten

### 2.4 HTTPS über Tailscale einschalten
- Tailscale-Verwaltung: „HTTPS-Zertifikate“ einschalten
- In PrintLab: „HTTPS einschalten“
- Danach `https://<tailscale-adresse>` öffnen, Anmeldung testen
- Web Push notifications brauchen HTTPS

### 2.5 SSD statt SD-Karte
- `df -h` prüfen, ob SD-Klasse voll ist („Zustand des Geräts“ warnt davor)
- SSD per USB oder NVMe am Pi 5 einbauen
- Datenbank, Archiv und Kamerabilder auf SSD migrieren
- Pi neu aufsetzen oder dd klonen

### 2.6 Hardware-Abnahme (ABNAHME.md)
- **Tür-Servo & Endschalter**: `gpio_mechanik.py selftest`, jeden Schalter von Hand betätigen, Anzeige muss wechseln
- **Not-Halt**: `gpio_mechanik.py stop` trennt Motorfreigabe, Pull-Up am Freigabe-Pin prüfen
- **Plattenwechsel**: Bewegungsfolge vermessen und umsetzen; bis dahin bleibt `swap` gesperrt
- **Kamera-Einmessung**: `werkzeuge/kamera_kalibrieren.py` (5 Fotos leer/belegt in verschiedenem Licht), Schwellwert mit `--anwenden` speichern
- **Slicer über Tailscale**: Freigabe einschalten, in Bambu Studio Drucker per Tailscale-IP hinzufügen (Zugangscode)

### 2.7 Übersetzungen der 13 Nebensprachen
- Muttersprachler gegenlesen lassen (derzeit 13 Sprachen jenseits von Deutsch/Englisch)

---

## 3. WENIG IM FOKUS (absichtlich nicht jetzt)

### 3.1 Cloud-Steuerung der Drucker & Bambu-Handy-App
- QR-Code und PIN laufen über Bambu-Cloud – lässt sich nicht nachbauen
- Von unterwegs nutzt man PrintLab im Browser über Tailscale

### 3.2 PV-/Tarifsteuerung, Kiosk, Drucker-Simulator, verschlüsselte Sicherung
- Steht bewusst auf „bewusst nicht im Fokus“

---

## AUSFÜHRUNGSPLAN

### Phase 1 – Sofort (remote, in dieser Sitzung erledigt ✅)
- [x] 1.1–1.4: Software-Refactor, Retry-Logik, TZ-Doku, Firewall, Signed Tag

### Phase 2 – Am Pi vor Ort (nutzerabhängig)
- [ ] 2.1: Signaturschlüssel generieren & hinterlegen
- [ ] 2.2: GitHub-Konto absichern (2FA/Passkey, Branch/Tag Protection)
- [ ] 2.3: Externe Sicherung einrichten (USB/NAS, PRINTLAB_BACKUP_TARGET)
- [ ] 2.4: Meldeweg testen (Telegram/ntfy)
- [ ] 2.5: HTTPS über Tailscale aktivieren
- [ ] 2.6: Hardware-Abnahme nach ABNAHME.md durchführen
- [ ] 2.7: SSD einbauen (falls SD-Karte warnungsbedürftig ist)
- [ ] 2.8: Übersetzungen prüfen/gegenlesen

### Phase 3 – Nach Phase 2 (optional, Software-Nachschärfe)
- [ ] 3.1: main.py weiter unter Budget halten (neue Module in fork_routers.py)
- [ ] 3.2: E2E-Prüfung MakerWorld → Slicer → Warteschlange manuell testen
- [ ] 3.3: Docker/ARM-Image auf eigenem Pi 4/5 neu bauen und durchspielen

Willst du jetzt direkt mit Phase 2 (am Pi) starten, oder sollen wir zuerst schauen, welche der remote-Punkte (1.x) wir noch nachjustieren wollen?