"""Automatische Umverteilung eines abgebrochenen Auftrags.

Scheitert ein Druck in der Warteschlange (nicht: vom Benutzer abgebrochen),
wird der Auftrag **einmal** als neuer Eintrag wieder eingereiht — ohne festen
Drucker, aber mit dem Modell des gescheiterten Geräts als Ziel. Der Scheduler
sucht dann ein freies Gerät desselben Modells; so kann derselbe Fehler nicht
auf demselben Drucker endlos wiederholt werden.

Regeln:

* Nur ``failed`` wird umverteilt, ``cancelled``/``aborted`` (Benutzer) nie.
* Höchstens ``max_retries`` Wiederholungen je Auftragskette. Die Kette wird
  über eine Merkliste (``data/auto_requeue_log.json``) verfolgt, nicht über
  eine neue Datenbankspalte — der neue Eintrag erbt die Kette seines Vorgängers.
* Original und Wiederholung bleiben getrennt: der Fehlschlag bleibt mit seiner
  Meldung sichtbar, die Wiederholung ist ein eigener Eintrag.
* Standardmäßig **aus**; jede Umverteilung wird gemeldet (Ereignis
  ``queue_job_added``) und in der Merkliste festgehalten.

Nicht abgedeckt: ein Auftrag, der schon beim Senden an den Drucker scheitert
(Upload), läuft über denselben Pfad und wird ebenfalls umverteilt — auch das
nur einmal.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

CONFIG_PATH = settings.base_dir / "auto_requeue.json"
LOG_PATH = settings.base_dir / "auto_requeue_log.json"
MAX_LOG = 500

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "max_retries": 1,
    "require_sibling": True,
}
MAX_RETRIES_LIMIT = 5
_lock = threading.Lock()


def _as_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if minimum <= number <= maximum else fallback


def read_config() -> dict[str, Any]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "enabled": bool(data.get("enabled", DEFAULTS["enabled"])),
        "max_retries": _as_int(data.get("max_retries"), 0, MAX_RETRIES_LIMIT, DEFAULTS["max_retries"]),
        "require_sibling": bool(data.get("require_sibling", DEFAULTS["require_sibling"])),
    }


def write_config(update: dict[str, Any]) -> dict[str, Any]:
    merged = {**read_config(), **{k: v for k, v in (update or {}).items() if k in DEFAULTS}}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return read_config()


def _read_log() -> list[dict[str, Any]]:
    try:
        data = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_log(entries: list[dict[str, Any]]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOG_PATH.with_name(LOG_PATH.name + ".tmp")
    tmp.write_text(json.dumps(entries[:MAX_LOG], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LOG_PATH)


def entries(limit: int = 50) -> list[dict[str, Any]]:
    return _read_log()[: max(1, min(int(limit), MAX_LOG))]


def root_of(item_id: int) -> int:
    """Ursprünglicher Auftrag einer Kette (der Eintrag selbst, wenn er nie wiederholt wurde)."""
    for entry in _read_log():
        if entry.get("retry_id") == int(item_id):
            return int(entry.get("root_id") or item_id)
    return int(item_id)


def retries_used(root_id: int) -> int:
    return sum(1 for entry in _read_log() if entry.get("root_id") == int(root_id))


def should_requeue(status: str | None, config: dict[str, Any], used: int) -> bool:
    """Nur ein echter Fehlschlag, nur bei eingeschalteter Regel und nur im Budget."""
    return status == "failed" and bool(config.get("enabled")) and used < int(config.get("max_retries", 0))


def record(root_id: int, retry_id: int, printer_id: int | None, target: str, reason: str) -> dict[str, Any]:
    """Eine Umverteilung festhalten (unter dem Lock, damit zwei Fehlschläge nicht doppelt zählen)."""
    entry = {
        "root_id": int(root_id),
        "retry_id": int(retry_id),
        "printer_id": printer_id,
        "target": target,
        "reason": reason[:200],
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _write_log([entry, *_read_log()])
    return entry


async def _job_name(db, item) -> str:
    """Dateiname für die Meldung — Archiv zuerst, sonst Bibliotheksdatei."""
    from sqlalchemy import select

    from backend.app.models.archive import PrintArchive
    from backend.app.models.library import LibraryFile

    try:
        if item.archive_id:
            archive = await db.scalar(select(PrintArchive).where(PrintArchive.id == item.archive_id))
            if archive is not None:
                return archive.print_name or archive.filename or f"Auftrag {item.id}"
        if item.library_file_id:
            library_file = await db.scalar(select(LibraryFile).where(LibraryFile.id == item.library_file_id))
            if library_file is not None:
                return library_file.filename or f"Auftrag {item.id}"
    except Exception as e:  # noqa: BLE001 - nur der Anzeigename, kein Grund zu scheitern
        logger.debug("Could not resolve job name for queue item %s: %s", item.id, e)
    return f"Auftrag {item.id}"


async def maybe_requeue(db, queue_item_id: int, status: str | None) -> dict[str, Any] | None:
    """Nach dem Abschluss eines Warteschlangen-Eintrags: ggf. einmal umverteilen.

    Gibt den Merklisten-Eintrag zurück, wenn umverteilt wurde, sonst ``None``.
    Fehler werden geloggt, nicht geworfen: der Abschluss des ursprünglichen
    Auftrags darf daran nicht scheitern.
    """
    config = read_config()
    if not config["enabled"] or status != "failed":
        return None

    from backend.app.models.print_queue import PrintQueueItem
    from backend.app.models.printer import Printer

    try:
        item = await db.scalar(select_item(PrintQueueItem, queue_item_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("Auto-requeue: could not load queue item %s: %s", queue_item_id, e)
        return None
    if item is None or item.status != "failed":
        return None

    root = root_of(item.id)
    if not should_requeue(status, config, retries_used(root)):
        return None
    if item.archive_id is None and item.library_file_id is None:
        return None

    printer = await db.scalar(select_item(Printer, item.printer_id)) if item.printer_id else None
    target = (printer.model if printer is not None else None) or item.target_model
    if not target:
        logger.info("Auto-requeue: no model known for queue item %s, leaving it failed", item.id)
        return None

    if config["require_sibling"] and printer is not None:
        # Ohne ein zweites Gerät desselben Modells würde der Scheduler denselben
        # Drucker wieder wählen — dann ist der Fehlschlag keine Umverteilung.
        siblings = await db.scalar(select_sibling_count(Printer, target, item.printer_id))
        if not siblings:
            logger.info("Auto-requeue: item %s failed on the only printer of model %s, not requeueing", item.id, target)
            return None

    from backend.app.models.print_queue import PrintQueueItem as QueueItem

    retry = QueueItem(
        printer_id=None,
        target_model=target,
        target_location=item.target_location,
        required_filament_types=item.required_filament_types,
        archive_id=item.archive_id,
        library_file_id=item.library_file_id,
        plate_id=item.plate_id,
        priority=item.priority,
        scheduled_time=None,
        manual_start=False,
        ams_mapping=None,  # das gescheiterte Gerät hatte eine andere Zuordnung
        filament_overrides=item.filament_overrides,
        print_time_seconds=item.print_time_seconds,
        created_by_id=item.created_by_id,
        cost_center_id=item.cost_center_id,
        project_id=item.project_id,
        batch_id=item.batch_id,
        status="pending",
    )
    db.add(retry)
    try:
        await db.commit()
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        logger.warning("Auto-requeue: could not create retry for item %s: %s", item.id, e)
        return None
    await db.refresh(retry)

    entry = record(root, retry.id, item.printer_id, retry.target_model or "irgendein Drucker", item.error_message or "")
    logger.info("Auto-requeue: item %s failed, requeued as %s (target %s)", item.id, retry.id, retry.target_model)

    # Meldung über denselben Weg wie ein manuell eingereihter Auftrag; ohne
    # konfigurierte Kanäle passiert nichts.
    try:
        from backend.app.services.notification_service import notification_service

        await notification_service.on_queue_job_added(
            job_name=await _job_name(db, retry),
            target=retry.target_model or "irgendein Drucker",
            db=db,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("Auto-requeue notification failed: %s", e)

    try:
        from backend.app.core.websocket import ws_manager

        await ws_manager.broadcast({"type": "queue_item_requeued", "item_id": retry.id, "source_id": item.id})
    except Exception:  # noqa: BLE001
        pass
    return entry


def select_item(model, item_id: int):
    """Kleine Hilfe, damit die Abfrage oben lesbar bleibt und leicht zu ersetzen ist."""
    from sqlalchemy import select

    return select(model).where(model.id == int(item_id))


def select_sibling_count(model, target_model: str, excluded_id: int | None):
    """Anzahl weiterer Drucker desselben Modells (ohne das gescheiterte Gerät)."""
    from sqlalchemy import func, select

    query = select(func.count(model.id)).where(model.model == target_model)
    if excluded_id is not None:
        query = query.where(model.id != int(excluded_id))
    return query
