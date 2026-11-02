"""Auto-Einrichtung: was das System selbst erledigt und was es dem Benutzer überlässt."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.app.services import assistant_config, auto_setup, update_guard

UNIT_WITHOUT_GUARD = "[Service]\nExecStart=/usr/bin/python3 -m uvicorn app\n"


@pytest.fixture(autouse=True)
def no_systemctl(monkeypatch):
    """``ensure_systemd_guard`` ruft ``systemctl daemon-reload``; auf dem Testrechner gibt es das nicht."""
    monkeypatch.setattr(update_guard.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))


def deps(tmp_path: Path, **overrides) -> auto_setup.Deps:
    unit = tmp_path / "printlab.service"
    unit.write_text(UNIT_WITHOUT_GUARD, encoding="utf-8")

    async def reachable(_config):
        return {"reachable": True, "model_present": True}

    async def remote_off():
        return {"state": "off"}

    async def remote_connect(_port):
        return {"state": "connected"}

    values = {
        "data_dir": tmp_path,
        "app_dir": tmp_path / "app",
        "auth_enabled": True,
        "port": 8000,
        "linux": lambda: True,
        "python": "/usr/bin/python3",
        "unit_path": unit,
        "assistant_status": reachable,
        "remote_status": remote_off,
        "remote_setup": remote_connect,
    }
    values.update(overrides)
    return auto_setup.Deps(**values)


def states(result: dict) -> dict[str, str]:
    return {item["id"]: item["state"] for item in result["items"]}


async def test_plan_lists_everything_the_system_can_do(tmp_path):
    result = await auto_setup.plan(deps(tmp_path))

    assert states(result) == {"guard": "todo", "assistant": "todo", "remote": "todo"}
    assert result["todo"] == 3


async def test_plan_changes_nothing(tmp_path):
    d = deps(tmp_path)
    await auto_setup.plan(d)

    assert d.unit_path.read_text(encoding="utf-8") == UNIT_WITHOUT_GUARD
    assert assistant_config.read(tmp_path)["enabled"] is False


async def test_run_sets_up_guard_assistant_and_remote(tmp_path):
    d = deps(tmp_path)

    result = await auto_setup.run(d)

    assert states(result) == {"guard": "changed", "assistant": "changed", "remote": "changed"}
    assert "update_guard.py" in d.unit_path.read_text(encoding="utf-8")
    assert assistant_config.read(tmp_path)["enabled"] is True
    assert result["changed"] == 3


async def test_second_run_finds_nothing_left(tmp_path):
    d = deps(tmp_path)
    await auto_setup.run(d)

    async def remote_on():
        return {"state": "connected", "serving": True}

    d.remote_status = remote_on
    result = await auto_setup.run(d)

    assert states(result) == {"guard": "done", "assistant": "done", "remote": "done"}
    assert result["changed"] == 0


async def test_without_systemd_unit_the_guard_is_manual(tmp_path):
    d = deps(tmp_path, unit_path=tmp_path / "missing.service")

    assert states(await auto_setup.plan(d))["guard"] == "manual"


async def test_not_linux_leaves_guard_and_remote_to_the_user(tmp_path):
    result = states(await auto_setup.plan(deps(tmp_path, linux=lambda: False)))

    assert result["guard"] == "manual"
    assert result["remote"] == "manual"


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        ({"reachable": False}, "no_server"),
        ({"reachable": True, "model_present": False}, "no_model"),
    ],
)
async def test_assistant_needs_a_server_with_the_model(tmp_path, status, detail):
    async def probe(_config):
        return status

    item = next(
        i for i in (await auto_setup.plan(deps(tmp_path, assistant_status=probe)))["items"] if i["id"] == "assistant"
    )

    assert (item["state"], item["detail"]) == ("manual", detail)


async def test_remote_access_needs_the_login(tmp_path):
    d = deps(tmp_path, auth_enabled=False)

    item = next(i for i in (await auto_setup.plan(d))["items"] if i["id"] == "remote")

    assert (item["state"], item["detail"]) == ("manual", "needs_auth")


async def test_remote_login_link_is_handed_to_the_user(tmp_path):
    async def waiting(_port):
        return {"state": "needs_login", "login_url": "https://login.tailscale.com/a/abc"}

    result = await auto_setup.run(deps(tmp_path, remote_setup=waiting), only=["remote"])

    remote = next(i for i in result["items"] if i["id"] == "remote")
    assert (remote["state"], remote["detail"]) == ("needs_user", "https://login.tailscale.com/a/abc")


async def test_only_runs_the_requested_steps(tmp_path):
    d = deps(tmp_path)

    result = await auto_setup.run(d, only=["assistant"])

    assert states(result) == {"guard": "todo", "assistant": "changed", "remote": "todo"}
    assert d.unit_path.read_text(encoding="utf-8") == UNIT_WITHOUT_GUARD


async def test_a_failing_step_does_not_stop_the_others(tmp_path):
    async def broken(_port):
        raise RuntimeError("Tailscale nicht erreichbar")

    result = await auto_setup.run(deps(tmp_path, remote_setup=broken))

    assert states(result) == {"guard": "changed", "assistant": "changed", "remote": "failed"}
    assert next(i for i in result["items"] if i["id"] == "remote")["detail"] == "RuntimeError"


async def test_failure_detail_never_carries_the_message(tmp_path):
    async def broken(_port):
        raise RuntimeError("geheimer Token tskey-123")

    result = await auto_setup.run(deps(tmp_path, remote_setup=broken), only=["remote"])

    assert "tskey" not in str(result)
