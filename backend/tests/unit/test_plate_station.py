"""Unit Tests für das PrintLab Platten-, Tür- und Waschstationssystem."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from backend.app.services.plate_station_service import (
    DoorState,
    PlateSlotStatus,
    PlateStationService,
    PlateStationState,
    PlateType,
)


@pytest.fixture
def fresh_station(tmp_path):
    state_file = tmp_path / "test_plate_station_state.json"
    srv = PlateStationService(state_file=state_file)
    return srv


@pytest.fixture
def isolated_singleton(tmp_path, monkeypatch):
    """Die Schnittstelle benutzt die gemeinsame Instanz: Zustand und Datei vom Entwicklungsstand trennen."""
    from backend.app.services.plate_station_service import plate_station_service

    monkeypatch.setattr(plate_station_service, "state_file", tmp_path / "plate_station_state.json")
    monkeypatch.setattr(plate_station_service, "state", PlateStationState())
    return plate_station_service


@pytest.mark.asyncio
async def test_door_open_and_close(fresh_station):
    srv = fresh_station
    assert srv.state.door_state == DoorState.CLOSED
    assert srv.state.door_angle_deg == 0.0

    # Tür öffnen
    res_open = await srv.open_door()
    assert res_open["status"] == "ok"
    assert srv.state.door_state == DoorState.OPEN
    assert srv.state.door_angle_deg == 115.0

    # Nochmal öffnen (idempotent)
    res_open_again = await srv.open_door()
    assert res_open_again["status"] == "ok"

    # Tür schließen
    res_close = await srv.close_door()
    assert res_close["status"] == "ok"
    assert srv.state.door_state == DoorState.CLOSED
    assert srv.state.door_angle_deg == 0.0


@pytest.mark.asyncio
async def test_swap_plate_lifecycle(fresh_station):
    srv = fresh_station
    initial_status = srv.get_status()
    assert initial_status["magazine"]["ready_count"] >= 3
    assert initial_status["magazine"]["empty_count"] >= 1

    # Swap durchführen
    res = await srv.swap_plate(target_plate_type=PlateType.TEXTURED_PEI)
    assert res["status"] == "ok"
    assert "erfolgreich" in res["message"]

    # Prüfen, dass alte Platte samt Teilen in Slot 4 abgelegt wurde (FULL: Teile liegen noch drauf)
    slot4 = next(s for s in srv.state.magazine_slots if s.slot_id == res["stored_dirty_slot"])
    assert slot4.status == PlateSlotStatus.FULL

    # Tür muss nach Swap wieder sicher geschlossen sein
    assert srv.state.door_state == DoorState.CLOSED


@pytest.mark.asyncio
async def test_wash_plate_cycle(fresh_station):
    srv = fresh_station
    # Markiere Slot 4 als DIRTY
    srv.update_slot(slot_id=4, status=PlateSlotStatus.DIRTY)

    ipa_before = srv.state.ipa_level_pct
    res_wash = await srv.wash_plate(slot_id=4)
    assert res_wash["status"] == "ok"
    assert res_wash["slot_id"] == 4
    assert res_wash["wash_cycles"] >= 1

    # IPA muss verbraucht worden sein
    assert srv.state.ipa_level_pct < ipa_before

    # Slot 4 muss wieder READY sein
    slot4 = next(s for s in srv.state.magazine_slots if s.slot_id == 4)
    assert slot4.status == PlateSlotStatus.READY


@pytest.mark.asyncio
async def test_plate_station_api_endpoints(async_client: AsyncClient, isolated_singleton):
    # Status abrufen
    resp = await async_client.get("/api/v1/fleet/plate-station/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "door" in data
    assert "magazine" in data
    assert "station" in data

    # Tür öffnen via API
    resp_open = await async_client.post("/api/v1/fleet/plate-station/door/open")
    assert resp_open.status_code == 200
    assert resp_open.json()["status"] == "ok"

    # Tür schließen via API
    resp_close = await async_client.post("/api/v1/fleet/plate-station/door/close")
    assert resp_close.status_code == 200
    assert resp_close.json()["status"] == "ok"

    # Plattenwechsel via API
    resp_swap = await async_client.post("/api/v1/fleet/plate-station/swap", json={"desired_plate_type": "textured_pei"})
    assert resp_swap.status_code == 200
    assert resp_swap.json()["status"] == "ok"
    assert resp_swap.json()["simulated"] is True

    # Slot manuell updaten
    resp_slot = await async_client.post(
        "/api/v1/fleet/plate-station/slots/2", json={"status": "dirty", "label": "Fach 2 - Benutzt"}
    )
    assert resp_slot.status_code == 200
    assert resp_slot.json()["slot"]["status"] == "dirty"

    # Waschen via API
    resp_wash = await async_client.post("/api/v1/fleet/plate-station/wash", json={"slot_id": 2})
    assert resp_wash.status_code == 200
    assert resp_wash.json()["status"] == "ok"
