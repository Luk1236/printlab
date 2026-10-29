"""Fehlerhilfe-API: Katalog, Einstellungen und Sofort-Eingriff."""

import pytest
from httpx import AsyncClient

from backend.app.services import countermeasures


@pytest.fixture(autouse=True)
def _temp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(countermeasures, "CONFIG_PATH", tmp_path / "countermeasures.json")
    countermeasures.reset_memory()


class TestCatalog:
    @pytest.mark.asyncio
    async def test_lists_categories_patterns_and_manual_actions(self, async_client: AsyncClient):
        response = await async_client.get("/api/v1/error-help")
        assert response.status_code == 200
        data = response.json()
        assert {entry["id"] for entry in data["categories"]} == {"extrusion", "thermal", "mechanical", "slicer"}
        assert len(data["patterns"]) >= 11
        assert any(pattern["id"] == "heat_creep" for pattern in data["patterns"])
        assert any(action["id"] == "chamber_fan_full" for action in data["manual_actions"])
        assert data["rules"]["chamber_hot"]["title"]


class TestSettings:
    @pytest.mark.asyncio
    async def test_round_trip_only_changes_sent_fields(self, async_client: AsyncClient):
        response = await async_client.put(
            "/api/v1/error-help/countermeasures",
            json={"dry_run": False, "printers": {"7": {"enabled": True, "rules": {"chamber_hot": True}}}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is False
        assert data["printers"]["7"]["enabled"] is True
        assert data["thresholds"]["hot_c"] == 38.0  # unverändert

        response = await async_client.get("/api/v1/error-help/countermeasures")
        assert response.status_code == 200
        body = response.json()
        assert body["config"]["dry_run"] is False
        assert body["printers"] == []

    @pytest.mark.asyncio
    async def test_rejects_unknown_rule_and_bad_printer_key(self, async_client: AsyncClient):
        unknown = await async_client.put(
            "/api/v1/error-help/countermeasures",
            json={"printers": {"7": {"enabled": True, "rules": {"does_not_exist": True}}}},
        )
        assert unknown.status_code == 400
        bad_key = await async_client.put(
            "/api/v1/error-help/countermeasures", json={"printers": {"werkstatt": {"enabled": True}}}
        )
        assert bad_key.status_code == 400

    @pytest.mark.asyncio
    async def test_reports_printers_with_their_rule_state(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(model="X1C")
        await async_client.put(
            "/api/v1/error-help/countermeasures",
            json={"printers": {str(printer.id): {"enabled": True, "rules": {"chamber_cold": True}}}},
        )
        body = (await async_client.get("/api/v1/error-help/countermeasures")).json()
        row = next(entry for entry in body["printers"] if entry["id"] == printer.id)
        assert row["enabled"] is True and row["rules"]["chamber_cold"] is True
        assert row["running"] is False and row["available_actions"] == []


class TestManualAction:
    @pytest.mark.asyncio
    async def test_unknown_printer_is_a_404(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/error-help/countermeasures/9999/action", json={"action_id": "chamber_fan_full"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_a_disconnected_printer_is_a_400(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory()
        response = await async_client.post(
            f"/api/v1/error-help/countermeasures/{printer.id}/action", json={"action_id": "chamber_fan_full"}
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_action_is_rejected_before_sending(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory()
        response = await async_client.post(
            f"/api/v1/error-help/countermeasures/{printer.id}/action", json={"action_id": "warp_drive"}
        )
        # Der Drucker ist nicht verbunden; die Meldung nennt den Zustand, nicht den Befehl.
        assert response.status_code == 400
