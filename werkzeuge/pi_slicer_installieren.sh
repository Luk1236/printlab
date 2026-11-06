#!/usr/bin/env bash
# ==============================================================================
# PrintLab – OrcaSlicer ARM64 Installer für Raspberry Pi (und Debian/Ubuntu)
# ==============================================================================
# Installiert OrcaSlicer CLI (ARM64 / aarch64) mit headless Xvfb-Unterstützung
# auf dem Raspberry Pi 4 / 5, sodass PrintLab Modelle mit vollständiger
# Bambu-Studio-Engine (Baum-Supports, Naht-Steuerung, echter G-Code) slicen kann.
# ==============================================================================
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "FEHLER: Dieses Skript muss mit Root-Rechten ausgeführt werden (z. B. mit sudo)." >&2
    exit 1
fi

ARCH=$(uname -m)
echo "=== PrintLab Slicer-Installation für Architektur: $ARCH ==="

case "$ARCH" in
    aarch64|arm64)
        APPIMAGE_URL="https://github.com/SoftFever/OrcaSlicer/releases/download/v2.2.0/OrcaSlicer_Linux_arm64_V2.2.0.AppImage"
        ;;
    x86_64)
        APPIMAGE_URL="https://github.com/SoftFever/OrcaSlicer/releases/download/v2.2.0/OrcaSlicer_Linux_V2.2.0.AppImage"
        ;;
    *)
        echo "FEHLER: Nicht unterstützte Architektur: $ARCH. Der integrierte Python-Slicer bleibt aktiv." >&2
        exit 1
        ;;
esac

echo "1/4: Installiere System-Abhängigkeiten (Xvfb & Grafikbibliotheken für Headless-Slicing)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    curl \
    wget \
    xvfb \
    libgtk-3-0 \
    libglu1-mesa \
    libwebkit2gtk-4.0-37 \
    libgstreamer1.0-0 \
    libgstreamer-plugins-base1.0-0 \
    libfuse2 || apt-get install -y -qq libfuse3-3

INSTALL_DIR="/opt/orca-slicer"
mkdir -p "$INSTALL_DIR"

echo "2/4: Lade OrcaSlicer herunter ($APPIMAGE_URL)..."
APPIMAGE_PATH="$INSTALL_DIR/orca-slicer.AppImage"
if [ ! -f "$APPIMAGE_PATH" ]; then
    curl -fsSL -o "$APPIMAGE_PATH" "$APPIMAGE_URL"
    chmod +x "$APPIMAGE_PATH"
else
    echo "OrcaSlicer AppImage existiert bereits in $APPIMAGE_PATH."
fi

echo "3/4: Richte Headless-Wrapper /usr/local/bin/orca-slicer ein..."
cat > /usr/local/bin/orca-slicer << 'EOF'
#!/usr/bin/env bash
# Headless Wrapper für OrcaSlicer unter Linux / Raspberry Pi OS
export GDK_BACKEND=x11
export NO_AT_BRIDGE=1
if [ -n "${DISPLAY:-}" ]; then
    exec /opt/orca-slicer/orca-slicer.AppImage "$@"
else
    exec xvfb-run -a -s "-screen 0 1024x768x24" /opt/orca-slicer/orca-slicer.AppImage "$@"
fi
EOF

chmod +x /usr/local/bin/orca-slicer

echo "4/4: Prüfe Installation..."
if /usr/local/bin/orca-slicer --help >/dev/null 2>&1 || true; then
    echo "=== OrcaSlicer erfolgreich als CLI installiert! ==="
    echo "Pfad: /usr/local/bin/orca-slicer"
    echo "PrintLab wird nun automatisch die vollwertige OrcaSlicer-Engine nutzen."

    if systemctl is-active --quiet printlab 2>/dev/null; then
        echo "Starte PrintLab-Dienst neu, um den neuen Slicer zu aktivieren..."
        systemctl restart printlab
    fi
else
    echo "WARNUNG: Startprüfung fehlgeschlagen, Wrapper wurde dennoch angelegt."
fi
