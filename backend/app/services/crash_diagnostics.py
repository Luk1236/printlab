"""Erkennung von Rechner- und Dienst-Abstürzen (gedacht für den Raspberry Pi)
sowie Diagnose der Absturzursache (Unterspannung, OOM-Killer, Überhitzung, Kernel-Panic, Watchdog).

Speichert den Zustand vor und nach Neustarts und analysiert die vorherigen Boot-Logs,
damit der Benutzer sofort erfährt, warum das System abgestürzt ist, und automatische
Schutzmaßnahmen greifen.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BOOT_STATE_FILE = "boot_state.json"
CRASH_REPORT_FILE = "last_crash_report.json"

# Häufigste Absturzursachen
CAUSE_UNDERVOLTAGE = "undervoltage"
CAUSE_OOM = "oom"
CAUSE_THERMAL = "thermal"
CAUSE_KERNEL_PANIC = "kernel_panic"
CAUSE_WATCHDOG = "watchdog"
CAUSE_POWER_LOSS = "power_loss"
CAUSE_SERVICE_CRASH = "service_crash"


def _data_dir(base_dir: Path | str) -> Path:
    p = Path(base_dir)
    data = p / "data"
    if data.is_dir() or not p.exists():
        return data
    return p


def get_system_boot_id() -> str | None:
    """Eindeutige ID des aktuellen Linux-Boots aus /proc/sys/kernel/random/boot_id."""
    try:
        path = Path("/proc/sys/kernel/random/boot_id")
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        pass
    # Fallback für Nicht-Linux oder Systeme ohne boot_id
    try:
        raw = Path("/proc/uptime").read_text(encoding="utf-8", errors="replace").strip()
        uptime_sec = float(raw.split()[0])
        boot_epoch = int(time.time() - uptime_sec)
        return f"uptime-{boot_epoch}"
    except (OSError, ValueError, IndexError):
        return None


def read_previous_boot_logs(max_lines: int = 30) -> list[str]:
    """Liest die letzten Zeilen vor dem vorherigen Neustart aus dem systemd-Journal (journalctl -b -1)."""
    if shutil.which("journalctl") is None:
        return []
    try:
        res = subprocess.run(  # noqa: S603 - feste Argumentliste
            ["journalctl", "-b", "-1", "-n", str(max_lines), "--no-pager"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def check_undervoltage_flags() -> tuple[bool, list[str]]:
    """Prüft vcgencmd get_throttled auf Unterspannung (aktuell oder seit Boot)."""
    if shutil.which("vcgencmd") is None:
        return False, []
    try:
        out = subprocess.run(  # noqa: S603
            ["vcgencmd", "get_throttled"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout
        val_str = out.strip().split("=")[-1]
        val = int(val_str, 16)
        flags: list[str] = []
        if val & 0x1:
            flags.append("Unterspannung liegt aktuell an (unter 4,63 V)")
        if val & 0x10000:
            flags.append("Unterspannung seit dem Systemstart aufgetreten")
        if val & 0x40000:
            flags.append("Throttling/Takt-Drosselung seit dem Systemstart aufgetreten")
        if val & 0x80000:
            flags.append("Temperaturgrenze seit dem Systemstart erreicht")
        has_undervoltage = bool(val & 0x10001)
        return has_undervoltage, flags
    except (OSError, subprocess.SubprocessError, ValueError):
        return False, []


def determine_cause_from_logs(logs: list[str], throttled_flags: list[str]) -> tuple[str, str, str, list[str]]:
    """Analysiert Logs und Hardware-Flags und liefert (cause, title, explanation, recommendations)."""
    # 1. Unterspannung hat höchste Priorität beim Pi
    if any("Unterspannung" in f for f in throttled_flags):
        return (
            CAUSE_UNDERVOLTAGE,
            "Unterspannung erkannt (Netzteil zu schwach / Spannungseinbruch)",
            "Der Raspberry Pi hat einen kritischen Spannungsabfall unter 4,63 V registriert. "
            "Dies ist die häufigste Ursache für plötzliche Komplett-Abstürze oder spontane Reboots des Pi.",
            [
                "Offizielles Raspberry Pi 27W USB-C Netzteil (5,1 V / 5 A) für Pi 5 verwenden.",
                "USB-Peripherie (Kameras, externe Festplatten/SSDs, Sensoren) über einen aktiven USB-Hub mit separater Stromversorgung betreiben.",
                "USB-Kabel und Mehrfachsteckdosen auf Wackelkontakt oder Übergangswiderstand prüfen.",
            ],
        )

    log_blob = "\n".join(logs).lower()

    # 2. Out of Memory
    if "out of memory" in log_blob or "oom-killer" in log_blob or "killed process" in log_blob:
        return (
            CAUSE_OOM,
            "Arbeitsspeicher erschöpft (Out of Memory - OOM-Killer)",
            "Dem Betriebssystem ist der Arbeitsspeicher (RAM) vollständig ausgegangen. "
            "Der Linux-Kernel musste Prozesse zwangsweise beenden oder das System ist eingefroren.",
            [
                "Swap-Speicher einrichten oder vergrößern (z. B. 2 GB Swap mit werkzeuge/pi_absturzschutz.sh).",
                "Große 3MF-Modelle über den PC-Slicer statt über das integrierte Sidecar auf dem Pi verarbeiten.",
                "Parallele Video-Livestreams auf der Kamera-Wand reduzieren.",
            ],
        )

    # 3. Überhitzung
    if "critical temperature" in log_blob or any("Temperaturgrenze" in f for f in throttled_flags):
        return (
            CAUSE_THERMAL,
            "Kritische Überhitzung (Thermisches Not-Aus)",
            "Der Prozessor hat die Notfall-Temperaturschwelle überschritten (über 82 °C) und der Rechner "
            "hat sich zum Schutz der Komponenten notabgeschaltet.",
            [
                "Lüfter auf Funktion und Staubablagerungen prüfen.",
                "Kühlkörper-Sitz kontrollieren und für freie Luftzirkulation im Gehäuse sorgen.",
            ],
        )

    # 4. Kernel Panic / Oops
    if "kernel panic" in log_blob or "internal error: oops" in log_blob or "bug: unable to handle" in log_blob:
        return (
            CAUSE_KERNEL_PANIC,
            "Kernel-Panic / Betriebssystem-Fehler",
            "Ein schwerer Treiber- oder Kernel-Fehler im Betriebssystem hat den Absturz ausgelöst.",
            [
                "Betriebssystem-Pakete aktualisieren (sudo apt update && sudo apt upgrade).",
                "SD-Karte oder Dateisystem auf Fehler prüfen (Dateisystem-Check).",
            ],
        )

    # 5. Watchdog-Reset (System-Freeze)
    if "watchdog" in log_blob:
        return (
            CAUSE_WATCHDOG,
            "Hardware-Watchdog-Neustart (System hatte sich aufgehängt)",
            "Das System hat für mehr als 15 Sekunden nicht mehr reagiert (mögliche I/O-Blockade der SD-Karte). "
            "Der Hardware-Watchdog hat den Pi automatisch neu gestartet, um den Betrieb wiederherzustellen.",
            [
                "Schnellere SD-Karte (Klasse A2/U3) oder USB-SSD/NVMe nutzen, um I/O-Hänger zu vermeiden.",
                "Absturzschutz mit werkzeuge/pi_absturzschutz.sh aktiv halten.",
            ],
        )

    # 6. Plötzlicher Stromausfall / Hard Reset
    return (
        CAUSE_POWER_LOSS,
        "Plötzlicher Stromausfall / Harter Neustart",
        "Der Raspberry Pi wurde ohne reguläres Herunterfahren abrupt stromlos oder hart zurückgesetzt. "
        "Es wurden keine Kernel-Panics oder Unterspannungsmeldungen im Systemjournal hinterlassen.",
        [
            "Stromversorgung und Zuleitung auf Unterbrechungen prüfen.",
            "Den Raspberry Pi immer über das System-Menü sauber herunterfahren statt den Stecker zu ziehen.",
        ],
    )


def record_heartbeat(base_dir: Path | str) -> None:
    """Schreibt periodisch einen Heartbeat mit aktueller Boot-ID und Zeitstempel."""
    data_dir = _data_dir(base_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    state_file = data_dir / BOOT_STATE_FILE  # SEC-PATH-OK: feste Namenskonstante
    boot_id = get_system_boot_id()
    state = {
        "boot_id": boot_id,
        "pid": os.getpid(),
        "last_heartbeat": time.time(),
        "clean_shutdown": False,
    }
    try:
        temp_file = data_dir / f"{BOOT_STATE_FILE}.tmp"
        temp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp_file.replace(state_file)
    except OSError as exc:
        logger.debug("Fehler beim Schreiben des Boot-Heartbeats: %s", exc)


def record_clean_shutdown(base_dir: Path | str) -> None:
    """Wird beim sauberen Herunterfahren von PrintLab (Lifespan-Ende) aufgerufen."""
    data_dir = _data_dir(base_dir)
    state_file = data_dir / BOOT_STATE_FILE  # SEC-PATH-OK: feste Namenskonstante
    if not state_file.exists():
        return
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["clean_shutdown"] = True
        state["shutdown_at"] = time.time()
        temp_file = data_dir / f"{BOOT_STATE_FILE}.tmp"
        temp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp_file.replace(state_file)
        logger.info("[CrashDiagnostics] Sauberer Shutdown registriert.")
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Fehler beim Aktualisieren des Shutdown-Status: %s", exc)


def check_and_generate_crash_report(base_dir: Path | str) -> dict[str, Any] | None:
    """Untersucht beim Start, ob der letzte Stopp ein Absturz oder Rechner-Reboot war.

    Gibt den neu generierten Crash-Report zurück, falls ein Absturz erkannt wurde.
    """
    data_dir = _data_dir(base_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    state_file = data_dir / BOOT_STATE_FILE  # SEC-PATH-OK: feste Namenskonstante
    report_file = data_dir / CRASH_REPORT_FILE  # SEC-PATH-OK: feste Namenskonstante

    current_boot_id = get_system_boot_id()
    if not state_file.exists():
        # Erster Start: Heartbeat anlegen, kein vorangegangener Absturz bekannt
        record_heartbeat(base_dir)
        return None

    try:
        prev_state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        record_heartbeat(base_dir)
        return None

    prev_boot_id = prev_state.get("boot_id")
    clean_shutdown = prev_state.get("clean_shutdown", True)
    last_heartbeat = prev_state.get("last_heartbeat", 0)

    # Wenn der Dienst sauber beendet wurde (regulärer Shutdown/Reboot), liegt kein Absturz vor
    if clean_shutdown:
        record_heartbeat(base_dir)
        return None

    # Prüfen, ob Rechner oder Dienst abgestürzt ist
    is_new_system_boot = bool(current_boot_id and prev_boot_id and current_boot_id != prev_boot_id)
    is_service_crash = not is_new_system_boot

    # Ein Absturz oder Rechner-Reboot ist aufgetreten!
    logger.warning(
        "[CrashDiagnostics] Unerwarteter Neustart erkannt (Neuer Boot: %s, Unsauberer Shutdown: %s). Starte Ursachen-Analyse...",
        is_new_system_boot,
        not clean_shutdown,
    )

    # Hardware-Flags und vorherige Logs holen
    has_undervoltage, throttled_flags = check_undervoltage_flags()
    recent_logs = read_previous_boot_logs(max_lines=30)

    cause, title, explanation, recommendations = determine_cause_from_logs(recent_logs, throttled_flags)

    report = {
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "is_system_reboot": is_new_system_boot,
        "is_service_crash": is_service_crash,
        "previous_boot_id": prev_boot_id,
        "current_boot_id": current_boot_id,
        "last_heartbeat": last_heartbeat,
        "cause": cause,
        "title": title,
        "explanation": explanation,
        "recommendations": recommendations,
        "throttled_flags": throttled_flags,
        "recent_logs": recent_logs[-15:] if recent_logs else [],
        "dismissed": False,
    }

    try:
        report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("[CrashDiagnostics] Absturz-Diagnosebericht gespeichert: %s", title)
    except OSError as exc:
        logger.warning("[CrashDiagnostics] Konnte Absturzbericht nicht speichern: %s", exc)

    # Aktuellen Heartbeat für diesen Boot setzen
    record_heartbeat(base_dir)
    return report


def get_last_report(base_dir: Path | str) -> dict[str, Any] | None:
    """Gibt den letzten gespeicherten Absturzbericht zurück (oder None)."""
    data_dir = _data_dir(base_dir)
    report_file = data_dir / CRASH_REPORT_FILE  # SEC-PATH-OK: feste Namenskonstante
    if not report_file.exists():
        return None
    try:
        return json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def dismiss_report(base_dir: Path | str) -> dict[str, bool]:
    """Markiert den aktuellen Absturzbericht als vom Benutzer zur Kenntnis genommen."""
    data_dir = _data_dir(base_dir)
    report_file = data_dir / CRASH_REPORT_FILE  # SEC-PATH-OK: feste Namenskonstante
    if not report_file.exists():
        return {"success": True}
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
        report["dismissed"] = True
        report["dismissed_at"] = datetime.now(timezone.utc).isoformat()
        report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"success": True}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Fehler beim Ausblenden des Absturzberichts: %s", exc)
        return {"success": False}


async def check_crash_and_notify(base_dir: Path | str, session_factory: Any) -> None:
    """Wird im Startup-Flow aufgerufen. Analysiert Reboots und sendet ggf. System-Benachrichtigungen."""
    import asyncio

    report = await asyncio.to_thread(check_and_generate_crash_report, base_dir)
    if not report or report.get("dismissed"):
        return

    # Meldung vorbereiten
    title = f"⚠️ Pi nach Absturz neu gestartet: {report['title']}"
    message = f"{report['explanation']}\n\nEmpfohlene Maßnahme: {report['recommendations'][0]}"

    logger.warning("[CrashDiagnostics] %s — %s", title, message)

    try:
        from backend.app.services.notification_service import notification_service

        async with session_factory() as db:
            await notification_service.on_app_message(
                db,
                sender="PrintLab System",
                title=title,
                message=message,
            )
    except Exception as exc:  # noqa: BLE001 - Benachrichtigung darf Start nie gefährden
        logger.debug("[CrashDiagnostics] App-Benachrichtigung für Absturz übersprungen: %s", exc)
