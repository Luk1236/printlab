"""Werkseinstellungen: PrintLab auf den Auslieferungszustand zurücksetzen, mit Sicherung vorher.

Der Ablauf ist bewusst zweistufig, damit nichts halb passiert:

1. :func:`perform_reset` legt zuerst eine ZIP-Sicherung an (Datenbank und Konfigurationsdateien) und schreibt eine
   Auftragsdatei. Danach werden alle Daten in ``data/reset-<Zeitstempel>/`` **verschoben** — nichts wird gelöscht.
   Anschließend wird das Schema neu angelegt.
2. :func:`apply_pending` läuft beim Start **vor** ``init_db`` und führt einen unterbrochenen Auftrag zu Ende.

Damit ist der Reset umkehrbar: Die Sicherung enthält Datenbank und Einstellungen, die verschobenen Ordner enthalten
Bilder, Archive und Bibliothek. Wer sicher ist, löscht ``reset-<Zeitstempel>`` und die ZIP-Datei von Hand.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PENDING_FILE = "factory-reset.json"
RESET_PREFIX = "reset-"
RESTORE_PREFIX = "before-restore-"
RESET_NAME_RX = re.compile(r"reset-\d{8}-\d{6}")
# Diese Ordner bleiben stehen: Sicherungen sind die Rettung, Protokolle helfen beim Nachsehen.
KEEP = ("backups", "logs", PENDING_FILE)
CONFIG_DIRS = ("certs",)
SUPPORTED_PREFIX = "sqlite"

_lock = asyncio.Lock()


class FactoryResetError(RuntimeError):
    """Der Reset ist nicht möglich; die Meldung ist für die Oberfläche bestimmt."""


def _keep(name: str) -> bool:
    return name in KEEP or name.startswith(RESET_PREFIX)


def sqlite_db_path(database_url: str) -> Path:
    """Dateipfad der lokalen Datenbank aus ``sqlite+aiosqlite:///…``."""
    if not database_url.startswith(SUPPORTED_PREFIX):
        raise FactoryResetError(
            "Die Werkseinstellungen setzen eine lokale Datenbank voraus. Bei einer externen Datenbank "
            "(DATABASE_URL) bitte die Datenbank von Hand leeren."
        )
    _, _, raw = database_url.partition(":///")
    if not raw or raw == ":memory:":
        raise FactoryResetError("Die Datenbank liegt nur im Arbeitsspeicher; es gibt nichts zurückzusetzen.")
    return Path(raw)


def preview(data_dir: Path, database_url: str) -> dict[str, Any]:
    """Was würde verschwinden und was bleibt? Ändert nichts."""
    supported = database_url.startswith(SUPPORTED_PREFIX)
    entries = []
    if data_dir.is_dir():
        entries = sorted(
            entry.name for entry in data_dir.iterdir() if not _keep(entry.name) and entry.name != PENDING_FILE
        )
    return {
        "supported": supported,
        "data_dir": str(data_dir),
        "items": entries,
        "kept": ["backups", "logs"],
        "pending": (data_dir / PENDING_FILE).is_file(),
    }


def _write_marker(data_dir: Path, target: Path, backup: Path) -> None:
    marker = {
        "requested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": target.name,
        "backup": backup.name,
    }
    (data_dir / PENDING_FILE).write_text(json.dumps(marker, indent=2), encoding="utf-8")


def create_backup(data_dir: Path, db_path: Path) -> Path:
    """Datenbank und Einstellungen in eine ZIP-Datei; Bilder und Archive bleiben in ``reset-…``."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups = data_dir / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"factory-reset-{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{db_path}{suffix}")
            if path.is_file():
                archive.write(path, f"db/{path.name}")
        for entry in sorted(data_dir.iterdir()):
            if entry.is_dir() or _keep(entry.name) or entry.name == PENDING_FILE:
                continue
            archive.write(entry, f"config/{entry.name}")
        for folder in CONFIG_DIRS:
            root = data_dir / folder
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, f"{folder}/{path.relative_to(root).as_posix()}")
    logger.info("Werkseinstellungen: Sicherung geschrieben (%s)", target.name)
    return target


def apply_pending(data_dir: Path) -> Path | None:
    """Verschiebt alle Daten in den Reset-Ordner. Gibt den Ordner zurück, sonst ``None``."""
    marker_path = data_dir / PENDING_FILE
    if not marker_path.is_file():
        return None
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Werkseinstellungen: Auftragsdatei unlesbar (%s); sie wird entfernt.", exc)
        marker_path.unlink(missing_ok=True)
        return None

    target = data_dir / str(marker.get("target") or f"{RESET_PREFIX}{datetime.now():%Y%m%d-%H%M%S}")
    target.mkdir(parents=True, exist_ok=True)
    for entry in data_dir.iterdir():
        if entry in (marker_path, target) or _keep(entry.name) or entry.name.startswith(RESET_PREFIX):
            continue
        destination = target / entry.name
        if destination.exists():
            # Zweiter Anlauf nach einem Abbruch: die frühere Datei gewinnt, die neue bekommt einen Zusatz.
            destination = target / f"{entry.name}.neu"
        shutil.move(str(entry), str(destination))
    (target / "README.txt").write_text(
        "PrintLab wurde auf den Auslieferungszustand zurückgesetzt.\n\n"
        f"Zeitpunkt: {marker.get('requested_at', 'unbekannt')}\n"
        f"Sicherung: backups/{marker.get('backup', '-')}\n\n"
        "Hier liegen die verschobenen Daten (Archive, Bibliothek, Bilder, Einstellungen, Datenbank).\n"
        "Zum Wiederherstellen PrintLab stoppen, die Dateien an ihren Platz zurücklegen und die Sicherung\n"
        "aus dem Ordner backups entpacken.\n"
        "Wenn alles läuft, darf dieser Ordner gelöscht werden.\n",
        encoding="utf-8",
    )
    marker_path.unlink(missing_ok=True)
    logger.info("Werkseinstellungen: Daten nach %s verschoben", target.name)
    return target


def list_archives(data_dir: Path) -> list[dict[str, Any]]:
    """Vorhandene Reset-Ordner, neueste zuerst."""
    if not data_dir.is_dir():
        return []
    archives = []
    for entry in sorted(data_dir.iterdir(), reverse=True):
        if not entry.is_dir() or not RESET_NAME_RX.fullmatch(entry.name):
            continue
        stamp = entry.name.removeprefix(RESET_PREFIX)
        backup = data_dir / "backups" / f"factory-reset-{stamp}.zip"
        archives.append(
            {
                "name": entry.name,
                "modified": datetime.fromtimestamp(entry.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "has_database": (entry / "printlab.db").is_file(),
                "backup": backup.name if backup.is_file() else None,
            }
        )
    return archives


def _archive_dir(data_dir: Path, name: str) -> Path:
    if not RESET_NAME_RX.fullmatch(name):
        raise FactoryResetError("Unbekannter Reset-Ordner.")
    target = data_dir / name
    if not target.is_dir():
        raise FactoryResetError("Diesen Reset-Ordner gibt es nicht mehr.")
    return target


def restore_files(data_dir: Path, name: str) -> dict[str, Any]:
    """Dateien eines Reset-Ordners zurücklegen; der aktuelle Stand wandert nach ``before-restore-…``."""
    target = _archive_dir(data_dir, name)
    safety = data_dir / f"{RESTORE_PREFIX}{datetime.now():%Y%m%d-%H%M%S}"
    safety.mkdir(parents=True, exist_ok=True)

    for entry in list(data_dir.iterdir()):
        if entry in (safety, target) or _keep(entry.name) or entry.name.startswith((RESET_PREFIX, RESTORE_PREFIX)):
            continue
        shutil.move(str(entry), str(safety / entry.name))

    restored = 0
    for entry in target.iterdir():
        if entry.name == "README.txt":
            continue
        destination = data_dir / entry.name
        if destination.exists():
            destination = safety / f"{entry.name}.vorhanden"
        shutil.move(str(entry), str(destination))
        restored += 1
    # Der Hinweiszettel des Resets gehört nicht zurück; ohne ihn ist der Ordner leer und kann weg.
    (target / "README.txt").unlink(missing_ok=True)
    try:
        target.rmdir()
    except OSError:
        pass
    logger.info("Wiederhergestellt: %s Dateien aus %s", restored, name)
    return {"safety": safety.name, "items": restored}


async def restore(data_dir: Path, name: str) -> dict[str, Any]:
    """Reset rückgängig machen. Der aktuelle Stand bleibt in ``before-restore-…`` erhalten."""
    _archive_dir(data_dir, name)
    async with _lock:
        from backend.app.services.print_scheduler import scheduler as print_scheduler
        from backend.app.services.printer_manager import printer_manager

        print_scheduler.stop()
        printer_manager.disconnect_all()

        from backend.app.core import database as database_module

        await database_module.engine.dispose()
        result = await asyncio.to_thread(restore_files, data_dir, name)
        await database_module.init_db()
        return {
            "ok": True,
            "restored": name,
            **result,
            "message": "Der Stand wurde zurückgeholt. Die Seite neu laden.",
        }


async def perform_reset(data_dir: Path, database_url: str) -> dict[str, Any]:
    """Sichern, verschieben, Schema neu anlegen. Wirft :class:`FactoryResetError`, wenn es nicht geht."""
    db_path = sqlite_db_path(database_url)
    async with _lock:
        backup = await asyncio.to_thread(create_backup, data_dir, db_path)
        stamp = backup.stem.removeprefix("factory-reset-")
        target = data_dir / f"{RESET_PREFIX}{stamp}"
        _write_marker(data_dir, target, backup)

        # Schreibzugriffe anhalten, Verbindungen schließen, dann die Datei verschieben (Windows sperrt sie sonst).
        from backend.app.services.print_scheduler import scheduler as print_scheduler
        from backend.app.services.printer_manager import printer_manager

        print_scheduler.stop()
        printer_manager.disconnect_all()

        from backend.app.core import database as database_module

        await database_module.engine.dispose()
        moved_to = await asyncio.to_thread(apply_pending, data_dir)
        await database_module.init_db()

        return {
            "ok": True,
            "backup": f"backups/{backup.name}",
            "moved_to": moved_to.name if moved_to else None,
            "message": "PrintLab wurde zurückgesetzt. Die Seite neu laden — dann beginnt die Einrichtung von vorn.",
        }
