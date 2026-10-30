"""Laufende lokale Fehlerüberwachung: Bestätigung, Aktion und Grenzen."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services import local_ai_watch


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(local_ai_watch, "CONFIG_PATH", tmp_path / "watch.json")
    monkeypatch.setattr(local_ai_watch, "_printer_state", {})
    monkeypatch.setattr(local_ai_watch, "_run_lock", asyncio.Lock())
    monkeypatch.setattr(local_ai_watch.assistant_config, "read", lambda _dir: {"vision_model": "vision"})
    local_ai_watch.save_config({"enabled": True, "min_consecutive": 2, "cooldown_minutes": 30})


def _printer_manager(state="RUNNING"):
    manager = MagicMock()
    manager.get_all_statuses.return_value = {7: SimpleNamespace(state=state, gcode_file="job.3mf")}
    manager.is_connected.return_value = True
    client = MagicMock()
    client.pause_print.return_value = True
    manager.get_client.return_value = client
    manager.get_printer.return_value = SimpleNamespace(name="X1C")
    return manager, client


def _run_check(result):
    manager, client = _printer_manager()
    with (
        patch("backend.app.services.printer_manager.printer_manager", manager),
        patch("backend.app.services.obico_detection.capture_frame_for_printer", AsyncMock(return_value=b"frame")),
        patch.object(local_ai_watch.ai_error_scan, "classify", AsyncMock(return_value=result)),
        patch.object(local_ai_watch.failure_images, "save_failure_image", return_value="fail.jpg"),
        patch.object(local_ai_watch.ai_error_scan, "record") as record,
        patch.object(local_ai_watch.ai_error_scan, "announce_finding", AsyncMock()) as announce,
        patch.object(local_ai_watch, "_pause", AsyncMock(return_value=True)) as pause,
    ):
        out = asyncio.run(local_ai_watch.check_once())
    return out, record, announce, pause, manager, client


STRINGING = {"pattern_id": "stringing", "confidence": 0.9, "reason": "Fäden", "model": "vision"}


class TestWatch:
    def test_needs_two_consecutive_detections_before_acting(self):
        first, record, announce, _pause, _m, _c = _run_check(STRINGING)
        assert first[0]["action"] is None and record.call_count == 0
        second, record, announce, _pause, _m, _c = _run_check(STRINGING)
        assert second[0]["action"] == "notify"
        record.assert_called_once()
        assert record.call_args.kwargs["source"] == "watch" and record.call_args.kwargs["image_name"] == "fail.jpg"
        announce.assert_awaited_once()

    def test_a_different_pattern_restarts_the_count(self):
        _run_check(STRINGING)
        out, record, _announce, _pause, _m, _c = _run_check(
            {"pattern_id": "warping", "confidence": 0.9, "reason": "", "model": "vision"}
        )
        assert out[0]["action"] is None and record.call_count == 0

    def test_low_confidence_does_not_count(self):
        out, record, _announce, _pause, _m, _c = _run_check(
            {"pattern_id": "stringing", "confidence": 0.2, "reason": "", "model": "vision"}
        )
        assert out[0]["action"] is None and record.call_count == 0

    def test_pause_action_pauses_the_print(self):
        local_ai_watch.save_config({"action": "pause", "min_consecutive": 1})
        out, _record, _announce, pause, _m, _c = _run_check(STRINGING)
        assert out[0]["action"] == "pause"
        pause.assert_awaited()

    def test_not_running_resets_the_state(self):
        _run_check(STRINGING)
        assert 7 in local_ai_watch._printer_state
        manager, _client = _printer_manager(state="IDLE")
        with (
            patch("backend.app.services.printer_manager.printer_manager", manager),
            patch.object(local_ai_watch.ai_error_scan, "classify", AsyncMock()),
        ):
            asyncio.run(local_ai_watch.check_once())
        assert 7 not in local_ai_watch._printer_state

    def test_missing_frame_is_reported_without_raising(self):
        manager, _client = _printer_manager()
        with (
            patch("backend.app.services.printer_manager.printer_manager", manager),
            patch("backend.app.services.obico_detection.capture_frame_for_printer", AsyncMock(return_value=None)),
        ):
            out = asyncio.run(local_ai_watch.check_once())
        assert out[0]["error"] == "Kein Kamerabild erhalten."


class TestConfig:
    def test_values_are_clamped_and_actions_validated(self):
        config = local_ai_watch.save_config(
            {"interval_seconds": 1, "min_confidence": 500, "min_consecutive": 99, "cooldown_minutes": 99999}
        )
        assert config["interval_seconds"] == local_ai_watch.MIN_INTERVAL
        assert config["min_confidence"] == 100
        assert config["min_consecutive"] == 10
        assert config["cooldown_minutes"] == 1440
        with pytest.raises(ValueError):
            local_ai_watch.save_config({"action": "shutdown"})

    def test_printer_list_is_deduplicated(self):
        config = local_ai_watch.save_config({"printers": [3, 3, 1]})
        assert config["printers"] == [1, 3]
