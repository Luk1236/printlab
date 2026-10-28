"""Nachkalkulation: Druckjobs mit einem Angebot verknüpfen und Ist-Kosten vergleichen."""

import pytest
from httpx import AsyncClient

from backend.app.services import quote_actuals, quote_history

BODY = {
    "customer": "Kunde",
    "material": 2,
    "energy": 1,
    "labor": 5,
    "subtotal": 8,
    "markup": 1.6,
    "total": 9.6,
}
RATES = {"material_per_kg": 20.0, "energy_per_kwh": 0.3, "power_watts": 100.0}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_history, "HISTORY_PATH", tmp_path / "quote_history.json")


class TestCompute:
    def test_uses_archive_costs_and_keeps_the_quoted_labor(self):
        quote = {"id": "q", "labor": 5, "subtotal": 8, "total": 9.6, "currency": "EUR"}
        archive = {"id": 1, "filament_used_grams": 100, "print_time_seconds": 3600, "cost": 3.0, "energy_cost": 0.5}
        result = quote_actuals.compute(quote, [archive], RATES)
        assert (result["material"], result["energy"], result["labor"]) == (3.0, 0.5, 5.0)
        assert result["actual_cost"] == 8.5 and result["deviation"] == 0.5
        assert result["profit"] == 1.1 and result["lines"][0]["estimated"] is False

    def test_missing_costs_are_estimated_from_grams_and_time(self):
        archive = {"id": 1, "filament_used_grams": 100, "print_time_seconds": 7200, "cost": None, "energy_cost": None}
        result = quote_actuals.compute({"labor": 0, "subtotal": 0, "total": 0}, [archive], RATES)
        assert result["material"] == 2.0 and result["energy"] == 0.06
        assert result["lines"][0]["estimated"] is True

    def test_nothing_linked_and_bad_values(self):
        empty = quote_actuals.compute({"labor": 5, "subtotal": 8, "total": 9.6}, [], RATES)
        assert empty["linked"] == 0 and empty["actual_cost"] == 5.0
        odd = quote_actuals.compute({"labor": "x", "total": None}, [{"id": 1, "cost": "kaputt"}], RATES)
        assert odd["actual_cost"] == 0.0

    def test_extra_items_count_as_revenue_only(self):
        quote = {"labor": 0, "subtotal": 0, "total": 9.0, "extras": 9.0}
        assert quote_actuals.compute(quote, [], RATES)["profit"] == 9.0


class TestApi:
    async def create_quote(self, client: AsyncClient) -> str:
        return (await client.post("/api/v1/quote/history", json=BODY)).json()["id"]

    @pytest.mark.asyncio
    async def test_link_and_compare(self, async_client: AsyncClient, printer_factory, archive_factory):
        printer = await printer_factory()
        archive = await archive_factory(
            printer.id, filament_used_grams=100.0, print_time_seconds=3600, cost=3.0, energy_cost=0.5
        )
        qid = await self.create_quote(async_client)
        linked = await async_client.put(f"/api/v1/quote/history/{qid}/archives", json={"archive_ids": [archive.id]})
        assert linked.status_code == 200 and linked.json()["archive_ids"] == [archive.id]
        data = (await async_client.get(f"/api/v1/quote/history/{qid}/actuals")).json()
        assert data["linked"] == 1 and data["material"] == 3.0 and data["energy"] == 0.5
        assert data["actual_cost"] == 8.5 and data["missing_ids"] == []
        assert data["lines"][0]["filename"] == "Test Print"

    @pytest.mark.asyncio
    async def test_no_links_gives_an_empty_comparison(self, async_client: AsyncClient):
        qid = await self.create_quote(async_client)
        data = (await async_client.get(f"/api/v1/quote/history/{qid}/actuals")).json()
        assert data["linked"] == 0 and data["actual_cost"] == 5.0

    @pytest.mark.asyncio
    async def test_unknown_quote_archive_and_bad_input(self, async_client: AsyncClient):
        assert (await async_client.get("/api/v1/quote/history/nix/actuals")).status_code == 404
        assert (
            await async_client.put("/api/v1/quote/history/nix/archives", json={"archive_ids": []})
        ).status_code == 404
        qid = await self.create_quote(async_client)
        missing = await async_client.put(
            f"/api/v1/quote/history/{qid}/archives", json={"archive_ids": [999999]}, headers={"Accept-Language": "en"}
        )
        assert missing.status_code == 400 and "not found" in missing.json()["detail"]
        assert quote_history.get(qid)["archive_ids"] == []  # unbekannte Nummern werden nicht behalten
        for bad in ("1", [True], [0], [1.5], ["a"], list(range(1, 52))):
            resp = await async_client.put(f"/api/v1/quote/history/{qid}/archives", json={"archive_ids": bad})
            assert resp.status_code == 400, bad

    @pytest.mark.asyncio
    async def test_duplicates_are_dropped(self, async_client: AsyncClient, printer_factory, archive_factory):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        qid = await self.create_quote(async_client)
        resp = await async_client.put(
            f"/api/v1/quote/history/{qid}/archives", json={"archive_ids": [archive.id, archive.id]}
        )
        assert resp.json()["archive_ids"] == [archive.id]
