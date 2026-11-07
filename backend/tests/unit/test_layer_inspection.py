"""Unit-Tests für den kontinuierlichen Schichtanalyse-Dienst."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import cv2
import numpy as np
import pytest

from backend.app.services.layer_inspection import (
    DEFAULT_PRINTER_CONFIG,
    LayerInspectionService,
)


def _make_dummy_spaghetti_image() -> bytes:
    img = np.zeros((480, 640, 3), dtype=np.uint8) + 30
    np.random.seed(42)
    for _ in range(80):
        c = (int(np.random.randint(180, 460)), int(np.random.randint(140, 360)))
        ax = (int(np.random.randint(12, 50)), int(np.random.randint(12, 50)))
        cv2.ellipse(img, c, ax, int(np.random.randint(0, 360)), 0, 360, (230, 230, 230), 2)
    _, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes()


def _make_clean_image() -> bytes:
    img = np.zeros((480, 640, 3), dtype=np.uint8) + 40
    for y in range(100, 380, 20):
        cv2.line(img, (150, y), (490, y), (200, 200, 200), 2)
    _, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes()


@pytest.fixture
def service(tmp_path):
    cfg_file = tmp_path / "layer_inspection.json"
    return LayerInspectionService(path=cfg_file)


def test_default_config(service):
    cfg = service.get_config(printer_id=1)
    assert cfg["enabled"] is False
    assert cfg["layer_interval"] == 2
    assert cfg["sensitivity_threshold"] == 0.65
    assert cfg["consecutive_alerts"] == 2
    assert cfg["auto_pause"] is True


def test_configure(service):
    updated = service.configure(
        printer_id=1,
        updates={
            "enabled": True,
            "layer_interval": 5,
            "sensitivity_threshold": 0.70,
            "consecutive_alerts": 3,
            "auto_pause": False,
        },
    )
    assert updated["enabled"] is True
    assert updated["layer_interval"] == 5
    assert updated["sensitivity_threshold"] == 0.70
    assert updated["consecutive_alerts"] == 3
    assert updated["auto_pause"] is False

    # Status prüfen
    status = service.get_status(printer_id=1)
    assert status["config"]["enabled"] is True
    assert status["consecutive_alerts"] == 0


def test_should_inspect(service):
    # Standardmäßig deaktiviert
    assert not service.should_inspect(1, layer_num=4)

    service.configure(1, {"enabled": True, "layer_interval": 3, "min_layer": 3})
    assert not service.should_inspect(1, layer_num=2)  # < min_layer
    assert service.should_inspect(1, layer_num=3)  # min_layer und % 3 == 0
    assert not service.should_inspect(1, layer_num=4)  # 4 % 3 != 0
    assert not service.should_inspect(1, layer_num=5)  # 5 % 3 != 0
    assert service.should_inspect(1, layer_num=6)  # 6 % 3 == 0


@pytest.mark.asyncio
async def test_observe_clean_print(service):
    service.configure(1, {"enabled": True, "layer_interval": 1, "min_layer": 1})
    clean_bytes = _make_clean_image()

    res = await service.observe(
        printer_id=1,
        printer_name="Bambu X1C",
        layer_num=2,
        image_data=clean_bytes,
    )
    assert res is not None
    assert not res["analysis"]["is_failure"]
    assert res["history_item"]["action_taken"] == "ok"
    assert service.get_status(1)["consecutive_alerts"] == 0


@pytest.mark.asyncio
async def test_observe_failure_and_auto_pause(service, monkeypatch):
    service.configure(
        1,
        {
            "enabled": True,
            "layer_interval": 1,
            "min_layer": 1,
            "consecutive_alerts": 2,
            "auto_pause": True,
            "save_debug_snapshots": False,
        },
    )
    spag_bytes = _make_dummy_spaghetti_image()

    mock_client = MagicMock()
    mock_client.state = MagicMock()
    mock_client.state.state = "RUNNING"
    mock_client.pause_print = AsyncMock()

    mock_db = MagicMock()

    # Schicht 1: Erster Fehler erkannt -> Status Warning (1/2)
    res1 = await service.observe(
        printer_id=1,
        printer_name="Bambu X1C",
        layer_num=3,
        image_data=spag_bytes,
        client=mock_client,
        db=mock_db,
    )
    assert res1 is not None
    assert res1["analysis"]["is_failure"]
    assert "warning (1/2)" in res1["history_item"]["action_taken"]
    assert mock_client.pause_print.call_count == 0

    # Schicht 2: Zweiter Fehler in Folge -> Trigger Pause!
    res2 = await service.observe(
        printer_id=1,
        printer_name="Bambu X1C",
        layer_num=4,
        image_data=spag_bytes,
        client=mock_client,
        db=mock_db,
    )
    assert res2 is not None
    assert res2["analysis"]["is_failure"]
    assert res2["history_item"]["action_taken"] == "paused"
    assert mock_client.pause_print.call_count == 1


@pytest.mark.asyncio
async def test_test_frame(service):
    img_bytes = _make_clean_image()
    res = await service.test_frame(printer_id=1, image_data=img_bytes)
    assert res["printer_id"] == 1
    assert "result" in res
    assert "debug_image_b64" in res["result"]
