"""Prognose der Druckwarteschlange auf dem Server (Gegenstück zu ``frontend/src/utils/queueForecast.ts``).

Wann ist jeder wartende Auftrag voraussichtlich fertig? Reihenfolge wie im Planer (Priorität zuerst, dann Position oder
„kürzeste zuerst"). Aufträge für einen festen Drucker reihen sich hinter dessen laufenden Druck ein; Aufträge für „irgendein
Drucker dieses Modells" gehen an den passenden Drucker, der zuerst frei wird (bei Gleichstand der mit der kleineren
Nummer). Aufträge zum manuellen Start, solche, die auf den Benutzer warten, und solche ohne Druckzeit zählen nicht mit.
Eine Schätzung ohne Fehlschläge, Plattenwechsel und Aufheizen; beide Fassungen müssen dieselben Ergebnisse liefern
(gleiche Testfälle in ``test_queue_forecast.py`` und ``queueForecast.test.ts``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.utils.printer_models import normalize_printer_model

_HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class PrinterLive:
    """Was die Prognose vom Zustand eines Druckers braucht."""

    remaining_minutes: float | None = None
    state: str | None = None
    progress: float | None = None


def _model_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (normalize_printer_model(value) or value or "").lower())


def _candidate_models(item: Any) -> list[str]:
    variants = getattr(item, "variants", None) or []
    models = [v.target_model for v in variants] if variants else [item.target_model]
    return [key for key in (_model_key(m) for m in models) if key]


def _busy_only(reason: str) -> bool:
    return all(part.strip().startswith("Busy:") for part in reason.split(" | "))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _order_key(item: Any, sjf: bool):
    priority = -(item.priority if item.priority is not None else 1)
    if sjf:
        seconds = item.print_time_seconds if item.print_time_seconds is not None else float("inf")
        return (priority, 0 if item.been_jumped else 1, seconds, item.position, item.id)
    return (priority, item.position, item.id)


def forecast_ends(
    items: Iterable[Any],
    printers: Iterable[Any],
    live: dict[int, PrinterLive],
    sjf: bool,
    now: datetime,
) -> dict[int, datetime]:
    """Voraussichtliches Ende je wartendem Auftrag (nur Aufträge, die sich einplanen lassen)."""
    items = list(items)
    now = _aware(now)
    active = sorted((p for p in printers if p.is_active), key=lambda p: p.id)
    free_at: dict[int, datetime] = {p.id: now for p in active}
    running: set[int] = set()

    for p in active:
        state = live.get(p.id)
        if state and state.remaining_minutes and state.remaining_minutes > 0 and state.state != "IDLE":
            free_at[p.id] = now + timedelta(minutes=state.remaining_minutes)
            running.add(p.id)

    # Läuft ein Auftrag, dessen Drucker keine Restzeit meldet, zählt die Druckzeit abzüglich Fortschritt.
    for item in items:
        if item.status != "printing" or item.printer_id not in free_at or item.printer_id in running:
            continue
        progress = (live.get(item.printer_id) or PrinterLive()).progress or 0
        if item.print_time_seconds:
            remaining = timedelta(seconds=item.print_time_seconds * max(0.0, 1 - progress / 100))
        else:
            remaining = _HOUR
        free_at[item.printer_id] = now + remaining
        running.add(item.printer_id)

    pending = [
        item
        for item in items
        if item.status == "pending"
        and not item.manual_start
        and not (item.waiting_reason and not _busy_only(item.waiting_reason))
    ]
    pending.sort(key=lambda item: _order_key(item, sjf))

    ends: dict[int, datetime] = {}
    for item in pending:
        seconds = item.print_time_seconds or 0
        if seconds <= 0:
            continue
        if item.printer_id is not None:
            targets = [p for p in active if p.id == item.printer_id]
        else:
            models = _candidate_models(item)
            targets = [
                p
                for p in active
                if models
                and _model_key(p.model) in models
                and (not item.target_location or p.location == item.target_location)
            ]
        if not targets:
            continue
        best = min(targets, key=lambda p: (free_at[p.id], p.id))
        scheduled = _aware(item.scheduled_time) if item.scheduled_time else None
        start = max(free_at[best.id], scheduled if scheduled and scheduled > now else now)
        end = start + timedelta(seconds=seconds)
        ends[item.id] = end
        free_at[best.id] = end
    return ends
