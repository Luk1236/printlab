"""Auftrags-Priorität und Liefertermin der Druckwarteschlange.

Drei Stufen: ``urgent`` (2) vor ``normal`` (1) vor ``low`` (0). Die Stufe sortiert vor der Reihenfolge der Warteschlange
(und vor „kürzeste zuerst"); innerhalb einer Stufe gilt wie bisher die Position. Der Liefertermin ändert die Reihenfolge
nicht, er löst nur eine Warnung aus.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

PRIORITY_LOW = 0
PRIORITY_NORMAL = 1
PRIORITY_URGENT = 2
PRIORITY_VALUES = (PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_URGENT)

DUE_OVERDUE = "overdue"  # Termin ist vorbei und der Auftrag nicht fertig
DUE_TOO_LATE = "too_late"  # selbst bei sofortigem Start wird der Termin nicht gehalten

_OPEN = ("pending", "printing")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def printer_usage_seconds(runtime_seconds: int | None, print_hours_offset: float | None) -> float:
    """Bisherige Betriebszeit eines Druckers: gezählte Laufzeit plus der eingetragene Sockel."""
    return float(runtime_seconds or 0) + float(print_hours_offset or 0.0) * 3600.0


def due_warning(
    due_at: datetime | None,
    status: str | None,
    print_time_seconds: int | None,
    now: datetime | None = None,
) -> str | None:
    """Warnstufe für einen Auftrag mit Liefertermin oder ``None``."""
    if due_at is None or status not in _OPEN:
        return None
    current = _aware(now) if now else datetime.now(timezone.utc)
    due = _aware(due_at)
    if due < current:
        return DUE_OVERDUE
    if print_time_seconds and current + timedelta(seconds=print_time_seconds) > due:
        return DUE_TOO_LATE
    return None
