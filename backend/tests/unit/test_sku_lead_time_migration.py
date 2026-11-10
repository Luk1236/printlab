"""Regression: ``filament_sku_settings.lead_time_days`` darf beim Start nicht zurückgesetzt werden (T3-01).

Früher lief ``UPDATE ... SET lead_time_days = 0 WHERE lead_time_days = 7`` bei jedem Start und überschrieb damit
auch bewusst gesetzte Lieferzeiten von 7 Tagen. Der Altwert wird nur noch einmalig umgestellt, und zwar nur auf
Tabellen aus der Zeit vor der Spalte ``safety_margin_value``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.core.database import run_migrations


@pytest.fixture(autouse=True)
def force_sqlite_dialect(monkeypatch):
    from backend.app.core import database as database_module, db_dialect

    monkeypatch.setattr(db_dialect, "is_sqlite", lambda: True)
    monkeypatch.setattr(db_dialect, "is_postgres", lambda: False)
    monkeypatch.setattr(database_module, "is_sqlite", lambda: True)


async def _engine_with_current_schema():
    import importlib
    import pkgutil

    import backend.app.models as models_pkg
    from backend.app.core.database import Base

    # Wie init_db(): alle Modelle registrieren, sonst fehlen Tabellen für die Migrationen.
    for module in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"backend.app.models.{module.name}")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _lead_times(engine) -> list[int]:
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT lead_time_days FROM filament_sku_settings ORDER BY id"))
        return [row[0] for row in result]


async def _insert_current(conn, material: str, lead_time: int) -> None:
    await conn.execute(
        text(
            "INSERT INTO filament_sku_settings "
            "(material, lead_time_days, safety_margin_value, safety_margin_unit, alerts_snoozed) "
            "VALUES (:m, :lt, 14, 'days', 0)"
        ),
        {"m": material, "lt": lead_time},
    )


@pytest.mark.asyncio
async def test_user_set_lead_time_of_seven_survives_restarts():
    engine = await _engine_with_current_schema()
    try:
        async with engine.begin() as conn:
            await _insert_current(conn, "PLA", 7)
        for _ in range(3):  # drei Neustarts
            async with engine.begin() as conn:
                await run_migrations(conn)
        assert await _lead_times(engine) == [7]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_default_is_reset_once_and_later_choices_stay():
    engine = await _engine_with_current_schema()
    try:
        # Tabelle aus der alten Zeit: Standard 7, noch ohne safety_margin_value.
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE filament_sku_settings"))
            await conn.execute(
                text(
                    """CREATE TABLE filament_sku_settings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        material VARCHAR(50) NOT NULL,
                        subtype VARCHAR(50),
                        brand VARCHAR(100),
                        lead_time_days INTEGER NOT NULL DEFAULT 7,
                        safety_margin_days INTEGER NOT NULL DEFAULT 14,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (material, subtype, brand)
                    )"""
                )
            )
            await conn.execute(text("INSERT INTO filament_sku_settings (material, lead_time_days) VALUES ('PLA', 7)"))
            await conn.execute(text("INSERT INTO filament_sku_settings (material, lead_time_days) VALUES ('PETG', 3)"))

        async with engine.begin() as conn:  # erster Start nach dem Update
            await run_migrations(conn)
        assert await _lead_times(engine) == [0, 3]  # Altwert 7 umgestellt, 3 unberührt

        # Jemand stellt jetzt bewusst 7 Tage ein; der nächste Start darf das nicht mehr ändern.
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE filament_sku_settings SET lead_time_days = 7 WHERE material = 'PLA'"))
        async with engine.begin() as conn:
            await run_migrations(conn)
        assert await _lead_times(engine) == [7, 3]
    finally:
        await engine.dispose()
