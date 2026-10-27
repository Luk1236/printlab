"""Tests for the quote calculator endpoint (auth disabled, test DB override)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.settings import Settings

pytestmark = pytest.mark.usefixtures("test_engine")


async def _seed_rate(db: AsyncSession, key: str, value: str) -> None:
    row = Settings(key=key, value=value)
    db.add(row)
    await db.commit()


@pytest.mark.anyio
class TestQuote:
    async def test_quote_matches_hand_computation(self, async_client: AsyncClient, db_session):
        # Seed the rates explicitly: grams=500 @22 -> 11.00 material;
        # 120 min @120 W, 0.35/kWh -> 0.24 kWh = 0.084; labor 60 min @15 = 15;
        # 10% markup on 26.084 -> subtotal 26.08, markup 2.61, total 28.69.
        await _seed_rate(db_session, "default_filament_cost", "22")
        await _seed_rate(db_session, "energy_cost_per_kwh", "0.35")
        await _seed_rate(db_session, "printer_power_watts", "120")
        await _seed_rate(db_session, "labor_rate_per_hour", "15")
        await _seed_rate(db_session, "quote_markup_percent", "10")
        resp = await async_client.get(
            "/api/v1/quote",
            params={
                "grams": 500,
                "duration_minutes": 120,
                "labor_minutes": 60,
                "currency": "EUR",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["material"] == 11.0
        assert body["energy"] == 0.08
        assert body["labor"] == 15.0
        assert body["subtotal"] == 26.08
        assert body["markup"] == 2.61
        assert body["total"] == 28.69
        assert body["currency"] == "EUR"

    async def test_rate_override_for_pricey_material(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/v1/quote",
            params={"grams": 1000, "duration_minutes": 0, "filament_cost_per_kg": 40},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["material"] == 40.0

    async def test_zero_inputs_yield_zero(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/quote", params={"grams": 0, "duration_minutes": 0})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["material"] == 0.0
        assert body["energy"] == 0.0
        assert body["total"] == 0.0

    async def test_invalid_grams_rejected(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/quote", params={"grams": -5, "duration_minutes": 10})
        assert resp.status_code == 422
