"""The live database is renamed from bambuddy.db to printlab.db on start, sidecar files included."""

from backend.app.core import config


def test_old_database_is_renamed_with_its_wal_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_data_dir", tmp_path)
    (tmp_path / "bambuddy.db").write_bytes(b"db")
    (tmp_path / "bambuddy.db-wal").write_bytes(b"wal")
    (tmp_path / "bambuddy.db-shm").write_bytes(b"shm")
    result = config._migrate_database()
    assert result == tmp_path / "printlab.db"
    assert (tmp_path / "printlab.db").read_bytes() == b"db"
    assert (tmp_path / "printlab.db-wal").read_bytes() == b"wal"
    assert (tmp_path / "printlab.db-shm").read_bytes() == b"shm"
    assert not (tmp_path / "bambuddy.db").exists()


def test_existing_new_database_is_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_data_dir", tmp_path)
    (tmp_path / "printlab.db").write_bytes(b"new")
    (tmp_path / "bambuddy.db").write_bytes(b"old")
    assert config._migrate_database() == tmp_path / "printlab.db"
    assert (tmp_path / "printlab.db").read_bytes() == b"new"
    assert (tmp_path / "bambuddy.db").read_bytes() == b"old"


def test_fresh_install_uses_the_new_name(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_data_dir", tmp_path)
    assert config._migrate_database() == tmp_path / "printlab.db"


def test_very_old_name_is_migrated_too(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_data_dir", tmp_path)
    (tmp_path / "bambutrack.db").write_bytes(b"x")
    assert config._migrate_database() == tmp_path / "printlab.db"
    assert (tmp_path / "printlab.db").exists()


def test_legacy_environment_variables_are_mirrored(monkeypatch):
    import importlib

    monkeypatch.setenv("BAMBUDDY_LOCAL_LOGIN", "true")
    monkeypatch.delenv("PRINTLAB_LOCAL_LOGIN", raising=False)
    importlib.reload(config)
    import os

    assert os.environ["PRINTLAB_LOCAL_LOGIN"] == "true"
    monkeypatch.delenv("PRINTLAB_LOCAL_LOGIN", raising=False)
