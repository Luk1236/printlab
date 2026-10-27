import pytest
from httpx import AsyncClient

from backend.app.services import quote_history


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_history, "HISTORY_PATH", tmp_path / "quote_history.json")


BODY = {"customer": "Kunde", "description": "Teil", "material": 1, "energy": 1, "labor": 1, "subtotal": 3, "markup": 0.6, "total": 3.6}


class TestQuoteHistoryApi:
    @pytest.mark.asyncio
    async def test_save_list_delete_roundtrip(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/quote/history", json=BODY)
        assert resp.status_code == 200
        entry_id = resp.json()["id"]
        listed = (await async_client.get("/api/v1/quote/history")).json()
        assert [e["id"] for e in listed["entries"]] == [entry_id]
        assert listed["customers"][0]["total"] == 3.6
        assert (await async_client.delete(f"/api/v1/quote/history/{entry_id}")).status_code == 200
        assert (await async_client.delete(f"/api/v1/quote/history/{entry_id}")).status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_quote_is_a_400(self, async_client: AsyncClient):
        resp = await async_client.post("/api/v1/quote/history", json={**BODY, "customer": ""})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_filter_by_customer(self, async_client: AsyncClient):
        await async_client.post("/api/v1/quote/history", json=BODY)
        await async_client.post("/api/v1/quote/history", json={**BODY, "customer": "Andere"})
        listed = (await async_client.get("/api/v1/quote/history", params={"customer": "andere"})).json()
        assert [e["customer"] for e in listed["entries"]] == ["Andere"]
