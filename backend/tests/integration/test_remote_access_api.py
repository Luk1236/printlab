import pytest
from httpx import AsyncClient

from backend.app.api.routes import remote_access as routes
from backend.app.services import audit_log, remote_access as ra


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "STATE_DIR", tmp_path / "ts")
    monkeypatch.setattr(ra, "BIN_DIR", tmp_path / "ts" / "bin")
    monkeypatch.setattr(ra, "CONFIG_PATH", tmp_path / "ts" / "remote_access.json")
    monkeypatch.setattr(ra, "_system_cli", lambda: None)
    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")


class TestRemoteAccessApi:
    @pytest.mark.asyncio
    async def test_status_is_readable_without_auth_and_reports_it(self, async_client: AsyncClient):
        body = (await async_client.get("/api/v1/remote-access")).json()
        assert body["auth_enabled"] is False and body["installed"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["setup", "share"])
    async def test_setup_and_share_need_auth(self, async_client: AsyncClient, path):
        resp = await async_client.post(f"/api/v1/remote-access/{path}")
        assert resp.status_code == 403 and "Anmeldung" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_turning_it_off_is_always_allowed(self, async_client: AsyncClient):
        assert (await async_client.post("/api/v1/remote-access/disable")).status_code == 200

    @pytest.mark.asyncio
    async def test_setup_with_auth_calls_the_service_with_the_port(self, async_client: AsyncClient, monkeypatch):
        seen = {}

        async def fake_auth(db):
            return True

        async def fake_setup(port):
            seen["port"] = port
            return {"state": "login", "login_url": "https://login.tailscale.com/a/x", "supported": True}

        monkeypatch.setattr(routes, "is_auth_enabled", fake_auth)
        monkeypatch.setattr(ra, "supported", lambda: True)
        monkeypatch.setattr(ra, "setup", fake_setup)
        resp = await async_client.post("/api/v1/remote-access/setup", params={"port": 8123})
        assert resp.status_code == 200 and seen["port"] == 8123
        assert resp.json()["login_url"].endswith("/a/x")

    @pytest.mark.asyncio
    async def test_service_errors_become_400(self, async_client: AsyncClient, monkeypatch):
        async def fake_auth(db):
            return True

        async def failing(port):
            raise ra.RemoteAccessError("Prüfsumme des Tailscale-Downloads stimmt nicht — abgebrochen.")

        monkeypatch.setattr(routes, "is_auth_enabled", fake_auth)
        monkeypatch.setattr(ra, "supported", lambda: True)
        monkeypatch.setattr(ra, "setup", failing)
        resp = await async_client.post("/api/v1/remote-access/setup")
        assert resp.status_code == 400 and "Prüfsumme" in resp.json()["detail"]
