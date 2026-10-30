# Abnahme: was automatisch geprüft wird und was du selbst testen musst

Für eine Sitzung am Gerät in sinnvoller Reihenfolge (Update → Angebots-Link → Hardware, mit Erwartungen,
Abbruchkriterien und Protokoll) gibt es die Arbeitsliste [`ABNAHME-PI.md`](ABNAHME-PI.md). Dieses Dokument bleibt die
Übersicht aller Prüfungen und die Referenz für Mechanik, Kamera und Betrieb.

## 1. Automatischer Check auf dem Pi

```bash
cd ~/printlab
.venv/bin/python werkzeuge/abnahme.py          # Liste
.venv/bin/python werkzeuge/abnahme.py --json   # für Programme
```

Der Check läuft auf dem Pi selbst, ohne Anmeldung und ohne Drucker. Stufen: **OK**, **WARN** (sollte man beheben), **FAIL**
(so nicht sicher oder stabil), **SKIP** (hier nicht prüfbar). Rückgabecode 1, sobald etwas FAIL ist.

| Prüfung | Was sie feststellt |
|---|---|
| PrintLab antwortet | Dienst läuft, Version |
| Anmeldung | an **und** vorgeschrieben (`PRINTLAB_REQUIRE_AUTH=1`); aus ist ein FAIL |
| Dienst-Datei | `Restart=always`, Update-Schutz, Auto-Neustart, vorgeschriebene Anmeldung |
| git | vorhanden, Programmordner ist ein Git-Ordner (sonst kein Update) |
| Signatur | Updates nur von signierten Tags (`docs/UPDATE-SIGNATUR.md`); `ssh-keygen` vorhanden |
| Überwachung | Timer `printlab-watch.timer` aktiv, Meldeweg (Telegram/ntfy) eingetragen |
| Zugangsdatei | `~/.config/printlab.env` nur für dich lesbar (Rechte 600) |
| Sicherungen | neueste Sicherung vorhanden, **geprüft** (Datenbank-Integrität, JSON), nicht älter als 14 Tage |
| Sicherung nach außen | `PRINTLAB_BACKUP_TARGET` gesetzt und erreichbar |
| Zustand des Geräts | Temperatur, Unterspannung/Drosselung, freier Speicher, SD-Karte, Arbeitsspeicher |
| Virtueller Drucker | die vier Ports (3000, 3002, 990, 8883) lauschen, wenn er aktiviert ist |

Dasselbe sieht man laufend in PrintLab unter **Wartung → Zustand des Geräts**.

## 2. Was nur du mit echter Hardware testen kannst

Reihenfolge von „kann nichts kaputtmachen" bis „bewegt Mechanik". Jeden Punkt abhaken, Auffälligkeiten notieren.

### Software und Netz (ohne Mechanik)

- [ ] **Update ohne Signatur:** In Einstellungen → System auf die neueste Version aktualisieren, danach
      `journalctl --user -u printlab -n 40`. Ab dem Update danach gilt der Rückbau-Schutz.
- [ ] **Rückbau** (nur in einer Testkopie, nicht auf dem Betriebs-Pi): ein Update bauen, das nicht startet, und prüfen, dass
      nach dem vierten Startversuch der alte Stand samt Datenbank zurück ist und Einstellungen → System einen Hinweis zeigt.
- [ ] **Überwachung:** Meldeweg eintragen, `systemctl --user stop printlab`, warten (3 Minuten), Meldung und Neustart prüfen.
- [ ] **Sicherung nach außen:** USB-Stick einstecken, `PRINTLAB_BACKUP_TARGET` setzen,
      `systemctl --user start printlab-backup.service`, Ergebnis in „Zustand des Geräts". Dann Stick abziehen und prüfen, dass
      die Meldung „Sicherungsziel nicht erreichbar" kommt und nichts auf der SD-Karte landet.
- [ ] **Wiederherstellen:** eine Sicherung auf einem zweiten Rechner einspielen und PrintLab damit starten.
- [ ] **HTTPS:** In der Tailscale-Verwaltung „HTTPS-Zertifikate" einschalten, in PrintLab „HTTPS einschalten", die
      `https://…ts.net`-Adresse öffnen, Anmeldung testen.
- [ ] **Slicer über Tailscale:** Freigabe einschalten, in Bambu Studio den Drucker per IP hinzufügen (Tailscale-Adresse,
      Zugangscode), einmal mit Handy-Hotspot am PC.
- [ ] **Virtueller Drucker im Heimnetz:** Bambu Studio sendet eine Datei, sie landet in der Warteschlange.
- [ ] **Angebot-PDF** mit eigenen Firmendaten drucken und gegenlesen (Umsatzsteuerhinweis mit dem Steuerberater klären).

### Kamera

- [ ] **Einmessen:** je 5 Fotos leer/belegt in verschiedenem Licht, `werkzeuge/kamera_kalibrieren.py` (siehe
      `docs/INSTALLATION-PI.md`), Schwellwert mit `--anwenden` speichern, danach „Platte frei automatisch bestätigen"
      testen: bei leerem Bett bestätigt es, bei einem Teil auf dem Bett nicht.

### Mechanik (immer mit der Hand am Netzstecker, Gestänge zuerst abgekoppelt)

- [ ] **Not-Halt-Hardware:** ein Schalter, der den Motorstrom unabhängig von Software trennt (Software ist nie der Not-Aus).
- [ ] **GPIO-Selbsttest:** `gpio_mechanik.py selftest`, jeden Schalter von Hand betätigen, Anzeige muss wechseln.
- [ ] **Servo ohne Gestänge:** `gpio_mechanik.py servo 90`; Drehrichtung und Hebel prüfen; Winkel für „zu" und „offen" in
      `data/gpio_mechanik.json` eintragen.
- [ ] **Tür mit Endschaltern:** `door_open`, `door_close`, `door_check`; bei verdecktem Schalter muss es mit Fehler abbrechen
      (nie „offen" melden, ohne dass der Schalter es bestätigt).
- [ ] **Not-Halt-Befehl:** `gpio_mechanik.py stop` trennt die Motorfreigabe (Pull-Up am Freigabe-Pin prüfen).
- [ ] **Plattenwechsel:** Positionen im Einmess-Assistenten aufnehmen (Wartung → Hardware & Optik). Eine begonnene,
      nicht abgeschlossene Einmessung sperrt den Wechsel samt Automatik; erst nach Probelauf freigeben. Ablauf in
      [`ABNAHME-PI.md`](ABNAHME-PI.md) Abschnitte 3.2–3.5.
