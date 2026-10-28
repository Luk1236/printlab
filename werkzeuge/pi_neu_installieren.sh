#!/usr/bin/env bash
# PrintLab auf dem Raspberry Pi neu aufspielen (ohne Docker, ohne Root-Rechte).
#
# Entfernt alte Versionen (PrintLab, Bambuddy, Bambuddy-Fork) im Home-Ordner, sichert vorher deren Daten
# und spielt den aktuellen Stand aus GitHub neu auf. Läuft als normaler Benutzer; der Dienst startet
# beim Hochfahren von selbst (systemd --user, "Linger" muss eingeschaltet sein).
#
# Aufruf (das Repo ist öffentlich, ein Token ist nicht nötig):
#   curl -fsSL https://raw.githubusercontent.com/Luk1236/printlab/bambu-monitor-port/werkzeuge/pi_neu_installieren.sh | bash
# Nur bei einem privaten Fork: GH_TOKEN (GitHub-Token mit Leserecht) vorher mit export setzen.
#
# Optionen (Umgebungsvariablen):
#   PRINTLAB_REF=v1.2.2        Tag oder Branch (Standard: bambu-monitor-port)
#   PRINTLAB_FRESH_DATA=1      gesicherte Daten NICHT zurückspielen (leere Datenbank)
#   PRINTLAB_UPDATE_PUBKEY="ssh-ed25519 AAAA..."   öffentlicher Signaturschlüssel: Updates werden dann nur noch von
#                              Tags angenommen, die damit signiert sind (siehe docs/UPDATE-SIGNATUR.md)
#   PRINTLAB_STORE_TOKEN=1     (nur mit GH_TOKEN) Token in ~/.config/printlab.env (nur für dich lesbar) speichern,
#                              damit die Update-Funktion in PrintLab ein privates Repo erreicht
set -euo pipefail

REPO="Luk1236/printlab"
REF="${PRINTLAB_REF:-bambu-monitor-port}"
DIR="$HOME/printlab"
BACKUP="$HOME/printlab-backups/$(date +%Y%m%d-%H%M%S)"
GH_TOKEN="${GH_TOKEN:-}"   # leer = öffentliches Repo, anonym

step() { printf '\n== %s\n' "$1"; }

step "1/7 Dienste stoppen"
for unit in printlab-backup.timer printlab-watch.timer printlab.service bambuddy.service; do
  systemctl --user disable --now "$unit" 2>/dev/null || true
done

step "2/7 Daten sichern nach $BACKUP"
mkdir -p "$BACKUP"
for d in "$DIR" "$HOME/bambuddy" "$HOME/Bambuddy" "$HOME/Bambuddy-Fork"; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  for sub in data logs; do
    [ -d "$d/$sub" ] && cp -a "$d/$sub" "$BACKUP/$name-$sub"
  done
  for f in "$d"/*.db "$d"/*.db-wal "$d"/*.db-shm "$d"/hardware*.json "$d"/magazine*.json \
           "$d"/price_list.json "$d"/quote_history.json; do
    [ -e "$f" ] && cp -a "$f" "$BACKUP/$name-$(basename "$f")"
  done
done
echo "gesichert: $(du -sh "$BACKUP" | cut -f1)"

step "3/7 alte Versionen entfernen"
rm -rf "$DIR" "$HOME/bambuddy" "$HOME/Bambuddy" "$HOME/Bambuddy-Fork"
rm -f "$HOME/.config/systemd/user/bambuddy.service"

step "4/7 Quellcode holen ($REF)"
if [ -n "$GH_TOKEN" ]; then
  git clone --quiet --depth 1 --branch "$REF" "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git" "$DIR"
else
  git clone --quiet --depth 1 --branch "$REF" "https://github.com/${REPO}.git" "$DIR"
fi
git -C "$DIR" remote set-url origin "https://github.com/${REPO}.git"   # Token nicht auf der Platte lassen
echo "Stand: $(git -C "$DIR" log --oneline -1)"
mkdir -p "$DIR/data" "$DIR/logs"

if [ -z "${PRINTLAB_FRESH_DATA:-}" ] && [ -d "$BACKUP/printlab-data" ]; then
  step "   Daten zurückspielen"
  cp -a "$BACKUP/printlab-data/." "$DIR/data/"
fi

if [ -n "${PRINTLAB_UPDATE_PUBKEY:-}" ]; then
  step "   Update-Signaturschlüssel hinterlegen"
  if printf '%s' "$PRINTLAB_UPDATE_PUBKEY" | grep -Eq '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+) [A-Za-z0-9+/=]+( [^"]*)?$'; then
    printf 'printlab namespaces="git" %s
' "$PRINTLAB_UPDATE_PUBKEY" > "$DIR/data/update_allowed_signers"
    command -v ssh-keygen >/dev/null || echo "Hinweis: ssh-keygen fehlt (sudo apt install openssh-client), sonst lehnt PrintLab alle Updates ab."
    echo "Updates werden ab jetzt nur noch mit gültiger Signatur eingespielt."
  else
    echo "PRINTLAB_UPDATE_PUBKEY sieht nicht wie ein öffentlicher SSH-Schlüssel aus, nicht hinterlegt." >&2
  fi
fi

step "5/7 Python-Umgebung und Pakete (dauert einige Minuten)"
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install --quiet --upgrade pip wheel
"$DIR/.venv/bin/pip" install --quiet -r "$DIR/requirements.txt"

step "6/7 Dienst einrichten und starten"
mkdir -p "$HOME/.config/systemd/user"
if [ -n "${PRINTLAB_STORE_TOKEN:-}" ] && [ -n "$GH_TOKEN" ]; then
  umask 077
  printf 'PRINTLAB_GITHUB_TOKEN=%s\n' "$GH_TOKEN" > "$HOME/.config/printlab.env"
  umask 022
  echo "Token für die Update-Funktion gespeichert: ~/.config/printlab.env (Rechte 600)"
fi
cat > "$HOME/.config/systemd/user/printlab.service" <<'EOF'
[Unit]
Description=PrintLab
After=network-online.target

[Service]
WorkingDirectory=%h/printlab
Environment=DATA_DIR=%h/printlab/data
Environment=LOG_DIR=%h/printlab/logs
# Nach einem Update in PrintLab beendet sich der Dienst sauber; Restart=always startet ihn mit dem neuen Stand
Environment=PRINTLAB_AUTO_RESTART=1
# Anmeldung vorgeschrieben: bis das Passwort angelegt ist, ist die Schnittstelle gesperrt (nur /setup ist erreichbar)
Environment=PRINTLAB_REQUIRE_AUTH=1
EnvironmentFile=-%h/.config/printlab.env
# Update-Schutz: baut nach einem Update, das nicht anläuft, auf die vorherige Version zurück (und spielt dabei
# bei Bedarf Pakete neu ein, das kann dauern)
TimeoutStartSec=900
ExecStartPre=-%h/printlab/.venv/bin/python %h/printlab/werkzeuge/update_guard.py
ExecStart=%h/printlab/.venv/bin/python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --loop asyncio
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
# Überwachung von außen: prüft jede Minute, startet PrintLab bei Ausfall neu und meldet es (siehe werkzeuge/ueberwachung.py)
cat > "$HOME/.config/systemd/user/printlab-watch.service" <<'EOF'
[Unit]
Description=PrintLab Überwachung

[Service]
Type=oneshot
Environment=DATA_DIR=%h/printlab/data
EnvironmentFile=-%h/.config/printlab.env
ExecStart=/usr/bin/python3 %h/printlab/werkzeuge/ueberwachung.py
EOF
cat > "$HOME/.config/systemd/user/printlab-watch.timer" <<'EOF'
[Unit]
Description=PrintLab Überwachung jede Minute

[Timer]
OnBootSec=3min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
EOF
# Tägliche Sicherung auf einen Datenträger außerhalb der SD-Karte (nur aktiv, wenn PRINTLAB_BACKUP_TARGET in
# ~/.config/printlab.env gesetzt ist, siehe werkzeuge/sicherung_extern.py)
cat > "$HOME/.config/systemd/user/printlab-backup.service" <<'EOF'
[Unit]
Description=PrintLab Sicherung nach außen

[Service]
Type=oneshot
Environment=DATA_DIR=%h/printlab/data
EnvironmentFile=-%h/.config/printlab.env
ExecStart=/usr/bin/python3 %h/printlab/werkzeuge/sicherung_extern.py
EOF
cat > "$HOME/.config/systemd/user/printlab-backup.timer" <<'EOF'
[Unit]
Description=PrintLab Sicherung nach außen jeden Tag

[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now printlab.service
systemctl --user enable --now printlab-watch.timer
systemctl --user enable --now printlab-backup.timer

step "7/7 Prüfen"
for _ in $(seq 1 90); do   # der erste Start dauert auf dem Pi gut eine Minute (Datenbank, Schlüssel, Kataloge)
  if curl -fsS -m 5 http://localhost:8000/api/v1/updates/version 2>/dev/null; then
    echo
    echo "PrintLab läuft: http://$(hostname -I | awk '{print $1}'):8000"
    echo "Sicherung der alten Daten: $BACKUP"
    exit 0
  fi
  sleep 4
done
echo "PrintLab antwortet noch nicht. Protokoll: journalctl --user -u printlab -n 40 --no-pager" >&2
exit 1
