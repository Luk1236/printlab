# PrintLab auf dem Raspberry Pi (4/5)

> **Stand:** Anleitung, noch nicht auf echter Hardware durchgespielt. Beim ersten Durchlauf bitte Abweichungen
> notieren und hier nachtragen. Ein Raspberry Pi 3 mit 1 GB reicht nach heutigem Wissen **nicht** zuverlässig
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

## Erster Start

1. Einrichtung abschließen und **Anmeldung einschalten** (Passwort wählen). Ohne Anmeldung sind Hardware-Befehle
   gesperrt, und jeder im Netz könnte Drucker steuern.
2. Drucker hinzufügen (IP, Seriennummer, Zugangscode).
3. Optional PC-Slicer: auf dem Windows-PC `starte_pc_slicer.bat`, in den PrintLab-Einstellungen die Adresse des PCs
   eintragen. Auf dem PC `PC_SLICER_ALLOWED_IPS=<pi-ip>` setzen, sonst weist der Slicer den Pi ab.

## Betrieb

| Aufgabe | Befehl |
|---|---|
| Protokoll ansehen | `docker compose logs -f printlab` |
| Stoppen / Starten | `docker compose stop` / `docker compose start` |
| Aktualisieren | `git pull && docker compose up -d --build` |
| Sicherung | Einstellungen → Sicherung (lokale Sicherung) oder Volume `printlab_data` kopieren |

## Zugriff von unterwegs

Am einfachsten über **Tailscale** (`curl -fsSL https://tailscale.com/install.sh | sh`, `sudo tailscale up`). So
bleibt PrintLab außerhalb des Heimnetzes unsichtbar; HTTPS ist dann nur nötig, wenn weitere Personen zugreifen.

## Bekannte Grenzen

- Pi 3 (1 GB): kein offizieller Betrieb; mit viel Swap möglich, aber Speichermangel ist ein bekanntes Risiko.
- ARM-Image und Kamera-Prüfungen (OpenCV) wurden noch nicht auf dem Pi getestet.
