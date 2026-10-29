"""Vorgeschlagene Aktionen des Assistenten prüfen.

Das Modell schreibt am Ende seiner Antwort eine Zeile ``ACTIONS: [...]``. Nichts davon wird blind übernommen: Es sind nur
zwei Aktionsarten erlaubt, Auftragsnummern müssen in der Datenübersicht vorkommen und zu einem wartenden Auftrag gehören,
Werte werden streng geprüft. Die Beschriftung für die Bestätigung erzeugt PrintLab selbst, nicht das Modell. Ausgeführt
wird in der Oberfläche über die normalen Warteschlangen-Funktionen (mit deren Rechteprüfung) und erst nach Bestätigung.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

MAX_ACTIONS = 5
PRIORITY_LEVELS = {"low": 0, "normal": 1, "urgent": 2}
_MARKER = re.compile(r"^\s*ACTIONS:\s*(.*)$", re.IGNORECASE | re.MULTILINE | re.DOTALL)

LABELS = {
    "de": {
        "set_priority": "Priorität von Auftrag {item} ({name}) auf „{value}“ setzen",
        "set_due_date": "Liefertermin von Auftrag {item} ({name}) auf {value} setzen",
        "clear_due": "Liefertermin von Auftrag {item} ({name}) entfernen",
        "priority": {"urgent": "Eilig", "normal": "Standard", "low": "Niedrig"},
    },
    "en": {
        "set_priority": "Set the priority of item {item} ({name}) to “{value}”",
        "set_due_date": "Set the due date of item {item} ({name}) to {value}",
        "clear_due": "Remove the due date of item {item} ({name})",
        "priority": {"urgent": "Urgent", "normal": "Normal", "low": "Low"},
    },
}


def split_reply(text: str) -> tuple[str, str | None]:
    """Antworttext ohne ``ACTIONS:``-Zeile und der Rest nach dem Marker (oder None)."""
    match = _MARKER.search(text)
    if not match:
        return text.strip(), None
    return text[: match.start()].strip(), match.group(1).strip()


def _parse_list(raw: str) -> list[Any]:
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _parse_due(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def validate(raw: str | None, known_items: dict[int, str], lang: str = "de") -> tuple[list[dict[str, Any]], int]:
    """(geprüfte Aktionen, Anzahl abgelehnter Vorschläge). ``known_items``: Nummer → Name der wartenden Aufträge."""
    if not raw:
        return [], 0
    labels = LABELS["en" if lang == "en" else "de"]
    accepted: list[dict[str, Any]] = []
    rejected = 0
    for entry in _parse_list(raw)[: MAX_ACTIONS + 5]:
        if len(accepted) >= MAX_ACTIONS:
            rejected += 1
            continue
        action = _one(entry, known_items, labels)
        if action is None:
            rejected += 1
        elif action not in accepted:
            accepted.append(action)
    return accepted, rejected


def _one(entry: Any, known_items: dict[int, str], labels: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    item_id = entry.get("item_id")
    if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id not in known_items:
        return None
    name = known_items[item_id]
    kind = entry.get("type")
    if kind == "set_priority":
        level = entry.get("priority")
        if level not in PRIORITY_LEVELS:
            return None
        text = labels["set_priority"].format(item=item_id, name=name, value=labels["priority"][level])
        return {"type": kind, "item_id": item_id, "priority": PRIORITY_LEVELS[level], "label": text}
    if kind == "set_due_date":
        if entry.get("due_at") is None:
            return {
                "type": kind,
                "item_id": item_id,
                "due_at": None,
                "label": labels["clear_due"].format(item=item_id, name=name),
            }
        due = _parse_due(entry.get("due_at"))
        if due is None or not 2000 <= due.year <= 2100:
            return None
        text = labels["set_due_date"].format(item=item_id, name=name, value=due.astimezone().strftime("%Y-%m-%d %H:%M"))
        return {"type": kind, "item_id": item_id, "due_at": due.isoformat(), "label": text}
    return None
