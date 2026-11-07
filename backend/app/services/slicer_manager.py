"""Automatischer OrcaSlicer-Download & Manager aus GitHub (SoftFever/OrcaSlicer).

Lädt bei Bedarf automatisch eine vollwertige OrcaSlicer-CLI direkt von GitHub herunter
und richtet sie betriebssystemspezifisch ein (Windows, Linux x86_64 und Linux ARM64 / Raspberry Pi).
Ersetzt den frueheren provisorischen Python-Slicer durch die echte offizielle Slicer-Engine.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

ORCA_VERSION = "2.4.2"
SOFTFEVER_REPO = "SoftFever/OrcaSlicer"
ARM64_REPO = "kldzj/orca-slicer-arm64"

# Bekannte Download-URLs fuer v2.4.2
URLS = {
    ("linux", "arm64"): f"https://github.com/{ARM64_REPO}/releases/download/v{ORCA_VERSION}-arm64/OrcaSlicer-{ORCA_VERSION}-arm64-linux.AppImage",
    ("linux", "aarch64"): f"https://github.com/{ARM64_REPO}/releases/download/v{ORCA_VERSION}-arm64/OrcaSlicer-{ORCA_VERSION}-arm64-linux.AppImage",
    ("linux", "x86_64"): f"https://github.com/{SOFTFEVER_REPO}/releases/download/v{ORCA_VERSION}/OrcaSlicer_Linux_AppImage_Ubuntu2404_V{ORCA_VERSION}.AppImage",
    ("windows", "x86_64"): f"https://github.com/{SOFTFEVER_REPO}/releases/download/v{ORCA_VERSION}/OrcaSlicer_Windows_V{ORCA_VERSION}_x64_portable.zip",
    ("windows", "amd64"): f"https://github.com/{SOFTFEVER_REPO}/releases/download/v{ORCA_VERSION}/OrcaSlicer_Windows_V{ORCA_VERSION}_x64_portable.zip",
    ("windows", "arm64"): f"https://github.com/{SOFTFEVER_REPO}/releases/download/v{ORCA_VERSION}/OrcaSlicer_Windows_V{ORCA_VERSION}_arm64_portable.zip",
}

_install_progress: dict[str, Any] = {
    "status": "idle",
    "percent": 0,
    "message": "",
    "error": None,
}


def get_slicer_dir() -> Path:
    """Verzeichnis fuer die heruntergeladene Slicer-Engine."""
    base = Path(getattr(settings, "base_dir", None) or Path.cwd())
    sdir = base / "data" / "slicer"
    sdir.mkdir(parents=True, exist_ok=True)
    return sdir


def get_system_arch() -> tuple[str, str]:
    """Liefert (system_lower, arch_lower), z.B. ('linux', 'aarch64') oder ('windows', 'amd64')."""
    sys_name = platform.system().lower()
    mach = platform.machine().lower()
    if mach in ("x86_64", "amd64"):
        mach = "x86_64"
    elif mach in ("aarch64", "arm64", "armv8l"):
        mach = "arm64"
    return sys_name, mach


def find_existing_slicer() -> str | None:
    """Prueft, ob bereits ein funktionierender Bambu Studio- oder OrcaSlicer existiert."""
    env_prog = (os.environ.get("BAMBU_STUDIO") or os.environ.get("ORCA_SLICER") or "").strip()
    if env_prog and Path(env_prog).is_file():
        return env_prog

    # 1. Managed PrintLab-Slicer in data/slicer
    sdir = get_slicer_dir()
    for candidate in [
        sdir / "run_slicer.sh",
        sdir / "orca-slicer",
        sdir / "orca-slicer.AppImage",
        sdir / "orca-slicer.exe",
        sdir / "OrcaSlicer.exe",
        sdir / "squashfs-root" / "AppRun",
    ]:
        if candidate.is_file():
            return str(candidate)

    # 2. System-Pfade
    sys_candidates = [
        r"C:\Program Files\Bambu Studio\bambu-studio.exe",
        r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
        r"C:\Program Files\Orca Slicer\orca-slicer.exe",
        Path.home() / "AppData/Local/Programs/OrcaSlicer/orca-slicer.exe",
        "/usr/local/bin/orca-slicer",
        "/usr/bin/orca-slicer",
        "/opt/orca-slicer/orca-slicer",
        "/opt/orca-slicer/orca-slicer.AppImage",
        "/usr/local/bin/bambu-studio",
        "/usr/bin/bambu-studio",
    ]
    for c in sys_candidates:
        if Path(c).is_file():
            return str(c)

    return None


def get_slicer_status() -> dict[str, Any]:
    """Status der Slicer-Engine fuer API und UI."""
    existing = find_existing_slicer()
    sys_name, arch = get_system_arch()
    return {
        "installed": bool(existing),
        "path": existing,
        "engine": "bambu-studio" if (existing and "bambu" in existing.lower()) else "orca-slicer",
        "version": ORCA_VERSION,
        "platform": f"{sys_name}_{arch}",
        "download_url": URLS.get((sys_name, arch)),
        "progress": dict(_install_progress),
    }


def install_orca_slicer_from_github() -> str:
    """Laedt die echte OrcaSlicer-CLI von GitHub herunter und richtet sie ein.
    
    Returns:
        Pfad zur ausfuehrbaren Datei.
    """
    global _install_progress
    sys_name, arch = get_system_arch()
    url = URLS.get((sys_name, arch)) or URLS.get((sys_name, "x86_64"))
    if not url:
        raise RuntimeError(f"Kein OrcaSlicer-Build fuer Plattform {sys_name}/{arch} gefunden.")

    sdir = get_slicer_dir()
    _install_progress = {
        "status": "downloading",
        "percent": 0,
        "message": f"Lade OrcaSlicer v{ORCA_VERSION} von GitHub...",
        "error": None,
    }
    logger.info("[Slicer-Manager] Lade OrcaSlicer von %s herunter...", url)

    try:
        # 1. Download
        ext = ".zip" if url.endswith(".zip") else ".AppImage"
        target_file = sdir / f"download_{ORCA_VERSION}{ext}"

        req = urllib.request.Request(url, headers={"User-Agent": "PrintLab-Slicer-Installer"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(target_file, "wb") as out_f:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out_f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = min(90, int(downloaded / total * 90))
                    _install_progress["percent"] = pct

        _install_progress["percent"] = 92
        _install_progress["message"] = "Entpacke & konfiguriere Slicer..."

        # 2. Einrichten
        if ext == ".zip":
            with zipfile.ZipFile(target_file, "r") as zf:
                zf.extractall(sdir)
            target_file.unlink(missing_ok=True)
            # Finde .exe
            exe = next(sdir.glob("**/orca-slicer.exe"), None) or next(sdir.glob("**/OrcaSlicer.exe"), None)
            if not exe:
                raise RuntimeError("orca-slicer.exe nicht in heruntergeladener ZIP gefunden.")
            final_bin = str(exe)
        else:
            # Linux AppImage
            appimage = sdir / "orca-slicer.AppImage"
            shutil.move(str(target_file), str(appimage))
            appimage.chmod(appimage.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

            # Versuchen, mit --appimage-extract zu entpacken, damit kein FUSE noetig ist
            try:
                subprocess.run(
                    [str(appimage), "--appimage-extract"],
                    cwd=str(sdir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    check=False,
                )
            except Exception as e:
                logger.warning("[Slicer-Manager] AppImage-Extraktion uebersprungen: %s", e)

            # Headless-Wrapper anlegen
            wrapper = sdir / "run_slicer.sh"
            wrapper_content = (
                "#!/usr/bin/env bash\n"
                "export GDK_BACKEND=x11\n"
                "export NO_AT_BRIDGE=1\n"
                "# Automatisch fehlende WebKitGTK 4.1 / Xvfb Laufzeitbibliotheken nachinstallieren falls sudo verfuegbar\n"
                'if ! ldconfig -p 2>/dev/null | grep -q "libwebkit2gtk-4.1"; then\n'
                '  if [ "$(id -u)" -eq 0 ]; then\n'
                "    apt-get update -qq 2>/dev/null && apt-get install -y -qq libwebkit2gtk-4.1-0 libjavascriptcoregtk-4.1-0 xvfb 2>/dev/null || true\n"
                "  elif sudo -n true 2>/dev/null; then\n"
                "    sudo -n apt-get update -qq 2>/dev/null && sudo -n apt-get install -y -qq libwebkit2gtk-4.1-0 libjavascriptcoregtk-4.1-0 xvfb 2>/dev/null || true\n"
                "  fi\n"
                "fi\n"
                'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
                'if [ -f "$DIR/squashfs-root/AppRun" ]; then\n'
                '  BIN="$DIR/squashfs-root/AppRun"\n'
                "else\n"
                '  BIN="$DIR/orca-slicer.AppImage"\n'
                "fi\n"
                'if [ -n "$DISPLAY" ]; then\n'
                '  exec "$BIN" "$@"\n'
                "elif command -v xvfb-run >/dev/null 2>&1; then\n"
                '  exec xvfb-run -a -s "-screen 0 1024x768x24" "$BIN" "$@"\n'
                "else\n"
                '  exec "$BIN" "$@"\n'
                "fi\n"
            )
            wrapper.write_text(wrapper_content, encoding="utf-8")
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            final_bin = str(wrapper)

        _install_progress = {
            "status": "completed",
            "percent": 100,
            "message": f"OrcaSlicer v{ORCA_VERSION} erfolgreich installiert!",
            "error": None,
        }
        logger.info("[Slicer-Manager] OrcaSlicer erfolgreich installiert: %s", final_bin)
        return final_bin

    except Exception as exc:
        _install_progress = {
            "status": "failed",
            "percent": 0,
            "message": f"Installation fehlgeschlagen: {exc}",
            "error": str(exc),
        }
        logger.error("[Slicer-Manager] Fehler bei OrcaSlicer-Installation: %s", exc, exc_info=True)
        raise
