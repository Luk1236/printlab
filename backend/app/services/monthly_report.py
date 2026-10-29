"""Monats-Report: Umsatz, Fertigung und Gewinn eines Kalendermonats.

Der Report sammelt nur, was schon existiert: Rechnungen und Angebote aus den
JSON-Ablagen (``invoices``/``quote_history``), Fertigungszahlen aus dem
Druck-Protokoll (``PrintLogEntry``, dieselbe Quelle wie die Archiv-Statistik)
und den Gewinn aus der Nachkalkulation (``quote_actuals``), aber nur für
Angebote des gewählten Monats mit verknüpften Archiven. Nichts wird gespeichert;
die Schnittstelle liefert das Zahlenwerk, das PDF macht daraus die Seite.

Bewusste Grenzen: Arbeitszeit bleibt wie im Angebot (nicht messbar), und
Angebote ohne verknüpfte Archive zählen bei Umsatz mit, bei Gewinn nicht.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.print_log import PrintLogEntry
from backend.app.services import invoices, quote_actuals, quote_history


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    last = first + timedelta(days=monthrange(year, month)[1]) - timedelta(days=1)
    return first, last


def _in_month_day(value: Any, start: date, end: date) -> bool:
    """Datum oder ISO-Zeitstempel innerhalb des Monats."""
    if not value:
        return False
    try:
        try:
            day = date.fromisoformat(str(value)[:10])
        except ValueError:
            day = datetime.fromisoformat(str(value)).date()
    except ValueError:
        return False
    return start <= day <= end


def _empty_money() -> dict[str, Any]:
    return {"count": 0, "open": 0.0, "paid": 0.0, "cancelled": 0.0, "total": 0.0, "overdue_count": 0, "overdue": 0.0}


def _add(money: dict[str, Any], entry: dict[str, Any], total_key: str) -> None:
    money["count"] += 1
    amount = float(entry.get(total_key) or 0)
    money["total"] += amount
    status = entry.get("status", "open")
    if status in ("open", "paid", "cancelled"):
        money[status] += amount


async def collect(db: AsyncSession, year: int, month: int, rates: dict[str, float]) -> dict[str, Any]:
    """Zahlenwerk für einen Monat (JSON-fähig)."""
    start, end = _month_bounds(year, month)
    today = date.today()

    invoices_by_currency: dict[str, dict[str, Any]] = {}
    for invoice in invoices.entries(limit=invoices.MAX_ENTRIES):
        if not _in_month_day(invoice.get("issued") or invoice.get("ts"), start, end):
            continue
        currency = str(invoice.get("currency") or "EUR")
        bucket = invoices_by_currency.setdefault(currency, _empty_money())
        _add(bucket, invoice, "total")
        if invoice.get("status") == "open":
            try:
                due = date.fromisoformat(str(invoice.get("due")))
            except ValueError:
                continue
            if due < today:
                bucket["overdue"] += float(invoice.get("total") or 0)
                bucket["overdue_count"] += 1

    quotes_by_currency: dict[str, float] = {}
    quotes_in_month: list[dict[str, Any]] = []
    for quote in quote_history.entries(limit=quote_history.MAX_ENTRIES):
        if not _in_month_day(quote.get("ts"), start, end):
            continue
        quotes_in_month.append(quote)
        currency = str(quote.get("currency") or "EUR")
        quotes_by_currency[currency] = quotes_by_currency.get(currency, 0.0) + float(quote.get("total") or 0)

    profit = {"quotes": 0, "estimated_quotes": 0, "per_currency": {}}
    for quote in quotes_in_month:
        ids = [i for i in quote.get("archive_ids", []) if isinstance(i, int)]
        if not ids:
            continue
        rows = (await db.scalars(select(PrintArchive).where(PrintArchive.id.in_(ids)))).all()
        archives = [
            {
                "id": row.id,
                "filament_used_grams": row.filament_used_grams,
                "print_time_seconds": row.print_time_seconds,
                "cost": row.cost,
                "energy_cost": row.energy_cost,
            }
            for row in rows
            if row.id in ids
        ]
        actuals = quote_actuals.compute(quote, archives, rates)
        currency = str(actuals.get("currency") or quote.get("currency") or "EUR")
        bucket = profit["per_currency"].setdefault(currency, {"revenue": 0.0, "actual_cost": 0.0, "profit": 0.0})
        bucket["revenue"] += float(actuals.get("revenue") or 0)
        bucket["actual_cost"] += float(actuals.get("actual_cost") or 0)
        bucket["profit"] += float(actuals.get("profit") or 0)
        profit["quotes"] += 1
        if any(line.get("estimated") for line in actuals.get("lines", [])):
            profit["estimated_quotes"] += 1

    start_dt = datetime(start.year, start.month, start.day)
    end_dt = datetime(end.year, end.month, end.day) + timedelta(days=1)
    conditions = (PrintLogEntry.created_at >= start_dt) & (PrintLogEntry.created_at < end_dt)
    total = (
        await db.execute(
            select(
                func.count(),
                func.sum(PrintLogEntry.duration_seconds),
                func.sum(PrintLogEntry.filament_used_grams),
                func.sum(PrintLogEntry.cost),
                func.sum(PrintLogEntry.energy_cost),
            ).where(conditions, PrintLogEntry.status == "completed")
        )
    ).one()
    failed = (await db.execute(select(func.count()).where(conditions, PrintLogEntry.status == "failed"))).scalar() or 0
    by_type = (
        await db.execute(
            select(PrintLogEntry.filament_type, func.sum(PrintLogEntry.filament_used_grams))
            .where(conditions, PrintLogEntry.status == "completed")
            .group_by(PrintLogEntry.filament_type)
        )
    ).all()
    by_printer = (
        await db.execute(
            select(
                PrintLogEntry.printer_name,
                func.count(),
                func.sum(PrintLogEntry.duration_seconds),
            )
            .where(conditions, PrintLogEntry.status == "completed")
            .group_by(PrintLogEntry.printer_name)
        )
    ).all()

    return {
        "year": year,
        "month": month,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "invoices": invoices_by_currency,
        "quotes": quotes_by_currency,
        "profit": profit,
        "production": {
            "prints": int(total[0] or 0),
            "failed": int(failed),
            "minutes": round((total[1] or 0) / 60),
            "grams": round(total[2] or 0),
            "material_cost": round(total[3] or 0, 2),
            "energy_cost": round(total[4] or 0, 2),
            "by_filament_type": [
                {"type": (rtype or "").strip() or "?", "grams": round(grams or 0)} for rtype, grams in by_type
            ],
            "by_printer": [
                {"name": name or "?", "prints": int(count or 0), "minutes": round((minutes or 0) / 60)}
                for name, count, minutes in by_printer
            ],
        },
    }
