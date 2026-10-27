# Sicherheit

Sicherheitslücken in PrintLab bitte **nicht** öffentlich als Issue melden, sondern privat über
GitHub („Report a vulnerability“ im Repository `Luk1236/printlab`) oder per E-Mail an den Betreiber.

Hinweise zum Betrieb:

- PrintLab im lokalen Netz betreiben; für Zugriff von außen Tailscale/VPN und HTTPS verwenden.
- Anmeldung einschalten (`werkzeuge\admin_passwort_setzen.py`), bevor Hardware-Befehle erreichbar sind.
- Der PC-Slicer lauscht standardmäßig nur auf dem eigenen Rechner; andere Rechner brauchen
  `PC_SLICER_ALLOWED_IPS` und/oder `PC_SLICER_TOKEN`.
- Zugangsdaten (Access Codes, Tokens) liegen in der Datenbank und in `data/`; nicht ins Repository,
  nicht in Backups ohne Verschlüsselung weitergeben.
