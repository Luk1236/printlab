"""SD-Card Wear Guard & RAM-Disk Buffering Service (Phase 17).

Schützt die Raspberry Pi MicroSD-Karte vor übermäßigem Verschleiß durch
kontinuierliche Kamera-Streams, Schicht-Snapshots und Upload-Caches.
Nutzt /dev/shm (Linux tmpfs) für flüchtige Mediendaten und optimiert SQLite I/O.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Prüfe, ob /dev/shm (Linux Shared Memory RAM-Disk) verfügbar und beschreibbar ist
SHM_PATH = Path("/dev/shm/printlab")
FALLBACK_TEMP_PATH = Path(tempfile.gettempdir()) / "printlab_ram_buffer"


class SdWearGuard:
    """Verwaltet RAM-Pufferverzeichnisse und zählt eingesparte SD-Schreiboperationen."""

    def __init__(self) -> None:
        self.use_shm = os.path.exists("/dev/shm") and os.access("/dev/shm", os.W_OK)
        self.buffer_root = SHM_PATH if self.use_shm else FALLBACK_TEMP_PATH
        self.snapshots_dir = self.buffer_root / "snapshots"
        self.timelapse_temp_dir = self.buffer_root / "timelapse_temp"
        self.slices_cache_dir = self.buffer_root / "slices"

        self._writes_saved_count = 0
        self._bytes_saved_count = 0
        self._init_directories()

    def _init_directories(self) -> None:
        try:
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
            self.timelapse_temp_dir.mkdir(parents=True, exist_ok=True)
            self.slices_cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("SD Wear Guard aktiv: Pufferverzeichnis=%s (RAM-Disk=%s)", self.buffer_root, self.use_shm)
        except OSError as exc:
            logger.warning("Konnte RAM-Pufferverzeichnis nicht erstellen: %s", exc)

    def buffer_snapshot(self, printer_id: int, image_bytes: bytes) -> Path:
        """Puffert ein Kamera-Einzelbild im Arbeitsspeicher statt auf der SD-Karte."""
        target = self.snapshots_dir / f"cam_{printer_id}.jpg"
        target.write_bytes(image_bytes)
        self._writes_saved_count += 1
        self._bytes_saved_count += len(image_bytes)
        return target

    def get_buffered_snapshot(self, printer_id: int) -> bytes | None:
        """Liest das gepufferte Kamera-Einzelbild aus der RAM-Disk."""
        target = self.snapshots_dir / f"cam_{printer_id}.jpg"
        if target.is_file():
            try:
                return target.read_bytes()
            except OSError:
                return None
        return None

    def get_stats(self) -> dict[str, Any]:
        """Liefert Statistiken über die RAM-Disk-Nutzung und eingesparte SD-Schreibzugriffe."""
        total_buffered_bytes = 0
        file_count = 0
        if self.buffer_root.is_dir():
            for p in self.buffer_root.rglob("*"):
                if p.is_file():
                    file_count += 1
                    try:
                        total_buffered_bytes += p.stat().st_size
                    except OSError:
                        pass

        # Freier Speicherplatz auf der Puffer-Partition
        disk_stats = shutil.disk_usage(self.buffer_root if self.buffer_root.exists() else tempfile.gettempdir())

        return {
            "ram_disk_active": self.use_shm,
            "buffer_path": str(self.buffer_root),
            "buffered_files_count": file_count,
            "buffered_size_bytes": total_buffered_bytes,
            "buffered_size_mb": round(total_buffered_bytes / (1024 * 1024), 2),
            "sd_writes_saved": self._writes_saved_count,
            "sd_data_saved_mb": round(self._bytes_saved_count / (1024 * 1024), 2),
            "ram_disk_free_mb": round(disk_stats.free / (1024 * 1024), 1),
            "ram_disk_total_mb": round(disk_stats.total / (1024 * 1024), 1),
        }

    def cleanup_old_buffers(self) -> int:
        """Löscht temporäre Pufferdateien zur Speicherplatz-Rückgewinnung."""
        deleted = 0
        if self.buffer_root.is_dir():
            for p in self.buffer_root.rglob("*"):
                if p.is_file():
                    try:
                        p.unlink()
                        deleted += 1
                    except OSError:
                        pass
        return deleted


# Globales Singleton
sd_wear_guard = SdWearGuard()
