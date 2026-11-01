# Ersteinrichtung — PrintLab Punkt für Punkt

Diese Anleitung führt in der Reihenfolge, in der die Punkte aufeinander aufbauen: von der Installation bis zum ersten
Druck. Sie ergänzt `docs/INSTALLATION-PI.md` (Aufsetzen des Pi) und `docs/ABNAHME-PI.md` (Abnahme von Hardware und
Update). Wer nur etwas nachschlagen will: In der App steht derselbe Ablauf unter **Einrichtung** in der Seitenleiste
und unter **Wartung → System**.

Jeder Schritt nennt das Ziel, die Handlung und woran man erkennt, dass er wirklich erledigt ist. „Fertig“ heißt
nicht „Knopf gedrückt“, sondern „das Ergebnis ist sichtbar“.

---

## 0. Vor dem Start

| Was | Prüfen |
|---|---|
| Pi oder Rechner | PrintLab läuft nativ auf einem Pi 5 (empfohlen) oder im Docker-Container. |
| Netz | Pi und Drucker im selben Netz; dem Drucker am Router eine feste Adresse (DHCP-Reservierung) geben. |
| Drucker | Modell, IP-Adresse und Zugangscode (LCD des Druckers) zur Hand. |
| Zeit | Datum und Uhrzeit stimmen (`date` auf dem Pi). Signaturprüfung, Angebots-Link und Zertifikate hängen daran. |
| Zugriff | Adresse, unter der PrintLab erreichbar ist (`http://printlab.local:8000` oder die Tailscale-Adresse). |

Der Einrichtungssassistent zeigt immer nur die **offenen** Punkte. Erledigtes verschwindet von selbst, weil er den
echten Zustand liest und nichts zwischenspeichert.

---

## 1. PrintLab starten

**Ziel:** Die Oberfläche lädt und ist erreichbar.

1. Dienst starten: `systemctl --user start printlab` (nativ) oder `docker compose up -d` (Docker).
2. Adresse im Browser öffnen.
3. Bei einer frischen Installation ohne Anmeldung erscheint `/setup` — dort wird zuerst die Anmeldung eingerichtet.

**Erledigt, wenn** die Startseite lädt und unter **Wartung → System** ein Assistent mit offenen Punkten steht.

**Wenn nicht:** `journalctl --user -u printlab -n 50` lesen. Kein „Application startup failed“, kein Traceback.

---

## 2. Anmeldung einschalten (Pflicht)

**Ziel:** Niemand im Netz kann ohne Konto steuern, drucken oder Einstellungen ändern.

1. Auf `/setup` **Anmeldung aktivieren** wählen.
2. Benutzername und Passwort für den ersten Administrator setzen (mindestens 6 Zeichen).
3. Speichern und mit dem neuen Konto anmelden.

**Erledigt, wenn** die Checkliste „Anmeldung eingeschaltet“ als erledigt zeigt und ein Abmelden/Anmelden funktioniert.

**Wenn nicht:** Bei bereits vorhandenen Administratoren lässt `/setup` die Felder leer — dann nur „Anmeldung
aktivieren“ und mit dem bestehenden Konto anmelden.

> PrintLab steuert Drucker, Dateien und Kameras. Ohne Anmeldung gehört die Adresse nicht ins Netz, auch nicht in ein
> Gäste-WLAN.

---

## 3. Ersten Drucker verbinden (Pflicht)

**Ziel:** PrintLab liest Status, AMS und Kamera des Druckers.

1. **Drucker → Drucker hinzufügen**. Discovery starten oder „manuell per IP“ wählen.
2. Modell, IP-Adresse und Zugangscode eintragen.
3. Am Drucker **LAN-Only-Modus** und (bei X1/H2/P2S) **Entwicklermodus** einschalten — ohne das sind MQTT und FTP
   gesperrt.
4. Speichern und die Statuskarte beobachten.

**Erledigt, wenn** die Karte „Verbunden“ zeigt, Temperatur und Fortschritt live laufen und das AMS erscheint.

**Wenn nicht:** Am Drucker-Kartenmenü **Verbindungsdiagnose** öffnen. Sie prüft Netz, Port 8883, FTP und Kamera
einzeln und nennt den fehlenden Punkt.

---

## 4. Material und Bestand (empfohlen)

**Ziel:** Verbrauch, Restgewicht und Kosten stimmen.

1. **Einstellungen → Bestandsmodus** wählen: intern, Spoolman oder keiner. Die Wahl ist später nicht ohne
   Datenverlust umstellbar.
2. Bei „intern“: Spulen anlegen oder RFID im AMS erkennen lassen.
3. Optional Lieferantenpreise pflegen — dann rechnet der Nachbestellvorschlag mit echten Kosten.

**Erledigt, wenn** die Spulen in der Bestandsliste stehen und die AMS-Fächer ihnen zugeordnet sind.

---

## 5. Meldungen einrichten (empfohlen)

**Ziel:** Ein fehlgeschlagener Druck bleibt nicht unbemerkt.

1. **Wartung → System → Meldewege**: Telegram-Token und Chat-Nummer oder eine ntfy-Adresse eintragen.
2. Speichern, dann **Testmeldung** senden.

**Erledigt, wenn** die Testmeldung auf dem Handy ankommt.

**Wenn nicht:** Der Server zeigt die Fehlerart an (HTTP-Code, Zeitüberschreitung), nicht den Token. Bei ntfy keine
`localhost`-Adresse verwenden — sie wird bewusst abgelehnt.

---

## 6. Sicherung nach außen (empfohlen)

**Ziel:** Ein defekter Pi kostet keine Daten.

1. USB-Stick oder NAS einhängen.
2. `PRINTLAB_BACKUP_TARGET` in `~/.config/printlab.env` auf den Pfad setzen und den Dienst neu starten.
3. Unter **Wartung → System → Zustand des Geräts** prüfen, ob die letzte Sicherung als in Ordnung gilt.

**Erledigt, wenn** die externe Sicherung mit Datum und Größe erscheint.

---

## 7. Updates absichern (empfohlen)

**Ziel:** Nur geprüfte Versionen werden eingespielt.

1. Signaturschlüssel erzeugen und auf dem Pi hinterlegen (`docs/UPDATE-SIGNATUR.md`).
2. In PrintLab die Signaturprüfung einschalten.
3. **Einstellungen → Aktualisierungen → Jetzt prüfen** und einmal installieren.

**Erledigt, wenn** die Version nach dem Neustart stimmt und die Signaturprüfung als aktiv gilt.

---

## 8. Fernzugriff (optional)

**Ziel:** PrintLab von unterwegs, ohne Portfreigabe.

1. Tailscale auf dem Pi einrichten und in PrintLab **Wartung → System → Fernzugriff** verbinden.
2. HTTPS in der Tailscale-Verwaltung einschalten, dann in PrintLab „HTTPS einschalten“.

**Erledigt, wenn** die Tailscale-Adresse von einem Mobilgerät **ohne** Heim-WLAN lädt und ein Schloss zeigt.

---

## 9. Erster Druck

**Ziel:** Der Weg Datei → Warteschlange → Drucker funktioniert einmal von Hand.

1. Datei über **Dateien** hochladen (3MF oder G-code) oder aus MakerWorld importieren.
2. In der **Warteschlange** einreihen, Drucker und Platte wählen.
3. Starten und den Fortschritt auf der Druckerkarte beobachten.

**Erledigt, wenn** der Drucker läuft, PrintLab Fortschritt und Restzeit zeigt und der Auftrag nach dem Ende im
**Archiv** mit Dauer und Material steht.

---

## Wo der Assistent steht

- **Einrichtung** in der Seitenleiste (ganze Seite: Assistent, Checkliste, Werkseinstellungen).
- **Wartung → System** (dieselben Karten im Betrieb).
- Nach jedem Start prüft PrintLab den Zustand neu; ein erledigter Punkt verschwindet ohne Zutun.

---

## Werkseinstellungen — zurücksetzen und neu einrichten

**Was passiert:** PrintLab sichert zuerst Datenbank und Einstellungen in eine ZIP-Datei unter `data/backups/`.
Danach werden **alle** Daten in `data/reset-<Zeitstempel>/` verschoben — Drucker, Warteschlange, Archiv, Bibliothek,
Material, Bilder und Einstellungen. Anschließend legt PrintLab ein leeres Schema an; die Einrichtung beginnt von vorn.
**Gelöscht wird nichts.** Sicherungen und Protokolle bleiben an ihrem Platz.

**Voraussetzungen:** lokale Datenbank (SQLite, der Normalfall) und eingeschaltete Anmeldung. Bei einer externen
Datenbank (`DATABASE_URL`) verweigert PrintLab den Reset bewusst — dort wird die Datenbank von Hand geleert.

### Ablauf

1. **Einrichtung → Werkseinstellungen** (oder **Wartung → System**).
2. **Werkseinstellungen …** drücken.
3. `ZURÜCKSETZEN` eintippen und **Jetzt zurücksetzen** drücken.
4. Warten, bis die Meldung erscheint; die Seite lädt danach neu.
5. Die Einrichtung beginnt bei Schritt 2 (Anmeldung) — die Schritte 3 bis 9 wie oben durchgehen.

### Zurückholen

1. PrintLab stoppen.
2. Die Dateien aus `data/reset-<Zeitstempel>/` an ihren alten Platz zurücklegen (Datenbank nach `data/`,
   Ordner wie `archive`, `library` nach `data/`).
3. Die ZIP-Datei aus `data/backups/factory-reset-…zip` entpacken: `db/` enthält die Datenbank, `config/` die
   Einstellungsdateien.
4. PrintLab starten und die Daten prüfen.
5. Erst wenn alles läuft, `reset-<Zeitstempel>/` und die ZIP-Datei löschen — vorher sind sie die Rückfahrkarte.

### Was ein Reset **nicht** ändert

- Den Programmcode und die gebaute Oberfläche.
- Protokolle (`logs/`) und Sicherungen (`data/backups/`).
- Einstellungen, die in der Dienstumgebung stehen (`~/.config/printlab.env`, `docker-compose.yml`). Wer auch die
  zurücksetzen will, leert bzw. entfernt diese Dateien von Hand — danach beginnt PrintLab mit den Vorgaben.
