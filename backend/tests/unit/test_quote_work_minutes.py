"""Zeitbuchung am Angebot: Nachkalkulation nutzt gebuchte Arbeitszeit, Route setzt und entfernt sie."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from backend.app.services import quote_actuals, quote_history

RATES = {"material_per_kg": 20.0, "energy_per_kwh": 0.3, "power_watts": 100.0, "labor_rate_per_hour": 30.0}


class TestCompute:
    def test_labor_comes_from_the_quote_without_booking(self):
        quote = {
            "id": "q",
            "currency": "EUR",
            "labor": 15.0,
            "subtotal": 100.0,
            "total": 120.0,
            "archive_ids": [],
            "archives": [],
        }
        result = quote_actuals.compute(quote, [], RATES)
        assert result["labor"] == 15.0 and result["labor_measured"] is False

    def test_logged_work_replaces_the_quoted_labor(self):
        quote = {"id": "q", "currency": "EUR", "labor": 15.0, "work_minutes": 90, "subtotal": 100.0, "total": 120.0}
        result = quote_actuals.compute(quote, [], RATES)
        assert result["labor_measured"] is True
        assert result["work_minutes"] == 90
        assert result["labor"] == 45.0  # 90 min × 30 EUR/h
        assert result["profit"] == round(120.0 - 45.0, 2)


@pytest.fixture
def quotes_file(tmp_path, monkeypatch):
    path = tmp_path / "quote_history.json"
    monkeypatch.setattr(quote_history, "HISTORY_PATH", path)
    return path


class TestWorkMinutesAPI:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_set_and_clear(self, async_client: AsyncClient, quotes_file):
        quotes_file.write_text(
            json.dumps([{"id": "q1", "customer": "K", "currency": "EUR", "total": 1.0}]), encoding="utf-8"
        )
        set_value = await async_client.put("/api/v1/quote/history/q1/work-minutes", json={"work_minutes": 45})
        assert set_value.status_code == 200 and set_value.json()["work_minutes"] == 45
        assert quote_history.get("q1")["work_minutes"] == 45
        cleared = await async_client.put("/api/v1/quote/history/q1/work-minutes", json={"work_minutes": None})
        assert cleared.status_code == 200 and "work_minutes" not in cleared.json()
        assert "work_minutes" not in quote_history.get("q1")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rejects_out_of_range(self, async_client: AsyncClient, quotes_file):
        quotes_file.write_text(json.dumps([{"id": "q1", "currency": "EUR", "total": 1.0}]), encoding="utf-8")
        assert (
            await async_client.put("/api/v1/quote/history/q1/work-minutes", json={"work_minutes": -5})
        ).status_code == 422
        assert (
            await async_client.put("/api/v1/quote/history/q1/work-minutes", json={"work_minutes": "viele"})
        ).status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_unknown_quote_is_404(self, async_client: AsyncClient, quotes_file):
        response = await async_client.put("/api/v1/quote/history/q9/work-minutes", json={"work_minutes": 10})
        assert response.status_code == 404
