"""Tests for the auto plate change refinements: persisted queue gate, cancel, low-supply warning."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.app.services import auto_plate_change, hardware_extension


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    cfg = tmp_path / "hardware.json"
    monkeypatch.setattr(hardware_extension, "CONFIG_PATH", cfg)
    monkeypatch.setattr(auto_plate_change, "_config_path", lambda: cfg)
    monkeypatch.setattr(auto_plate_change, "_broadcast", lambda payload: None)
    auto_plate_change._TASKS.clear()
    auto_plate_change._LAST.clear()
    return cfg


class TestConfigPersistence:
    def test_only_with_queue_and_low_supply_are_saved(self):
        cfg = auto_plate_change.write_config({"only_with_queue": True, "low_supply_warning": 2})
        assert cfg["only_with_queue"] is True
        assert cfg["low_supply_warning"] == 2
        again = auto_plate_change.read_config()
        assert again["only_with_queue"] is True
        assert again["low_supply_warning"] == 2

    def test_boolean_keys_are_coerced(self):
        cfg = auto_plate_change.write_config({"only_with_queue": "", "skip_if_offline": 0})
        assert cfg["only_with_queue"] is False
        assert cfg["skip_if_offline"] is False

    def test_negative_low_supply_is_clamped(self):
        cfg = auto_plate_change.write_config({"low_supply_warning": -3})
        assert cfg["low_supply_warning"] == 0


class TestLowSupplyWarning:
    cfg = {"low_supply_warning": 1}

    def test_no_warning_when_magazine_is_full(self):
        assert auto_plate_change._low_supply_warning({"supply_ready": 3, "storage_empty": 3}, self.cfg) is None

    def test_warns_when_one_fresh_plate_is_left(self):
        text = auto_plate_change._low_supply_warning({"supply_ready": 1, "storage_empty": 3}, self.cfg)
        assert "frische Platte" in text

    def test_warns_when_storage_is_full(self):
        text = auto_plate_change._low_supply_warning({"supply_ready": 3, "storage_empty": 0}, self.cfg)
        assert "Ablagefach" in text

    def test_threshold_zero_only_warns_on_empty(self):
        cfg = {"low_supply_warning": 0}
        assert auto_plate_change._low_supply_warning({"supply_ready": 1, "storage_empty": 1}, cfg) is None
        assert auto_plate_change._low_supply_warning({"supply_ready": 0, "storage_empty": 1}, cfg)


def _patch_runtime(monkeypatch, state, hw):
    monkeypatch.setattr(
        "backend.app.services.printer_manager.printer_manager",
        SimpleNamespace(get_status=lambda pid: state),
    )
    monkeypatch.setattr("backend.app.services.hardware_extension.get_hardware", lambda: hw)


class FakeHardware:
    def __init__(self, supply=1):
        self.supply = supply
        self.changed: list[str] = []

    def status(self):
        return {"door": "closed", "busy": False, "supply_ready": self.supply, "storage_empty": 3}

    def change_plate(self, job):
        self.changed.append(job)
        self.supply -= 1
        return True, "ok"


class TestRunChange:
    def test_success_with_low_supply_records_warning(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="FINISH", temperatures={"bed_temp": 30.0})
        hw = FakeHardware(supply=1)
        _patch_runtime(monkeypatch, state, hw)
        cfg = dict(auto_plate_change.DEFAULTS, enabled=True, low_supply_warning=1)
        asyncio.run(auto_plate_change._run_change(1, "job", cfg))
        last = auto_plate_change.last_run(1)
        assert last["ok"] is True
        assert "frische Platte" in last["warning"]
        assert hw.changed == ["job"]

    def test_new_print_aborts_wait_without_change(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="RUNNING", temperatures={"bed_temp": 80.0})
        hw = FakeHardware()
        _patch_runtime(monkeypatch, state, hw)
        cfg = dict(auto_plate_change.DEFAULTS, enabled=True)
        asyncio.run(auto_plate_change._run_change(1, "job", cfg))
        last = auto_plate_change.last_run(1)
        assert last["ok"] is False
        assert "Neuer Druck" in last["message"]
        assert hw.changed == []

    def test_cancel_during_cooldown_wait(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="FINISH", temperatures={"bed_temp": 90.0})
        hw = FakeHardware()
        _patch_runtime(monkeypatch, state, hw)
        cfg = dict(auto_plate_change.DEFAULTS, enabled=True, poll_seconds=1, max_wait_seconds=60)
        monkeypatch.setattr(auto_plate_change, "read_config", lambda: cfg)

        async def main():
            assert auto_plate_change.schedule(4, "job") is True
            await asyncio.sleep(0.05)
            assert auto_plate_change.cancel(4, reason="test") == 1
            with pytest.raises(asyncio.CancelledError):
                await auto_plate_change._TASKS[4]

        asyncio.run(main())
        last = auto_plate_change.last_run(4)
        assert last["ok"] is False
        assert "abgebrochen" in last["message"]
        assert hw.changed == []

    def test_cancel_ignores_other_printers_and_finished_tasks(self):
        assert auto_plate_change.cancel(99) == 0
        assert auto_plate_change.cancel() == 0
