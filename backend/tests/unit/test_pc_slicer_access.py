"""Access guard of the PC slicer: loopback always, others only via allow-list and/or token."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.pc_slicer import _client_allowed, app as slicer_app


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("PC_SLICER_ALLOWED_IPS", raising=False)
    monkeypatch.delenv("PC_SLICER_TOKEN", raising=False)


class TestClientAllowed:
    def test_loopback_is_always_allowed(self):
        assert _client_allowed("127.0.0.1", {})
        assert _client_allowed("::1", {})

    def test_remote_denied_by_default(self):
        assert not _client_allowed("192.168.178.133", {})

    def test_allow_list_exact_ip_and_network(self, monkeypatch):
        monkeypatch.setenv("PC_SLICER_ALLOWED_IPS", "192.168.178.133, 10.0.0.0/24")
        assert _client_allowed("192.168.178.133", {})
        assert _client_allowed("10.0.0.77", {})
        assert not _client_allowed("192.168.178.134", {})
        assert not _client_allowed(None, {})

    def test_garbage_allow_list_entries_do_not_open_access(self, monkeypatch):
        monkeypatch.setenv("PC_SLICER_ALLOWED_IPS", "nonsense")
        assert not _client_allowed("192.168.178.133", {})

    def test_token_required_when_set(self, monkeypatch):
        monkeypatch.setenv("PC_SLICER_TOKEN", "geheim")
        assert not _client_allowed("192.168.178.5", {})
        assert not _client_allowed("192.168.178.5", {"authorization": "Bearer falsch"})
        assert _client_allowed("192.168.178.5", {"authorization": "Bearer geheim"})
        assert _client_allowed("192.168.178.5", {"x-slicer-token": "geheim"})

    def test_allow_list_and_token_must_both_match(self, monkeypatch):
        monkeypatch.setenv("PC_SLICER_ALLOWED_IPS", "192.168.178.133")
        monkeypatch.setenv("PC_SLICER_TOKEN", "geheim")
        assert _client_allowed("192.168.178.133", {"x-slicer-token": "geheim"})
        assert not _client_allowed("192.168.178.133", {})
        assert not _client_allowed("192.168.178.9", {"x-slicer-token": "geheim"})


class TestGuardOverHttp:
    async def test_remote_client_gets_403(self):
        transport = ASGITransport(app=slicer_app, client=("192.168.178.50", 5000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 403

    async def test_local_client_passes(self):
        transport = ASGITransport(app=slicer_app, client=("127.0.0.1", 5000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
        assert resp.status_code == 200
