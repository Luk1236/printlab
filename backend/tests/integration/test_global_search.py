"""Globale Suche: Treffer, Grenzen und Sichtbarkeit.

Die Route ist die einzige Quelle der Befehlspalette. Geprüft wird, dass sie die vier Bereiche findet, den Begriff
nicht in SQL einsetzt (Muster bleibt parametrisiert), zu kurze Begriffe ablehnt und den Papierkorb auslässt.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer


@pytest.mark.asyncio
async def test_finds_printers_archives_library_and_queue(async_client, db_session: AsyncSession):
    printer = Printer(
        name="Werkstatt X1C",
        serial_number="01P00A000001",
        ip_address="192.168.1.20",
        access_code="12345678",
        model="X1C",
    )
    db_session.add(printer)
    archive = PrintArchive(filename="benchy_werkstatt.3mf", file_path="/tmp/a.3mf", file_size=1, print_name="Benchy")
    db_session.add(archive)
    await db_session.commit()

    library = LibraryFile(filename="benchy_werkstatt.3mf", file_path="/tmp/l.3mf", file_type="3mf", file_size=2)
    db_session.add(library)
    await db_session.commit()

    db_session.add(PrintQueueItem(library_file_id=library.id, position=0, created_by_id=None))
    await db_session.commit()

    response = await async_client.get("/api/v1/search", params={"q": "benchy"})
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    kinds = {entry["kind"] for entry in results}
    assert {"archive", "library", "queue"} <= kinds
    assert all("benchy" in entry["title"].lower() for entry in results if entry["kind"] in {"archive", "library"})

    response = await async_client.get("/api/v1/search", params={"q": "Werkstatt"})
    printer_hits = [entry for entry in response.json()["results"] if entry["kind"] == "printer"]
    assert [entry["title"] for entry in printer_hits] == ["Werkstatt X1C"]
    assert printer_hits[0]["subtitle"] == "X1C · 192.168.1.20"


@pytest.mark.asyncio
async def test_trashed_library_file_and_deleted_archive_are_hidden(async_client, db_session: AsyncSession):
    from datetime import datetime

    archived = PrintArchive(
        filename="geloescht.3mf", file_path="/tmp/g.3mf", file_size=1, deleted_at=datetime(2026, 1, 1)
    )
    trashed = LibraryFile(
        filename="geloescht.3mf", file_path="/tmp/g.3mf", file_type="3mf", file_size=1, deleted_at=datetime(2026, 1, 1)
    )
    db_session.add_all([archived, trashed])
    await db_session.commit()

    response = await async_client.get("/api/v1/search", params={"q": "geloescht"})
    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.asyncio
async def test_short_query_is_rejected_and_wildcards_stay_literal(async_client, db_session: AsyncSession):
    assert (await async_client.get("/api/v1/search", params={"q": "b"})).status_code == 422

    db_session.add(
        Printer(
            name="Prozent % Drucker",
            serial_number="01P00A000002",
            ip_address="10.0.0.9",
            access_code="12345678",
        )
    )
    await db_session.commit()

    # ``%`` darf nicht als Platzhalter durchschlagen: sonst fände ein Prozentzeichen alles.
    response = await async_client.get("/api/v1/search", params={"q": "%%"})
    assert response.status_code == 200
    assert response.json()["results"] == []
