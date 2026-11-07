#!/usr/bin/env bash
# ==============================================================================
# PrintLab – OrcaSlicer ARM64 Installer für Raspberry Pi (und Debian/Ubuntu)
# ==============================================================================
# Installiert OrcaSlicer CLI (v2.4.2 ARM64 / aarch64) mit headless Xvfb-Unterstützung
# und WebKitGTK 4.1-Laufzeitumgebung auf dem Raspberry Pi 4 / 5, sodass PrintLab
# 3D-Modelle sauber und fehlerfrei mit echter Bambu-Engine slicen kann.
# ==============================================================================
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "FEHLER: Dieses Skript muss mit Root-Rechten ausgeführt werden (z. B. mit sudo bash werkzeuge/pi_slicer_installieren.sh)." >&2
    exit 1
fi

ARCH=$(uname -m)
echo "=== PrintLab Slicer-Installation für Architektur: $ARCH ==="

case "$ARCH" in
    aarch64|arm64)
        APPIMAGE_URL="https://github.com/kldzj/orca-slicer-arm64/releases/download/v2.4.2-arm64/OrcaSlicer-2.4.2-arm64-linux.AppImage"
        ;;
    x86_64)
        APPIMAGE_URL="https://github.com/SoftFever/OrcaSlicer/releases/download/v2.4.2/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage"
        ;;
    *)
        echo "FEHLER: Nicht unterstützte Architektur: $ARCH." >&2
        exit 1
        ;;
esac

echo "1/4: Installiere System-Abhängigkeiten (WebKitGTK 4.1, Xvfb & GTK3)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || true
apt-get install -y -qq \
    curl \
    wget \
    xvfb \
    libgtk-3-0 \
    libglu1-mesa \
    libwebkit2gtk-4.1-0 \
    libjavascriptcoregtk-4.1-0 \
    libgstreamer1.0-0 \
    libgstreamer-plugins-base1.0-0 \
    libfuse2 || apt-get install -y -qq libwebkit2gtk-4.0-37 libfuse3-3 || true

# Symlink-Kompatibilität zwischen WebKitGTK 4.0 und 4.1 sicherstellen
for libdir in /usr/lib/aarch64-linux-gnu /usr/lib/arm-linux-gnueabihf /usr/lib/x86_64-linux-gnu /usr/lib64 /usr/lib; do
    if [ -d "$libdir" ]; then
        if [ -f "$libdir/libwebkit2gtk-4.0.so.37" ] && [ ! -f "$libdir/libwebkit2gtk-4.1.so.0" ]; then
            ln -sf "$libdir/libwebkit2gtk-4.0.so.37" "$libdir/libwebkit2gtk-4.1.so.0" || true
            ln -sf "$libdir/libjavascriptcoregtk-4.0.so.18" "$libdir/libjavascriptcoregtk-4.1.so.0" || true
        fi
        if [ -f "$libdir/libwebkit2gtk-4.1.so.0" ] && [ ! -f "$libdir/libwebkit2gtk-4.0.so.37" ]; then
            ln -sf "$libdir/libwebkit2gtk-4.1.so.0" "$libdir/libwebkit2gtk-4.0.so.37" || true
            ln -sf "$libdir/libjavascriptcoregtk-4.1.so.0" "$libdir/libjavascriptcoregtk-4.0.so.18" || true
        fi
    fi
done
ldconfig 2>/dev/null || true

INSTALL_DIR="/opt/orca-slicer"
mkdir -p "$INSTALL_DIR"

echo "2/4: Lade OrcaSlicer v2.4.2 herunter ($APPIMAGE_URL)..."
APPIMAGE_PATH="$INSTALL_DIR/orca-slicer.AppImage"
curl -fsSL -o "$APPIMAGE_PATH" "$APPIMAGE_URL"
chmod +x "$APPIMAGE_PATH"

echo "Extrahiere AppImage zur Vermeidung von FUSE-Abhängigkeiten..."
cd "$INSTALL_DIR"
"$APPIMAGE_PATH" --appimage-extract >/dev/null 2>&1 || true

echo "3/4: Richte Headless-Wrapper /usr/local/bin/orca-slicer ein..."
cat > /usr/local/bin/orca-slicer << 'EOF'
#!/usr/bin/env bash
# Headless Wrapper für OrcaSlicer unter Linux / Raspberry Pi OS
export GDK_BACKEND=x11
export NO_AT_BRIDGE=1

# Prüfe WebKitGTK-Laufzeitbibliothek
if ! ldconfig -p 2>/dev/null | grep -q "libwebkit2gtk-4.1"; then
    if [ "$(id -u)" -eq 0 ]; then
        apt-get install -y -qq libwebkit2gtk-4.1-0 libjavascriptcoregtk-4.1-0 2>/dev/null || true
    elif sudo -n true 2>/dev/null; then
        sudo -n apt-get install -y -qq libwebkit2gtk-4.1-0 libjavascriptcoregtk-4.1-0 2>/dev/null || true
    fi
fi

if [ -f /opt/orca-slicer/squashfs-root/AppRun ]; then
    BIN="/opt/orca-slicer/squashfs-root/AppRun"
else
    BIN="/opt/orca-slicer/orca-slicer.AppImage"
fi

if [ -n "${DISPLAY:-}" ]; then
    exec "$BIN" "$@"
elif command -v xvfb-run >/dev/null 2>&1; then
    exec xvfb-run -a -s "-screen 0 1024x768x24" "$BIN" "$@"
else
    exec "$BIN" "$@"
fi
EOF

chmod +x /usr/local/bin/orca-slicer

# Ebenfalls in data/slicer spiegeln falls vorhanden
PRINTLAB_DIR="$(dirname "$(dirname "$(readlink -f "$0")")")"
if [ -d "$PRINTLAB_DIR/data/slicer" ]; then
    mkdir -p "$PRINTLAB_DIR/data/slicer"
    cp -f /usr/local/bin/orca-slicer "$PRINTLAB_DIR/data/slicer/run_slicer.sh" 2>/dev/null || true
fi

echo "4/4: Prüfe Installation..."
if /usr/local/bin/orca-slicer --help >/dev/null 2>&1 || true; then
    echo "=== OrcaSlicer v2.4.2 erfolgreich als CLI installiert! ==="
    echo "Pfad: /usr/local/bin/orca-slicer"
    echo "PrintLab wird nun automatisch die vollwertige OrcaSlicer-Engine nutzen."

    if systemctl is-active --quiet printlab 2>/dev/null; then
        echo "Starte PrintLab-Dienst (System) neu..."
        systemctl restart printlab || true
    fi
    # Falls PrintLab als systemd-User-Dienst läuft (z.B. Benutzer lukas oder pi)
    TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo 'lukas')}"
    if [ -n "$TARGET_USER" ] && id "$TARGET_USER" &>/dev/null; then
        su - "$TARGET_USER" -c "systemctl --user restart printlab 2>/dev/null" || true
    fi
else
    echo "Installation abgeschlossen."
fi
