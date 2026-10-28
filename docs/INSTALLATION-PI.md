# PrintLab auf dem Raspberry Pi (4/5)

> **Stand:** auf einem Raspberry Pi 5 installiert und im Betrieb (Software, Fernzugriff, Updates). Die Teile mit
> Mechanik (Tür-Servo, Endschalter, Plattenwechsler) und der Slicer über Tailscale sind noch nicht an echter Hardware
> erprobt, siehe `docs/ABNAHME.md`. Ein Raspberry Pi 3 mit 1 GB reicht nach heutigem Wissen **nicht** zuverlässig
> (Speicher).

## Voraussetzungen

- Raspberry Pi 4 oder 5 mit **64-Bit-Raspberry-Pi-OS** (`uname -m` meldet `aarch64`), mindestens 2 GB RAM, besser 4 GB.
- 2 GB Swap (`sudo dphys-swapfile swapoff`, in `/etc/dphys-swapfile` `CONF_SWAPSIZE=2048`, `sudo dphys-swapfile setup`,
  `sudo dphys-swapfile swapon`).
- Docker und das Compose-Plugin (`curl -fsSL https://get.docker.com | sh`, danach `sudo usermod -aG docker $USER`
  und neu anmelden).
- Der Drucker im **LAN-Modus** mit **Developer Mode**; nur **ein** Client darf mit dem Drucker sprechen (alte
  Monitore und Bambu Handy beenden).

## Installation

```bash
git clone https://github.com/Luk1236/printlab.git
cd printlab
git checkout bambu-monitor-port
docker compose up -d --build
```

Der erste Bau dauert auf dem Pi mehrere Minuten (Frontend und Python-Pakete). PrintLab ist danach unter
`http://<pi-ip>:8000` erreichbar. Daten liegen in den Docker-Volumes `printlab_data` und `printlab_logs`.

Für Drucker-Erkennung und virtuellen Drucker muss der Container im Host-Netzwerk laufen (`network_mode: host`,
siehe Kommentare in `docker-compose.yml`).

### Alternative: fertiges Image

Nach dem ersten Release-Lauf (Tag pushen, Workflow „Release“) liegt ein Multi-Arch-Image in der GitHub Container
Registry. In `docker-compose.yml` dann statt `build: .` die Zeile `image: ghcr.io/luk1236/printlab:latest` verwenden und
`docker compose pull && docker compose up -d` ausführen (bei einem privaten Repo vorher `docker login ghcr.io`).

## Erster Start

1. Einrichtung abschließen und **Anmeldung einschalten** (Passwort wählen). Ohne Anmeldung sind Hardware-Befehle
   gesperrt, und jeder im Netz könnte Drucker steuern. Der Installer setzt dafür `PRINTLAB_REQUIRE_AUTH=1`: bis das
   Passwort angelegt ist, ist die Schnittstelle gesperrt (403), nur die Einrichtungsseite `/setup` ist erreichbar, und sie
   lässt sich nicht ohne Administrator und Passwort abschließen. Bei einer älteren Installation die Zeile
   `Environment=PRINTLAB_REQUIRE_AUTH=1` in `~/.config/systemd/user/printlab.service` ergänzen und
   `systemctl --user daemon-reload && systemctl --user restart printlab` ausführen. **Öffne die Einrichtung selbst, gleich
   nach dem Start:** wer die Seite zuerst aufruft, legt den Administrator an.
2. Drucker hinzufügen (IP, Seriennummer, Zugangscode).
3. Optional PC-Slicer: auf dem Windows-PC `starte_pc_slicer.bat`, in den PrintLab-Einstellungen die Adresse des PCs
   eintragen. Auf dem PC `PC_SLICER_ALLOWED_IPS=<pi-ip>` setzen, sonst weist der Slicer den Pi ab. Sicherer als die
   IP-Liste ist ein Token: dieselbe Variable `PC_SLICER_TOKEN=<geheim>` auf **beiden** Rechnern setzen (PC und Pi,
   z. B. in `docker-compose.yml` unter `environment:`) — der Slicer-Client in PrintLab schickt den Token dann
   automatisch mit, und die `PC_SLICER_ALLOWED_IPS`-Liste kann entfallen.

## Updates

Unter **Einstellungen → System** stehen auch die automatischen **Sicherungen vor Updates** mit „Wiederherstellen“. Die
Wiederherstellung läuft beim nächsten Start (PrintLab startet dafür neu), der Stand davor wird ebenfalls gesichert; sie geht
nur mit eingeschalteter Anmeldung und dem Update-Schutz im Dienst. Nach einem Update zeigt die Oberfläche „startet neu“
und lädt sich selbst neu, sobald PrintLab wieder antwortet.

PrintLab prüft unter **Einstellungen → System** auf neue Versionen (Releases von `Luk1236/printlab`) und kann sie
selbst einspielen. Das Repo ist öffentlich, ein Token ist nicht nötig (nur bei einem privaten Fork:
`PRINTLAB_GITHUB_TOKEN`, beim Neuaufspielen mit `PRINTLAB_STORE_TOKEN=1` in `~/.config/printlab.env` mit Rechten 600).
Nach dem Update startet sich der Dienst von selbst neu. Voraussetzung: PrintLab wurde mit
`werkzeuge/pi_neu_installieren.sh` installiert (Git-Ordner, Dienst mit `Restart=always`).

**Sicherung und Rückbau:** Vor jedem Update sichert PrintLab Datenbank und Einstellungsdateien nach
`<Datenordner>/update-backups/<Zeitstempel>` (die letzten 3 bleiben). Startet die neue Version nicht stabil an, stellt
`werkzeuge/update_guard.py` beim vierten Startversuch den alten Stand samt Datenbank wieder her und PrintLab zeigt unter
„Einstellungen → System“ einen Hinweis. Eine Sicherung prüfen:
`~/printlab/.venv/bin/python ~/printlab/werkzeuge/backup_pruefen.py` (ohne Argument: die neueste).

## Überwachung und Meldung aufs Handy

Der Installer richtet einen Timer ein (`printlab-watch.timer`), der jede Minute prüft, ob PrintLab antwortet. Nach 3
Fehlschlägen startet er den Dienst neu und meldet es. Den Meldeweg trägst du am einfachsten in PrintLab unter **Wartung →
Meldung bei Ausfall** ein (Telegram-Bot-Token und Chat-Nummer oder eine ntfy-Adresse, dann „Testmeldung senden“); Token und
Adressen werden nur gespeichert und nie wieder angezeigt. Alternativ in `~/.config/printlab.env` (Rechte 600, diese
Variablen haben Vorrang):

```
PRINTLAB_ALERT_TELEGRAM_TOKEN=<Bot-Token von @BotFather>
PRINTLAB_ALERT_TELEGRAM_CHAT=<deine Chat-Nummer>
# oder ntfy:  PRINTLAB_ALERT_NTFY_URL=https://ntfy.sh/ein-langes-geheimes-thema
```

Der Timer liest die Datei bei jedem Lauf neu, ein Neustart ist nicht nötig. Status:
`systemctl --user list-timers printlab-watch.timer`, Meldungen: `journalctl --user -u printlab-watch -n 20`.

## Sicherung nach außen (USB-Stick, Festplatte, NAS)

Sicherungen nur auf der SD-Karte schützen nicht vor einem Ausfall der Karte. Der Installer richtet deshalb einen
Tages-Timer ein (`printlab-backup.timer`, 03:30 Uhr), der eine **geprüfte** Sicherung auf einen anderen Datenträger legt.
Er tut nichts, solange kein Ziel eingestellt ist. In `~/.config/printlab.env` eintragen (Rechte 600):

```
PRINTLAB_BACKUP_TARGET=/media/usb/printlab-sicherung
PRINTLAB_BACKUP_KEEP=7
```

Der Ordner muss auf dem Datenträger **schon existieren** (zum Beispiel `mkdir /media/usb/printlab-sicherung`). PrintLab legt
ihn nie selbst an, damit bei nicht eingestecktem Stick nichts auf der SD-Karte landet. Liegt das Ziel auf demselben
Datenträger wie die Daten, lehnt das Skript ab (`PRINTLAB_BACKUP_ALLOW_SAME_DISK=1` erlaubt es trotzdem). Jede Sicherung wird
nach dem Schreiben geprüft (Datenbank-Integrität, gültiges JSON); eine beschädigte wird gelöscht und über den
Überwachungs-Meldeweg gemeldet. Sofort ausführen: `systemctl --user start printlab-backup.service`, Ergebnis:
`journalctl --user -u printlab-backup -n 20` und unter Wartung → Zustand des Geräts. Gesichert werden die Datenbanken und
Einstellungsdateien, **nicht** `~/.config/printlab.env` (die Zugangsdaten bewahrst du selbst auf).

## Zustand des Geräts

Unter **Wartung → Zustand des Geräts** zeigt PrintLab Temperatur, Spannung (Unterspannung des Netzteils), freien
Speicherplatz, Art des Datenträgers (SD-Karte, USB, NVMe), Arbeitsspeicher, Laufzeit und die letzten Sicherungen, mit
Hinweisen bei Problemen. **SD-Karte:** sie verschleißt durch die vielen Schreibvorgänge der Datenbank; eine SSD per USB oder
NVMe (Pi 5) ist deutlich haltbarer, und PrintLab weist darauf hin. Umzug auf eine SSD: Pi von der SSD starten, dann
`pi_neu_installieren.sh` erneut ausführen (die Daten bleiben erhalten).

## Betrieb

| Aufgabe | Befehl |
|---|---|
| Protokoll ansehen | `docker compose logs -f printlab` |
| Stoppen / Starten | `docker compose stop` / `docker compose start` |
| Aktualisieren | `git pull && docker compose up -d --build` |
| Alles prüfen | `~/printlab/.venv/bin/python ~/printlab/werkzeuge/abnahme.py` (siehe `docs/ABNAHME.md`) |
| Sicherung | Einstellungen → Sicherung (lokale Sicherung) oder Volume `printlab_data` kopieren |

## Tür und Plattenwechsler am GPIO

`werkzeuge/gpio_mechanik.py` steuert die Servo-Tür und liest die Endschalter (Standard-Pins: Servo GPIO 18, Endschalter
offen 23, zu 24, Plattensensor 25; `gpio_mechanik.py pins` zeigt alle). Auf dem Pi 5 zuerst `sudo apt install
python3-rpi-lgpio`. Ablauf zum Einrichten (im Ordner `~/printlab`, **ohne** angeschlossenes Gestänge):

1. `.venv/bin/python werkzeuge/gpio_mechanik.py selftest` — Schalter von Hand betätigen, Anzeige prüfen.
2. `... servo 90` — Servo fährt langsam auf 90 Grad; Drehrichtung und Hebel prüfen, Winkel für „zu“ und „offen“ in
   `data/gpio_mechanik.json` eintragen (Vorlage: `werkzeuge/gpio_mechanik.beispiel.json`).
3. In PrintLab (Wartung → Hardware) Modus „command“ und die Befehle eintragen, als Liste ohne Shell, zum Beispiel
   `["/home/<benutzer>/printlab/.venv/bin/python", "/home/<benutzer>/printlab/werkzeuge/gpio_mechanik.py", "door_open"]`
   (ebenso `door_close`, `door_check`, `stop` für den Not-Halt).

Der Plattenwechsel selbst (`swap`) bleibt gesperrt, bis die Bewegungsfolge der Mechanik vermessen und umgesetzt ist.

## Kamera einmessen

Am einfachsten in PrintLab unter **Wartung → Kamera einmessen**: Drucker wählen, Fotos mit leerem und mit belegtem Bett
hochladen, „Auswerten“, Vorschlag ansehen und „Schwellwert übernehmen“. Die Bilder werden nicht gespeichert; Voraussetzung ist
eine Referenz des Druckers (Kamera-Seite). Dasselbe geht als Werkzeug auf dem Pi. Für „Platte frei automatisch bestätigen“: Fotos mit leerem Bett in einen Ordner `leer`, Fotos mit Teilen darauf in `belegt`
legen (je 5 bis 10, verschiedenes Licht), dann `DATA_DIR=~/printlab/data .venv/bin/python werkzeuge/kamera_kalibrieren.py
--printer-id 1 --leer leer --belegt belegt`. Das Werkzeug zeigt die Messwerte, einen Schwellwert und die Mindest-Sicherheit;
mit `--anwenden` wird der Schwellwert gespeichert (`--zuruecksetzen` nimmt ihn zurück).

## Zugriff von unterwegs (Fernzugriff in PrintLab)

PrintLab hat den Fernzugriff eingebaut: Seite **Wartung → Fernzugriff (Tailscale)**. Er läuft ohne Root-Rechte und
ohne Docker-Änderungen und öffnet nichts im öffentlichen Internet.

1. **Anmeldung einschalten** (Voraussetzung, sonst lehnt PrintLab das Einrichten ab).
2. „Fernzugriff einrichten“ drücken. PrintLab lädt die offiziellen Tailscale-Programme (Prüfsumme wird kontrolliert)
   in den Datenordner, startet sie im Userspace-Modus und zeigt einen Anmelde-Link.
3. Link öffnen und mit dem **kostenlosen Tailscale-Konto** anmelden. Danach gibt PrintLab den Port frei und zeigt die
   Adresse (`http://100.x.y.z:8000`).
4. Auf PC oder Handy Tailscale mit **demselben Konto** installieren und die Adresse öffnen.

**Slicer von unterwegs (Versuch):** In derselben Karte gibt „Slicer-Zugriff freigeben" die Ports des virtuellen Druckers
im Tailnet frei. In Bambu Studio dann Drucker per IP hinzufügen: IP = Tailscale-Adresse des Pi (`100.x.y.z`), Zugangscode
= der 8-stellige Code des virtuellen Druckers (Einstellungen → Virtueller Drucker, muss aktiviert sein). Der PC braucht
Tailscale mit demselben Konto. Die Erkennung im Netz gibt es darüber nicht, nur das Hinzufügen per IP. Noch nicht an
echter Hardware erprobt; bitte Meldungen aus Bambu Studio notieren. Beenden: „Slicer-Zugriff beenden".

**HTTPS (verschlüsselt):** „HTTPS einschalten" in derselben Karte bietet PrintLab zusätzlich unter
`https://<name>.<tailnet>.ts.net` mit einem echten Zertifikat an, damit Passwort und Sitzung auch im Browser
geschützt sind. Voraussetzung: In der Tailscale-Verwaltung (login.tailscale.com → DNS) sind MagicDNS und **HTTPS-Zertifikate**
eingeschaltet; sonst meldet Tailscale das, und die Meldung erscheint in PrintLab. Der QR-Code nimmt dann die HTTPS-Adresse.
Das Angebot bleibt im privaten Tailnet, nichts geht ins öffentliche Internet.

**Meldungen aufs Handy:** PrintLab hat dafür schon fertige Dienste (Einstellungen → Benachrichtigungen: ntfy, Pushover,
Telegram, E-Mail u. a.), die ohne HTTPS funktionieren. Sie melden Druckereignisse. Für den Ausfall von PrintLab oder des Pi
selbst (dann kann PrintLab nichts melden) gibt es die Überwachung von außen, siehe oben.

Beim Neustart des Pi stellt PrintLab die Verbindung selbst wieder her. „Ausschalten“ beendet Freigabe und Dienst.
Falls schon ein systemweites Tailscale läuft, benutzt PrintLab dieses unverändert. Stand: gegen die Tailscale-Befehle
getestet, aber noch nicht an einem echten Tailnet; beim ersten Durchlauf bitte Meldungen notieren.

## Bekannte Grenzen

- Pi 3 (1 GB): kein offizieller Betrieb; mit viel Swap möglich, aber Speichermangel ist ein bekanntes Risiko.
- ARM-Image und Kamera-Prüfungen (OpenCV) wurden noch nicht auf dem Pi getestet.

## Angebote und Rechnungen

Unter „Kalkulation/Angebote" lassen sich Angebote speichern und als PDF ausgeben. Im Verlauf erzeugt „Rechnung" aus einem
Angebot eine Rechnung (eigene, lückenlose Nummer; Zahlungsziel und Nummernformat unter „Firmendaten"). „Rechnungen" zeigt
Status, Fälligkeit und Summen; Rechnungen werden nie gelöscht, nur storniert. Zusätzliche Positionen (Versand,
Konstruktion …) lassen sich im Rechner anfügen. Im Verlauf verknüpft „Nachkalkulation" gedruckte Jobs aus dem Archiv mit
einem Angebot und stellt die Ist-Kosten dem Angebotspreis gegenüber. Es werden **keine** elektronischen
Rechnungsformate (XRechnung, ZUGFeRD) erzeugt, und die Pflichtangaben für den eigenen Betrieb (§ 14 UStG, Kleinunternehmer-
hinweis, Aufbewahrung) sind mit der Steuerberatung zu klären.

## Inbetriebnahme-Checkliste und Assistent

Einstellungen → System zeigt oben, was schon eingerichtet ist und was noch fehlt (Anmeldung, Drucker, Meldeweg, Sicherung
nach außen, Update-Schutz, Signatur, SSD, Fernzugriff, HTTPS), jeweils mit dem Hinweis, wie man es erledigt.
Seit v1.9.0 steht sie auf der Wartungsseite im Reiter „System & Betrieb"; der **Einrichtungsassistent** darüber zeigt die
offenen Punkte nacheinander (Pflicht zuerst) mit einem Knopf zur passenden Stelle. Ändern tut er nichts selbst.
