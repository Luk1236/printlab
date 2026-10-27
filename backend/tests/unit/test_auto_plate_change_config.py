"""Unit tests for the automatic plate change after print completion.

Covers the configuration round-trip, the enabled-gate on ``schedule`` and the
offline-skip path of the runnable with stubbed printer manager and hardware.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.app.services import auto_plate_change
from backend.app.services import hardware_extension


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point both the hardware config and the automation at a temp dir."""
    cfg = tmp_path / "hardware.json"
    monkeypatch.setattr(hardware_extension, "CONFIG_PATH", cfg)
    monkeypatch.setattr(auto_plate_change, "_config_path", lambda: cfg)
    return cfg


class TestConfig:
    def test_defaults_are_off(self):
        cfg = auto_plate_change.read_config()
        assert cfg["enabled"] is False
        assert cfg["cooldown_bed_temp"] > 0
        assert cfg["max_wait_seconds"] > 0
        assert cfg["poll_seconds"] >= 1
        assert cfg["skip_if_offline"] is True

    def test_read_returns_defaults_for_corrupt_file(self, isolated_config):
        isolated_config.write_text("not json", encoding="utf-8")
        assert auto_plate_change.read_config()["enabled"] is False

    def test_write_roundtrip_and_unknown_keys_ignored(self, isolated_config):
        # Pre-seed the hardware config so we can prove unrelated keys survive.
        isolated_config.write_text(
            json.dumps({"mode": "command", "door_open_command": "C:\\tool.exe"}),
            encoding="utf-8",
        )
        cfg = auto_plate_change.write_config(
            {"enabled": True, "cooldown_bed_temp": 40.5, "bogus": "x"}
        )
        assert cfg["enabled"] is True
        assert cfg["cooldown_bed_temp"] == 40.5
        assert "bogus" not in cfg
        # Second read must see the stored values, not the defaults.
        again = auto_plate_change.read_config()
        assert again["enabled"] is True
        assert again["cooldown_bed_temp"] == 40.5
        # The hardware section of the same file must remain untouched.
        on_disk = json.loads(isolated_config.read_text(encoding="utf-8"))
        assert on_disk["mode"] == "command"
        assert on_disk["door_open_command"] == "C:\\tool.exe"
        assert on_disk["auto_plate_change"]["enabled"] is True


class TestScheduleGate:
    def test_schedule_is_a_noop_when_disabled(self, monkeypatch):
        monkeypatch.setattr(
            auto_plate_change, "read_config", lambda: dict(auto_plate_change.DEFAULTS)
        )
        assert auto_plate_change.schedule(1, "job") is False
        assert 1 not in auto_plate_change._TASKS

    def test_schedule_creates_task_when_enabled(self, monkeypatch):
        pending: list[str] = []

        async def fake_run(printer_id, job_name, cfg):
            pending.append(job_name)

        monkeypatch.setattr(auto_plate_change, "_run_change", fake_run)
        monkeypatch.setattr(
            auto_plate_change, "read_config", lambda: dict(auto_plate_change.DEFAULTS, enabled=True)
        )

        async def main():
            assert auto_plate_change.schedule(1, "Wartung") is True
            task = auto_plate_change._TASKS.get(1)
            assert task is not None
            await task

        asyncio.run(main())
        assert pending == ["Wartung"]


class TestOfflineSkip:
    def test_offline_printer_never_touches_hardware(self, monkeypatch):
        offline = SimpleNamespace(connected=False)

        class FakeManager:
            def get_status(self, printer_id):
                return offline

        class ExplodeHardware:
            def change_plate(self, job_name=""):
                raise AssertionError("change_plate must not run when offline")

        monkeypatch.setattr(
            auto_plate_change, "read_config", lambda: dict(auto_plate_change.DEFAULTS, enabled=True)
        )
        monkeypatch.setattr(
            "backend.app.services.printer_manager.printer_manager", FakeManager()
        )
        monkeypatch.setattr(
            "backend.app.services.hardware_extension.get_hardware", lambda: ExplodeHardware()
        )
        cfg = dict(auto_plate_change.DEFAULTS, enabled=True, max_wait_seconds=10, poll_seconds=1)

        asyncio.run(auto_plate_change._run_change(1, "job", cfg))
        # The skip is recorded for the status endpoint.
        assert auto_plate_change.last_run(1)["ok"] is False
        assert "getrennt" in auto_plate_change.last_run(1)["message"]