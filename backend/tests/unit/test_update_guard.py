"""Update-Schutz: Sicherung, Zähler, Rückbau auf den alten Git-Stand samt Datenbank, Bestätigung."""

import asyncio
import os
import shutil
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

from backend.app.services import update_guard as ug

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git fehlt in dieser Umgebung")


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def install(tmp_path):
    """Ein Git-Ordner mit zwei Ständen und ein Datenordner mit Datenbank und Einstellungsdatei."""
    app = tmp_path / "app"
    app.mkdir()
    _git(app, "init", "-q")
    (app / "version.txt").write_text("alt")
    _git(app, "add", "-A")
    _git(app, "commit", "-q", "-m", "alt")
    old_commit = ug.current_commit(app)
    data = tmp_path / "data"
    data.mkdir()
    con = sqlite3.connect(data / "printlab.db")
    con.execute("create table t (v text)")
    con.execute("insert into t values ('vorher')")
    con.commit()
    con.close()
    (data / "hardware.json").write_text('{"gpio": 1}')
    return app, data, old_commit


def _move_to_new_version(app):
    (app / "version.txt").write_text("neu")
    _git(app, "add", "-A")
    _git(app, "commit", "-q", "-m", "neu")


def _db_value(data):
    con = sqlite3.connect(data / "printlab.db")
    try:
        return con.execute("select v from t").fetchone()[0]
    finally:
        con.close()


def test_prepare_backs_up_data_and_writes_the_marker(install):
    app, data, old_commit = install
    marker = ug.prepare(app, data, "v9.9.9", "1.0.0")
    assert marker["previous_commit"] == old_commit
    assert marker["starts"] == 0
    assert sorted(marker["saved"]) == ["hardware.json", "printlab.db"]
    assert ug.read_marker(data)["target_ref"] == "v9.9.9"
    backup = data / ug.BACKUP_FOLDER
    assert any((p / "printlab.db").exists() for p in backup.iterdir())


def test_prepare_fails_cleanly_without_a_git_checkout(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with pytest.raises(ug.UpdateGuardError):
        ug.prepare(tmp_path / "kein-git", data, "v1", "1.0.0")
    assert ug.read_marker(data) is None


def test_old_backups_are_pruned(install, monkeypatch):
    app, data, _ = install
    stamps = iter(f"20260101-00000{i}" for i in range(6))
    monkeypatch.setattr(ug.time, "strftime", lambda fmt: next(stamps) if "%H%M%S" in fmt and "T" not in fmt else "t")
    for _ in range(5):
        ug.prepare(app, data, "v1", "1.0.0")
    assert len(list((data / ug.BACKUP_FOLDER).iterdir())) == ug.KEEP_BACKUPS


def test_guard_without_a_pending_update_does_nothing(install):
    app, data, _ = install
    assert ug.guard(app, data) == "none"


def test_guard_counts_the_starts_and_leaves_stable_updates_alone(install):
    app, data, _ = install
    ug.prepare(app, data, "v2", "1.0.0")
    _move_to_new_version(app)
    for expected in (1, 2, 3):
        assert ug.guard(app, data) == "counted"
        assert ug.read_marker(data)["starts"] == expected
    assert (app / "version.txt").read_text() == "neu"


def test_fourth_unconfirmed_start_rolls_back_code_and_database(install):
    app, data, old_commit = install
    ug.prepare(app, data, "v2", "1.0.0")
    _move_to_new_version(app)
    con = sqlite3.connect(data / "printlab.db")
    con.execute("update t set v = 'kaputt-migriert'")
    con.commit()
    con.close()
    (data / "hardware.json").write_text('{"gpio": 99}')

    for _ in range(ug.MAX_STARTS):
        assert ug.guard(app, data) == "counted"
    assert ug.guard(app, data) == "rolled_back"

    assert ug.current_commit(app) == old_commit
    assert (app / "version.txt").read_text() == "alt"
    assert _db_value(data) == "vorher"
    assert (data / "hardware.json").read_text() == '{"gpio": 1}'
    assert ug.read_marker(data) is None
    notice = ug.read_rollback_notice(data)
    assert notice["from_ref"] == "v2" and notice["to_commit"] == old_commit
    assert ug.guard(app, data) == "none"  # nach dem Rückbau ist Ruhe

    ug.clear_rollback_notice(data)
    assert ug.read_rollback_notice(data) is None


def test_confirm_removes_the_marker(install):
    app, data, _ = install
    ug.prepare(app, data, "v2", "1.0.0")
    assert ug.confirm(data) is True
    assert ug.confirm(data) is False
    assert ug.guard(app, data) == "none"


@pytest.mark.parametrize(
    "bad", ["", "--hard", "-x", "HEAD~1", "abc", "zzzzzzzz", "a" * 65, "abc123; rm -rf /", None, 5]
)
def test_rollback_only_accepts_a_real_commit_hash(install, bad):
    app, data, old_commit = install
    assert ug.rollback(app, data, {"previous_commit": bad}, "x") is False
    assert ug.current_commit(app) == old_commit  # nichts wurde angefasst


@pytest.mark.asyncio
async def test_confirmation_runs_after_the_delay(install):
    app, data, _ = install
    assert ug.schedule_confirmation(data, delay=0) is False  # nichts offen
    ug.prepare(app, data, "v2", "1.0.0")
    assert ug.schedule_confirmation(data, delay=0.01) is True
    await asyncio.sleep(0.1)
    assert ug.read_marker(data) is None


class TestSystemdUnit:
    UNIT = "[Service]\nWorkingDirectory=%h/printlab\nExecStart=/x/python -m uvicorn app\nRestart=always\n"

    def test_adds_the_guard_once(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ug.subprocess, "run", lambda *a, **k: None)
        unit = tmp_path / "printlab.service"
        unit.write_text(self.UNIT)
        assert ug.ensure_systemd_guard(tmp_path / "app", "/x/python", unit) is True
        text = unit.read_text()
        assert "ExecStartPre=-/x/python " in text and "update_guard.py" in text
        assert text.index("ExecStartPre") < text.index("ExecStart=")
        assert ug.ensure_systemd_guard(tmp_path / "app", "/x/python", unit) is False

    def test_missing_unit_is_ignored(self, tmp_path):
        assert ug.ensure_systemd_guard(tmp_path, "python", tmp_path / "gibt-es-nicht.service") is False


@pytest.mark.skipif(os.name == "nt", reason="Dateirechte nur unter POSIX")
def test_backups_are_only_readable_by_the_owner(install):
    app, data, _ = install
    marker = ug.prepare(app, data, "v2", "1.0.0")
    backup = Path(marker["backup_dir"])
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert stat.S_IMODE(backup.parent.stat().st_mode) == 0o700
    for name in marker["saved"]:
        assert stat.S_IMODE((backup / name).stat().st_mode) == 0o600


class TestReinstallRequirements:
    def test_runs_pip_with_the_requirements_of_the_old_state(self, tmp_path, monkeypatch):
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"], seen["cwd"] = cmd, kwargs.get("cwd")

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(ug.subprocess, "run", fake_run)
        assert ug.reinstall_requirements(tmp_path, "/x/python") is True
        assert seen["cmd"][:5] == ["/x/python", "-m", "pip", "install", "-q"] and seen["cmd"][-1].endswith(
            "requirements.txt"
        )

    def test_failures_are_not_fatal(self, tmp_path, monkeypatch):
        (tmp_path / "requirements.txt").write_text("fastapi\n")

        def boom(*a, **k):
            raise OSError("kein pip")

        monkeypatch.setattr(ug.subprocess, "run", boom)
        assert ug.reinstall_requirements(tmp_path, "python") is False
        assert ug.reinstall_requirements(tmp_path / "leer", "python") is False


def test_unit_gets_a_long_start_timeout_with_the_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(ug.subprocess, "run", lambda *a, **k: None)
    unit = tmp_path / "printlab.service"
    unit.write_text("[Service]\nExecStart=/x/python -m uvicorn app\n")
    assert ug.ensure_systemd_guard(tmp_path / "app", "/x/python", unit) is True
    text = unit.read_text()
    assert "TimeoutStartSec=900" in text and text.index("TimeoutStartSec") < text.index("ExecStart=")
    unit.write_text("[Service]\nTimeoutStartSec=30\nExecStart=/x/python app\n")
    ug.ensure_systemd_guard(tmp_path / "app", "/x/python", unit)
    assert unit.read_text().count("TimeoutStartSec") == 1  # eine vorhandene Einstellung bleibt


class TestRestore:
    def backup_with(self, data, label="20260101-120000", value="gesichert"):
        folder = data / ug.BACKUP_FOLDER / label
        folder.mkdir(parents=True)
        con = sqlite3.connect(folder / "printlab.db")
        con.execute("create table t (v text)")
        con.execute("insert into t values (?)", (value,))
        con.commit()
        con.close()
        (folder / "hardware.json").write_text('{"gpio": 7}')
        return folder

    def test_lists_backups_newest_first_and_ignores_foreign_folders(self, install):
        _, data, _ = install
        self.backup_with(data, "20260101-120000")
        self.backup_with(data, "20260301-120000")
        (data / ug.BACKUP_FOLDER / "meine-fotos").mkdir()
        listed = ug.list_backups(data)
        assert [b["name"] for b in listed] == ["20260301-120000", "20260101-120000"]
        assert listed[0]["files"] == ["hardware.json", "printlab.db"] and listed[0]["size_bytes"] > 0

    def test_listing_without_backups_is_empty(self, install):
        _, data, _ = install
        assert ug.list_backups(data) == []

    def test_request_marks_the_restore_for_the_next_start(self, install):
        _, data, _ = install
        self.backup_with(data)
        ug.request_restore(data, "20260101-120000")
        assert ug.restore_pending(data) == "20260101-120000"

    @pytest.mark.parametrize("name", ["", "../daten", "..\\x", "20260101-12000", "abc", "20260101-120000/../x"])
    def test_bad_names_are_refused(self, install, name):
        _, data, _ = install
        with pytest.raises(ug.UpdateGuardError):
            ug.request_restore(data, name)
        assert ug.restore_pending(data) is None

    def test_unknown_empty_or_damaged_backups_are_refused(self, install):
        _, data, _ = install
        with pytest.raises(ug.UpdateGuardError, match="nicht mehr"):
            ug.request_restore(data, "20260101-120000")
        folder = data / ug.BACKUP_FOLDER / "20260102-120000"
        folder.mkdir(parents=True)
        with pytest.raises(ug.UpdateGuardError, match="keine Datenbank"):
            ug.request_restore(data, "20260102-120000")
        (folder / "printlab.db").write_bytes(b"kaputt" * 100)
        with pytest.raises(ug.UpdateGuardError, match="beschädigt"):
            ug.request_restore(data, "20260102-120000")
        assert ug.restore_pending(data) is None

    def test_guard_applies_the_restore_and_keeps_a_safety_copy(self, install):
        app, data, _ = install
        self.backup_with(data, "20260101-120000", value="alt")
        ug.request_restore(data, "20260101-120000")
        con = sqlite3.connect(data / "printlab.db")
        con.execute("update t set v = 'neu-und-falsch'")
        con.commit()
        con.close()
        assert ug.guard(app, data) == "restored"
        assert _db_value(data) == "alt"
        assert (data / "hardware.json").read_text() == '{"gpio": 7}'
        assert ug.restore_pending(data) is None
        assert ug.read_restore_notice(data)["name"] == "20260101-120000"
        # die Sicherung des Zustands davor ist vorhanden und enthält den "falschen" Wert
        names = [b["name"] for b in ug.list_backups(data)]
        assert len(names) == 2
        newest = data / ug.BACKUP_FOLDER / names[0]
        con = sqlite3.connect(newest / "printlab.db")
        assert con.execute("select v from t").fetchone()[0] == "neu-und-falsch"
        con.close()
        assert ug.guard(app, data) == "none"  # nur einmal
        ug.clear_restore_notice(data)
        assert ug.read_restore_notice(data) is None

    def test_a_vanished_backup_fails_without_touching_anything(self, install):
        app, data, _ = install
        self.backup_with(data)
        ug.request_restore(data, "20260101-120000")
        shutil.rmtree(data / ug.BACKUP_FOLDER / "20260101-120000")
        assert ug.guard(app, data) == "restore_failed"
        assert _db_value(data) == "vorher"
        assert ug.restore_pending(data) is None  # kein zweiter Versuch beim nächsten Start

    def test_guard_in_unit(self, tmp_path):
        unit = tmp_path / "printlab.service"
        assert ug.guard_in_unit(unit) is False
        unit.write_text("[Service]\nExecStart=x\n")
        assert ug.guard_in_unit(unit) is False
        unit.write_text("[Service]\nExecStartPre=-x update_guard.py\nExecStart=x\n")
        assert ug.guard_in_unit(unit) is True
