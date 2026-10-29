"""Zahlungserinnerung: meldet überfällige, offene Rechnungen über die Meldewege.

Einmal am Tag geprüft (Timer des systemd-Dienstes läuft ohnehin weiter): Jede
offene Rechnung mit überschrittenem Zahlungsziel bekommt **einmal** die Meldung
``invoice_reminder`` an die Kanäle mit eingeschalteter „Zahlungserinnerung" und
wird markiert (``reminder_sent_at``). Später bezahlt und wieder geöffnet?
Dann kommt die Erinnerung erneut (die Markierung wird beim Wiederöffnen
zurückgesetzt). Stornierte und bezahlte Rechnungen ruhen für immer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from backend.app.services import invoices

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # viermal am Tag; markiert je Rechnung trotzdem nur einmal
EVENT_FIELD = "on_invoice_reminder"
EVENT_TYPE = "invoice_reminder"

# Zustand der Überwachung für die Systemprüfung (services/selftest.py)
STATE: dict[str, object] = {"started": None, "last_run": None, "last_error": None}


def _fmt_day(value: str | None) -> str:
    try:
        return date.fromisoformat(str(value)).strftime("%d.%m.%Y")
    except ValueError:
        return "-"


async def check_reminders(db, notifier) -> list[str]:
    """Überfällige, offene Rechnungen melden; gibt die Rechnungsnummern zurück, die neu erinnert wurden.

    ``notifier(db, invoice)`` verschickt die Meldung und liefert True, wenn sie an mindestens einen Kanal ging;
    nur dann gilt die Rechnung als erinnert (ein Kanal-Ausfall wird morgen erneut versucht).
    """
    today = date.today()
    newly: list[str] = []
    for invoice in invoices.entries(limit=invoices.MAX_ENTRIES):
        if invoice.get("status") != "open":
            continue
        if invoice.get("reminder_sent_at"):
            continue
        try:
            due = date.fromisoformat(str(invoice.get("due")))
        except ValueError:
            continue  # ohne Zahlungsziel keine Erinnerung (Altbestände ohne Feld)
        if due >= today:
            continue
        try:
            sent = await notifier(db, invoice)
        except Exception:  # eine kaputte Meldung darf die Prüfung nicht abbrechen
            logger.exception("Invoice reminder for %s failed", invoice.get("id"))
            sent = False
        if sent:
            try:
                invoices.mark_reminded(str(invoice.get("id")))
            except (invoices.InvoiceError, OSError) as exc:  # Datei weg? Morgen erneut probieren
                logger.warning("Invoice reminder could not be marked for %s: %s", invoice.get("id"), exc)
            newly.append(str(invoice.get("number") or invoice.get("id")))
    return newly


async def notify_reminder(db, invoice: dict) -> bool:
    """Meldung ``invoice_reminder`` über die Kanäle verschicken; False, wenn kein Kanal sie haben will."""
    from backend.app.services.notification_service import notification_service

    providers = await notification_service._get_providers_for_event(db, EVENT_FIELD, None)
    if not providers:
        return False
    variables = {
        "invoice_number": str(invoice.get("number") or invoice.get("id") or "-"),
        "customer": str(invoice.get("customer") or "-"),
        "due": _fmt_day(invoice.get("due")),
        "total": _fmt_amount(invoice),
        "days": str(max(0, (date.today() - _parse_day(invoice.get("due"))).days)),
    }
    title, message = await notification_service._build_message_from_template(db, EVENT_TYPE, variables)
    await notification_service._send_to_providers(
        providers, title, message, db, EVENT_TYPE, None, None, force_immediate=True, variables=variables
    )
    return True


def _parse_day(value: str | None) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return date.today()


def _fmt_amount(invoice: dict) -> str:
    try:
        return f"{float(invoice.get('total') or 0):.2f} {invoice.get('currency') or 'EUR'}"
    except (TypeError, ValueError):
        return "-"


async def send_test(db) -> tuple[int, list[str]]:
    """Probemeldung „Zahlungserinnerung" an jeden Kanal, der sie will; (Anzahl erfolgreich, Kanäle mit Fehler)."""
    from backend.app.services.notification_service import notification_service as service

    providers = await service._get_providers_for_event(db, EVENT_FIELD, None)
    if not providers:
        return 0, []
    variables = {
        "invoice_number": "A-2026-0001 (Systemprüfung)",
        "customer": "Testkunde",
        "due": "-",
        "total": "-",
        "days": "0",
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
    STATE["started"] = datetime.now(timezone.utc)
    await asyncio.sleep(120)  # nach dem Start erst die Einrichtung einsammeln
    while True:
        try:
            async with session_factory() as db:
                await check_reminders(db, notify_reminder)
            STATE["last_run"], STATE["last_error"] = datetime.now(timezone.utc), None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Invoice reminder check failed")
            STATE["last_error"] = str(exc)[:200]
        await asyncio.sleep(interval)
