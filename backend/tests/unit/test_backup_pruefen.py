"""Sicherungen prüfen (werkzeuge/backup_pruefen.py) und die Prüfung der Update-Sicherung."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from backend.app.services import update_guard as ug

SCRIPT = Path(__file__).resolve().parents[3] / "werkzeuge" / "backup_pruefen.py"
spec = importlib.util.spec_from_file_location("backup_pruefen", SCRIPT)
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)


def make_db(path):
    con = sqlite3.connect(path)
    con.execute("create table t (v text)")
    con.execute("insert into t values ('x')")
    con.commit()
    con.close()


def test_good_backup_has_no_problems(tmp_path):
    make_db(tmp_path / "printlab.db")
    (tmp_path / "hardware.json").write_text('{"a": 1}')
    assert bp.check_folder(tmp_path) == []


def test_broken_database_json_and_empty_file_are_found(tmp_path):
    (tmp_path / "printlab.db").write_bytes(b"das ist keine datenbank" * 50)
    (tmp_path / "leer.db").write_bytes(b"")
    (tmp_path / "kaputt.json").write_text("{nope")
    problems = " | ".join(bp.check_folder(tmp_path))
    assert "printlab.db" in problems and "leer.db: leer" in problems and "kaputt.json" in problems


def test_backup_without_a_database_is_a_problem(tmp_path):
    (tmp_path / "x.json").write_text("{}")
    assert bp.check_folder(tmp_path) == ["keine Datenbank in der Sicherung"]


def test_database_without_tables_is_a_problem(tmp_path):
    sqlite3.connect(tmp_path / "leer.db").close()
    # eine nie beschriebene SQLite-Datei hat 0 Byte
    assert bp.check_folder(tmp_path)


def test_main_exit_codes(tmp_path, capsys):
    make_db(tmp_path / "printlab.db")
    assert bp.main(["x", str(tmp_path)]) == 0
    (tmp_path / "printlab.db").write_bytes(b"kaputt" * 100)
    assert bp.main(["x", str(tmp_path)]) == 1
    assert bp.main(["x", str(tmp_path / "gibt-es-nicht")]) == 2
    assert "MANGEL" in capsys.readouterr().out


def test_newest_backup_picks_the_latest_folder(tmp_path, monkeypatch):
    root = tmp_path / "update-backups"
    old, new = root / "a", root / "b"
    old.mkdir(parents=True)
    new.mkdir()
    import os

    os.utime(old, (1, 1))
    monkeypatch.setattr(bp, "DATA_DIR", tmp_path)
    monkeypatch.setattr(bp.Path, "home", classmethod(lambda cls: tmp_path / "kein-home"))
    monkeypatch.setattr(bp, "APP_DIR", tmp_path / "kein-app")
    assert bp.newest_backup() == new


class TestUpdateBackupVerification:
    def test_verify_sqlite(self, tmp_path):
        make_db(tmp_path / "ok.db")
        (tmp_path / "bad.db").write_bytes(b"xxxx" * 200)
        assert ug.verify_sqlite(tmp_path / "ok.db") is True
        assert ug.verify_sqlite(tmp_path / "bad.db") is False
        assert ug.verify_sqlite(tmp_path / "fehlt.db") is False

    def test_a_corrupt_copy_aborts_the_backup(self, tmp_path, monkeypatch):
        data = tmp_path / "data"
        data.mkdir()
        make_db(data / "printlab.db")
        monkeypatch.setattr(ug, "verify_sqlite", lambda path: False)
        with pytest.raises(sqlite3.DatabaseError):
            ug.backup_data(data, tmp_path / "backup")
