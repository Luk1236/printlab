"""Datenbank-Wartung: prüfen und komprimieren.

Die Tests benutzen eine eigene SQLite-Datei im Temp-Ordner — nie die Datenbank des Testlaufs.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.services import db_maintenance


def _engine(tmp_path):
    return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wartung.db'}")


@pytest.mark.asyncio
async def test_status_reports_path_and_size(tmp_path):
    engine = _engine(tmp_path)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)"))
    try:
        result = await db_maintenance.status(engine)
        assert result["supported"] is True
        assert result["dialect"] == "sqlite"
        assert result["path"].endswith("wartung.db")
        assert result["size_bytes"] > 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_check_reports_ok_for_a_healthy_database(tmp_path):
    engine = _engine(tmp_path)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)"))
        await conn.execute(text("INSERT INTO demo (value) VALUES ('x')"))
    try:
        result = await db_maintenance.run("check", engine)
        assert result["ok"] is True
        assert result["action"] == "check"
        assert result["detail"] == ["ok"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_vacuum_frees_space_after_deletes(tmp_path):
    engine = _engine(tmp_path)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)"))
        await conn.execute(
            text("INSERT INTO demo (value) VALUES (:value)"),
            [{"value": "x" * 400} for _ in range(2000)],
        )
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM demo"))
    try:
        result = await db_maintenance.run("vacuum", engine)
        assert result["ok"] is True
        assert result["action"] == "vacuum"
        assert result["saved_bytes"] > 0
        assert result["size_bytes"] < 800_000
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_action_is_refused(tmp_path):
    engine = _engine(tmp_path)
    try:
        with pytest.raises(db_maintenance.DatabaseMaintenanceError):
            await db_maintenance.run("drop", engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_memory_database_is_not_offered():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        assert (await db_maintenance.status(engine))["supported"] is False
        with pytest.raises(db_maintenance.DatabaseMaintenanceError):
            await db_maintenance.run("check", engine)
    finally:
        await engine.dispose()
