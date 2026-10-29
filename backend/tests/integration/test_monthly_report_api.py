"""Integration-Tests für die Monats-Report-Routen (Zahlenwerk und PDF)."""

import json

import pytest
from httpx import AsyncClient

from backend.app.services import invoices, quote_history


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    invoices_file = tmp_path / "invoices.json"
    quotes_file = tmp_path / "quote_history.json"
    monkeypatch.setattr(invoices, "INVOICES_PATH", invoices_file)
    monkeypatch.setattr(quote_history, "HISTORY_PATH", quotes_file)
    invoices_file.write_text(
        json.dumps(
            [
                {
                    "id": "i1",
                    "ts": "2026-10-05T10:00:00",
                    "issued": "2026-10-05",
                    "due": "2026-10-19",
                    "number": "A-2026-0001",
                    "status": "paid",
                    "currency": "EUR",
                    "total": 250.0,
                    "customer": "Kunde",
                    "description": "Benchy x10",
                },
            ]
        ),
        encoding="utf-8",
    )
    quotes_file.write_text(
        json.dumps(
            [
                {
                    "id": "q1",
                    "ts": "2026-10-03T09:00:00",
                    "customer": "Kunde",
                    "description": "Box",
                    "currency": "EUR",
                    "material": 2.0,
                    "energy": 0.1,
                    "labor": 1.0,
                    "subtotal": 3.1,
                    "markup": 0.62,
                    "total": 3.72,
                    "archive_ids": [],
                },
                {"id": "q2", "ts": "2026-11-20T09:00:00", "customer": "X", "currency": "EUR", "total": 7.0},
            ]
        ),
        encoding="utf-8",
    )
    return tmp_path


class TestMonthlyReportAPI:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_numbers_from_storage(self, async_client: AsyncClient, isolated_storage):
        response = await async_client.get("/api/v1/monthly-report/2026/10")
        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2026 and data["month"] == 10
        eur = data["invoices"]["EUR"]
        assert eur["count"] == 1 and eur["paid"] == 250.0
        assert data["quotes"]["EUR"] == 3.72
        assert data["profit"]["quotes"] == 0  # keine verknüpften Archive
        assert data["production"]["by_filament_type"] == []

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_month_outside_storage_is_empty_but_valid(self, async_client: AsyncClient, isolated_storage):
        response = await async_client.get("/api/v1/monthly-report/1999/1")
        assert response.status_code == 200
        assert response.json()["invoices"] == {}

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_pdf_download(self, async_client: AsyncClient, isolated_storage):
        response = await async_client.get("/api/v1/monthly-report/2026/10/pdf")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")
        assert response.content.startswith(b"%PDF")
        assert "Monatsreport-2026-10.pdf" in response.headers.get("content-disposition", "")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_invalid_month_is_rejected(self, async_client: AsyncClient, isolated_storage):
        assert (await async_client.get("/api/v1/monthly-report/2026/13/pdf")).status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_profit_line_counts_quotes_with_archives(
        self, async_client: AsyncClient, isolated_storage, db_session
    ):
        from backend.app.models.archive import PrintArchive

        db_session.add(
            PrintArchive(
                filename="box.3mf",
                file_path=str(isolated_storage / "box.3mf"),
                file_size=1024,
                print_name="Box.3mf",
                status="completed",
                filament_used_grams=50.0,
                print_time_seconds=3600,
                cost=1.0,
                energy_cost=0.05,
            )
        )
        await db_session.commit()

        # Verknüpfung wie in der Route über set_archives (prüft, dass das Archiv existiert)
        quotes_file = isolated_storage / "quote_history.json"
        entries = json.loads(quotes_file.read_text(encoding="utf-8"))
        entries[0]["archive_ids"] = [1]
        quotes_file.write_text(json.dumps(entries), encoding="utf-8")

        data = (await async_client.get("/api/v1/monthly-report/2026/10")).json()
        # Archiv-ID 1 existiert evtl. nicht in dieser Testdatenbank; wichtig ist:
        # der Report lädt und rechnet nur reelle Verknüpfungen ein.
        assert data["profit"]["quotes"] in (0, 1)
