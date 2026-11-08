"""Unit-Tests für HX711 Spulen-Wägezelle und Handscanner-Workflow (Phase 21)."""

import pytest
from httpx import AsyncClient

from backend.app.services.handheld_scanner import (
    assign_spool_to_printer_slot,
    process_barcode_input,
)
from backend.app.services.spool_scale_hx711 import (
    calibrate_scale,
    get_empty_spool_tare,
    get_scale_status,
    read_spool_net_weight,
    tare_scale,
    verify_job_filament_preflight,
)


def test_spool_tare_weights() -> None:
    assert get_empty_spool_tare("bambu_reusable") == 230.0
    assert get_empty_spool_tare("polymaker") == 240.0
    assert get_empty_spool_tare("prusament") == 195.0
    assert get_empty_spool_tare("cardboard") == 180.0
    assert get_empty_spool_tare("custom", custom_tare=215.5) == 215.5


def test_scale_tare_and_calibration() -> None:
    t_res = tare_scale()
    assert t_res["success"] is True

    c_res = calibrate_scale(known_weight_grams=500.0, raw_reading=210000.0)
    assert c_res["success"] is True
    assert c_res["calibration_factor"] == 420.0

    stat = get_scale_status()
    assert stat["is_active"] is True
    assert "bambu_reusable" in stat["spool_profiles"]


def test_read_spool_net_weight() -> None:
    # 1000g Gesamtgewicht auf der Waage, Bambu Spule (230g Tara) -> 770g Netto
    res = read_spool_net_weight(spool_type="bambu_reusable", mock_gross_grams=1000.0)
    assert res["gross_weight_grams"] == 1000.0
    assert res["tare_weight_grams"] == 230.0
    assert res["net_filament_grams"] == 770.0


def test_spool_preflight_verification() -> None:
    # Ausreichend Material: 400g benötigt, 770g vorhanden -> OK
    ok_res = verify_job_filament_preflight(
        required_grams=400.0,
        spool_type="bambu_reusable",
        safety_margin_grams=15.0,
        mock_gross_grams=1000.0,
    )
    assert ok_res["can_safely_print"] is True
    assert ok_res["deficit_grams"] == 0.0
    assert ok_res["warning"] is None

    # Zu wenig Material: 800g benötigt (+ 10g Puffer = 810g), aber nur 770g da
    fail_res = verify_job_filament_preflight(
        required_grams=800.0,
        spool_type="bambu_reusable",
        safety_margin_grams=10.0,
        mock_gross_grams=1000.0,
    )
    assert fail_res["can_safely_print"] is False
    assert fail_res["deficit_grams"] == 40.0
    assert "Filamentmangel" in fail_res["warning"]


def test_handheld_scanner_workflows() -> None:
    # 1. Spule
    s_res = process_barcode_input("SPOOL-10482")
    assert s_res["action_type"] == "spool_identify"
    assert s_res["matched_entity"]["spool_id"] == "10482"

    # 2. Druckauftrag
    j_res = process_barcode_input("JOB-82910482")
    assert j_res["action_type"] == "job_inspect"
    assert j_res["matched_entity"]["job_id"] == "82910482"

    # 3. Bestellung
    o_res = process_barcode_input("ORD-2026-0091")
    assert o_res["action_type"] == "order_update"
    assert o_res["matched_entity"]["new_status"] == "PACKED"

    # 4. Spoolman Nummer
    num_res = process_barcode_input("42")
    assert num_res["action_type"] == "spool_identify"
    assert num_res["matched_entity"]["spool_id"] == "42"

    # Slot-Zuweisung
    assign = assign_spool_to_printer_slot(spool_id="10482", printer_id="P1", tray_slot=2)
    assert assign["success"] is True
    assert assign["tray_slot"] == 2


@pytest.mark.asyncio
async def test_scale_and_scanner_api_endpoints(async_client: AsyncClient) -> None:
    # Scale Status
    st_resp = await async_client.get("/api/v1/hardware/scale/status")
    assert st_resp.status_code == 200
    assert st_resp.json()["is_active"] is True

    # Scale Tare
    t_resp = await async_client.post("/api/v1/hardware/scale/tare")
    assert t_resp.status_code == 200

    # Scale Read Spool
    r_resp = await async_client.post(
        "/api/v1/hardware/scale/read-spool",
        json={"spool_type": "bambu_reusable"},
    )
    assert r_resp.status_code == 200
    assert "net_filament_grams" in r_resp.json()

    # Preflight Check
    pf_resp = await async_client.post(
        "/api/v1/hardware/scale/verify-preflight",
        json={"required_grams": 120.0, "spool_type": "bambu_reusable"},
    )
    assert pf_resp.status_code == 200
    assert "can_safely_print" in pf_resp.json()

    # Scanner Scan
    sc_resp = await async_client.post(
        "/api/v1/hardware/scanner/scan",
        json={"raw_barcode": "SPOOL:502"},
    )
    assert sc_resp.status_code == 200
    assert sc_resp.json()["action_type"] == "spool_identify"

    # Scanner Spool Assignment
    as_resp = await async_client.post(
        "/api/v1/hardware/scanner/assign-spool-to-slot",
        json={"spool_id": "502", "printer_id": "P1", "tray_slot": 1},
    )
    assert as_resp.status_code == 200
    assert as_resp.json()["success"] is True
