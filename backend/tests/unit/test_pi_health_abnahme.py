"""Zustand des Pi (pi_health) und Abnahme-Check (werkzeuge/abnahme.py)."""

import importlib.util
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from backend.app.services import pi_health as ph

MOUNTS = """\
/dev/mmcblk0p2 / ext4 rw 0 0
/dev/mmcblk0p1 /boot/firmware vfat rw 0 0
/dev/sda1 /media/usb ext4 rw 0 0
/dev/nvme0n1p1 /mnt/ssd ext4 rw 0 0
tmpfs /run tmpfs rw 0 0
"""


class TestStorageKind:
    def test_root_on_sd_card(self):
        assert ph.storage_kind("/home/pi/printlab/data", MOUNTS) == {"device": "/dev/mmcblk0p2", "kind": "sd"}

    def test_usb_and_nvme_mounts_win_over_root(self):
        assert ph.storage_kind("/media/usb/printlab", MOUNTS)["kind"] == "usb"
        assert ph.storage_kind("/mnt/ssd/data", MOUNTS)["kind"] == "nvme"

    def test_longest_mount_wins_not_a_prefix_lookalike(self):
        assert ph.storage_kind("/media/usbstick/x", MOUNTS)["kind"] == "sd"  # nicht /media/usb

    def test_unknown_without_mounts(self):
        assert ph.storage_kind("/x", "") is None
        assert ph.storage_kind("/x", "tmpfs /run tmpfs rw 0 0\n") is None


class TestReadings:
    def test_cpu_temperature(self, tmp_path):
        f = tmp_path / "temp"
        f.write_text("61234\n")
        assert ph.cpu_temp_c(str(f)) == 61.2
        assert ph.cpu_temp_c(str(tmp_path / "gibt-es-nicht")) is None
        f.write_text("kaputt")
        assert ph.cpu_temp_c(str(f)) is None

    def test_throttle_flags(self):
        assert ph.decode_throttled(0) == []
        flags = ph.decode_throttled(0x50005)
        assert "Unterspannung (jetzt)" in flags and "gedrosselt seit dem Start" in flags

    def test_memory(self):
        text = "MemTotal: 4000000 kB\nMemAvailable: 100000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"
        assert ph.memory(text) == {"total": 4_096_000_000, "available": 102_400_000, "swap_total": 0, "swap_free": 0}
        assert ph.memory("Unsinn") is None

    def test_missing_system_files_give_none_not_errors(self):
        assert ph.disk("/gibt/es/nicht/xyz") is None


class TestBackups:
    def test_latest_backup_age(self, tmp_path):
        root = tmp_path / "update-backups"
        old, new = root / "a", root / "b"
        old.mkdir(parents=True)
        new.mkdir()
        os.utime(old, (time.time() - 40 * 86400,) * 2)
        os.utime(new, (time.time() - 2 * 86400,) * 2)
        result = ph.latest_backup(tmp_path)
        assert result["path"].endswith("b") and 1.9 < result["age_days"] < 2.1

    def test_extra_folder_counts(self, tmp_path):
        ext = tmp_path / "usb"
        (ext / "x").mkdir(parents=True)
        assert ph.latest_backup(tmp_path / "leer", [ext])["path"].endswith("x")

    def test_none_without_backups(self, tmp_path):
        assert ph.latest_backup(tmp_path) is None


class TestWarnings:
    def base(self, **over):
        info = {
            "cpu_temp_c": 50.0,
            "throttled": {"value": 0, "flags": []},
            "disk": {"total": 64e9, "free": 30e9},
            "storage": {"device": "/dev/nvme0n1p1", "kind": "nvme"},
            "memory": {"total": 4e9, "available": 2e9, "swap_total": 1e9, "swap_free": 1e9},
            "backup": {"path": "x", "age_days": 1.0},
        }
        info.update(over)
        return info

    def test_healthy_system_has_no_warnings(self):
        assert ph.warnings_for(self.base()) == []

    def test_each_problem_is_reported_with_its_level(self):
        info = self.base(
            cpu_temp_c=85.0,
            throttled={"value": 1, "flags": ["Unterspannung (jetzt)"]},
            disk={"total": 64e9, "free": 0.5e9},
            storage={"device": "/dev/mmcblk0p2", "kind": "sd"},
            memory={"total": 4e9, "available": 1e8, "swap_total": 0, "swap_free": 0},
            backup={"path": "x", "age_days": 30.0},
        )
        levels = {w["level"] + ":" + w["text"][:12] for w in ph.warnings_for(info)}
        assert len(ph.warnings_for(info)) == 6
        assert any(w["level"] == "crit" and "Unterspannung" in w["text"] for w in ph.warnings_for(info))
        assert any("SD-Karte" in w["text"] for w in ph.warnings_for(info))
        assert levels

    def test_warm_but_not_critical_and_no_backup(self):
        out = ph.warnings_for(self.base(cpu_temp_c=78.0, backup=None))
        assert [w["level"] for w in out] == ["warn", "warn"]

    def test_unknown_values_are_not_warnings(self):
        info = {
            "cpu_temp_c": None,
            "throttled": None,
            "disk": None,
            "storage": None,
            "memory": None,
            "backup": {"age_days": 1},
        }
        assert ph.warnings_for(info) == []

    def test_snapshot_never_raises(self, tmp_path):
        snap = ph.snapshot(tmp_path)
        assert {"cpu_temp_c", "disk", "storage", "memory", "backup", "warnings"} <= set(snap)


# --- Abnahme-Check ---------------------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve().parents[3] / "werkzeuge" / "abnahme.py"
if not SCRIPT.exists():
    pytest.skip("werkzeuge/ fehlt in dieser Umgebung", allow_module_level=True)
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("abnahme", SCRIPT)
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "HOME", tmp_path)
    monkeypatch.setattr(ab, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(ab, "UNIT", tmp_path / "printlab.service")
    monkeypatch.setattr(ab, "ENV_FILE", tmp_path / "printlab.env")
    (tmp_path / "data").mkdir()
    monkeypatch.delenv("PRINTLAB_BACKUP_TARGET", raising=False)
    return tmp_path


class TestAbnahme:
    def test_service_reachable_or_not(self, monkeypatch):
        monkeypatch.setattr(ab, "get_json", lambda path, timeout=8.0: (200, {"version": "1.6.3"}))
        assert ab.check_service()[0] == ab.OK
        monkeypatch.setattr(ab, "get_json", lambda path, timeout=8.0: (None, None))
        assert ab.check_service()[0] == ab.FAIL

    @pytest.mark.parametrize(
        ("data", "level"),
        [
            ({"auth_enabled": False}, "FAIL"),
            ({"auth_enabled": True, "auth_required": False}, "WARN"),
            ({"auth_enabled": True, "auth_required": True}, "OK"),
        ],
    )
    def test_auth_levels(self, monkeypatch, data, level):
        monkeypatch.setattr(ab, "get_json", lambda path, timeout=8.0: (200, data))
        assert ab.check_auth()[0] == level

    def test_unit_file(self, home):
        assert ab.check_unit()[0] == ab.SKIP
        ab.UNIT.write_text("[Service]\nRestart=always\n")
        level, _, detail = ab.check_unit()
        assert level == ab.WARN and "update_guard" in detail.lower() or "Update-Schutz" in detail
        ab.UNIT.write_text(
            "Restart=always\nExecStartPre=-x update_guard.py\nEnvironment=PRINTLAB_AUTO_RESTART=1\nEnvironment=PRINTLAB_REQUIRE_AUTH=1\n"
        )
        assert ab.check_unit()[0] == ab.OK

    def test_alert_channel(self, home):
        assert ab.check_alert_channel()[0] == ab.WARN
        ab.ENV_FILE.write_text("PRINTLAB_ALERT_NTFY_URL=https://ntfy.sh/x\n")
        assert ab.check_alert_channel()[0] == ab.OK

    @pytest.mark.skipif(os.name == "nt", reason="Dateirechte nur unter POSIX")
    def test_env_file_permissions(self, home):
        assert ab.check_env_permissions()[0] == ab.SKIP
        ab.ENV_FILE.write_text("X=1\n")
        os.chmod(ab.ENV_FILE, 0o644)
        assert ab.check_env_permissions()[0] == ab.FAIL
        os.chmod(ab.ENV_FILE, 0o600)
        assert ab.check_env_permissions()[0] == ab.OK

    def test_signature_levels(self, home, monkeypatch):
        assert ab.check_signature()[0] == ab.WARN
        (ab.DATA_DIR / "update_allowed_signers").write_text('x namespaces="git" ssh-ed25519 AAAA\n')
        monkeypatch.setattr(ab.shutil, "which", lambda name: None)
        assert ab.check_signature()[0] == ab.FAIL
        monkeypatch.setattr(ab.shutil, "which", lambda name: "/usr/bin/ssh-keygen")
        assert ab.check_signature()[0] == ab.OK

    def test_backups(self, home):
        assert ab.check_backups()[0] == ab.WARN
        folder = ab.DATA_DIR / "update-backups" / "a"
        folder.mkdir(parents=True)
        (folder / "printlab.db").write_bytes(b"kaputt" * 100)
        assert ab.check_backups()[0] == ab.FAIL
        (folder / "printlab.db").unlink()
        con = sqlite3.connect(folder / "printlab.db")
        con.execute("create table t (v)")
        con.commit()
        con.close()
        assert ab.check_backups()[0] == ab.OK

    def test_external_backup_target(self, home, monkeypatch):
        assert ab.check_external_backup()[0] == ab.WARN
        monkeypatch.setenv("PRINTLAB_BACKUP_TARGET", str(home / "gibt-es-nicht"))
        assert ab.check_external_backup()[0] == ab.FAIL
        (home / "usb").mkdir()
        monkeypatch.setenv("PRINTLAB_BACKUP_TARGET", str(home / "usb"))
        assert ab.check_external_backup()[0] == ab.OK

    def test_a_crashing_check_does_not_stop_the_others(self):
        def boom():
            raise RuntimeError("x")

        def fine():
            return ab.OK, "fein", ""

        results = ab.run_all([boom, fine])
        assert results[0]["level"] == ab.FAIL and "abgestürzt" in results[0]["detail"]
        assert results[1]["level"] == ab.OK

    def test_exit_code_and_output(self, home, monkeypatch, capsys):
        monkeypatch.setattr(ab, "CHECKS", [lambda: (ab.OK, "a", ""), lambda: (ab.WARN, "b", "Hinweis")])
        assert ab.main([]) == 0
        monkeypatch.setattr(ab, "CHECKS", [lambda: (ab.FAIL, "c", "kaputt")])
        assert ab.main(["--json"]) == 1
        assert '"level": "FAIL"' in capsys.readouterr().out


class TestWarningCodes:
    def test_codes_and_parameters_for_the_ui(self):
        info = {
            "cpu_temp_c": 85.0,
            "throttled": {"value": 1, "flags": ["Unterspannung (jetzt)"]},
            "disk": {"total": 64e9, "free": 0.5e9},
            "storage": {"device": "/dev/mmcblk0p2", "kind": "sd"},
            "memory": None,
            "backup": {"path": "x", "age_days": 30.0},
            "external_backup": {"ok": False, "detail": "Stick fehlt"},
        }
        by_code = {w["code"]: w for w in ph.warnings_for(info)}
        assert set(by_code) == {"temp_critical", "undervoltage", "disk_low", "sd_card", "backup_old", "external_failed"}
        assert by_code["temp_critical"]["params"] == {"temp": 85.0}
        assert by_code["disk_low"]["params"] == {"free_gb": 0.5}
        assert by_code["backup_old"]["params"] == {"days": 30.0}
        assert by_code["external_failed"]["level"] == "crit" and "Stick fehlt" in by_code["external_failed"]["text"]

    def test_a_successful_external_backup_is_not_a_warning(self):
        info = {"backup": {"age_days": 1}, "external_backup": {"ok": True, "detail": "x"}}
        assert ph.warnings_for(info) == []

    def test_external_status_is_read_from_the_data_folder(self, tmp_path):
        assert ph.external_backup_status(tmp_path) is None
        (tmp_path / "last_external_backup.json").write_text('{"ok": true, "detail": "x"}')
        assert ph.external_backup_status(tmp_path)["ok"] is True
        (tmp_path / "last_external_backup.json").write_text("kaputt")
        assert ph.external_backup_status(tmp_path) is None


def test_health_check_is_skipped_when_nothing_is_measurable(monkeypatch):
    monkeypatch.setattr(
        ab.pi_health,
        "snapshot",
        lambda data_dir: {"cpu_temp_c": None, "storage": None, "memory": None, "warnings": []},
    )
    assert ab.check_health()[0] == ab.SKIP


def test_health_check_fails_on_critical_and_warns_on_the_rest(monkeypatch):
    def snap(level, code):
        return lambda data_dir: {
            "cpu_temp_c": 80.0,
            "storage": None,
            "memory": None,
            "warnings": [{"level": level, "code": code, "text": "x", "params": {}}],
        }

    monkeypatch.setattr(ab.pi_health, "snapshot", snap("crit", "undervoltage"))
    assert ab.check_health()[0] == ab.FAIL
    monkeypatch.setattr(ab.pi_health, "snapshot", snap("warn", "sd_card"))
    assert ab.check_health()[0] == ab.WARN
