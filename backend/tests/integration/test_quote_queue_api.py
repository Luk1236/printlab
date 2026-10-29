"""Integration-Tests: Angebot → Warteschlange (verknüpfte Druckjobs neu einreihen)."""

import json

import pytest
from httpx import AsyncClient

from backend.app.services import quote_history


@pytest.fixture
def quotes_file(tmp_path, monkeypatch):
    path = tmp_path / "quote_history.json"
    monkeypatch.setattr(quote_history, "HISTORY_PATH", path)
    return path


def _write_quote(path, entry: dict) -> None:
    path.write_text(json.dumps([entry]), encoding="utf-8")


class TestQuoteQueueAPI:
    @pytest.fixture
    async def printer_factory(self, db_session):
        _counter = [0]

        async def _create_printer(**kwargs):
            from backend.app.models.printer import Printer

            _counter[0] += 1
            counter = _counter[0]
            defaults = {
                "name": f"Test Printer {counter}",
                "ip_address": f"192.168.1.{100 + counter}",
                "serial_number": f"TESTSERIAL{counter:04d}",
                "access_code": "12345678",
                "model": "X1C",
            }
            defaults.update(kwargs)
            printer = Printer(**defaults)
            db_session.add(printer)
            await db_session.commit()
            await db_session.refresh(printer)
            return printer

        return _create_printer

    @pytest.fixture
    async def archive_factory(self, db_session):
        _counter = [0]

        async def _create_archive(**kwargs):
            from backend.app.models.archive import PrintArchive

            _counter[0] += 1
            counter = _counter[0]
            defaults = {
                "filename": f"test_print_{counter}.3mf",
                "print_name": f"Test Print {counter}",
                "file_path": f"/tmp/test_print_{counter}.3mf",
                "file_size": 1024,
                "content_hash": f"testhash{counter:08d}",
                "status": "completed",
            }
            defaults.update(kwargs)
            archive = PrintArchive(**defaults)
            db_session.add(archive)
            await db_session.commit()
            await db_session.refresh(archive)
            return archive

        return _create_archive

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_enqueue_links_every_archive_once(
        self, async_client: AsyncClient, quotes_file, printer_factory, archive_factory
    ):
        printer = await printer_factory()
        first, second = await archive_factory(), await archive_factory()
        _write_quote(
            quotes_file,
            {
                "id": "q1",
                "ts": "2026-10-03T09:00:00",
                "customer": "Kunde",
                "currency": "EUR",
                "total": 10.0,
                "archive_ids": [first.id, second.id],
            },
        )
        response = await async_client.post(
            "/api/v1/quote/history/q1/queue",
            json={"printer_id": printer.id, "priority": 2, "quantity": 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert sorted(row["archive_id"] for row in data["queued"]) == sorted([first.id, second.id])
        assert data["errors"] == []

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_missing_archive_ends_up_in_errors(
        self, async_client: AsyncClient, quotes_file, printer_factory, archive_factory
    ):
        printer = await printer_factory()
        archive = await archive_factory()
        _write_quote(
            quotes_file,
            {
                "id": "q1",
                "ts": "2026-10-03T09:00:00",
                "customer": "K",
                "currency": "EUR",
                "total": 1.0,
                "archive_ids": [archive.id, 999999],
            },
        )
        response = await async_client.post("/api/v1/quote/history/q1/queue", json={"printer_id": printer.id})
        assert response.status_code == 200
        data = response.json()
        assert len(data["queued"]) == 1 and data["queued"][0]["archive_id"] == archive.id
        assert data["errors"] and data["errors"][0]["archive_id"] == 999999

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_quote_without_links_is_rejected(self, async_client: AsyncClient, quotes_file):
        _write_quote(quotes_file, {"id": "q2", "ts": "2026-10-03T09:00:00", "currency": "EUR", "total": 1.0})
        response = await async_client.post("/api/v1/quote/history/q2/queue", json={})
        assert response.status_code == 400
        assert "Nachkalkulation" in response.json()["detail"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_unknown_quote_and_conflicting_target(self, async_client: AsyncClient, quotes_file):
        assert (await async_client.post("/api/v1/quote/history/q9/queue", json={})).status_code == 404
        response = await async_client.post(
            "/api/v1/quote/history/q9/queue", json={"printer_id": 1, "target_model": "X1C"}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_invalid_priority_and_quantity(self, async_client: AsyncClient, quotes_file):
        _write_quote(quotes_file, {"id": "q3", "ts": "2026-10-03T09:00:00", "archive_ids": [1]})
        assert (await async_client.post("/api/v1/quote/history/q3/queue", json={"priority": 9})).status_code == 422
        assert (await async_client.post("/api/v1/quote/history/q3/queue", json={"quantity": 99})).status_code == 422
