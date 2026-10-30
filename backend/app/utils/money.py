"""Geldbeträge: rechnen mit ``Decimal``, ausgeben als ``float`` mit zwei Nachkommastellen.

Rechnungen und Angebote liefen bisher über ``float`` und ``round(..., 2)``. Bei mehreren Positionen
können sich dadurch Cent-Differenzen zwischen der Summenzeile und der Addition der Positionen ergeben
(0.1 + 0.2 ≠ 0.3). Hier wird kaufmännisch auf Cent gerundet (``ROUND_HALF_UP``) und erst am Ende in
``float`` umgewandelt, weil die Speicherung (JSON, SQLite-Float-Spalten) und die PDF-Ausgabe ``float``
erwarten.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")


def to_decimal(value: Any) -> Decimal:
    """Zahl, Text oder None sicher in ``Decimal`` wandeln (None/Unbrauchbares → 0)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def money(value: Any) -> Decimal:
    """Auf Cent kaufmännisch runden."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def as_float(value: Any) -> float:
    """Gerundeter Betrag als ``float`` für JSON, Speicherung und Anzeige."""
    return float(money(value))
