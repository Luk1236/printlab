"""Meldewege über die Schnittstelle: Auth-Pflicht, keine Geheimnisse in Antworten, Test-Senden."""

import pytest
from httpx import AsyncClient

from backend.app.api.routes import system as system_routes
from backend.app.services import alert_channels

TOKEN = "123456789:" + "A" * 35


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(system_routes.settings, "base_dir", tmp_path)
    for name in alert_channels.ENV_KEYS.values():
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def auth_on(monkeypatch):
    async def on(db):
        return True

    monkeypatch.setattr(system_routes, "is_auth_enabled", on)


class TestAlertsApi:
    @pytest.mark.asyncio
    async def test_status_starts_empty(self, async_client: AsyncClient):
        data = (await async_client.get("/api/v1/system/alerts")).json()
        assert data == {"telegram": False, "telegram_chat": "", "ntfy": False, "ntfy_host": ""}

    @pytest.mark.asyncio
    async def test_changing_needs_authentication(self, async_client: AsyncClient):
        resp = await async_client.put("/api/v1/system/alerts", json={"ntfy_url": "https://ntfy.sh/x"})
        assert resp.status_code == 403
        assert (await async_client.post("/api/v1/system/alerts/test")).status_code == 403

    @pytest.mark.asyncio
    async def test_saves_and_never_returns_secrets(self, async_client: AsyncClient, auth_on):
        resp = await async_client.put(
            "/api/v1/system/alerts",
            json={"telegram_token": TOKEN, "telegram_chat": "42", "ntfy_url": "https://ntfy.sh/geheim"},
        )
        assert resp.status_code == 200
        body = (resp.text + (await async_client.get("/api/v1/system/alerts")).text).lower()
        assert TOKEN.lower() not in body and "geheim" not in body
        assert resp.json()["telegram"] is True and resp.json()["ntfy_host"] == "ntfy.sh"

    @pytest.mark.asyncio
    async def test_invalid_input_is_a_400_with_a_translated_message(self, async_client: AsyncClient, auth_on):
        resp = await async_client.put(
            "/api/v1/system/alerts", json={"ntfy_url": "http://127.0.0.1/x"}, headers={"Accept-Language": "en"}
        )
        assert resp.status_code == 400 and "not allowed" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_test_alert_needs_a_channel_and_reports_the_result(
        self, async_client: AsyncClient, auth_on, monkeypatch
    ):
        resp = await async_client.post("/api/v1/system/alerts/test", headers={"Accept-Language": "en"})
        assert resp.status_code == 400 and "No alert channel" in resp.json()["detail"]
        await async_client.put("/api/v1/system/alerts", json={"ntfy_url": "https://ntfy.sh/x"})
        monkeypatch.setattr(alert_channels, "_post", lambda url, data, timeout=10.0: None)
        resp = await async_client.post("/api/v1/system/alerts/test")
        assert resp.status_code == 200 and resp.json() == {"sent": ["ntfy"], "errors": []}
