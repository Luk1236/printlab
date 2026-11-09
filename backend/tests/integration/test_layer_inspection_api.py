"""Integrationstests für die Layer-Inspection und Spaghetti-Erkennungs-API."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from httpx import AsyncClient

from backend.app.core.config import settings as app_settings
from backend.app.models.printer import Printer

PREFIX = app_settings.api_prefix


def _make_test_image() -> bytes:
    img = np.zeros((300, 300, 3), dtype=np.uint8) + 50
    cv2.rectangle(img, (50, 50), (250, 250), (200, 200, 200), 2)
    _, enc = cv2.imencode(".jpg", img)
    return enc.tobytes()


@pytest.fixture(autouse=True)
def _isolated_layer_inspection_config(tmp_path, monkeypatch):
    """Die Konfiguration liegt sonst in data/layer_inspection.json: Der PUT eines Laufs würde den nächsten färben."""
    from backend.app.services.layer_inspection import layer_inspection_service

    monkeypatch.setattr(layer_inspection_service, "path", tmp_path / "layer_inspection.json")
    monkeypatch.setattr(layer_inspection_service, "_config", {})


@pytest.fixture
async def sample_printer(db_session):
    printer = Printer(
        name="Test X1C",
        ip_address="192.168.1.100",
        access_code="12345678",
        serial_number="012345678901234",
    )
    db_session.add(printer)
    await db_session.commit()
    await db_session.refresh(printer)
    return printer


@pytest.mark.asyncio
async def test_layer_inspection_get_and_put(async_client: AsyncClient, sample_printer: Printer):
    # GET status
    res = await async_client.get(f"{PREFIX}/printers/{sample_printer.id}/layer-inspection")
    assert res.status_code == 200
    data = res.json()
    assert data["printer_id"] == sample_printer.id
    assert "config" in data
    assert data["config"]["enabled"] is False

    # PUT config
    put_res = await async_client.put(
        f"{PREFIX}/printers/{sample_printer.id}/layer-inspection",
        json={
            "enabled": True,
            "layer_interval": 3,
            "sensitivity_threshold": 0.72,
            "consecutive_alerts": 3,
            "auto_pause": True,
        },
    )
    assert put_res.status_code == 200
    cfg = put_res.json()["config"]
    assert cfg["enabled"] is True
    assert cfg["layer_interval"] == 3
    assert cfg["sensitivity_threshold"] == 0.72
    assert cfg["consecutive_alerts"] == 3

    # Reset
    reset_res = await async_client.post(f"{PREFIX}/printers/{sample_printer.id}/layer-inspection/reset")
    assert reset_res.status_code == 200
    assert reset_res.json()["consecutive_alerts"] == 0


@pytest.mark.asyncio
async def test_layer_inspection_test_upload(async_client: AsyncClient, sample_printer: Printer):
    img_bytes = _make_test_image()
    files = {"file": ("test.jpg", img_bytes, "image/jpeg")}
    res = await async_client.post(
        f"{PREFIX}/printers/{sample_printer.id}/layer-inspection/test",
        files=files,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["printer_id"] == sample_printer.id
    assert "result" in data
    assert not data["result"]["is_failure"]
    assert "debug_image_b64" in data["result"]
    assert data["result"]["debug_image_b64"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_layer_inspection_not_found(async_client: AsyncClient):
    res = await async_client.get(f"{PREFIX}/printers/99999/layer-inspection")
    assert res.status_code == 404
