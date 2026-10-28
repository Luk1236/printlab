"""Ausweg über ``git ls-remote``, wenn die GitHub-Schnittstelle gesperrt ist (60 Abfragen pro Stunde ohne Anmeldung)."""

import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

import backend.app.api.routes.updates as updates_module

TAGS = (
    "aaa\trefs/tags/v1.8.0\n"
    "bbb\trefs/tags/v1.9.0\n"
    "ccc\trefs/tags/v1.10.0b1\n"
    "ddd\trefs/tags/v1.2.0\n"
    "eee\trefs/tags/nightly\n"
    "fff\trefs/tags/vx\n"
)


class _Proc:
    def __init__(self, out: str, code: int = 0):
        self._out, self.returncode = out.encode(), code

    async def communicate(self):
        return self._out, b""


def fake_git(out: str, code: int = 0):
    return patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_Proc(out, code)))


@pytest.fixture(autouse=True)
def _state():
    updates_module._github_rate_limit_until = 0.0
    updates_module._update_status = {"status": "idle", "progress": 0, "message": "", "error": None}
    yield
    updates_module._github_rate_limit_until = 0.0


class TestGitTagReleases:
    @pytest.mark.asyncio
    async def test_lists_version_tags_newest_first_and_ignores_others(self):
        with fake_git(TAGS), patch.object(updates_module, "_find_executable", return_value="git"):
            tags = [r["tag_name"] for r in await updates_module._git_tag_releases()]
        assert tags == ["v1.10.0b1", "v1.9.0", "v1.8.0", "v1.2.0"]

    @pytest.mark.asyncio
    async def test_entries_look_like_releases(self):
        with fake_git(TAGS), patch.object(updates_module, "_find_executable", return_value="git"):
            first = (await updates_module._git_tag_releases())[1]
        assert first["tag_name"] == "v1.9.0" and first["body"] == ""
        assert first["html_url"].endswith("/releases/tag/v1.9.0")

    @pytest.mark.asyncio
    async def test_no_git_failure_or_timeout_gives_an_empty_list(self):
        with patch.object(updates_module, "_find_executable", return_value=None):
            assert await updates_module._git_tag_releases() == []
        with fake_git("", 128), patch.object(updates_module, "_find_executable", return_value="git"):
            assert await updates_module._git_tag_releases() == []
        with (
            patch.object(updates_module, "_find_executable", return_value="git"),
            patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("kein git"))),
        ):
            assert await updates_module._git_tag_releases() == []


class _Limited:
    status_code = 403
    headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 600)}
    text = "API rate limit exceeded"

    def raise_for_status(self):
        raise AssertionError("darf nicht aufgerufen werden")


class _Client:
    calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def get(self, *_, **__):
        type(self).calls += 1
        return _Limited()


def limited_api():
    import httpx

    _Client.calls = 0
    return patch.object(httpx, "AsyncClient", _Client)


FAKE = [
    {"tag_name": "v1.10.0b1", "name": "v1.10.0b1", "body": "", "html_url": "u", "published_at": ""},
    {"tag_name": "v1.9.0", "name": "v1.9.0", "body": "", "html_url": "u", "published_at": ""},
]


class TestCheckFallsBack:
    @pytest.mark.asyncio
    async def test_a_rate_limited_check_still_finds_the_update_via_git(self, async_client: AsyncClient):
        with (
            limited_api(),
            patch.object(updates_module, "_git_tag_releases", AsyncMock(return_value=FAKE)),
            patch.object(updates_module, "PRINTLAB_VERSION", "1.8.0"),
        ):
            body = (await async_client.get("/api/v1/updates/check")).json()
        assert body["update_available"] is True and body["latest_version"] == "1.9.0"
        assert "error" not in body
        assert updates_module._update_status["error"] is None

    @pytest.mark.asyncio
    async def test_beta_versions_are_included_only_when_asked(self, async_client: AsyncClient):
        with (
            limited_api(),
            patch.object(updates_module, "_git_tag_releases", AsyncMock(return_value=FAKE)),
            patch.object(updates_module, "PRINTLAB_VERSION", "1.8.0"),
        ):
            stable = (await async_client.get("/api/v1/updates/check")).json()
            await async_client.put("/api/v1/settings/", json={"include_beta_updates": True})
            beta = (await async_client.get("/api/v1/updates/check")).json()
        assert stable["latest_version"] == "1.9.0"
        assert beta["latest_version"] == "1.10.0b1"

    @pytest.mark.asyncio
    async def test_during_the_backoff_window_no_api_call_is_made(self, async_client: AsyncClient):
        updates_module._github_rate_limit_until = time.time() + 600
        with (
            limited_api(),
            patch.object(updates_module, "_git_tag_releases", AsyncMock(return_value=FAKE)),
            patch.object(updates_module, "PRINTLAB_VERSION", "1.9.0"),
        ):
            body = (await async_client.get("/api/v1/updates/check")).json()
        assert _Client.calls == 0
        assert body["latest_version"] == "1.9.0" and body["update_available"] is False

    @pytest.mark.asyncio
    async def test_without_git_the_old_rate_limit_message_stays(self, async_client: AsyncClient):
        with limited_api(), patch.object(updates_module, "_git_tag_releases", AsyncMock(return_value=[])):
            body = (await async_client.get("/api/v1/updates/check")).json()
        assert "rate limit" in body["error"].lower() and body["retry_after_seconds"] > 0


class TestTargetDiscoveryFallsBack:
    @pytest.mark.asyncio
    async def test_target_tag_comes_from_git_when_limited(self, db_session):
        with limited_api(), patch.object(updates_module, "_git_tag_releases", AsyncMock(return_value=FAKE)):
            assert await updates_module._discover_target_release(db_session) == "v1.9.0"

    @pytest.mark.asyncio
    async def test_target_tag_during_backoff(self, db_session):
        updates_module._github_rate_limit_until = time.time() + 600
        with limited_api(), patch.object(updates_module, "_git_tag_releases", AsyncMock(return_value=FAKE)):
            assert await updates_module._discover_target_release(db_session) == "v1.9.0"
        assert _Client.calls == 0

    @pytest.mark.asyncio
    async def test_no_target_when_git_has_nothing(self, db_session):
        with limited_api(), patch.object(updates_module, "_git_tag_releases", AsyncMock(return_value=[])):
            assert await updates_module._discover_target_release(db_session) is None
