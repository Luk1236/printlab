"""Unit-Tests für automatischen Druckbett-Auswurf (Phase 22)."""

import pytest
from httpx import AsyncClient

from backend.app.services.auto_ejector import (
    build_toolhead_sweep_gcode,
    can_safely_eject,
    execute_part_ejection,
    get_ejector_config,
    get_material_eject_temp,
    update_ejector_config,
)


def test_ejector_config_defaults_and_updates() -> None:
    cfg = get_ejector_config()
    assert cfg["enabled"] is True
    assert cfg["mode"] == "toolhead_sweep"
    assert cfg["max_bed_temp_c"] == 35.0

    updated = update_ejector_config({"mode": "gpio_servo", "gpio_pin": 23, "max_bed_temp_c": 30.0})
    assert updated["mode"] == "gpio_servo"
    assert updated["gpio_pin"] == 23
    assert updated["max_bed_temp_c"] == 30.0

    # Reset zurück auf Standard
    update_ejector_config({"mode": "toolhead_sweep", "gpio_pin": 18, "max_bed_temp_c": 35.0})


def test_material_eject_temperatures() -> None:
    assert get_material_eject_temp("PLA") == 32.0
    assert get_material_eject_temp("PETG") == 30.0
    assert get_material_eject_temp("ABS") == 45.0
    assert get_material_eject_temp("UNKNOWN_MATERIAL") == 35.0


def test_can_safely_eject_conditions() -> None:
    # 1. Bett zu heiß für PLA (55°C > 32°C)
    safe, reason = can_safely_eject(current_bed_temp=55.0, filament_type="PLA", ignore_temp=False)
    assert safe is False
    assert "zu heiß" in reason

    # 2. Bett ausreichend abgekühlt (28°C <= 32°C)
    safe_cold, reason_cold = can_safely_eject(current_bed_temp=28.0, filament_type="PLA", ignore_temp=False)
    assert safe_cold is True
    assert "abgekühlt" in reason_cold

    # 3. Force-Override (Bett 60°C, aber ignore_temp=True)
    safe_force, reason_force = can_safely_eject(current_bed_temp=60.0, filament_type="PLA", ignore_temp=True)
    assert safe_force is True
    assert "übersprungen" in reason_force


def test_build_toolhead_sweep_gcode() -> None:
    gcode = build_toolhead_sweep_gcode(bed_width=256.0, bed_depth=256.0)
    assert "M104 S0" in gcode
    assert "G1 Z8 F1200" in gcode
    assert "Y20.0" in gcode
    assert "G1 X18 Y258" in gcode


def test_execute_part_ejection() -> None:
    # Gesperrt bei 60°C
    res_blocked = execute_part_ejection(printer_id="P1", current_bed_temp=60.0, filament_type="PLA", force=False)
    assert res_blocked["success"] is False
    assert res_blocked["ejected"] is False

    # Erfolgreich bei 28°C
    res_ok = execute_part_ejection(printer_id="P1", current_bed_temp=28.0, filament_type="PLA", force=False)
    assert res_ok["success"] is True
    assert res_ok["ejected"] is True
    assert "erfolgreich ausgeworfen" in res_ok["message"]


@pytest.mark.asyncio
async def test_auto_ejector_api_endpoints(async_client: AsyncClient) -> None:
    # 1. Config GET
    cfg_resp = await async_client.get("/api/v1/automation/ejector/config")
    assert cfg_resp.status_code == 200
    assert cfg_resp.json()["enabled"] is True

    # 2. Config PUT
    put_resp = await async_client.put(
        "/api/v1/automation/ejector/config",
        json={"max_bed_temp_c": 33.0},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["max_bed_temp_c"] == 33.0

    # 3. Status GET
    st_resp = await async_client.get("/api/v1/automation/ejector/status/PRINTER-1?current_bed_temp_c=25.0&filament_type=PLA")
    assert st_resp.status_code == 200
    assert st_resp.json()["can_eject"] is True

    # 4. Trigger POST
    trig_resp = await async_client.post(
        "/api/v1/automation/ejector/trigger",
        json={"printer_id": "PRINTER-1", "current_bed_temp_c": 26.0, "filament_type": "PLA"},
    )
    assert trig_resp.status_code == 200
    assert trig_resp.json()["ejected"] is True
