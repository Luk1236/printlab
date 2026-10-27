"""Hardware commands run as shell commands on the server, so they may only be edited with auth enabled."""

import pytest
from httpx import AsyncClient

from backend.app.services import audit_log, hardware_extension


@pytest.fixture
def isolated_hardware(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware_extension, "CONFIG_PATH", tmp_path / "hardware.json")
    monkeypatch.setattr(hardware_extension, "MAGAZINE_PATH", tmp_path / "magazine.json")
    monkeypatch.setattr(hardware_extension, "_per_printer", {})
    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")
    return hardware_extension.get_hardware


class TestCommandConfigGuard:
    @pytest.mark.asyncio
    async def test_commands_are_refused_without_auth(self, async_client: AsyncClient, printer_factory, isolated_hardware):
        printer = await printer_factory(name="P2S")
        resp = await async_client.put(
            f"/api/v1/printers/{printer.id}/hardware/config",
            json={"mode": "command", "door_open_command": "calc.exe"},
        )
        assert resp.status_code == 403
        assert "Anmeldung" in resp.json()["detail"]
        assert isolated_hardware(printer.id).config()["door_open_command"] == ""

    @pytest.mark.asyncio
    async def test_non_command_settings_still_work_without_auth(
        self, async_client: AsyncClient, printer_factory, isolated_hardware
    ):
        printer = await printer_factory(name="P2S")
        resp = await async_client.put(
            f"/api/v1/printers/{printer.id}/hardware/config",
            json={"timeout_seconds": 20},
        )
        assert resp.status_code == 200
        assert isolated_hardware(printer.id).config()["timeout_seconds"] == 20.0
