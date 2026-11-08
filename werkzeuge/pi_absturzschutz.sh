#!/usr/bin/env bash
# ==============================================================================
# PrintLab - Raspberry Pi Absturzschutz & Watchdog-Automatisierung
# ==============================================================================
# Konfiguriert den Hardware-Watchdog des Raspberry Pi, automatisches Rebooten
# bei Kernel-Panics/Freezes, persistente Crash-Logs und Dienst-Auto-Neustart.
#
# Aufruf auf dem Raspberry Pi:
#   sudo ./werkzeuge/pi_absturzschutz.sh
# ==============================================================================

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
   echo "FEHLER: Dieses Skript muss als root (sudo) ausgefuehrt werden." >&2
   exit 1
fi

echo "============================================================"
echo " PrintLab: Raspberry Pi Absturzschutz & Watchdog-Einrichtung"
echo "============================================================"

# 1. Hardware-Watchdog in config.txt aktivieren
CONFIG_TXT="/boot/firmware/config.txt"
[[ -f "$CONFIG_TXT" ]] || CONFIG_TXT="/boot/config.txt"

if [[ -f "$CONFIG_TXT" ]]; then
    if ! grep -q "^dtparam=watchdog=on" "$CONFIG_TXT"; then
        echo "--> Aktiviere Hardware-Watchdog in $CONFIG_TXT ..."
        echo "dtparam=watchdog=on" >> "$CONFIG_TXT"
    else
        echo "[OK] Hardware-Watchdog in $CONFIG_TXT bereits aktiv."
    fi
fi

# 2. Kernel-Modul bcm2835_wdt laden
if ! grep -q "^bcm2835_wdt" /etc/modules 2>/dev/null; then
    echo "--> Trage bcm2835_wdt in /etc/modules ein ..."
    echo "bcm2835_wdt" >> /etc/modules
fi
modprobe bcm2835_wdt 2>/dev/null || true

# 3. Systemd Hardware Watchdog konfigurieren
mkdir -p /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/10-watchdog.conf << 'EOF'
[Manager]
# Rechner rebootet automatisch, wenn das System 15 Sekunden lang einfriert
RuntimeWatchdogSec=15s
RebootWatchdogSec=2min
KExecWatchdogSec=2min
EOF
echo "[OK] Systemd Runtime-Watchdog auf 15s konfiguriert."

# 4. Automatischer Kernel-Reboot bei Panic / Freeze / Deadlock
cat > /etc/sysctl.d/99-crash-reboot.conf << 'EOF'
# Nach einem Kernel-Panic oder Softlockup wartet das System 10 Sekunden und rebootet dann sauber
kernel.panic = 10
kernel.panic_on_oops = 1
kernel.softlockup_panic = 1
kernel.hung_task_panic = 1
kernel.hung_task_timeout_secs = 120
# OOM-Killer beendet sofort den speicherhungrigen Prozess statt das System im Swap-Thrashing einzufrieren
vm.panic_on_oom = 0
vm.oom_kill_allocating_task = 1
EOF
sysctl -p /etc/sysctl.d/99-crash-reboot.conf 2>/dev/null || true
echo "[OK] Kernel-Panic & Deadlock Auto-Reboot auf 10s sowie OOM-Sofort-Schutz gesetzt."

# 5. Persistentes systemd-Journal (damit Crash-Logs nach Reboot erhalten bleiben)
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/persistent.conf << 'EOF'
[Journal]
Storage=persistent
SystemMaxUse=100M
EOF
systemctl restart systemd-journald 2>/dev/null || true
echo "[OK] Persistenter Log-Speicher fuer Crash-Diagnose aktiviert."

# 6. Swap-Speicher auf 2 GB erhoehen (Schutz gegen Out-Of-Memory bei grossen Slices)
if [[ -f /etc/dphys-swapfile ]]; then
    if grep -q "^CONF_SWAPSIZE=" /etc/dphys-swapfile; then
        CURRENT_SWAP=$(grep "^CONF_SWAPSIZE=" /etc/dphys-swapfile | cut -d= -f2)
        if [[ "$CURRENT_SWAP" -lt 2048 ]]; then
            echo "--> Erhoehe Swap-Speicher von ${CURRENT_SWAP}MB auf 2048MB ..."
            sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
            dphys-swapfile swapoff 2>/dev/null || true
            dphys-swapfile setup 2>/dev/null || true
            dphys-swapfile swapon 2>/dev/null || true
            echo "[OK] 2 GB Swapfile erfolgreich eingerichtet."
        else
            echo "[OK] Swap-Speicher bereits ausreichend gross (${CURRENT_SWAP}MB)."
        fi
    fi
fi

# 7. PrintLab Service Auto-Restart & User-Linger absichern (System- und User-Units)
if systemctl list-unit-files printlab.service &>/dev/null; then
    mkdir -p /etc/systemd/system/printlab.service.d
    cat > /etc/systemd/system/printlab.service.d/restart.conf << 'EOF'
[Unit]
StartLimitIntervalSec=0

[Service]
Restart=always
RestartSec=3s
OOMScoreAdjust=-200
EOF
    systemctl daemon-reload
    systemctl reset-failed printlab.service 2>/dev/null || true
    echo "[OK] PrintLab System-Service Auto-Restart abgesichert (Restart=always, StartLimitIntervalSec=0)."
fi

TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo pi)}"
if id "$TARGET_USER" &>/dev/null; then
    loginctl enable-linger "$TARGET_USER" 2>/dev/null || true
    echo "[OK] systemd Linger fuer Benutzer '$TARGET_USER' aktiviert (Dienst startet beim Booten ohne Login)."
    USER_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
    USER_UID=$(id -u "$TARGET_USER")
    if [[ -n "$USER_HOME" && -d "$USER_HOME/.config/systemd/user" ]]; then
        mkdir -p "$USER_HOME/.config/systemd/user/printlab.service.d"
        cat > "$USER_HOME/.config/systemd/user/printlab.service.d/restart.conf" << 'EOF'
[Unit]
StartLimitIntervalSec=0

[Service]
Restart=always
RestartSec=5s
KillMode=process
OOMScoreAdjust=-200
Environment=PRINTLAB_DISABLE_ASSISTANT_AUTOSETUP=1
EOF
        chown -R "$TARGET_USER:$TARGET_USER" "$USER_HOME/.config/systemd/user/printlab.service.d"
        sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$USER_UID" systemctl --user daemon-reload 2>/dev/null || true
        sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$USER_UID" systemctl --user reset-failed printlab.service 2>/dev/null || true
        sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$USER_UID" systemctl --user enable --now printlab.service 2>/dev/null || true
        sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$USER_UID" systemctl --user enable --now printlab-watch.timer 2>/dev/null || true
        echo "[OK] PrintLab User-Service & Watch-Timer fuer '$TARGET_USER' abgesichert und neu geladen."
    fi
fi

# 7b. Falls Ollama auf dem Pi installiert ist: RAM-Fresser beim Booten begrenzen
if systemctl list-unit-files ollama.service &>/dev/null; then
    mkdir -p /etc/systemd/system/ollama.service.d
    cat > /etc/systemd/system/ollama.service.d/pi-memory.conf << 'EOF'
[Service]
Environment="OLLAMA_KEEP_ALIVE=2m"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
OOMScoreAdjust=500
EOF
    systemctl daemon-reload
    echo "[OK] Ollama Speicherschutz (OLLAMA_KEEP_ALIVE=2m, OOMScoreAdjust=500) gesetzt."
fi

# 8. Status-Check Hardware
echo ""
echo "=== Hardware-Zustandspruefung ==="
if command -v vcgencmd &>/dev/null; then
    TEMP=$(vcgencmd measure_temp 2>/dev/null || echo "unbekannt")
    THROTTLED=$(vcgencmd get_throttled 2>/dev/null || echo "unbekannt")
    echo "CPU-Temperatur : $TEMP"
    echo "Throttled-Status: $THROTTLED"
    if [[ "$THROTTLED" == *"0x0"* ]]; then
        echo "Netzteil/Spannung: PERFEKT (Keine Unterspannung festgestellt)"
    else
        echo "ACHTUNG: Throttled-Wert ist $THROTTLED - Netzteil oder Kuehlung pruefen!"
    fi
else
    echo "vcgencmd nicht verfuegbar (kein Raspberry Pi OS oder emulierte Umgebung)."
fi

echo ""
echo "============================================================"
echo " Absturzschutz erfolgreich eingerichtet!"
echo " Bei einem Freeze/Crash startet der Pi nun automatisch neu"
echo " und PrintLab meldet beim Start den Grund im Dashboard."
echo "============================================================"
