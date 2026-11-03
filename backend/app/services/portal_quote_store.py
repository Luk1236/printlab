"""SQLite-gespeicherte Angebots-Registry des Kundenportals.

Der Checkout darf ausschließlich Kalkulationen abrechnen, die dieser Server
selbst erzeugt hat — der Zahlbetrag kommt nie aus dem Request. Die Registry
liegt in der Hauptdatenbank (Tabelle ``portal_quotes``), damit ein neu
gestartetes Backend laufende Stripe-Checkout-Angebote erneut auflösen kann;
die Lebensdauer entspricht der Stripe-Session (60 Minuten).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.portal_quote import PortalQuote

logger = logging.getLogger(__name__)

# Muss zur Stripe-Session-Laufzeit passen (Session: 60 Minuten).
QUOTE_TTL_SECONDS = 3600.0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _expiry_utc() -> datetime:
    return _now_utc() + timedelta(seconds=QUOTE_TTL_SECONDS)


async def store_quote(db: AsyncSession, quote: dict[str, Any]) -> dict[str, Any]:
    """Nimmt eine Kalkulation in die Registry auf (Upsert, neu gestrichelte TTL)."""
    key = str(quote.get("quote_id") or "").strip().upper()
    if not key:
        raise ValueError("Kalkulation ohne quote_id kann nicht gespeichert werden.")

    row = await db.get(PortalQuote, key)
    expires = _expiry_utc()
    if row is None:
        row = PortalQuote(quote_id=key, payload=quote, created_at=_now_utc(), expires_at=expires)
        db.add(row)
    else:
        row.payload = quote
        row.expires_at = expires
    await db.commit()
    return quote


async def get_quote(db: AsyncSession, quote_id: str) -> dict[str, Any] | None:
    """Liefert eine gültige Kalkulation oder ``None`` (unbekannt / abgelaufen)."""
    key = (quote_id or "").strip().upper()
    if not key:
        return None
    await purge_expired(db)
    row = await db.get(PortalQuote, key)
    if row is None:
        return None
    payload = dict(row.payload or {})
    payload.pop("_created_at", None)  # Altlast aus der früheren In-Memory-Registry
    return payload


async def purge_expired(db: AsyncSession) -> int:
    """Räumt abgelaufene Angebote auf; Rückgabe der entfernten Zeilen."""
    result = await db.execute(delete(PortalQuote).where(PortalQuote.expires_at < _now_utc()))
    await db.commit()
    return int(result.rowcount or 0)


def quote_expires_in_minutes() -> int:
    """Angebotslaufzeit in Minuten (für Client-Anzeige)."""
    return int(QUOTE_TTL_SECONDS / 60.0)
