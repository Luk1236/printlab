"""Zustand des Rechners, auf dem PrintLab läuft (gedacht für den Raspberry Pi): Speicherart, Temperatur, Spannung,
Speicherplatz, Arbeitsspeicher, letzte Sicherung.

Nur Standardbibliothek und ohne Root-Rechte. Alles, was es auf einem anderen System nicht gibt (Windows, andere
Linux-Geräte), liefert ``None`` statt eines Fehlers. Wird von der Wartungsseite, der Schnittstelle und dem
Abnahme-Check (``werkzeuge/abnahme.py``) benutzt.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

BACKUP_FOLDERS = ("update-backups",)
LOW_DISK_BYTES = 1_000_000_000
TEMP_WARN_C = 75.0
TEMP_CRIT_C = 82.0
BACKUP_MAX_AGE_DAYS = 14

# Bits von ``vcgencmd get_throttled``
_THROTTLE_BITS = {
    0x1: "Unterspannung (jetzt)",
    0x2: "Frequenz begrenzt (jetzt)",
    0x4: "gedrosselt (jetzt)",
    0x8: "Temperaturgrenze erreicht (jetzt)",
    0x10000: "Unterspannung seit dem Start",
    0x20000: "Frequenz begrenzt seit dem Start",
    0x40000: "gedrosselt seit dem Start",
    0x80000: "Temperaturgrenze seit dem Start erreicht",
}


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def storage_kind(path: Path | str, mounts_text: str | None = None) -> dict[str, str] | None:
    """Gerät und Art des Datenträgers, auf dem ``path`` liegt: ``sd``, ``nvme``, ``usb`` oder ``other``."""
    text = mounts_text if mounts_text is not None else _read("/proc/mounts")
    if not text:
        return None
    p = Path(path)
    target = str(p.resolve() if p.exists() else p).replace("\\", "/")  # Links nur auflösen, wenn es den Pfad gibt
    best: tuple[int, str] | None = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith("/dev/"):
            continue
        mount = parts[1].replace("\\040", " ")
        if target == mount or target.startswith(mount.rstrip("/") + "/") or mount == "/":
            if best is None or len(mount) > best[0]:
                best = (len(mount), parts[0])
    if best is None:
        return None
    device = best[1]
    name = device.rsplit("/", 1)[-1]
    if name.startswith("mmcblk"):
        kind = "sd"
    elif name.startswith("nvme"):
        kind = "nvme"
    elif name.startswith("sd"):
        kind = "usb"
    else:
        kind = "other"
    return {"device": device, "kind": kind}


def cpu_temp_c(path: str = "/sys/class/thermal/thermal_zone0/temp") -> float | None:
    raw = _read(path)
    try:
        return round(int((raw or "").strip()) / 1000, 1)
    except ValueError:
        return None


def decode_throttled(value: int) -> list[str]:
    return [text for bit, text in _THROTTLE_BITS.items() if value & bit]


def throttled() -> dict[str, Any] | None:
    """Spannungs- und Drosselungsmeldungen des Pi (``vcgencmd``), sonst None."""
    if shutil.which("vcgencmd") is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            ["vcgencmd", "get_throttled"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
        value = int(out.strip().split("=")[-1], 16)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return {"value": value, "flags": decode_throttled(value)}


def memory(meminfo_text: str | None = None) -> dict[str, int] | None:
    text = meminfo_text if meminfo_text is not None else _read("/proc/meminfo")
    if not text:
        return None
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
            try:
                values[key] = int(rest.split()[0]) * 1024
            except (ValueError, IndexError):
                pass
    if "MemTotal" not in values or "MemAvailable" not in values:
        return None
    return {
        "total": values["MemTotal"],
        "available": values["MemAvailable"],
        "swap_total": values.get("SwapTotal", 0),
        "swap_free": values.get("SwapFree", 0),
    }


def uptime_seconds() -> float | None:
    raw = _read("/proc/uptime")
    try:
        return float((raw or "").split()[0])
    except (ValueError, IndexError):
        return None


def disk(path: Path | str) -> dict[str, int] | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {"total": usage.total, "free": usage.free}


def latest_backup(data_dir: Path | str, extra_dirs: list[Path] | None = None) -> dict[str, Any] | None:
    """Neueste Sicherung aus dem Datenordner (``update-backups``) und weiteren Ordnern; Alter in Tagen."""
    roots = [Path(data_dir).joinpath(name) for name in BACKUP_FOLDERS]  # SEC-PATH-OK: feste Namenskonstanten
    roots += [Path(p) for p in (extra_dirs or [])]
    found: list[tuple[float, Path]] = []
    for root in roots:
        try:
            found += [(p.stat().st_mtime, p) for p in root.iterdir() if p.is_dir()]
        except OSError:
            continue
    if not found:
        return None
    mtime, path = max(found)
    return {"path": str(path), "age_days": round((time.time() - mtime) / 86400, 1)}


def warnings_for(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Hinweise aus den Messwerten: ``level`` ist ``warn`` oder ``crit``, ``code`` und ``params`` für die Oberfläche."""
    out: list[dict[str, Any]] = []

    def add(level: str, code: str, text: str, **params: Any) -> None:
        out.append({"level": level, "code": code, "text": text, "params": params})

    temp = info.get("cpu_temp_c")
    if temp is not None:
        if temp >= TEMP_CRIT_C:
            add("crit", "temp_critical", f"Prozessor sehr heiß ({temp:g} °C): Kühlung prüfen.", temp=temp)
        elif temp >= TEMP_WARN_C:
            add("warn", "temp_hot", f"Prozessor heiß ({temp:g} °C): Lüfter oder Gehäuse prüfen.", temp=temp)
    flags = (info.get("throttled") or {}).get("flags") or []
    if any("Unterspannung" in f for f in flags):
        add("crit", "undervoltage", "Unterspannung erkannt: Netzteil prüfen (der Pi 5 braucht 5 V / 5 A).")
    elif flags:
        add("warn", "throttled", "Der Prozessor wurde gedrosselt: " + ", ".join(flags) + ".")
    free = (info.get("disk") or {}).get("free")
    if free is not None and free < LOW_DISK_BYTES:
        add("crit", "disk_low", f"Wenig Speicherplatz: noch {free / 1e9:.1f} GB frei.", free_gb=round(free / 1e9, 1))
    store = info.get("storage") or {}
    if store.get("kind") == "sd":
        add(
            "warn",
            "sd_card",
            "Die Daten liegen auf einer SD-Karte, die mit der Zeit verschleißt: SSD (USB oder NVMe) empfohlen.",
        )
    mem = info.get("memory")
    if mem and mem["available"] < 200_000_000 and mem.get("swap_total", 0) == 0:
        add("warn", "memory_low", "Wenig freier Arbeitsspeicher und kein Swap eingerichtet.")
    backup = info.get("backup")
    if backup is None:
        add("warn", "backup_none", "Es gibt noch keine Sicherung.")
    elif backup["age_days"] > BACKUP_MAX_AGE_DAYS:
        add("warn", "backup_old", f"Die letzte Sicherung ist {backup['age_days']:g} Tage alt.", days=backup["age_days"])
    external = info.get("external_backup")
    if external is not None and not external.get("ok"):
        add(
            "crit",
            "external_failed",
            "Die letzte Sicherung nach außen ist fehlgeschlagen: " + str(external.get("detail", "")),
        )
    return out


def backup_dirs() -> list[Path]:
    """Weitere Orte, an denen Sicherungen liegen: Neuaufspielen (~/printlab-backups) und das externe Ziel."""
    dirs = [Path.home() / "printlab-backups"]
    target = os.environ.get("PRINTLAB_BACKUP_TARGET", "").strip()
    if target:
        dirs.append(Path(target))
    return dirs


def external_backup_status(data_dir: Path | str) -> dict[str, Any] | None:
    """Ergebnis des letzten Laufs von ``werkzeuge/sicherung_extern.py`` (oder None, wenn nie gelaufen)."""
    raw = _read(str(Path(data_dir).joinpath("last_external_backup.json")))  # SEC-PATH-OK: feste Namenskonstante
    try:
        data = json.loads(raw or "")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def snapshot(data_dir: Path | str, extra_backup_dirs: list[Path] | None = None) -> dict[str, Any]:
    if extra_backup_dirs is None:
        extra_backup_dirs = backup_dirs()
    info: dict[str, Any] = {
        "cpu_temp_c": cpu_temp_c(),
        "throttled": throttled(),
        "disk": disk(data_dir),
        "storage": storage_kind(data_dir),
        "memory": memory(),
        "uptime_seconds": uptime_seconds(),
        "backup": latest_backup(data_dir, extra_backup_dirs),
        "external_backup": external_backup_status(data_dir),
    }
    info["warnings"] = warnings_for(info)
    return info
