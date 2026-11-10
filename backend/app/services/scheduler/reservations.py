"""Aufräumer für Budget-Reservierungen verwaister Warteschlangen-Aufträge (T4-02 der Code-Analyse).

Eine Reservierung mit Status ``active`` zählt gegen das Budget der Kostenstelle, egal in welchem
Zustand der Auftrag ist (``finance_budget.get_cost_center_reserved_map``). Freigegeben wird sie beim
Löschen, Abbrechen, im Wächter und in der Abrechnung. Wo ein Auftrag anders endet — Abgleich für
hängengebliebene Aufträge, Anhalten bei Offline-Drucker, frühe Ausstiege der Abrechnung, gelöschte
Stapel —, blieb sie bisher für immer stehen. Die Stellen, die man kennt, geben jetzt selbst frei;
dieser Aufräumer fängt den Rest ab, damit eine vergessene Stelle nicht wieder dauerhaft Budget kostet.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.finance import BudgetReservation
from backend.app.models.print_queue import PrintQueueItem

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer

# Endzustände eines Auftrags. ``pending`` und ``printing`` (und alles Unbekannte) halten ihre Reservierung.
TERMINAL_QUEUE_STATUSES = ("completed", "failed", "cancelled", "skipped", "aborted")

# So lange nach dem Ende eines Auftrags darf die Abrechnung noch die Reservierung verbrauchen.
ORPHAN_GRACE = timedelta(minutes=10)

# Höchstens einmal je Stunde: die Abfrage ist billig, aber das Ergebnis ändert sich selten.
MIN_INTERVAL_SECONDS = 3600.0

_next_run: float = 0.0


async def release_orphaned_reservations(db: AsyncSession, *, force: bool = False) -> int:
    """Aktive ``print_queue``-Reservierungen freigeben, deren Auftrag beendet ist oder fehlt.

    Gibt die Zahl der freigegebenen Reservierungen zurück. Wirft nie: ein Fehler hier darf die
    Warteschlange nicht anhalten. ``force`` überspringt die Zeitsperre (Tests).
    """
    global _next_run
    now_mono = time.monotonic()
    if not force and now_mono < _next_run:
        return 0
    _next_run = now_mono + MIN_INTERVAL_SECONDS

    # Spalten sind ohne Zeitzone gespeichert (UTC), deshalb ein Vergleichswert ohne Zeitzone.
    cutoff = (datetime.now(timezone.utc) - ORPHAN_GRACE).replace(tzinfo=None)
    try:
        result = await db.execute(
            select(BudgetReservation)
            .outerjoin(PrintQueueItem, PrintQueueItem.id == BudgetReservation.source_id)
            .where(BudgetReservation.status == "active", BudgetReservation.source_type == "print_queue")
            .where(
                or_(
                    PrintQueueItem.id.is_(None),
                    and_(
                        PrintQueueItem.status.in_(TERMINAL_QUEUE_STATUSES),
                        or_(PrintQueueItem.completed_at.is_(None), PrintQueueItem.completed_at < cutoff),
                    ),
                )
            )
        )
        orphans = list(result.scalars().all())
        if not orphans:
            return 0
        released_at = datetime.now(timezone.utc)
        for reservation in orphans:
            reservation.status = "released"
            reservation.released_at = released_at
        await db.commit()
        logger.warning(
            "Released %d budget reservation(s) of finished or removed queue items: %s (T4-02)",
            len(orphans),
            [(r.id, r.source_id, r.amount) for r in orphans],
        )
        return len(orphans)
    except Exception:
        logger.warning("Budget reservation cleanup failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            logger.debug("Rollback after a failed reservation cleanup failed too", exc_info=True)
        return 0
