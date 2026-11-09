"""Unit-Tests für GPIO Hardware-Taster, Entprellung & Not-Halt-Dienst (Phase 5)."""

from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.gpio_hardware import GpioHardwareService


def test_gpio_service_initial_state(tmp_path):
    cfg_file = tmp_path / "gpio_hardware.json"
    service = GpioHardwareService(config_path=cfg_file)

    status = service.get_status()
    assert status["estop_triggered"] is False
    assert status["is_simulated"] is True
    assert status["pins"]["estop"]["pin"] == 26
    assert status["pins"]["estop"]["mode"] == "nc"


def test_gpio_service_estop_trigger_and_reset(tmp_path):
    cfg_file = tmp_path / "gpio_hardware.json"
    service = GpioHardwareService(config_path=cfg_file)

    # 1. Not-Halt auslösen
    status = service.trigger_emergency_stop(source="test_trigger", user="test_user")
    assert status["estop_triggered"] is True
    assert service.is_estop_active() is True
    assert status["estop_source"] == "test_trigger"
    assert status["led_state"] == "estop"

    # 2. Not-Halt quittieren
    ok, msg = service.reset_emergency_stop(user="test_user")
    assert ok is True
    assert service.is_estop_active() is False
    assert "erfolgreich quittiert" in msg
    assert service.get_status()["led_state"] == "ready"


def test_gpio_service_save_config_and_calibration(tmp_path):
    cfg_file = tmp_path / "gpio_hardware.json"
    service = GpioHardwareService(config_path=cfg_file)

    # Konfiguration speichern
    new_cfg = service.save_config({"debounce_ms": 100, "estop_mode": "no"})
    assert new_cfg["debounce_ms"] == 100
    assert new_cfg["estop_mode"] == "no"

    # Kalibrierung speichern
    ok, msg = service.save_servo_calibration(15.5, 160.0)
    assert ok is True
    assert service.config["door_servo_min_angle"] == 15.5
    assert service.config["door_servo_max_angle"] == 160.0

    # Ungültige Kalibrierung ablehnen
    bad_ok, _ = service.save_servo_calibration(170.0, 10.0)
    assert bad_ok is False


@pytest.mark.asyncio
async def test_gpio_api_endpoints(async_client):
    # 1. Status abfragen
    resp = await async_client.get("/api/v1/printers/hardware/gpio/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "estop_triggered" in data
    assert "pins" in data

    # 2. Not-Halt per API auslösen
    resp_trigger = await async_client.post("/api/v1/printers/hardware/gpio/estop/trigger")
    assert resp_trigger.status_code == 200
    assert resp_trigger.json()["status"]["estop_triggered"] is True

    # 3. Not-Halt per API quittieren
    resp_reset = await async_client.post("/api/v1/printers/hardware/gpio/estop/reset")
    assert resp_reset.status_code == 200
    assert resp_reset.json()["status"]["estop_triggered"] is False

    # 4. Servo-Kalibrierung per API speichern
    resp_cal = await async_client.post(
        "/api/v1/printers/hardware/servo/calibrate",
        json={"min_angle": 12.0, "max_angle": 150.0},
    )
    assert resp_cal.status_code == 200
    assert resp_cal.json()["success"] is True
