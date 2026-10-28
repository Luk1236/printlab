"""Schnittstelle /system/pi-health."""

import pytest
from httpx import AsyncClient


class TestPiHealthApi:
    @pytest.mark.asyncio
    async def test_returns_the_snapshot_with_all_keys(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/system/pi-health")
        assert resp.status_code == 200
        data = resp.json()
        assert {"cpu_temp_c", "throttled", "disk", "storage", "memory", "backup", "external_backup", "warnings"} <= set(
            data
        )
        assert isinstance(data["warnings"], list)

    @pytest.mark.asyncio
    async def test_values_come_from_the_service(self, async_client: AsyncClient, monkeypatch):
        from backend.app.services import pi_health

        fake = {"cpu_temp_c": 51.5, "warnings": [{"level": "warn", "code": "sd_card", "text": "x", "params": {}}]}
        monkeypatch.setattr(pi_health, "snapshot", lambda data_dir, extra=None: fake)
        assert (await async_client.get("/api/v1/system/pi-health")).json() == fake
