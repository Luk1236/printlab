"""Unit-Tests für Touchscreen Kiosk-Modus & SD-Card Wear Guard (Phase 17)."""

import pytest
from httpx import AsyncClient

from backend.app.models.printer import Printer
from backend.app.services.pi_sd_wear_guard import sd_wear_guard


def test_sd_wear_guard_buffering():
    """Prüft das Schreiben und Lesen von Kamera-Snapshots in den RAM-Puffer."""
    dummy_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01" + b"\x00" * 50
    path = sd_wear_guard.buffer_snapshot(printer_id=99, image_bytes=dummy_jpg)

    assert path.is_file()
    assert path.name == "cam_99.jpg"

    read_back = sd_wear_guard.get_buffered_snapshot(printer_id=99)
    assert read_back == dummy_jpg

    stats = sd_wear_guard.get_stats()
    assert stats["sd_writes_saved"] >= 1
    assert stats["buffered_size_bytes"] > 0
    assert "ram_disk_free_mb" in stats


def test_sd_wear_guard_cleanup():
    """Prüft das Bereinigen der Pufferdateien."""
    cleaned = sd_wear_guard.cleanup_old_buffers()
    assert cleaned >= 0


@pytest.mark.asyncio
async def test_kiosk_api_routes(async_client: AsyncClient, db_session):
    """Prüft die Touchscreen-Endpunkte unter /api/v1/kiosk/."""
    # Drucker anlegen für Tests
    printer = Printer(
        name="Kiosk-X1C",
        model="X1-Carbon",
        serial_number="SN-KIOSK-001",
        ip_address="192.168.1.150",
        access_code="12345678",
    )
    db_session.add(printer)
    await db_session.commit()

    # 1. Kiosk Status
    status_resp = await async_client.get("/api/v1/kiosk/status")
    assert status_resp.status_code == 200
    sdata = status_resp.json()
    assert "printers" in sdata
    assert "sd_wear_guard" in sdata
    assert sdata["total_printers"] >= 1

    # 2. Quick Action: Preheat PLA
    preheat_resp = await async_client.post(
        f"/api/v1/kiosk/printers/{printer.id}/quick-action",
        json={"action": "preheat", "preset": "PLA"},
    )
    assert preheat_resp.status_code == 200
    pdata = preheat_resp.json()
    assert pdata["success"] is True
    assert pdata["bed_temp"] == 55
    assert pdata["nozzle_temp"] == 220

    # 3. Quick Action: Plate Clear
    clear_resp = await async_client.post(
        f"/api/v1/kiosk/printers/{printer.id}/quick-action",
        json={"action": "plate_clear"},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["success"] is True

    # 4. Quick Action: E-Stop ohne Bestätigung -> 400
    estop_fail = await async_client.post(
        f"/api/v1/kiosk/printers/{printer.id}/quick-action",
        json={"action": "e_stop", "confirmed": False},
    )
    assert estop_fail.status_code == 400

    # 5. Quick Action: E-Stop mit Bestätigung -> 200
    estop_ok = await async_client.post(
        f"/api/v1/kiosk/printers/{printer.id}/quick-action",
        json={"action": "e_stop", "confirmed": True},
    )
    assert estop_ok.status_code == 200
    assert estop_ok.json()["success"] is True

    # 6. SD Guard Stats & Cleanup
    stats_resp = await async_client.get("/api/v1/kiosk/sd-guard/stats")
    assert stats_resp.status_code == 200
    assert "sd_writes_saved" in stats_resp.json()

    clean_resp = await async_client.post("/api/v1/kiosk/sd-guard/cleanup")
    assert clean_resp.status_code == 200
    assert clean_resp.json()["success"] is True
