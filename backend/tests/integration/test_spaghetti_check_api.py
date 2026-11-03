"""Spaghetti-Prüfung: Schnittstelle (Lesen, Speichern, unbekannter Drucker)."""

import pytest
from httpx import AsyncClient

from backend.app.services import spaghetti_check


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(spaghetti_check, "CONFIG_PATH", tmp_path / "spaghetti_check.json")


async def test_read_returns_the_defaults(async_client: AsyncClient, printer_factory):
    printer = await printer_factory()

    response = await async_client.get(f"/api/v1/printers/{printer.id}/spaghetti-check")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "max_components": 25, "min_changed_percent": 0.5}


async def test_saved_values_come_back_on_the_next_read(async_client: AsyncClient, printer_factory):
    printer = await printer_factory()
    payload = {"enabled": True, "max_components": 40, "min_changed_percent": 1.5}

    saved = await async_client.put(f"/api/v1/printers/{printer.id}/spaghetti-check", json=payload)

    assert saved.status_code == 200
    assert saved.json() == payload
    assert (await async_client.get(f"/api/v1/printers/{printer.id}/spaghetti-check")).json() == payload


async def test_saving_for_an_unknown_printer_gets_404(async_client: AsyncClient):
    response = await async_client.put(
        "/api/v1/printers/999999/spaghetti-check",
        json={"enabled": True, "max_components": 40, "min_changed_percent": 1.5},
    )

    assert response.status_code == 404
