"""Unit-Tests für die Absturz-Erkennung und Diagnose (crash_diagnostics)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from backend.app.services.crash_diagnostics import (
    CAUSE_KERNEL_PANIC,
    CAUSE_OOM,
    CAUSE_POWER_LOSS,
    CAUSE_THERMAL,
    CAUSE_UNDERVOLTAGE,
    CAUSE_WATCHDOG,
    check_and_generate_crash_report,
    determine_cause_from_logs,
    dismiss_report,
    get_last_report,
    record_clean_shutdown,
    record_heartbeat,
)


def test_determine_cause_undervoltage():
    cause, title, explanation, recs = determine_cause_from_logs(
        logs=["system running fine"],
        throttled_flags=["Unterspannung seit dem Systemstart aufgetreten"],
    )
    assert cause == CAUSE_UNDERVOLTAGE
    assert "Unterspannung" in title
    assert len(recs) >= 2


def test_determine_cause_oom():
    logs = [
        "app invoked oom-killer: gfp_mask=0x100cca",
        "Out of memory: Killed process 1234 (python)",
    ]
    cause, title, explanation, recs = determine_cause_from_logs(logs, [])
    assert cause == CAUSE_OOM
    assert "Arbeitsspeicher" in title
    assert any("Swap" in r for r in recs)


def test_determine_cause_thermal():
    cause, title, explanation, recs = determine_cause_from_logs(
        ["thermal shutdown triggered"],
        ["Temperaturgrenze seit dem Systemstart erreicht"],
    )
    assert cause == CAUSE_THERMAL
    assert "Überhitzung" in title


def test_determine_cause_kernel_panic():
    logs = ["Kernel panic - not syncing: Fatal exception in interrupt", "Rebooting in 10 seconds..."]
    cause, title, explanation, recs = determine_cause_from_logs(logs, [])
    assert cause == CAUSE_KERNEL_PANIC
    assert "Kernel-Panic" in title


def test_determine_cause_watchdog():
    logs = ["Hardware watchdog: ping timeout, resetting system now"]
    cause, title, explanation, recs = determine_cause_from_logs(logs, [])
    assert cause == CAUSE_WATCHDOG
    assert "Watchdog" in title


def test_determine_cause_power_loss_fallback():
    cause, title, explanation, recs = determine_cause_from_logs(["normal line 1", "normal line 2"], [])
    assert cause == CAUSE_POWER_LOSS
    assert "Stromausfall" in title


def test_clean_shutdown_does_not_trigger_crash_report(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    with patch("backend.app.services.crash_diagnostics.get_system_boot_id", return_value="boot-1"):
        record_heartbeat(tmp_path)
        record_clean_shutdown(tmp_path)

    with patch("backend.app.services.crash_diagnostics.get_system_boot_id", return_value="boot-2"):
        report = check_and_generate_crash_report(tmp_path)
        assert report is None


def test_unclean_reboot_generates_and_dismisses_crash_report(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    # 1. Simuliere laufenden Boot 1, der abstürzt (ohne record_clean_shutdown)
    with patch("backend.app.services.crash_diagnostics.get_system_boot_id", return_value="boot-crash"):
        record_heartbeat(tmp_path)

    # 2. Boot 2 startet nach Absturz
    with (
        patch("backend.app.services.crash_diagnostics.get_system_boot_id", return_value="boot-recovered"),
        patch(
            "backend.app.services.crash_diagnostics.check_undervoltage_flags",
            return_value=(True, ["Unterspannung seit dem Systemstart aufgetreten"]),
        ),
        patch(
            "backend.app.services.crash_diagnostics.read_previous_boot_logs", return_value=["Kernel crash log line 1"]
        ),
    ):
        report = check_and_generate_crash_report(tmp_path)
        assert report is not None
        assert report["cause"] == CAUSE_UNDERVOLTAGE
        assert report["dismissed"] is False

        # Report abfragen
        fetched = get_last_report(tmp_path)
        assert fetched is not None
        assert fetched["cause"] == CAUSE_UNDERVOLTAGE

        # Report verwerfen (dismiss)
        dismiss_report(tmp_path)
        dismissed_report = get_last_report(tmp_path)
        assert dismissed_report is not None
        assert dismissed_report["dismissed"] is True
