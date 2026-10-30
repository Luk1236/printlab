"""Tests for the auto plate change refinements: persisted queue gate, cancel, low-supply warning."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.app.services import auto_plate_change, hardware_extension


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    cfg = tmp_path / "hardware.json"
    monkeypatch.setattr(hardware_extension, "CONFIG_PATH", cfg)
    monkeypatch.setattr(
        auto_plate_change,
        "_config_path",
        lambda printer_id=None: cfg if printer_id is None else tmp_path / f"hardware_{printer_id}.json",
    )
    from backend.app.services import audit_log

    monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit_log.jsonl")

    async def _no_notify(printer_id, entry):
        return None

    monkeypatch.setattr(auto_plate_change, "_notify", _no_notify)
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
    monkeypatch.setattr("backend.app.services.hardware_extension.get_hardware", lambda *a, **k: hw)


class FakeHardware:
    def __init__(self, supply=1, door_ok=True, door_note="Endschalter: geschlossen"):
        self.supply = supply
        self.changed: list[str] = []
        self.door_ok = door_ok
        self.door_note = door_note
        self.door_checks = 0

    def status(self):
        return {"door": "closed", "busy": False, "supply_ready": self.supply, "storage_empty": 3}

    def verify_door_closed(self):
        self.door_checks += 1
        return self.door_ok, self.door_note

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
        monkeypatch.setattr(auto_plate_change, "read_config", lambda printer_id=None: cfg)

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


class TestSafetyGuards:
    """Fail-closed: ohne belegte Betttemperatur oder bestätigte Tür wird nicht bewegt."""

    @pytest.mark.parametrize("temperatures", [None, {}, {"nozzle": 200.0}, {"bed_temp": None}])
    def test_missing_bed_temperature_aborts(self, monkeypatch, temperatures):
        state = SimpleNamespace(connected=True, state="FINISH", temperatures=temperatures)
        hw = FakeHardware()
        _patch_runtime(monkeypatch, state, hw)
        cfg = dict(auto_plate_change.DEFAULTS, enabled=True, notify=False)
        asyncio.run(auto_plate_change._run_change(1, "job", cfg))
        last = auto_plate_change.last_run(1)
        assert last["ok"] is False
        assert "Betttemperatur unbekannt" in last["message"]
        assert hw.changed == []

    def test_open_door_aborts_before_any_movement(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="FINISH", temperatures={"bed_temp": 30.0})
        hw = FakeHardware(door_ok=False, door_note="Endschalter meldet open")
        _patch_runtime(monkeypatch, state, hw)
        cfg = dict(auto_plate_change.DEFAULTS, enabled=True, notify=False)
        asyncio.run(auto_plate_change._run_change(1, "job", cfg))
        last = auto_plate_change.last_run(1)
        assert last["ok"] is False
        assert "Tür" in last["message"] and "open" in last["message"]
        assert hw.changed == []

    def test_door_is_checked_fresh_once(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="FINISH", temperatures={"bed_temp": 30.0})
        hw = FakeHardware(supply=3, door_note="ohne Endschalter")
        _patch_runtime(monkeypatch, state, hw)
        cfg = dict(auto_plate_change.DEFAULTS, enabled=True, notify=False)
        asyncio.run(auto_plate_change._run_change(1, "job", cfg))
        assert hw.door_checks == 1
        assert "ohne Endschalter" in auto_plate_change.last_run(1)["message"]


class TestPerPrinterConfig:
    """Seit F5 gilt die Plattenwechsel-Automatik je Drucker, nicht mehr global."""

    def test_settings_of_one_printer_leave_the_other_alone(self):
        auto_plate_change.write_config({"enabled": True, "cooldown_bed_temp": 55.0}, printer_id=1)
        assert auto_plate_change.read_config(1)["enabled"] is True
        assert auto_plate_change.read_config(1)["cooldown_bed_temp"] == 55.0
        assert auto_plate_change.read_config(2)["enabled"] is False
        assert auto_plate_change.read_config(2)["cooldown_bed_temp"] == auto_plate_change.DEFAULTS["cooldown_bed_temp"]

    def test_legacy_global_setting_is_used_until_the_printer_has_its_own(self):
        auto_plate_change.write_config({"cooldown_bed_temp": 50.0})  # global, wie bis v1.16
        assert auto_plate_change.read_config(3)["cooldown_bed_temp"] == 50.0
        auto_plate_change.write_config({"cooldown_bed_temp": 40.0}, printer_id=3)
        assert auto_plate_change.read_config(3)["cooldown_bed_temp"] == 40.0
        assert auto_plate_change.read_config(4)["cooldown_bed_temp"] == 50.0  # global unverändert

    def test_per_printer_write_keeps_the_hardware_commands_of_that_printer(self, tmp_path):
        path = tmp_path / "hardware_7.json"
        path.write_text('{"mode": "command", "door_open_command": "tool.exe"}', encoding="utf-8")
        auto_plate_change.write_config({"enabled": True}, printer_id=7)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["mode"] == "command"
        assert saved["door_open_command"] == "tool.exe"
        assert saved["auto_plate_change"]["enabled"] is True


class TestWriteValidation:
    def test_invalid_numbers_are_ignored_and_do_not_reset_the_config(self):
        auto_plate_change.write_config({"enabled": True, "cooldown_bed_temp": 38.0})
        cfg = auto_plate_change.write_config({"cooldown_bed_temp": "heiß", "poll_seconds": None})
        assert cfg["enabled"] is True
        assert cfg["cooldown_bed_temp"] == 38.0

    def test_numeric_strings_are_coerced(self):
        cfg = auto_plate_change.write_config({"max_wait_seconds": "600"})
        assert cfg["max_wait_seconds"] == 600


class TestQueueProbe:
    def test_non_sqlite_database_is_not_probed(self, monkeypatch, tmp_path):
        from backend.app.services import hardware_extension

        monkeypatch.setattr(
            hardware_extension.settings, "database_url", "postgresql+asyncpg://u:p@host/db", raising=False
        )
        monkeypatch.chdir(tmp_path)
        assert auto_plate_change._has_pending_queue_item(1) is None
        assert list(tmp_path.iterdir()) == []


class TestAuditAndNotify:
    def _run(self, monkeypatch, state, hw, **cfg_over):
        sent = []

        async def fake_notify(printer_id, entry):
            sent.append(entry)

        monkeypatch.setattr(auto_plate_change, "_notify", fake_notify)
        _patch_runtime(monkeypatch, state, hw)
        cfg = dict(auto_plate_change.DEFAULTS, enabled=True, **cfg_over)
        asyncio.run(auto_plate_change._run_change(1, "job", cfg))
        return sent

    def test_result_is_written_to_the_audit_log_and_survives_a_restart(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="FINISH", temperatures={"bed_temp": 30.0})
        self._run(monkeypatch, state, FakeHardware(supply=3))
        auto_plate_change._LAST.clear()  # wie nach einem Neustart
        restored = auto_plate_change.last_run(1)
        assert restored["ok"] is True
        assert restored["job"] == "job"

    def test_failure_is_notified(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="RUNNING", temperatures={"bed_temp": 80.0})
        sent = self._run(monkeypatch, state, FakeHardware())
        assert len(sent) == 1 and sent[0]["ok"] is False

    def test_low_supply_warning_is_notified_even_on_success(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="FINISH", temperatures={"bed_temp": 30.0})
        sent = self._run(monkeypatch, state, FakeHardware(supply=1))
        assert len(sent) == 1 and sent[0]["ok"] is True and "warning" in sent[0]

    def test_clean_success_is_silent(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="FINISH", temperatures={"bed_temp": 30.0})
        assert self._run(monkeypatch, state, FakeHardware(supply=3)) == []

    def test_notify_can_be_switched_off(self, monkeypatch):
        state = SimpleNamespace(connected=True, state="RUNNING", temperatures={"bed_temp": 80.0})
        assert self._run(monkeypatch, state, FakeHardware(), notify=False) == []


class TestAutoConfirmPlateClear:
    """Fail-closed: only a confident 'empty' from the camera may lift the plate-clear gate."""

    def _setup(self, monkeypatch, result, awaiting=True, printer=True):
        gate = {"awaiting": awaiting}
        pm = SimpleNamespace(
            is_awaiting_plate_clear=lambda pid: gate["awaiting"],
            set_awaiting_plate_clear=lambda pid, value: gate.update(awaiting=value),
        )
        monkeypatch.setattr("backend.app.services.printer_manager.printer_manager", pm)

        async def fake_check(**kwargs):
            if isinstance(result, Exception):
                raise result
            return result

        fake_printer = SimpleNamespace(
            ip_address="1.2.3.4",
            access_code="x",
            model="P2S",
            external_camera_url=None,
            external_camera_type=None,
            external_camera_enabled=False,
            external_camera_snapshot_url=None,
        )

        async def fake_load(pid):
            return fake_printer if printer else None

        monkeypatch.setattr(auto_plate_change, "_load_printer", fake_load)
        return gate, fake_check

    def _result(self, **kw):
        base = {"is_empty": True, "confidence": 0.9, "needs_calibration": False}
        base.update(kw)
        return SimpleNamespace(**base)

    def test_confident_empty_bed_confirms(self, monkeypatch):
        gate, fake_check = self._setup(monkeypatch, self._result())
        ok, note = asyncio.run(auto_plate_change._confirm_plate_clear(1, 0.6, plate_check=fake_check))
        assert ok and "90%" in note, note
        assert gate["awaiting"] is False

    @pytest.mark.parametrize(
        "result",
        [
            SimpleNamespace(is_empty=False, confidence=0.95, needs_calibration=False),
            SimpleNamespace(is_empty=True, confidence=0.3, needs_calibration=False),
            SimpleNamespace(is_empty=True, confidence=0.0, needs_calibration=False),  # Kamera/OpenCV-Fehler
            SimpleNamespace(is_empty=True, confidence=0.9, needs_calibration=True),
            RuntimeError("camera down"),
        ],
    )
    def test_anything_doubtful_keeps_the_gate(self, monkeypatch, result):
        gate, fake_check = self._setup(monkeypatch, result)
        ok, note = asyncio.run(auto_plate_change._confirm_plate_clear(1, 0.6, plate_check=fake_check))
        assert not ok and "von Hand" in note
        assert gate["awaiting"] is True

    def test_unknown_printer_keeps_the_gate(self, monkeypatch):
        gate, fake_check = self._setup(monkeypatch, self._result(), printer=False)
        assert not asyncio.run(auto_plate_change._confirm_plate_clear(1, 0.6, plate_check=fake_check))[0]
        assert gate["awaiting"] is True

    def test_off_by_default_and_wired_into_the_run(self, monkeypatch):
        assert auto_plate_change.DEFAULTS["auto_confirm_plate_clear"] is False
        calls = []

        async def fake_confirm(pid, minc):
            calls.append(pid)
            return True, "Platte frei automatisch bestätigt."

        monkeypatch.setattr(auto_plate_change, "_confirm_plate_clear", fake_confirm)
        state = SimpleNamespace(connected=True, state="FINISH", temperatures={"bed_temp": 30.0})
        _patch_runtime(monkeypatch, state, FakeHardware(supply=3))
        asyncio.run(auto_plate_change._run_change(1, "job", dict(auto_plate_change.DEFAULTS)))
        assert calls == []
        asyncio.run(
            auto_plate_change._run_change(1, "job", dict(auto_plate_change.DEFAULTS, auto_confirm_plate_clear=True))
        )
        assert calls == [1]
        assert "automatisch bestätigt" in auto_plate_change.last_run(1)["message"]
