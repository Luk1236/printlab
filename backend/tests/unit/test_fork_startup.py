"""Eigene Start- und Torprüfungen (services/fork_startup.py)."""

import contextlib
import logging

import pytest

from backend.app.core import auth
from backend.app.services import fork_startup


class FakeSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


def fake_factory():
    return FakeSession()


def auth_is(monkeypatch, value):
    async def fake(db):
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(auth, "is_auth_enabled", fake)


class TestAuthGate:
    @pytest.mark.asyncio
    async def test_open_when_not_required(self, monkeypatch):
        monkeypatch.delenv("PRINTLAB_REQUIRE_AUTH", raising=False)
        auth_is(monkeypatch, False)
        assert await fork_startup.auth_gate(fake_factory, "/api/v1/x") is None

    @pytest.mark.asyncio
    async def test_locked_while_required_and_not_set_up(self, monkeypatch):
        monkeypatch.setenv("PRINTLAB_REQUIRE_AUTH", "1")
        auth_is(monkeypatch, False)
        status, content = await fork_startup.auth_gate(fake_factory, "/api/v1/x")
        assert status == 403 and content["auth_setup_required"] is True

    @pytest.mark.asyncio
    async def test_open_once_auth_is_set_up(self, monkeypatch):
        monkeypatch.setenv("PRINTLAB_REQUIRE_AUTH", "1")
        auth_is(monkeypatch, True)
        assert await fork_startup.auth_gate(fake_factory, "/api/v1/x") is None

    @pytest.mark.asyncio
    async def test_fails_closed_when_the_probe_breaks(self, monkeypatch):
        monkeypatch.setenv("PRINTLAB_REQUIRE_AUTH", "1")
        auth_is(monkeypatch, RuntimeError("DB weg"))
        status, content = await fork_startup.auth_gate(fake_factory, "/api/v1/x")
        assert status == 503 and "unavailable" in content["detail"]


class TestOnStartup:
    @pytest.mark.asyncio
    async def test_warns_when_listening_on_the_network_without_auth(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("HOST", "0.0.0.0")  # noqa: S104
        auth_is(monkeypatch, False)
        with caplog.at_level(logging.WARNING):
            await fork_startup.on_startup(tmp_path, fake_factory)
        assert any("Anmeldung ist ausgeschaltet" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_silent_on_loopback_or_with_auth(self, monkeypatch, tmp_path, caplog):
        auth_is(monkeypatch, False)
        monkeypatch.setenv("HOST", "127.0.0.1")
        with caplog.at_level(logging.WARNING):
            await fork_startup.on_startup(tmp_path, fake_factory)
        monkeypatch.setenv("HOST", "0.0.0.0")  # noqa: S104
        auth_is(monkeypatch, True)
        with caplog.at_level(logging.WARNING):
            await fork_startup.on_startup(tmp_path, fake_factory)
        assert not [r for r in caplog.records if "Anmeldung ist ausgeschaltet" in r.message]

    @pytest.mark.asyncio
    async def test_never_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOST", "0.0.0.0")  # noqa: S104
        auth_is(monkeypatch, RuntimeError("kaputt"))
        with contextlib.suppress(Exception):
            await fork_startup.on_startup(tmp_path, fake_factory)
        await fork_startup.on_startup(tmp_path, fake_factory)  # darf nicht werfen

    @pytest.mark.asyncio
    async def test_schedules_the_update_confirmation_when_an_update_is_pending(self, monkeypatch, tmp_path):
        from backend.app.services import update_guard

        monkeypatch.setenv("HOST", "127.0.0.1")
        calls = []
        monkeypatch.setattr(update_guard, "schedule_confirmation", lambda d: calls.append(d))
        await fork_startup.on_startup(tmp_path, fake_factory)
        assert calls == [tmp_path]
