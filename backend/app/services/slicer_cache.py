"""Slicer-Cache & temporaere Dateien: Bereinigung und Speicher-Hygiene.

Verwaltet und bereinigt temporaere Slicing-Ordner (`bambu_slice_*`), die bei
Slicing-Vorgaengen in `tempfile.gettempdir()` anfallen, und verhindert, dass
der Raspberry Pi oder Server bei haeufigem Slicen volllaeuft.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SLICE_TEMP_PREFIX = "bambu_slice_"
DEFAULT_MAX_AGE_SECONDS = 7200.0  # 2 Stunden


def _dir_size(path: Path) -> int:
    """Berechnet die Gesamtgroesse eines Verzeichnisses in Bytes."""
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _dir_size(Path(entry.path))
            except (OSError, PermissionError):
                pass
    except (OSError, PermissionError):
        pass
    return total


def get_slicer_cache_stats() -> dict[str, Any]:
    """Liefert Statistiken ueber temporaere Slicer-Ordner und Engine-Speicherbelegung."""
    temp_dir = Path(tempfile.gettempdir())
    folders_count = 0
    total_bytes = 0

    try:
        for entry in os.scandir(temp_dir):
            if entry.is_dir() and entry.name.startswith(SLICE_TEMP_PREFIX):
                folders_count += 1
                total_bytes += _dir_size(Path(entry.path))
    except (OSError, PermissionError) as exc:
        logger.debug("[Slicer-Cache] Fehler beim Scannen des Temp-Verzeichnisses: %s", exc)

    # Engine-Verzeichnis pruefen
    engine_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "slicer"
    engine_bytes = _dir_size(engine_dir) if engine_dir.is_dir() else 0

    # Freier Speicherplatz
    free_bytes = 0
    try:
        usage = shutil.disk_usage(temp_dir)
        free_bytes = usage.free
    except OSError:
        pass

    return {
        "temp_folders_count": folders_count,
        "temp_total_bytes": total_bytes,
        "temp_total_mb": round(total_bytes / (1024 * 1024), 2),
        "engine_dir_bytes": engine_bytes,
        "engine_dir_mb": round(engine_bytes / (1024 * 1024), 2),
        "free_disk_bytes": free_bytes,
        "free_disk_mb": round(free_bytes / (1024 * 1024), 2),
    }


def clean_slicer_cache(max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS, force_all: bool = False) -> dict[str, Any]:
    """Entfernt verwaiste temporaere Slicing-Ordner, die aelter als `max_age_seconds` sind."""
    temp_dir = Path(tempfile.gettempdir())
    now = time.time()
    deleted_count = 0
    freed_bytes = 0
    remaining_count = 0
    errors: list[str] = []

    try:
        entries = list(os.scandir(temp_dir))
    except (OSError, PermissionError) as exc:
        return {
            "deleted_folders": 0,
            "freed_bytes": 0,
            "freed_mb": 0.0,
            "remaining_folders": 0,
            "errors": [str(exc)],
        }

    for entry in entries:
        if not entry.is_dir() or not entry.name.startswith(SLICE_TEMP_PREFIX):
            continue

        folder_path = Path(entry.path)
        try:
            mtime = entry.stat().st_mtime
            age = now - mtime
            if force_all or age >= max_age_seconds:
                size = _dir_size(folder_path)
                shutil.rmtree(folder_path, ignore_errors=True)
                if not folder_path.exists():
                    deleted_count += 1
                    freed_bytes += size
                else:
                    remaining_count += 1
            else:
                remaining_count += 1
        except Exception as exc:
            errors.append(f"{entry.name}: {exc}")
            remaining_count += 1

    # Uebermaessige Slicer-Logs in data/slicer stutzen
    engine_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "slicer"
    if engine_dir.is_dir():
        for log_file in engine_dir.glob("*.log"):
            try:
                if log_file.is_file() and log_file.stat().st_size > 5 * 1024 * 1024:
                    freed_bytes += log_file.stat().st_size
                    log_file.write_text("", encoding="utf-8")
            except OSError:
                pass

    if deleted_count > 0:
        logger.info(
            "[Slicer-Cache] %d verwaiste Ordner bereinigt (%.2f MB freigegeben, %d verbleibend)",
            deleted_count,
            freed_bytes / (1024 * 1024),
            remaining_count,
        )

    return {
        "deleted_folders": deleted_count,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        "remaining_folders": remaining_count,
        "errors": errors,
    }


async def run_slicer_cache_watchdog(interval_seconds: float = 3600.0) -> None:
    """Hintergrund-Task: Bereinigt periodisch alle X Sekunden alte Slicer-Dateien."""
    logger.debug("[Slicer-Cache] Watchdog gestartet (Intervall: %s s)", interval_seconds)
    # Einmalige Bereinigung beim Start nach 15 Sekunden Wartezeit
    await asyncio.sleep(15.0)
    try:
        clean_slicer_cache()
    except Exception as exc:
        logger.debug("[Slicer-Cache] Fehler beim Initial-Sweep: %s", exc)

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            clean_slicer_cache()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[Slicer-Cache] Fehler im Watchdog-Durchlauf: %s", exc)
