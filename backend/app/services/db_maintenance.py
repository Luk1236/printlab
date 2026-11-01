"""Datenbank prüfen und komprimieren.

SQLite gibt nach dem Löschen großer Archive den Platz nicht von selbst zurück; die Datei bleibt groß und die
SD-Karte behält die belegten Blöcke. ``VACUUM`` schreibt die Datenbank neu und gibt den Platz frei, ``quick_check``
findet beschädigte Seiten, bevor ein Druckauftrag daran scheitert. Beides läuft nur auf SQLite — bei PostgreSQL
gehört das in die Datenbankverwaltung.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

ACTIONS = ("check", "vacuum")


class DatabaseMaintenanceError(RuntimeError):
    """Aktion nicht möglich; die Meldung ist für die Oberfläche bestimmt."""


def _db_path(engine: AsyncEngine) -> Path | None:
    url = engine.url
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:":
        return None
    return Path(database)


def _size(path: Path | None) -> int | None:
    try:
        return path.stat().st_size if path and path.is_file() else None
    except OSError:
        return None


def _engine(engine: AsyncEngine | None) -> AsyncEngine:
    if engine is not None:
        return engine
    from backend.app.core.database import engine as shared_engine

    return shared_engine


async def status(engine: AsyncEngine | None = None) -> dict[str, Any]:
    """Größe und Ort der Datenbank, ohne sie zu öffnen."""
    eng = _engine(engine)
    path = _db_path(eng)
    return {
        "supported": path is not None,
        "dialect": eng.dialect.name,
        "path": str(path) if path else None,
        "size_bytes": _size(path),
    }


async def run(action: str, engine: AsyncEngine | None = None) -> dict[str, Any]:
    """``check`` oder ``vacuum`` ausführen. Gibt Ergebnis und Größe vorher/nachher zurück."""
    if action not in ACTIONS:
        raise DatabaseMaintenanceError(f"Unbekannte Aktion {action!r}; erlaubt: {', '.join(ACTIONS)}.")
    eng = _engine(engine)
    path = _db_path(eng)
    if path is None:
        raise DatabaseMaintenanceError(
            "Datenbank-Wartung gibt es nur für die lokale SQLite-Datenbank; bei PostgreSQL übernimmt das die "
            "Datenbankverwaltung."
        )
    before = _size(path)
    if action == "check":
        async with eng.connect() as conn:
            rows = [str(row[0]) for row in await conn.execute(text("PRAGMA quick_check"))]
        ok = rows == ["ok"]
        logger.info("Datenbankprüfung: %s", "in Ordnung" if ok else rows[:3])
        return {"ok": ok, "action": action, "detail": rows[:5], "size_bytes": before, "saved_bytes": 0}

    # VACUUM verweigert eine laufende Transaktion; deshalb eine Verbindung im AUTOCOMMIT-Modus.
    async with eng.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("VACUUM"))
    after = _size(path)
    saved = max(0, (before or 0) - (after or 0))
    logger.info("Datenbank komprimiert: %s → %s Bytes (%s frei)", before, after, saved)
    return {"ok": True, "action": action, "detail": [], "size_bytes": after, "saved_bytes": saved}
