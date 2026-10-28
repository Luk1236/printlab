"""Vorgeschriebene Anmeldung (PRINTLAB_REQUIRE_AUTH=1): gesperrt, bis die Einrichtung mit Passwort abgeschlossen ist."""

import pytest
from httpx import AsyncClient

from backend.app.core import auth_policy


@pytest.fixture
def required(monkeypatch):
    monkeypatch.setenv("PRINTLAB_REQUIRE_AUTH", "1")


class TestPolicy:
    @pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
    def test_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv("PRINTLAB_REQUIRE_AUTH", value)
        assert auth_policy.is_required()

    @pytest.mark.parametrize("value", ["", "0", "no", "false", "off", "x"])
    def test_other_values_do_not_require(self, monkeypatch, value):
        monkeypatch.setenv("PRINTLAB_REQUIRE_AUTH", value)
        assert not auth_policy.is_required()

    def test_off_when_unset(self, monkeypatch):
        monkeypatch.delenv("PRINTLAB_REQUIRE_AUTH", raising=False)
        assert not auth_policy.is_required()


class TestRequiredMode:
    @pytest.mark.asyncio
    async def test_status_reports_the_requirement(self, async_client: AsyncClient, required):
        data = (await async_client.get("/api/v1/auth/status")).json()
        assert data["auth_required"] is True and data["auth_enabled"] is False

    @pytest.mark.asyncio
    async def test_status_is_false_by_default(self, async_client: AsyncClient, monkeypatch):
        monkeypatch.delenv("PRINTLAB_REQUIRE_AUTH", raising=False)
        assert (await async_client.get("/api/v1/auth/status")).json()["auth_required"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/printers/",
            "/api/v1/settings/",
            "/api/v1/archives/",
            "/api/v1/quote/company",
            "/api/v1/archives/1/thumbnail",  # sonst öffentliche Bild-Adresse
            "/api/v1/printers/1/camera/snapshot",  # sonst öffentliche Kamera-Adresse
        ],
    )
    async def test_api_is_locked_until_auth_is_set_up(self, async_client: AsyncClient, required, path):
        resp = await async_client.get(path)
        assert resp.status_code == 403
        assert resp.json()["auth_setup_required"] is True and "/setup" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_setup_and_version_stay_reachable(self, async_client: AsyncClient, required):
        assert (await async_client.get("/api/v1/auth/status")).status_code == 200
        assert (await async_client.get("/api/v1/updates/version")).status_code == 200

    @pytest.mark.asyncio
    async def test_setup_cannot_be_finished_without_auth(self, async_client: AsyncClient, required):
        resp = await async_client.post("/api/v1/auth/setup", json={"auth_enabled": False})
        assert resp.status_code == 400
        assert "vorgeschrieben" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_unlocks_once_auth_is_set_up(self, async_client: AsyncClient, required):
        resp = await async_client.post(
            "/api/v1/auth/setup",
            json={"auth_enabled": True, "admin_username": "chef", "admin_password": "Sehr-Geheim-1234!"},
        )
        assert resp.status_code == 200, resp.text
        locked = await async_client.get("/api/v1/printers/")
        assert locked.status_code == 401  # jetzt gilt die normale Anmeldung, nicht mehr die Einrichtungssperre
        assert "auth_setup_required" not in locked.json()


class TestNotRequired:
    @pytest.mark.asyncio
    async def test_default_behaviour_is_unchanged(self, async_client: AsyncClient, monkeypatch):
        monkeypatch.delenv("PRINTLAB_REQUIRE_AUTH", raising=False)
        assert (await async_client.get("/api/v1/printers/")).status_code == 200
        resp = await async_client.post("/api/v1/auth/setup", json={"auth_enabled": False})
        assert resp.status_code == 200
