"""Werkseinstellungen: Sichern, verschieben, wieder aufnehmen.

Die Tests arbeiten nur mit temporären Ordnern — angestoßen wird nie ein echter Reset des Testlaufs.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from backend.app.services import factory_reset


def _data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "printlab.db").write_bytes(b"SQLite format 3\x00")
    (data / "printlab.db-wal").write_bytes(b"wal")
    (data / "company.json").write_text('{"name": "Test"}', encoding="utf-8")
    (data / "archive").mkdir()
    (data / "archive" / "print.3mf").write_bytes(b"3mf")
    (data / "library").mkdir()
    (data / "library" / "model.stl").write_bytes(b"stl")
    (data / "backups").mkdir()
    (data / "backups" / "nightly.zip").write_bytes(b"zip")
    (data / "logs").mkdir()
    (data / "logs" / "printlab.log").write_text("log", encoding="utf-8")
    (data / "certs").mkdir()
    (data / "certs" / "tailscale.crt").write_text("cert", encoding="utf-8")
    return data


def test_preview_names_what_would_be_removed(tmp_path: Path):
    data = _data_dir(tmp_path)

    result = factory_reset.preview(data, f"sqlite+aiosqlite:///{data / 'printlab.db'}")

    assert result["supported"] is True
    assert result["pending"] is False
    assert "archive" in result["items"]
    assert "company.json" in result["items"]
    assert "backups" not in result["items"]
    assert "logs" not in result["items"]


def test_preview_refuses_external_database(tmp_path: Path):
    data = _data_dir(tmp_path)

    result = factory_reset.preview(data, "postgresql+asyncpg://user:pw@db/printlab")

    assert result["supported"] is False


def test_backup_holds_database_and_config_but_not_media(tmp_path: Path):
    data = _data_dir(tmp_path)

    backup = factory_reset.create_backup(data, data / "printlab.db")

    assert backup.parent == data / "backups"
    with zipfile.ZipFile(backup) as archive:
        names = set(archive.namelist())
    assert "db/printlab.db" in names
    assert "db/printlab.db-wal" in names
    assert "config/company.json" in names
    assert "certs/tailscale.crt" in names
    # Große Medien bleiben im Reset-Ordner, nicht in der ZIP-Datei.
    assert "archive/print.3mf" not in names
    assert "library/model.stl" not in names


def test_apply_pending_moves_everything_and_keeps_backups(tmp_path: Path):
    data = _data_dir(tmp_path)
    target = data / "reset-20260101-120000"
    (data / factory_reset.PENDING_FILE).write_text(
        json.dumps({"requested_at": "2026-01-01T12:00:00", "target": target.name, "backup": "x.zip"}),
        encoding="utf-8",
    )

    moved = factory_reset.apply_pending(data)

    assert moved == target
    assert (target / "printlab.db").is_file()
    assert (target / "archive" / "print.3mf").is_file()
    assert (target / "company.json").is_file()
    assert (target / "certs" / "tailscale.crt").is_file()
    # Sicherungen und Protokolle bleiben, damit man zurück kann.
    assert (data / "backups" / "nightly.zip").is_file()
    assert (data / "logs" / "printlab.log").is_file()
    assert not (data / "printlab.db").exists()
    assert not (data / "archive").exists()
    assert (target / "README.txt").is_file()
    assert not (data / factory_reset.PENDING_FILE).exists()


def test_apply_pending_without_marker_does_nothing(tmp_path: Path):
    data = _data_dir(tmp_path)

    assert factory_reset.apply_pending(data) is None
    assert (data / "printlab.db").is_file()


def test_apply_pending_survives_a_second_start(tmp_path: Path):
    """Nach einem Abbruch liegt die Auftragsdatei noch da; der zweite Lauf darf nichts doppelt verschieben."""
    data = _data_dir(tmp_path)
    target = data / "reset-20260101-120000"
    target.mkdir()
    (target / "printlab.db").write_bytes(b"old")
    (data / factory_reset.PENDING_FILE).write_text(
        json.dumps({"requested_at": "2026-01-01T12:00:00", "target": target.name, "backup": "x.zip"}),
        encoding="utf-8",
    )

    factory_reset.apply_pending(data)

    assert (target / "printlab.db").read_bytes() == b"old"
    assert (target / "printlab.db.neu").read_bytes().startswith(b"SQLite")


def test_apply_pending_refuses_a_target_outside_the_data_dir(tmp_path: Path):
    """Die Auftragsdatei liegt im Datenordner und ist damit änderbar: ein Pfad nach außen wird abgewiesen."""
    data = _data_dir(tmp_path)
    outside = tmp_path / "outside"
    (data / factory_reset.PENDING_FILE).write_text(
        json.dumps({"requested_at": "2026-01-01T12:00:00", "target": str(outside), "backup": "x.zip"}),
        encoding="utf-8",
    )

    moved = factory_reset.apply_pending(data)

    assert moved is not None
    assert moved.parent == data
    assert moved.name.startswith(factory_reset.RESET_PREFIX)
    assert not outside.exists()
    assert (moved / "printlab.db").is_file()


def test_list_archives_finds_reset_folders_with_their_backup(tmp_path: Path):
    data = _data_dir(tmp_path)
    archive = data / "reset-20260101-120000"
    archive.mkdir()
    (archive / "printlab.db").write_bytes(b"alt")
    (data / "backups" / "factory-reset-20260101-120000.zip").write_bytes(b"zip")
    (data / "reset-kaputt").mkdir()

    archives = factory_reset.list_archives(data)

    assert [item["name"] for item in archives] == ["reset-20260101-120000"]
    assert archives[0]["has_database"] is True
    assert archives[0]["backup"] == "factory-reset-20260101-120000.zip"


def test_restore_files_swaps_current_state_for_the_archive(tmp_path: Path):
    data = _data_dir(tmp_path)
    archive = data / "reset-20260101-120000"
    archive.mkdir()
    (archive / "printlab.db").write_bytes(b"alter Stand")
    (archive / "company.json").write_text('{"name": "Alt"}', encoding="utf-8")
    (archive / "README.txt").write_text("hinweis", encoding="utf-8")

    result = factory_reset.restore_files(data, archive.name)

    safety = data / result["safety"]
    assert (data / "printlab.db").read_bytes() == b"alter Stand"
    assert (safety / "printlab.db").read_bytes().startswith(b"SQLite")
    assert (data / "company.json").read_text(encoding="utf-8") == '{"name": "Alt"}'
    assert not archive.exists()
    # Sicherungen und Protokolle bleiben unangetastet.
    assert (data / "backups" / "nightly.zip").is_file()
    assert (data / "logs" / "printlab.log").is_file()


def test_restore_refuses_unknown_folder_names(tmp_path: Path):
    data = _data_dir(tmp_path)
    (data / "reset-20260101-120000").mkdir()

    with pytest.raises(factory_reset.FactoryResetError):
        factory_reset.restore_files(data, "../etc")
    with pytest.raises(factory_reset.FactoryResetError):
        factory_reset.restore_files(data, "reset-20000101-000000")


def test_sqlite_path_parsing():
    assert factory_reset.sqlite_db_path("sqlite+aiosqlite:////srv/printlab/printlab.db") == Path(
        "/srv/printlab/printlab.db"
    )
    with pytest.raises(factory_reset.FactoryResetError):
        factory_reset.sqlite_db_path("postgresql+asyncpg://db/printlab")
    with pytest.raises(factory_reset.FactoryResetError):
        factory_reset.sqlite_db_path("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_perform_reset_refuses_external_database(tmp_path: Path):
    data = _data_dir(tmp_path)

    with pytest.raises(factory_reset.FactoryResetError):
        await factory_reset.perform_reset(data, "postgresql+asyncpg://db/printlab")

    # Nichts angefasst, keine Sicherung, keine Auftragsdatei.
    assert (data / "printlab.db").is_file()
    assert not (data / factory_reset.PENDING_FILE).exists()
