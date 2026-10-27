"""Audit-Log für Hardware- und Wartungsaktionen (Roadmap P2).

Jede relevante Aktion (Tür, Plattenwechsel, Magazin, Not-Halt,
Konfigurationsänderung, Wartungsprogramme) landet als Zeile in
``data/audit_log.jsonl``: Zeitstempel, Drucker, Aktion, Ergebnis, optional
Benutzer. Die Datei wird auf ``MAX_LINES`` gekappt, das Lesen liefert die
neuesten Einträge zuerst.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

LOG_PATH = settings.base_dir / "audit_log.jsonl"
MAX_LINES = 2000
_lock = threading.Lock()


def record(action: str, ok: bool, message: str = "", printer_id: int | None = None,
           user: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Aktion protokollieren (Fehler beim Schreiben dürfen nie aufsteigen)."""
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "ok": ok,
        "message": message,
        "printer_id": printer_id,
        "user": user,
    }
    if details:
        entry["details"] = details
    try:
        with _lock:
            new_line = json.dumps(entry, ensure_ascii=False)
            existing: list[str] = []
            if LOG_PATH.exists():
                try:
                    existing = LOG_PATH.read_text(encoding="utf-8").splitlines()
                except (OSError, ValueError):
                    pass
            tmp = LOG_PATH.with_name(LOG_PATH.name + ".tmp")
            tmp.write_text(
                "\n".join([new_line, *existing[: MAX_LINES - 1]]), encoding="utf-8"
            )
            tmp.replace(LOG_PATH)
    except OSError as exc:
        logger.warning("[AuditLog] Schreiben fehlgeschlagen: %s", exc)
    return entry


def entries(limit: int = 50, printer_id: int | None = None) -> list[dict[str, Any]]:
    """Neueste Einträge; optional auf einen Drucker gefiltert."""
    out: list[dict[str, Any]] = []
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return out
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if printer_id is not None and entry.get("printer_id") not in (printer_id, None):
            continue
        out.append(entry)
        if len(out) >= max(1, min(limit, MAX_LINES)):
            break
    return out
