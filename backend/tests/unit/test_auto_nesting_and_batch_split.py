"""Unit- & API-Tests für Phase 13: 2D Auto-Nesting, 3D-Orientierungs-Analyse, M486-Injektor & Farm-Seriensplit."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from backend.app.models.printer import Printer
from backend.app.services.auto_nesting import (
    NestingPart,
    inject_m486_object_markers,
    pack_parts_onto_plates,
    split_batch_across_fleet,
    suggest_optimal_orientation,
)


def test_2d_bin_packing_with_90_degree_rotation_and_multi_plate_overflow():
    """Prüft kollisionsfreies 2D-Bin-Packing inkl. 90°-Drehung und Überlauf auf mehrere Platten."""
    parts = [
        # Bauteil 220x60 passt nur gedreht oder normal 3x nebeneinander (3 * 64 = 192 <= 246)
        NestingPart(
            part_id="rail",
            name="Führungsschiene",
            width_mm=220.0,
            depth_mm=60.0,
            height_mm=15.0,
            copies=5,
            allow_rotation=True,
            filament_grams_per_copy=35.0,
            print_minutes_per_copy=45.0,
        ),
        NestingPart(
            part_id="clip",
            name="Halteclip",
            width_mm=40.0,
            depth_mm=30.0,
            height_mm=12.0,
            copies=12,
            allow_rotation=True,
            filament_grams_per_copy=5.0,
            print_minutes_per_copy=10.0,
        ),
    ]
    res = pack_parts_onto_plates(parts, bed_width_mm=256.0, bed_depth_mm=256.0, margin_mm=5.0, spacing_mm=4.0)
    assert res["total_parts_requested"] == 17
    assert res["total_parts_placed"] == 17
    assert res["total_plates"] == 2
    assert res["collision_free"] is True
    assert res["oversized_parts"] == []
    assert res["total_filament_grams"] == round(5 * 35.0 + 12 * 5.0, 2)
    assert res["total_estimated_minutes"] == round(5 * 45.0 + 12 * 10.0, 2)


def test_2d_bin_packing_rotation_unlocks_wide_part_and_rejects_oversized():
    """Ein 60×240 mm Bauteil auf einem 250×100 mm Bett passt NUR mit 90°-Drehung."""
    part_rot = NestingPart(part_id="p1", name="Langteil", width_mm=60.0, depth_mm=230.0, copies=1, allow_rotation=True)
    part_no_rot = NestingPart(
        part_id="p2", name="Langteil-Gesperrt", width_mm=60.0, depth_mm=230.0, copies=1, allow_rotation=False
    )
    res = pack_parts_onto_plates(
        [part_rot, part_no_rot], bed_width_mm=250.0, bed_depth_mm=100.0, margin_mm=5.0, spacing_mm=2.0
    )
    assert res["total_parts_placed"] == 1
    assert len(res["oversized_parts"]) == 1
    assert res["oversized_parts"][0]["part_id"] == "p2"
    placement = res["plates"][0]["placements"][0]
    assert placement["part_id"] == "p1"
    assert placement["rotated_90"] is True
    assert placement["width_mm"] == 230.0
    assert placement["depth_mm"] == 60.0


def test_suggest_optimal_orientation_prefers_flat_stable_posture():
    """Ein schmaler, hoher Turm (20×20×150 mm) sollte flach gelegt werden (+90° X oder Y)."""
    result = suggest_optimal_orientation(
        (20.0, 20.0, 150.0),
        overhang_ratio_by_axis={"z_up": 0.05, "x_plus": 0.04, "y_plus": 0.08},
    )
    rec = result["recommended"]
    assert rec["orientation_id"] == "rotate_x_plus_90"
    assert rec["height_mm"] == 20.0
    assert rec["footprint_area_mm2"] == 3000.0
    assert rec["score"] > result["alternatives"][-1]["score"]


def test_inject_m486_object_markers_adds_missing_tags():
    """Prüft das Einfügen von M486 T<n>, M486 S<idx> und M486 S-1 in Slicer-G-Code."""
    raw_gcode = (
        "G28 ; Home\n"
        "; printing object Gehäuse_Links id:0\n"
        "G1 X10 Y10 E1.2\n"
        "; stop printing object Gehäuse_Links\n"
        "; printing object Gehäuse_Rechts id:1\n"
        "G1 X80 Y80 E2.4\n"
        "; stop printing object Gehäuse_Rechts\n"
        "M104 S0\n"
    )
    processed = inject_m486_object_markers(raw_gcode)
    assert processed["total_objects"] == 2
    assert processed["object_names"] == ["Gehäuse_Links", "Gehäuse_Rechts"]
    assert processed["already_had_m486"] is False
    assert processed["injected_markers"] == 5  # 1x T2, 2x S0/S1, 2x S-1
    assert "M486 T2" in processed["gcode"]
    assert "M486 S0" in processed["gcode"]
    assert "M486 S1" in processed["gcode"]
    assert "M486 S-1" in processed["gcode"]


def test_split_batch_across_fleet_balances_makespan():
    """Verteilt 4 Bauplatten auf 2 freie Farm-Drucker und halbiert die Durchlaufzeit."""
    parts = [
        NestingPart(
            part_id="box",
            name="Gehäuse",
            width_mm=110.0,
            depth_mm=110.0,
            copies=16,  # 4 Stück pro 256×256 Platte -> 4 Platten à 80 Min
            filament_grams_per_copy=20.0,
            print_minutes_per_copy=20.0,
        )
    ]
    nesting = pack_parts_onto_plates(parts)
    assert nesting["total_plates"] == 4

    printers = [
        {
            "id": 1,
            "name": "Farm-P1",
            "connected": True,
            "state": "IDLE",
            "plate_clear": True,
            "bed_temp": 25.0,
            "nozzle_diameter": 0.4,
            "is_hardened_nozzle": True,
            "total_operating_hours": 100.0,
            "ams_slots": [{"slot_id": "0-0", "material": "PLA", "color": "000000", "remaining_grams": 900.0}],
        },
        {
            "id": 2,
            "name": "Farm-P2",
            "connected": True,
            "state": "IDLE",
            "plate_clear": True,
            "bed_temp": 26.0,
            "nozzle_diameter": 0.4,
            "is_hardened_nozzle": True,
            "total_operating_hours": 120.0,
            "ams_slots": [{"slot_id": "0-0", "material": "PLA", "color": "000000", "remaining_grams": 850.0}],
        },
    ]
    split = split_batch_across_fleet(
        nesting, printers, job_requirements={"material": "PLA", "color": "000000", "nozzle_diameter": 0.4}
    )
    assert split["can_dispatch_parallel"] is True
    assert split["printers_used"] == 2
    assert split["single_printer_minutes"] == 320.0
    assert split["parallel_makespan_minutes"] == 160.0
    assert split["speedup_factor"] == 2.0


@pytest.mark.asyncio
async def test_phase13_fleet_api_endpoints(async_client: AsyncClient, db_session):
    """End-to-End API-Test für /fleet/auto-nest, /fleet/batch-split, /fleet/orientation-check und /fleet/gcode-m486."""
    p1 = Printer(name="API-Farm-1", serial_number="SN-N1", ip_address="192.168.1.91", access_code="111", is_active=True)
    p2 = Printer(name="API-Farm-2", serial_number="SN-N2", ip_address="192.168.1.92", access_code="222", is_active=True)
    db_session.add_all([p1, p2])
    await db_session.commit()

    fake_state = SimpleNamespace(
        connected=True,
        state="IDLE",
        temperatures={"bed": 24.0},
        nozzles=[SimpleNamespace(nozzle_diameter="0.4")],
        raw_data={"ams": [{"id": 0, "tray": [{"id": 0, "tray_type": "PETG", "tray_color": "FF0000", "remain": 90}]}]},
    )

    with patch("backend.app.api.routes.fleet.printer_manager.get_status", return_value=fake_state):
        # 1. /fleet/auto-nest
        nest_resp = await async_client.post(
            "/api/v1/fleet/auto-nest",
            json={
                "parts": [
                    {"part_id": "adapter", "name": "Adapterplatte", "width_mm": 100.0, "depth_mm": 100.0, "copies": 8}
                ]
            },
        )
        assert nest_resp.status_code == 200
        assert nest_resp.json()["total_plates"] == 2

        # 2. /fleet/batch-split
        split_resp = await async_client.post(
            "/api/v1/fleet/batch-split",
            json={
                "parts": [
                    {
                        "part_id": "adapter",
                        "name": "Adapterplatte",
                        "width_mm": 100.0,
                        "depth_mm": 100.0,
                        "copies": 8,
                        "print_minutes_per_copy": 30.0,
                    }
                ],
                "material": "PETG",
                "color": "FF0000",
            },
        )
        assert split_resp.status_code == 200
        split_data = split_resp.json()["fleet_split"]
        assert split_data["can_dispatch_parallel"] is True
        assert split_data["speedup_factor"] == 2.0

        # 3. /fleet/orientation-check
        orient_resp = await async_client.post(
            "/api/v1/fleet/orientation-check",
            json={"width_mm": 15.0, "depth_mm": 15.0, "height_mm": 120.0},
        )
        assert orient_resp.status_code == 200
        assert orient_resp.json()["recommended"]["height_mm"] == 15.0

        # 4. /fleet/gcode-m486
        m486_resp = await async_client.post(
            "/api/v1/fleet/gcode-m486",
            json={"gcode": "; printing object PartA id:0\nG1 X1 Y1\n; stop printing object PartA\n"},
        )
        assert m486_resp.status_code == 200
        assert m486_resp.json()["total_objects"] == 1
        assert "M486 S0" in m486_resp.json()["gcode"]
