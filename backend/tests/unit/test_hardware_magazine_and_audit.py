"""Unit tests for magazine slot editing, hardware config update and the audit log."""

import json

import pytest

from backend.app.services import audit_log
from backend.app.services.hardware_extension import HardwareExtension


@pytest.fixture()
def extension(tmp_path):
    """Fresh extension writing into a temp dir (simulated mode)."""
    return HardwareExtension(config_path=tmp_path / "hardware.json", magazine_path=tmp_path / "magazine.json")


class TestEditSlots:
    def test_set_label_and_status(self, extension):
        ok, msg = extension.edit_slots([{"id": 1, "label": "PEI Neu"}, {"id": 4, "status": "occupied"}])
        assert ok, msg
        slots = {s["id"]: s for s in extension.status()["slots"]}
        assert slots[1]["label"] == "PEI Neu"
        assert slots[4]["status"] == "occupied"
        # Supply stays "ready" unless edited; plate state untouched.
        assert slots[2]["status"] == "ready"

    def test_rejects_unknown_slot_and_status(self, extension):
        ok, _ = extension.edit_slots([{"id": 99, "status": "ready"}])
        assert ok is False
        ok, msg = extension.edit_slots([{"id": 2, "status": "bogus"}])
        assert ok is False
        assert "Unbekannter Status" in msg

    def test_clearing_occupied_removes_print_marker(self, extension):
        extension.edit_slots([{"id": 5, "status": "occupied"}])
        extension.edit_slots([{"id": 5, "status": "empty"}])
        slots = {s["id"]: s for s in extension.status()["slots"]}
        assert slots[5]["status"] == "empty"
        assert "print" not in slots[5]

    def test_magazine_survives_reload(self, extension, tmp_path):
        extension.edit_slots([{"id": 3, "label": "PEI C", "status": "used"}])
        reloaded = HardwareExtension(config_path=tmp_path / "hardware.json", magazine_path=tmp_path / "magazine.json")
        slots = {s["id"]: s for s in reloaded.status()["slots"]}
        assert slots[3]["status"] == "used"


class TestConfig:
    def test_update_known_keys_only(self, extension):
        ok, msg = extension.update_config({"mode": "command", "door_open_command": "tool.exe", "bogus": 1})
        assert ok is False
        ok, msg = extension.update_config({"mode": "command", "door_open_command": "tool.exe"})
        assert ok, msg
        cfg = extension.config()
        assert cfg["mode"] == "command"
        assert cfg["door_open_command"] == "tool.exe"
        # Persisted: a fresh instance reads the same values.
        assert HardwareExtension(config_path=extension.config_path).config()["mode"] == "command"

    def test_rejects_bad_mode_and_timeout(self, extension):
        assert extension.update_config({"mode": "nonsense"})[0] is False
        assert extension.update_config({"timeout_seconds": "x"})[0] is False


class TestAuditLog:
    def test_record_and_read_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit.jsonl")
        audit_log.record("door_open", True, "Tür geöffnet.", 1, "lukas")
        audit_log.record("plate_change", False, "Fehler", 2)
        entries = audit_log.entries(limit=10)
        assert [e["action"] for e in entries] == ["plate_change", "door_open"]  # newest first
        assert entries[0]["ok"] is False
        assert entries[1].get("user") == "lukas"

    def test_read_filters_by_printer(self, tmp_path, monkeypatch):
        monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit.jsonl")
        audit_log.record("door_open", True, "a", 1)
        audit_log.record("door_open", True, "b", 2)
        out = audit_log.entries(limit=10, printer_id=2)
        assert [e["message"] for e in out] == ["b"]

    def test_file_is_capped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(audit_log, "LOG_PATH", tmp_path / "audit.jsonl")
        monkeypatch.setattr(audit_log, "MAX_LINES", 5)
        monkeypatch.setattr(audit_log, "_lines_since_trim", 0)
        for i in range(10):
            audit_log.record("tick", True, str(i), 1)
        assert len(audit_log.entries(limit=100)) == 5
        # newest survived (chronological on disk: last line is the newest)
        assert json.loads(audit_log.LOG_PATH.read_text(encoding="utf-8").splitlines()[-1])["message"] == "9"

    def test_record_never_raises(self, tmp_path, monkeypatch):
        # Parent path is a FILE, so creating the log file must fail — and the
        # caller must never see an exception from the logger.
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(audit_log, "LOG_PATH", blocker / "audit.jsonl")
        entry = audit_log.record("test", True, "msg")
        assert entry["ok"] is True


class TestDoorStatus:
    """Der konfigurierte door_status_command wird jetzt wirklich ausgeführt."""

    def test_simulated_reports_state(self, extension):
        ok, msg = extension.open_door()
        assert ok, msg
        ok, msg = extension.check_door_status()
        assert ok, msg
        assert extension.status()["door"] == "open"

    def test_without_command_reports_cached_state(self, extension):
        ok, msg = extension.check_door_status()
        assert ok and "closed" in msg

    def test_command_output_sets_state(self, tmp_path):
        import sys

        extension = HardwareExtension(config_path=tmp_path / "hardware.json", magazine_path=tmp_path / "magazine.json")
        ok, msg = extension.update_config(
            {
                "mode": "command",
                "door_status_command": [sys.executable, "-c", "print('DOOR:OPEN')"],
            }
        )
        assert ok, msg
        ok, msg = extension.check_door_status()
        assert ok, msg
        assert extension.status()["door"] == "open"

    def test_unknown_output_is_reported(self, tmp_path):
        import sys

        extension = HardwareExtension(config_path=tmp_path / "hardware.json", magazine_path=tmp_path / "magazine.json")
        extension.update_config(
            {
                "mode": "command",
                "door_status_command": [sys.executable, "-c", "print('DOOR:UNKNOWN')"],
            }
        )
        ok, msg = extension.check_door_status()
        assert ok, msg
        assert extension.status()["door"] == "unknown"
