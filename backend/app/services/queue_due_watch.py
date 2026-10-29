"""Meldung, wenn ein Liefertermin in der Warteschlange nicht mehr zu halten ist.

Alle fünf Minuten wird die Prognose (``queue_forecast``) für die wartenden Aufträge mit Liefertermin berechnet. Gerät ein
Auftrag neu in Gefahr (Prognose liegt nach dem Termin, oder der Termin ist schon verstrichen), geht einmal die Meldung
``queue_due_risk`` an die Kanäle mit eingeschaltetem „Termin in Gefahr". Danach ist der Auftrag markiert
(``due_risk_notified``) und löst nichts mehr aus, bis er zwischendurch wieder im Plan war.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.models.print_queue import PrintQueueItem, PrintQueueVariant
from backend.app.models.printer import Printer
from backend.app.models.settings import Settings
from backend.app.services.queue_forecast import PrinterLive, forecast_ends

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300
EVENT_FIELD = "on_queue_due_risk"
EVENT_TYPE = "queue_due_risk"

# Zustand der Überwachung für die Systemprüfung (services/selftest.py)
STATE: dict[str, object] = {"started": None, "last_run": None, "last_error": None}


def _job_name(item: PrintQueueItem) -> str:
    archive = getattr(item, "archive", None)
    library = getattr(item, "library_file", None)
    return (
        (archive.print_name or archive.filename if archive else None)
        or (library.filename if library else None)
        or f"#{item.id}"
    )


def _fmt(moment: datetime | None) -> str:
    if moment is None:
        return "-"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def live_states(printers, status_of) -> dict[int, PrinterLive]:
    """Zustand der Drucker aus dem Druckerverwalter (``status_of(printer_id)`` liefert den Zustand oder None)."""
    states: dict[int, PrinterLive] = {}
    for printer in printers:
        state = status_of(printer.id)
        if state is not None:
            states[printer.id] = PrinterLive(
                remaining_minutes=getattr(state, "remaining_time", None),
                state=getattr(state, "state", None),
                progress=getattr(state, "progress", None),
            )
    return states


async def _sjf_enabled(db) -> bool:
    row = await db.scalar(select(Settings.value).where(Settings.key == "queue_shortest_first"))
    return str(row or "").lower() == "true"


async def check_due_dates(db, status_of, notifier, now: datetime | None = None) -> list[int]:
    """Prüfen und melden; gibt die Nummern der Aufträge zurück, die neu in Gefahr sind.

    ``notifier(db, item, expected_end, overdue)`` verschickt die Meldung und liefert True, wenn sie an mindestens einen
    Kanal ging; nur dann gilt der Auftrag als gemeldet.
    """
    now = now or datetime.now(timezone.utc)
    result = await db.execute(
        select(PrintQueueItem)
        .where(PrintQueueItem.status.in_(("pending", "printing")))
        .options(
            selectinload(PrintQueueItem.archive),
            selectinload(PrintQueueItem.library_file),
            selectinload(PrintQueueItem.variants).selectinload(PrintQueueVariant.library_file),
        )
    )
    items = list(result.scalars().all())
    if not any(item.due_at is not None for item in items if item.status == "pending"):
        # nichts zu prüfen; aber Markierungen aufräumen, falls ein Termin entfernt wurde
        changed = [item for item in items if item.due_risk_notified and item.due_at is None]
        for item in changed:
            item.due_risk_notified = False
        if changed:
            await db.commit()
        return []

    printers = list((await db.execute(select(Printer).where(Printer.is_active.is_(True)))).scalars().all())
    ends = forecast_ends(items, printers, live_states(printers, status_of), await _sjf_enabled(db), now)

    newly: list[int] = []
    for item in items:
        if item.status != "pending":
            continue
        if item.due_at is None:
            item.due_risk_notified = False
            continue
        due = item.due_at if item.due_at.tzinfo else item.due_at.replace(tzinfo=timezone.utc)
        end = ends.get(item.id)
        overdue = due < now
        at_risk = overdue or (end is not None and end > due)
        if not at_risk:
            item.due_risk_notified = False
        elif not item.due_risk_notified:
            try:
                sent = await notifier(db, item, end, overdue)
            except Exception:  # eine kaputte Meldung darf die Prüfung nicht abbrechen
                logger.exception("Due-risk notification for queue item %s failed", item.id)
                sent = False
            if sent:
                item.due_risk_notified = True
                newly.append(item.id)
    await db.commit()
    return newly


async def notify_due_risk(db, item: PrintQueueItem, expected_end: datetime | None, overdue: bool) -> bool:
    """Meldung ``queue_due_risk`` über die Kanäle verschicken; False, wenn kein Kanal sie haben will."""
    from backend.app.services.notification_service import notification_service

    providers = await notification_service._get_providers_for_event(db, EVENT_FIELD, None)
    if not providers:
        return False
    variables = {
        "job_name": _job_name(item),
        "due": _fmt(item.due_at),
        "expected": _fmt(expected_end),
        "reason": "The due date has passed." if overdue else "Expected to finish after the due date.",
    }
    title, message = await notification_service._build_message_from_template(db, EVENT_TYPE, variables)
    await notification_service._send_to_providers(providers, title, message, db, EVENT_TYPE, variables=variables)
    return True


async def send_test(db) -> tuple[int, list[str]]:
    """Probemeldung „Termin in Gefahr" an jeden Kanal, der sie will; (Anzahl erfolgreich, Kanäle mit Fehler)."""
    from backend.app.services.notification_service import notification_service as service

    providers = await service._get_providers_for_event(db, EVENT_FIELD, None)
    if not providers:
        return 0, []
    variables = {
        "job_name": "Testauftrag (Systemprüfung)",
        "due": "-",
        "expected": "-",
        "reason": "This is a test message from the system check.",
    }
    title, message = await service._build_message_from_template(db, EVENT_TYPE, variables)
    sent, failed = 0, []
    for provider in providers:
        success, error = await service._send_to_provider(
            provider, f"Test: {title}", message, db, event_type=EVENT_TYPE, variables=variables, photo_cache={}
        )
        await service._update_provider_status(db, provider.id, success, None if success else error)
        if success:
            sent += 1
        else:
            failed.append(f"{provider.name} ({error})")
    return sent, failed


async def run(session_factory, interval: float = CHECK_INTERVAL_SECONDS) -> None:
    """Dauerschleife für den Hintergrund; Fehler werden protokolliert und brechen sie nicht ab."""
    from backend.app.services.printer_manager import printer_manager

    STATE["started"] = datetime.now(timezone.utc)
    await asyncio.sleep(60)  # nach dem Start erst die Drucker verbinden lassen
    while True:
        try:
            async with session_factory() as db:
                await check_due_dates(db, printer_manager.get_status, notify_due_risk)
            STATE["last_run"], STATE["last_error"] = datetime.now(timezone.utc), None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Queue due-date check failed")
            STATE["last_error"] = str(exc)[:200]
        await asyncio.sleep(interval)
