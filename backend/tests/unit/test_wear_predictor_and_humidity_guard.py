"""Unit-Tests für Wear Predictor & AMS Humidity Guard (Phase 18)."""

import pytest
from httpx import AsyncClient

from backend.app.services.humidity_guard import (
    calculate_dew_point,
    evaluate_ams_humidity,
    get_drying_profile,
)
from backend.app.services.wear_predictor import (
    get_material_abrasive_factor,
    is_abrasive_material,
    predict_job_wear,
)


def test_abrasive_factors():
    """Prüft die Multiplikatoren für abrasive Werkstoffe."""
    assert get_material_abrasive_factor("PLA") == 1.0
    assert get_material_abrasive_factor("PETG") == 1.1
    assert get_material_abrasive_factor("PLA-CF") == 5.0
    assert get_material_abrasive_factor("PA-CF") == 6.0
    assert get_material_abrasive_factor("Glow-in-the-dark") == 4.0

    assert is_abrasive_material("PA-CF") is True
    assert is_abrasive_material("PLA") is False


def test_wear_prediction():
    """Prüft die Berechnung von Verschleiß und Düsenlebensdauer."""
    # 10h PLA-CF (Faktor 5x = 50h äquivalente Abnutzung)
    res = predict_job_wear(
        printer_id="P1",
        filament_type="PLA-CF",
        print_time_hours=10.0,
        nozzle_type="nozzle_hardened_steel",
    )
    assert res["effective_wear_hours"] == 50.0
    assert res["is_abrasive"] is True
    assert res["can_safely_print"] is True

    # Abrasives Material auf Messingdüse -> CRITICAL
    res_brass = predict_job_wear(
        printer_id="P1",
        filament_type="PA-CF",
        print_time_hours=5.0,
        nozzle_type="nozzle_brass",
    )
    assert res_brass["can_safely_print"] is False
    assert res_brass["warning_level"] == "CRITICAL"


def test_dew_point_and_drying_profile():
    """Prüft Taupunktberechnung und Trocknungsempfehlungen."""
    # Bei 25°C und 50% RH liegt der Taupunkt bei ca. 13.8°C
    dp = calculate_dew_point(25.0, 50.0)
    assert 13.0 <= dp <= 14.5

    # PA Profil
    pa_prof = get_drying_profile("PA-CF")
    assert pa_prof["max_humidity_pct"] == 20.0
    assert pa_prof["drying_temp_c"] == 80
    assert pa_prof["drying_hours"] == 8

    # TPU Profil
    tpu_prof = get_drying_profile("TPU-95A")
    assert tpu_prof["max_humidity_pct"] == 25.0


def test_evaluate_ams_humidity():
    """Prüft die AMS-Bewertung mit hygroskopischen Materialien."""
    # 22°C, 35% RH (für PLA ok, für PA zu feucht)
    eval_res = evaluate_ams_humidity(
        temp_c=22.0,
        humidity_pct=35.0,
        loaded_filaments=["PLA", "PA-CF"],
    )
    assert eval_res["dew_point_c"] < 22.0
    assert eval_res["overall_drying_recommended"] is True
    assert eval_res["spools"][0]["status"] == "DRY"  # PLA bis 45%
    assert eval_res["spools"][1]["status"] == "NEEDS_DRYING"  # PA max 20%


@pytest.mark.asyncio
async def test_maintenance_api_routes(async_client: AsyncClient):
    """Prüft die neuen Endpunkte unter /api/v1/maintenance/."""
    # 1. Wear Forecast
    w_resp = await async_client.post(
        "/api/v1/maintenance/wear/forecast",
        json={
            "printer_id": "SN-TEST-001",
            "filament_type": "PETG-CF",
            "print_time_hours": 8.5,
            "nozzle_type": "nozzle_hardened_steel",
        },
    )
    assert w_resp.status_code == 200
    assert w_resp.json()["is_abrasive"] is True
    assert w_resp.json()["abrasive_multiplier"] == 5.0

    # 2. AMS Drying Guard
    ams_resp = await async_client.post(
        "/api/v1/maintenance/ams/drying-guard",
        json={
            "temp_c": 21.5,
            "humidity_pct": 18.0,
            "loaded_filaments": ["PA-CF", "PETG"],
        },
    )
    assert ams_resp.status_code == 200
    assert ams_resp.json()["overall_drying_recommended"] is False

    # 3. Preflight Check
    pre_resp = await async_client.post(
        "/api/v1/maintenance/preflight-check",
        json={
            "printer_id": "SN-TEST-001",
            "filament_type": "PA-CF",
            "print_time_hours": 6.0,
            "ams_temp_c": 22.0,
            "ams_humidity_pct": 38.0,  # Zu feucht für PA-CF
            "nozzle_type": "nozzle_hardened_steel",
        },
    )
    assert pre_resp.status_code == 200
    pdata = pre_resp.json()
    assert pdata["preflight_passed"] is False
    assert len(pdata["critical_warnings"]) >= 1
