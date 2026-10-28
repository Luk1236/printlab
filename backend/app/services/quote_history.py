"""Angebotsverlauf: gespeicherte Angebote pro Kunde (Roadmap „Gewerbliches“).

Die Liste liegt in ``quote_history.json`` (neueste zuerst, höchstens ``MAX_ENTRIES``). Ein Eintrag hält Kunde,
Bezeichnung, die Eingaben und die berechneten Beträge fest, damit ein Angebot später nachvollziehbar bleibt,
auch wenn sich Tarife ändern.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

HISTORY_PATH = settings.base_dir / "quote_history.json"
MAX_ENTRIES = 1000
AMOUNT_KEYS = ("material", "energy", "labor", "subtotal", "markup", "total")
_lock = threading.Lock()


def _read() -> list[dict[str, Any]]:
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(entries: list[dict[str, Any]]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_PATH.with_name(HISTORY_PATH.name + ".tmp")
    tmp.write_text(json.dumps(entries[:MAX_ENTRIES], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HISTORY_PATH)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) < 1e9 else None  # NaN und absurde Werte raus


def _counter_path():
    return HISTORY_PATH.with_name("quote_counter.json")


def format_number(number_format: str, prefix: str, year: int, sequence: int) -> str:
    """Setzt Präfix, Jahr und laufende Nummer in das Format ein (nur die bekannten Platzhalter)."""
    return (
        number_format.replace("{prefix}", prefix)
        .replace("{year}", str(year))
        .replace("{yy}", f"{year % 100:02d}")
        .replace("{seq4}", f"{sequence:04d}")
        .replace("{seq5}", f"{sequence:05d}")
        .replace("{seq}", str(sequence))
    )


def _next_number(prefix: str, number_format: str = "{prefix}-{year}-{seq4}") -> str:
    """Laufende Angebotsnummer ``PRÄFIX-JAHR-0001``; der Zähler beginnt jedes Jahr neu und fällt nie zurück,
    auch wenn Angebote gelöscht werden (aufrufen unter ``_lock``)."""
    year = datetime.now(timezone.utc).year
    try:
        counter = json.loads(_counter_path().read_text(encoding="utf-8"))
        sequence = int(counter["seq"]) + 1 if int(counter["year"]) == year else 1
    except (OSError, ValueError, KeyError, TypeError):
        sequence = 1
    # Altbestand ohne Zähler: nicht unter die höchste schon vergebene Nummer fallen
    for entry in _read():
        match = re.fullmatch(r"[A-Za-z0-9]+-(\d{4})-(\d+)", str(entry.get("number", "")))
        if match and int(match.group(1)) == year:
            sequence = max(sequence, int(match.group(2)) + 1)
    _counter_path().write_text(json.dumps({"year": year, "seq": sequence}), encoding="utf-8")
    return format_number(number_format, prefix, year, sequence)


def get(entry_id: str) -> dict[str, Any] | None:
    return next((e for e in _read() if e.get("id") == entry_id), None)


def add(payload: dict[str, Any], prefix: str = "A", number_format: str = "{prefix}-{year}-{seq4}") -> dict[str, Any]:
    """Angebot speichern; ungültige Beträge werden abgelehnt (ValueError)."""
    customer = str(payload.get("customer", "")).strip()[:80]
    if not customer:
        raise ValueError("Kundenname fehlt.")
    amounts: dict[str, float] = {}
    for key in AMOUNT_KEYS:
        number = _number(payload.get(key))
        if number is None or number < 0:
            raise ValueError(f"Betrag „{key}“ fehlt oder ist ungültig.")
        amounts[key] = round(number, 2)
    entry: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(timezone.utc).isoformat(),
        "customer": customer,
        "customer_address": str(payload.get("customer_address", "")).strip()[:240],
        "description": str(payload.get("description", "")).strip()[:200],
        "currency": str(payload.get("currency", "EUR")).strip()[:8] or "EUR",
        **amounts,
    }
    inputs = payload.get("inputs")
    if isinstance(inputs, dict):
        entry["inputs"] = {str(k)[:40]: v for k, v in list(inputs.items())[:20] if _number(v) is not None}
    with _lock:
        entry["number"] = _next_number(prefix or "A", number_format)
        _write([entry, *_read()])
    return entry


def entries(customer: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    items = _read()
    if customer:
        needle = customer.strip().lower()
        items = [e for e in items if needle in str(e.get("customer", "")).lower()]
    return items[: max(1, min(int(limit), MAX_ENTRIES))]


def delete(entry_id: str) -> bool:
    with _lock:
        items = _read()
        kept = [e for e in items if e.get("id") != entry_id]
        if len(kept) == len(items):
            return False
        _write(kept)
    return True


def totals_by_customer() -> list[dict[str, Any]]:
    """Summe und Anzahl je Kunde (nur gleiche Währung wird zusammengezählt), größte Summe zuerst."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for e in _read():
        key = (str(e.get("customer", "")), str(e.get("currency", "EUR")))
        row = grouped.setdefault(key, {"customer": key[0], "currency": key[1], "count": 0, "total": 0.0})
        row["count"] += 1
        row["total"] = round(row["total"] + float(e.get("total", 0) or 0), 2)
    return sorted(grouped.values(), key=lambda r: r["total"], reverse=True)
