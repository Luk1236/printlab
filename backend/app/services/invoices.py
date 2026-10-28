"""Rechnungen aus gespeicherten Angeboten.

Gespeichert in ``invoices.json`` (neueste zuerst). Eine Rechnung übernimmt Kunde, Anschrift, Leistung und Beträge des
Angebots und bekommt eine **eigene, lückenlose Nummer** (Zähler in ``invoice_counter.json``). Rechnungen lassen sich
**nicht löschen, nur stornieren**: die Nummer bleibt vergeben, damit die Nummernfolge keine Lücke bekommt.

Zu jedem Angebot gibt es höchstens eine nicht stornierte Rechnung.

Nicht enthalten: elektronische Rechnungsformate (XRechnung, ZUGFeRD). Ob und ab wann sie für den eigenen Betrieb
verlangt werden und welche Pflichtangaben auf eine Rechnung gehören (§ 14 UStG), klärt die Steuerberatung.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.app.core.config import settings
from backend.app.services import quote_history

INVOICES_PATH = settings.base_dir / "invoices.json"
MAX_ENTRIES = 5000
DEFAULT_FORMAT = "{prefix}-{year}-{seq4}"
STATUSES = ("open", "paid", "cancelled")
_lock = threading.Lock()


class InvoiceError(ValueError):
    """Meldung, die der Benutzer lesen darf."""


def _counter_path():
    return INVOICES_PATH.with_name("invoice_counter.json")


def _read() -> list[dict[str, Any]]:
    try:
        data = json.loads(INVOICES_PATH.read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(entries: list[dict[str, Any]]) -> None:
    INVOICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = INVOICES_PATH.with_name(INVOICES_PATH.name + ".tmp")
    tmp.write_text(json.dumps(entries[:MAX_ENTRIES], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(INVOICES_PATH)


def _next_number(prefix: str, number_format: str) -> str:
    """Laufende Rechnungsnummer; der Zähler beginnt jedes Jahr neu und fällt nie zurück (unter ``_lock``)."""
    year = datetime.now(timezone.utc).year
    try:
        counter = json.loads(_counter_path().read_text(encoding="utf-8"))
        sequence = int(counter["seq"]) + 1 if int(counter["year"]) == year else 1
    except (OSError, ValueError, KeyError, TypeError):
        sequence = 1
    _counter_path().write_text(json.dumps({"year": year, "seq": sequence}), encoding="utf-8")
    return quote_history.format_number(number_format, prefix, year, sequence)


def _parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise InvoiceError(f"„{field}“ ist kein gültiges Datum (JJJJ-MM-TT).") from None


def entries(status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    items = _read()
    if status:
        items = [e for e in items if e.get("status") == status]
    return items[: max(1, min(int(limit), MAX_ENTRIES))]


def get(invoice_id: str) -> dict[str, Any] | None:
    return next((e for e in _read() if e.get("id") == invoice_id), None)


def for_quote(quote_id: str) -> dict[str, Any] | None:
    """Die nicht stornierte Rechnung zu einem Angebot."""
    return next((e for e in _read() if e.get("quote_id") == quote_id and e.get("status") != "cancelled"), None)


def create_from_quote(
    quote_id: str, company: dict[str, Any], service_date: str | None = None, today: date | None = None
) -> dict[str, Any]:
    quote = quote_history.get(quote_id)
    if quote is None:
        raise InvoiceError("Angebot nicht gefunden.")
    issued = today or datetime.now(timezone.utc).date()
    service = _parse_date(service_date, "Leistungsdatum") if service_date else issued
    days = int(company.get("payment_days") or 0)
    with _lock:
        if for_quote(quote_id) is not None:
            raise InvoiceError("Zu diesem Angebot gibt es schon eine Rechnung.")
        number = _next_number(
            str(company.get("invoice_prefix") or "R"), str(company.get("invoice_format") or DEFAULT_FORMAT)
        )
        invoice = {
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.now(timezone.utc).isoformat(),
            "number": number,
            "status": "open",
            "quote_id": quote_id,
            "quote_number": quote.get("number", ""),
            "issued": issued.isoformat(),
            "service_date": service.isoformat(),
            "due": (issued + timedelta(days=days)).isoformat(),
            "paid_at": None,
            **{k: quote.get(k, "") for k in ("customer", "customer_address", "description", "currency")},
            **{k: quote.get(k, 0) for k in quote_history.AMOUNT_KEYS},
            **{k: quote[k] for k in ("items", "extras") if k in quote},
        }
        _write([invoice, *_read()])
    return invoice


def _update(invoice_id: str, change) -> dict[str, Any]:
    with _lock:
        items = _read()
        for item in items:
            if item.get("id") == invoice_id:
                change(item)
                _write(items)
                return item
    raise InvoiceError("Rechnung nicht gefunden.")


def mark_paid(invoice_id: str, paid_at: str | None = None) -> dict[str, Any]:
    day = _parse_date(paid_at, "Zahlungsdatum") if paid_at else datetime.now(timezone.utc).date()

    def change(item: dict[str, Any]) -> None:
        if item.get("status") == "cancelled":
            raise InvoiceError("Eine stornierte Rechnung kann nicht als bezahlt gelten.")
        item["status"] = "paid"
        item["paid_at"] = day.isoformat()

    return _update(invoice_id, change)


def reopen(invoice_id: str) -> dict[str, Any]:
    """Zurück auf „offen“ (zum Beispiel nach einer Fehlbuchung)."""

    def change(item: dict[str, Any]) -> None:
        if item.get("status") == "cancelled":
            raise InvoiceError("Eine stornierte Rechnung lässt sich nicht wieder öffnen.")
        item["status"] = "open"
        item["paid_at"] = None

    return _update(invoice_id, change)


def cancel(invoice_id: str, reason: str = "") -> dict[str, Any]:
    def change(item: dict[str, Any]) -> None:
        if item.get("status") == "paid":
            raise InvoiceError(
                "Eine bezahlte Rechnung wird nicht storniert (Gutschrift mit der Steuerberatung klären)."
            )
        item["status"] = "cancelled"
        item["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        item["cancel_reason"] = str(reason).strip()[:200]

    return _update(invoice_id, change)


def overdue(today: date | None = None) -> list[dict[str, Any]]:
    """Offene Rechnungen, deren Zahlungsziel überschritten ist."""
    now = today or datetime.now(timezone.utc).date()
    out = []
    for item in _read():
        if item.get("status") != "open":
            continue
        try:
            if date.fromisoformat(str(item.get("due"))) < now:
                out.append(item)
        except ValueError:
            continue
    return out


def totals() -> dict[str, dict[str, float]]:
    """Summen je Währung: offen, überfällig, bezahlt (stornierte zählen nicht)."""
    result: dict[str, dict[str, float]] = {}
    overdue_ids = {i["id"] for i in overdue()}
    for item in _read():
        if item.get("status") == "cancelled":
            continue
        row = result.setdefault(str(item.get("currency") or "EUR"), {"open": 0.0, "overdue": 0.0, "paid": 0.0})
        amount = float(item.get("total") or 0)
        if item.get("status") == "paid":
            row["paid"] = round(row["paid"] + amount, 2)
        else:
            row["open"] = round(row["open"] + amount, 2)
            if item["id"] in overdue_ids:
                row["overdue"] = round(row["overdue"] + amount, 2)
    return result
