"""Einschalten eines Druckers für einen Auftrag mit festem Drucker (T4-01 der Code-Analyse).

``_power_on_and_wait`` blockiert die laufende Runde bis zu 180 Sekunden. Für Aufträge nach Modell ist das
gedeckelt: ein Einschalten je Runde und eine Abkühlzeit nach einem Fehlschlag (#2786). Für Aufträge mit
festem Drucker fehlte beides, so dass mehrere solche Aufträge die Runde jedes Mal um ein Vielfaches von 180 s
festhielten. Dieselben Regeln gelten jetzt für beide Zweige und teilen sich ``power_on_attempted`` und
``_wake_failures``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.services.scheduler.queue_pass import QueuePass


async def try_power_on_pinned(qp: QueuePass, printer_id: int, plug) -> bool | None:
    """Drucker über *plug* einschalten, höchstens einmal je Runde und mit Abkühlzeit nach Fehlschlag.

    Rückgabe: ``True`` verbunden, ``False`` Versuch gescheitert (Abkühlzeit läuft jetzt),
    ``None`` in dieser Runde nicht versucht (Abkühlzeit läuft noch oder das eine Einschalten
    der Runde ist schon verbraucht). Bei ``None`` bleibt der Auftrag mit Haltegrund liegen,
    die Runde wartet nicht.
    """
    scheduler = qp._s
    cooloff_until = scheduler._wake_failures.get(printer_id)
    if cooloff_until is not None:
        if time.monotonic() < cooloff_until:
            return None
        del scheduler._wake_failures[printer_id]
    if qp.power_on_attempted:
        return None
    qp.power_on_attempted = True
    powered_on = await scheduler._power_on_and_wait(plug, printer_id, qp.db)
    if not powered_on:
        scheduler._wake_failures[printer_id] = time.monotonic() + scheduler._wake_failure_cooloff
    return powered_on
