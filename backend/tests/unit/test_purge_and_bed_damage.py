"""Unit-Tests für Purge-Optimizer und Druckbett-Schadenszonen (Phase 19)."""

import pytest
from httpx import AsyncClient
from backend.app.services.auto_nesting import (
    NestingPart,
    pack_parts_onto_plates,
    verify_no_exclusion_collisions,
)
from backend.app.services.purge_optimizer import (
    analyze_gcode_tool_changes,
    optimize_purge_volume,
)

SAMPLE_SINGLE_COLOR_GCODE = """
; G-Code single color
G28
T0
M104 S215
G1 X10 Y10 E5 F3000
G1 X20 Y20 E10
M104 S0
"""

SAMPLE_MULTICOLOR_GCODE = """
; Bambu Studio Multi-Color GCode
G28
T0 ; Tool 0 (Black PLA)
G1 X10 Y10 E5
T1 ; Tool 1 (White PLA)
; FLUSH_START
G1 X20 Y20 E8
T0 ; Back to Tool 0
; purge volume: 380
G1 X30 Y30 E12
T2 ; Tool 2 (Red PLA)
G1 X40 Y40 E15
T0 ; Tool 0
G1 X50 Y50 E20
"""


def test_single_color_purge_analysis() -> None:
    res = analyze_gcode_tool_changes(SAMPLE_SINGLE_COLOR_GCODE)
    assert res["is_multicolor"] is False
    assert res["total_tool_changes"] == 0
    assert res["estimated_unoptimized_flush_grams"] == 0.0

    opt = optimize_purge_volume(SAMPLE_SINGLE_COLOR_GCODE)
    assert opt["optimized"] is False
    assert opt["saved_grams"] == 0.0


def test_multicolor_purge_optimization() -> None:
    res = analyze_gcode_tool_changes(SAMPLE_MULTICOLOR_GCODE)
    assert res["is_multicolor"] is True
    assert res["total_tool_changes"] == 4
    assert len(res["tools_detected"]) == 3
    assert res["estimated_unoptimized_flush_grams"] > 0.0

    opt = optimize_purge_volume(
        SAMPLE_MULTICOLOR_GCODE,
        flush_multiplier=0.65,
        enable_purge_to_infill=True,
        infill_purge_ratio=0.40,
        cost_per_kg_eur=30.0,
    )
    assert opt["optimized"] is True
    assert opt["original_purge_grams"] > opt["optimized_purge_grams"]
    assert opt["saved_grams"] > 0.0
    assert opt["saved_eur"] > 0.0
    assert opt["savings_percent"] > 50.0  # (1 - 0.65*0.6) = ~61% Ersparnis


def test_auto_nesting_respects_exclusion_zones() -> None:
    # 6 Bauteile 40x40 mm
    parts = [
        NestingPart(
            part_id="box",
            name="Box",
            width_mm=40.0,
            depth_mm=40.0,
            height_mm=15.0,
            copies=6,
            allow_rotation=True,
        )
    ]

    # Schadenszone auf dem PEI-Bett: 40x40 Quadrat im Zentrum (X: 100..150, Y: 100..150)
    exclusion_zones = [
        {
            "min_x": 100.0,
            "min_y": 100.0,
            "max_x": 150.0,
            "max_y": 150.0,
            "reason": "Scratched PEI sheet center",
        }
    ]

    res = pack_parts_onto_plates(
        parts,
        bed_width_mm=256.0,
        bed_depth_mm=256.0,
        margin_mm=5.0,
        spacing_mm=4.0,
        exclusion_zones=exclusion_zones,
    )

    assert res["total_parts_placed"] == 6
    assert res["collision_free"] is True
    assert res["exclusion_safe"] is True

    # Manuelle Überprüfung: Keine Bounding Box darf mit [100, 100, 150, 150] überlappen
    plate = res["plates"][0]
    for p in plate["placements"]:
        px0, py0 = p["min_x_mm"], p["min_y_mm"]
        px1, py1 = px0 + p["width_mm"], py0 + p["depth_mm"]
        overlap_x = px0 < 150.0 and px1 > 100.0
        overlap_y = py0 < 150.0 and py1 > 100.0
        assert not (overlap_x and overlap_y), f"Placement {p} collided with exclusion zone!"


@pytest.mark.asyncio
async def test_purge_optimize_api_endpoint(async_client: AsyncClient) -> None:
    resp = await async_client.post(
        "/api/v1/fleet/purge-optimize",
        json={
            "gcode": SAMPLE_MULTICOLOR_GCODE,
            "flush_multiplier": 0.60,
            "enable_purge_to_infill": True,
            "infill_purge_ratio": 0.35,
            "cost_per_kg_eur": 25.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["optimized"] is True
    assert data["saved_grams"] > 0
    assert "Spülmüll" in data["message"]


@pytest.mark.asyncio
async def test_auto_nest_api_with_exclusion_zones(async_client: AsyncClient) -> None:
    resp = await async_client.post(
        "/api/v1/fleet/auto-nest",
        json={
            "parts": [
                {
                    "part_id": "bracket",
                    "name": "Winkel",
                    "width_mm": 50.0,
                    "depth_mm": 30.0,
                    "height_mm": 10.0,
                    "copies": 4,
                }
            ],
            "exclusion_zones": [
                {
                    "min_x": 80.0,
                    "min_y": 80.0,
                    "max_x": 130.0,
                    "max_y": 130.0,
                    "reason": "Deep PEI dent",
                }
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_parts_placed"] == 4
    assert data["collision_free"] is True
    assert data["exclusion_safe"] is True
