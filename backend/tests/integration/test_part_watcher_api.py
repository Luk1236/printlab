"""Bauteil-Wächter: Umschalten darf die gespeicherte Schwelle nicht zurücksetzen."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from backend.app.services.part_watcher import part_watcher


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(part_watcher, "path", tmp_path / "part_watcher.json", raising=False)
    monkeypatch.setattr(part_watcher, "_config", {})


async def test_switching_keeps_the_saved_threshold(async_client: AsyncClient, printer_factory):
    printer = await printer_factory()
    url = f"/api/v1/printers/{printer.id}/part-watcher"
    await async_client.put(url, json={"enabled": True, "threshold": 3.5})

    response = await async_client.put(url, json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["threshold"] == 3.5


async def test_threshold_outside_the_limits_is_rejected(async_client: AsyncClient, printer_factory):
    printer = await printer_factory()

    response = await async_client.put(
        f"/api/v1/printers/{printer.id}/part-watcher", json={"enabled": True, "threshold": 99}
    )

    assert response.status_code == 422
