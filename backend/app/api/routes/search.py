"""Globale Suche über Drucker, Bibliothek, Archiv und Warteschlange.

Eine Route statt vier Abfragen: Die Befehlspalette (Strg+K) schickt einen Begriff und bekommt je Bereich höchstens
acht Treffer. Die Sichtbarkeit folgt denselben Regeln wie die Listen selbst — die Besitzrechte werden über
``require_ownership_permission`` geprüft, nicht hier nachgebaut; wer nur eigene Archive sehen darf, findet auch nur
eigene Archive. Druckernamen sind ohne ``printers:read`` nicht Teil der Antwort.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import require_ownership_permission
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer

router = APIRouter(prefix="/search", tags=["search"])

# Je Bereich. Mehr Treffer braucht die Palette nicht, und die Abfrage bleibt billig.
PER_GROUP = 8


def _like(term: str) -> str:
    """Muster für ``ILIKE``, in dem ``%``, ``_`` und ``\\`` Literale bleiben.

    Ohne die Maskierung fände ein Prozentzeichen alles — die Palette würde bei jeder Eingabe eines der Zeichen
    unbrauchbare Trefferlisten zeigen.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _queue_subtitle(item: PrintQueueItem) -> str:
    position = f"#{item.position + 1}"
    return f"{item.status} · {position}" if item.status else position


@router.get("")
async def global_search(
    q: str = Query(..., min_length=2, max_length=80),
    db: AsyncSession = Depends(get_db),
    archives_auth: tuple = Depends(
        require_ownership_permission(Permission.ARCHIVES_READ_ALL, Permission.ARCHIVES_READ_OWN)
    ),
    library_auth: tuple = Depends(
        require_ownership_permission(Permission.LIBRARY_READ_ALL, Permission.LIBRARY_READ_OWN)
    ),
    queue_auth: tuple = Depends(require_ownership_permission(Permission.QUEUE_READ_ALL, Permission.QUEUE_READ_OWN)),
):
    term = q.strip()
    if len(term) < 2:
        return {"query": q, "results": []}

    archive_user, archive_all = archives_auth
    library_user, library_all = library_auth
    queue_user, queue_all = queue_auth
    pattern = _like(term)
    results: list[dict] = []

    # Drucker: sichtbar für alle, die Drucker lesen dürfen (bei ausgeschalteter Anmeldung alle).
    if archive_user is None or archive_user.has_permission(Permission.PRINTERS_READ.value):
        rows = await db.execute(
            select(Printer.id, Printer.name, Printer.model, Printer.ip_address)
            .where(
                or_(
                    Printer.name.ilike(pattern, escape="\\"),
                    Printer.model.ilike(pattern, escape="\\"),
                    Printer.ip_address.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Printer.name)
            .limit(PER_GROUP)
        )
        for printer_id, name, model, ip_address in rows.all():
            results.append(
                {
                    "kind": "printer",
                    "id": printer_id,
                    "title": name,
                    "subtitle": " · ".join(part for part in (model, ip_address) if part),
                }
            )

    # Archiv: nur sichtbare (nicht gelöschte) Läufe; ohne READ_ALL auf eigene begrenzt.
    archive_conditions = [
        PrintArchive.deleted_at.is_(None),
        or_(
            PrintArchive.filename.ilike(pattern, escape="\\"),
            PrintArchive.print_name.ilike(pattern, escape="\\"),
        ),
    ]
    if archive_user is not None and not archive_all:
        archive_conditions.append(PrintArchive.created_by_id == archive_user.id)
    rows = await db.execute(
        select(PrintArchive.id, PrintArchive.filename, PrintArchive.print_name, PrintArchive.completed_at)
        .where(*archive_conditions)
        .order_by(PrintArchive.completed_at.desc())
        .limit(PER_GROUP)
    )
    for archive_id, filename, print_name, completed_at in rows.all():
        subtitle = print_name if print_name and print_name != filename else ""
        if completed_at:
            date = completed_at.strftime("%d.%m.%Y")
            subtitle = f"{subtitle} · {date}" if subtitle else date
        results.append({"kind": "archive", "id": archive_id, "title": filename, "subtitle": subtitle})

    # Bibliothek: Papierkorb bleibt draußen.
    library_conditions = [
        LibraryFile.deleted_at.is_(None),
        LibraryFile.filename.ilike(pattern, escape="\\"),
    ]
    if library_user is not None and not library_all:
        library_conditions.append(LibraryFile.created_by_id == library_user.id)
    rows = await db.execute(
        select(LibraryFile.id, LibraryFile.filename, LibraryFile.file_type)
        .where(*library_conditions)
        .order_by(LibraryFile.filename)
        .limit(PER_GROUP)
    )
    for file_id, filename, file_type in rows.all():
        results.append({"kind": "library", "id": file_id, "title": filename, "subtitle": (file_type or "").upper()})

    # Warteschlange: Titel steht am Archiv- oder Bibliothekseintrag, nicht am Auftrag.
    queue_conditions = [
        or_(
            PrintArchive.filename.ilike(pattern, escape="\\"),
            PrintArchive.print_name.ilike(pattern, escape="\\"),
            LibraryFile.filename.ilike(pattern, escape="\\"),
        )
    ]
    if queue_user is not None and not queue_all:
        queue_conditions.append(PrintQueueItem.created_by_id == queue_user.id)
    rows = await db.execute(
        select(PrintQueueItem, PrintArchive.filename, PrintArchive.print_name, LibraryFile.filename)
        .outerjoin(PrintArchive, PrintQueueItem.archive_id == PrintArchive.id)
        .outerjoin(LibraryFile, PrintQueueItem.library_file_id == LibraryFile.id)
        .where(*queue_conditions)
        .order_by(PrintQueueItem.position)
        .limit(PER_GROUP)
    )
    for item, archive_name, archive_print_name, library_name in rows.all():
        title = archive_print_name or archive_name or library_name
        if title:
            results.append({"kind": "queue", "id": item.id, "title": title, "subtitle": _queue_subtitle(item)})

    return {"query": term, "results": results}
