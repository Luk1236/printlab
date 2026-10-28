"""Updater for a private repository: git auth through the environment, auto restart, and the 404 hint."""

import base64
import os
import signal

import pytest

from backend.app.api.routes import updates


class TestGitAuth:
    def test_no_token_no_auth_environment(self, monkeypatch):
        monkeypatch.delenv("PRINTLAB_GITHUB_TOKEN", raising=False)
        assert updates._git_auth_env() is None

    def test_token_becomes_a_basic_auth_header_in_the_environment_only(self, monkeypatch):
        monkeypatch.setenv("PRINTLAB_GITHUB_TOKEN", "ghp_secret123")
        env = updates._git_auth_env()
        assert env["GIT_CONFIG_COUNT"] == "1"
        assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
        value = env["GIT_CONFIG_VALUE_0"]
        assert value.startswith("AUTHORIZATION: basic ")
        decoded = base64.b64decode(value.rsplit(" ", 1)[1]).decode()
        assert decoded == "x-access-token:ghp_secret123"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["PATH"] == os.environ["PATH"]  # normale Umgebung bleibt erhalten

    def test_blank_token_counts_as_none(self, monkeypatch):
        monkeypatch.setenv("PRINTLAB_GITHUB_TOKEN", "   ")
        assert updates._git_auth_env() is None

    def test_the_legacy_variable_name_still_works(self, monkeypatch):
        monkeypatch.delenv("PRINTLAB_GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("BAMBUDDY_GITHUB_TOKEN", "legacy")
        import importlib

        from backend.app.core import config

        importlib.reload(config)
        assert os.environ.get("PRINTLAB_GITHUB_TOKEN") == "legacy"
        monkeypatch.delenv("PRINTLAB_GITHUB_TOKEN", raising=False)


class TestAutoRestart:
    @pytest.mark.asyncio
    async def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("PRINTLAB_AUTO_RESTART", raising=False)
        assert updates._schedule_restart_after_update() is False

    @pytest.mark.asyncio
    async def test_on_schedules_a_sigterm_to_itself(self, monkeypatch):
        monkeypatch.setenv("PRINTLAB_AUTO_RESTART", "1")
        scheduled = []

        class FakeLoop:
            def call_later(self, delay, func, *args):
                scheduled.append((delay, func, args))

        monkeypatch.setattr(updates.asyncio, "get_running_loop", lambda: FakeLoop())
        assert updates._schedule_restart_after_update() is True
        delay, func, args = scheduled[0]
        assert delay >= 1 and func is os.kill and args == (os.getpid(), signal.SIGTERM)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["0", "", "no", "false"])
    async def test_other_values_do_not_restart(self, monkeypatch, value):
        monkeypatch.setenv("PRINTLAB_AUTO_RESTART", value)
        assert updates._schedule_restart_after_update() is False
