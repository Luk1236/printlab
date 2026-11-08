"""Unit-Tests für Düsenwechsel-Wartungsposition & Drucker-Reinigung."""

import pytest
from httpx import AsyncClient

from backend.app.services.maintenance_service_flow import (
    build_service_position_gcode,
    cleaning_motion_routine,
    cold_pull_routine,
    complete_maintenance_task,
    exit_service_position,
    move_to_service_position,
)


def test_build_service_position_gcode() -> None:
    # Standard: kein Vorheizen, Düse sicher aus
    gcode = build_service_position_gcode(lower_bed_mm=180.0, front_x_mm=128.0, front_y_mm=30.0, preheat_nozzle_c=0)
    assert "G1 Z180.0" in gcode
    assert "G1 X128.0 Y30.0" in gcode
    assert "M104 S0" in gcode
    assert "M140 S0" in gcode
    assert "M106 P1 S0" in gcode

    # Mit Vorheizen auf 130°C für Hot-Swap
    gcode_hot = build_service_position_gcode(preheat_nozzle_c=130)
    assert "M104 S130" in gcode_hot


def test_service_position_workflow() -> None:
    res = move_to_service_position(printer_id="P1-TEST", preheat_nozzle_c=0, lower_bed_mm=180.0)
    assert res["success"] is True
    assert res["chamber_light_on"] is True
    assert len(res["steps"]) >= 4
    assert len(res["safety_instructions"]) >= 1

    exit_res = exit_service_position(printer_id="P1-TEST", perform_home=True)
    assert exit_res["success"] is True
    assert exit_res["homed"] is True


def test_cold_pull_multistep_routine() -> None:
    # 1. Heat
    heat = cold_pull_routine(printer_id="P1", step="heat", filament_type="PLA")
    assert heat["step"] == "heat"
    assert heat["target_temp_c"] == 240
    assert heat["is_completed"] is False

    # 2. Cooldown
    cool = cold_pull_routine(printer_id="P1", step="cooldown", filament_type="PLA")
    assert cool["step"] == "cooldown"
    assert cool["target_temp_c"] == 85
    assert cool["is_completed"] is False

    # 3. Pull
    pull = cold_pull_routine(printer_id="P1", step="pull", filament_type="PLA")
    assert pull["step"] == "pull"
    assert "senkrecht nach oben" in pull["next_action"]

    # 4. Inspect
    inspect = cold_pull_routine(printer_id="P1", step="inspect", filament_type="PLA")
    assert inspect["is_completed"] is True

    # Ungültiger Schritt
    with pytest.raises(ValueError):
        cold_pull_routine(printer_id="P1", step="invalid_step")


def test_cleaning_motion_routines() -> None:
    # Carbon-Rods Routine
    carbon = cleaning_motion_routine(printer_id="P1", routine="carbon_rods", cycles=3)
    assert carbon["success"] is True
    assert "G1 X235" in carbon["gcode_sent"]
    assert "Isopropanol" in carbon["instructions"]

    # Z-Spindeln Schmieren
    z_spin = cleaning_motion_routine(printer_id="P1", routine="z_lead_screws", cycles=2)
    assert z_spin["success"] is True
    assert "G1 Z220" in z_spin["gcode_sent"]
    assert "Schmierfett" in z_spin["instructions"]

    # Nozzle Wiper
    wiper = cleaning_motion_routine(printer_id="P1", routine="nozzle_wipe", cycles=4)
    assert wiper["success"] is True
    assert "Wiper" in wiper["instructions"]


def test_complete_maintenance_task() -> None:
    res = complete_maintenance_task(printer_id="P1", component="nozzle", notes="E3D 0.4 Hardened Steel montiert")
    assert res["component"] == "nozzle"
    assert "wear_status" in res
    assert "erfolgreich quittiert" in res["message"]


@pytest.mark.asyncio
async def test_maintenance_flow_api_endpoints(async_client: AsyncClient) -> None:
    # 1. Service Position anfahren
    resp = await async_client.post(
        "/api/v1/maintenance/printers/TEST-PRINTER/service-position",
        json={"preheat_nozzle_c": 0, "lower_bed_mm": 180.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "service_position"
    assert data["bed_z_pos_mm"] == 180.0

    # 2. Cold Pull Step
    cp_resp = await async_client.post(
        "/api/v1/maintenance/printers/TEST-PRINTER/cold-pull",
        json={"step": "heat", "filament_type": "PETG"},
    )
    assert cp_resp.status_code == 200
    assert cp_resp.json()["target_temp_c"] == 250

    # 3. Cleaning Motion
    cm_resp = await async_client.post(
        "/api/v1/maintenance/printers/TEST-PRINTER/cleaning-motion",
        json={"routine": "carbon_rods", "cycles": 2},
    )
    assert cm_resp.status_code == 200
    assert cm_resp.json()["routine"] == "carbon_rods"

    # 4. Quittieren
    done_resp = await async_client.post(
        "/api/v1/maintenance/printers/TEST-PRINTER/complete-task",
        json={"component": "carbon_rods", "notes": "Gereinigt mit IPA 99.9%"},
    )
    assert done_resp.status_code == 200
    assert done_resp.json()["component"] == "steel_rods"

    # 5. Wartungsposition verlassen
    exit_resp = await async_client.post(
        "/api/v1/maintenance/printers/TEST-PRINTER/exit-service-position",
        json={"perform_home": True},
    )
    assert exit_resp.status_code == 200
    assert exit_resp.json()["homed"] is True
