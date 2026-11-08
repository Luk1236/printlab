"""Unit-Tests für KI-Druckbett-Räumungsprüfung (Phase 23)."""

import pytest
from httpx import AsyncClient

from backend.app.services.plate_clearance_detector import (
    acknowledge_bed_clear,
    get_bed_baseline,
    inspect_bed_clearance,
    set_bed_baseline,
)


def test_plate_clearance_empty_bed() -> None:
    res = inspect_bed_clearance(printer_id="P1", threshold=0.85, mock_has_obstacle=False)
    assert res["can_safely_print"] is True
    assert res["clearance_score"] >= 0.85
    assert res["status"] == "CLEARED_EMPTY"
    assert len(res["detected_anomalies"]) == 0


def test_plate_clearance_obstacle_detected() -> None:
    res = inspect_bed_clearance(
        printer_id="P1",
        threshold=0.85,
        mock_has_obstacle=True,
        mock_obstacle_type="forgotten_scraper",
    )
    assert res["can_safely_print"] is False
    assert res["clearance_score"] < 0.85
    assert res["status"] == "BLOCKED_OBSTACLE_DETECTED"
    assert len(res["detected_anomalies"]) > 0
    assert "forgotten_scraper" in res["detected_anomalies"][0]


def test_baseline_registration() -> None:
    b_res = set_bed_baseline("P2", {"resolution": "3840x2160", "mean_brightness": 130.0})
    assert b_res["success"] is True
    assert b_res["baseline"]["resolution"] == "3840x2160"

    retrieved = get_bed_baseline("P2")
    assert retrieved is not None
    assert retrieved["resolution"] == "3840x2160"


def test_operator_override() -> None:
    # 1. Override setzen
    ov_res = acknowledge_bed_clear(printer_id="P3", operator_name="Lukas", notes="Bett manuell gesäubert")
    assert ov_res["success"] is True

    # 2. Selbst wenn Hindernis simuliert wird, greift der manuelle Override
    ins = inspect_bed_clearance(printer_id="P3", mock_has_obstacle=True)
    assert ins["can_safely_print"] is True
    assert ins["status"] == "CLEARED_BY_OPERATOR"


@pytest.mark.asyncio
async def test_plate_clearance_api_endpoints(async_client: AsyncClient) -> None:
    # 1. Inspect Endpoint (Leer)
    i_resp = await async_client.post(
        "/api/v1/plate-clearance/inspect/TEST-PRINTER",
        json={"threshold": 0.80, "mock_has_obstacle": False},
    )
    assert i_resp.status_code == 200
    assert i_resp.json()["can_safely_print"] is True

    # 2. Inspect Endpoint (Blockiert)
    b_resp = await async_client.post(
        "/api/v1/plate-clearance/inspect/TEST-PRINTER",
        json={"threshold": 0.80, "mock_has_obstacle": True, "mock_obstacle_type": "spatula"},
    )
    assert b_resp.status_code == 200
    assert b_resp.json()["can_safely_print"] is False

    # 3. Set Baseline
    base_resp = await async_client.post(
        "/api/v1/plate-clearance/set-baseline/TEST-PRINTER",
        json={"resolution": "1920x1080", "mean_brightness": 125.0, "edge_density": 0.05},
    )
    assert base_resp.status_code == 200
    assert base_resp.json()["success"] is True

    # 4. Status GET
    st_resp = await async_client.get("/api/v1/plate-clearance/status/TEST-PRINTER")
    assert st_resp.status_code == 200
    assert st_resp.json()["has_baseline"] is True
