"""Plattenstation: Wechselzyklus, Plattenbilanz, Sperren, Fehlerfall und Umzug alter Stände."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from backend.app.services import plate_changer
from backend.app.services.gpio_hardware import gpio_service
from backend.app.services.plate_station_service import (
    DoorState,
    PlateSlotStatus,
    PlateStationService,
    PlateStationState,
    PlateType,
    SimulatedDriver,
)


@pytest.fixture
def station(tmp_path):
    return PlateStationService(state_file=tmp_path / "state.json")


def _plates(srv: PlateStationService) -> int:
    """Alle Platten der Anlage: die in den Fächern plus die auf dem Bett."""
    return sum(1 for s in srv.state.magazine_slots if s.status != PlateSlotStatus.EMPTY) + (
        1 if srv.state.bed_plate else 0
    )


class TestSwapCycle:
    async def test_runs_every_phase_in_order_and_ends_with_a_closed_door(self, station):
        result = await station.swap_plate()

        assert result["status"] == "ok"
        assert result["phases"] == [p.id for p in plate_changer.PHASES]
        assert result["simulated"] is True
        assert station.state.door_state == DoorState.CLOSED and station.state.door_angle_deg == 0.0
        assert station.state.current_phase is None and station.state.is_swapping is False

    async def test_the_used_plate_moves_to_the_free_slot_and_the_fresh_one_onto_the_bed(self, station):
        before_bed = station.state.bed_plate
        fresh = next(s for s in station.state.magazine_slots if s.status == PlateSlotStatus.READY)
        fresh_barcode = fresh.barcode

        result = await station.swap_plate()

        stored = next(s for s in station.state.magazine_slots if s.slot_id == result["stored_dirty_slot"])
        assert stored.status == PlateSlotStatus.FULL and stored.barcode == before_bed.barcode
        assert station.state.bed_plate.barcode == fresh_barcode
        assert fresh.status == PlateSlotStatus.EMPTY and fresh.barcode == ""
        assert result["active_slot"] == fresh.slot_id

    async def test_no_plate_is_ever_lost_or_doubled(self, station):
        total = _plates(station)
        for _ in range(3):
            result = await station.swap_plate()
            assert result["status"] == "ok"
            assert _plates(station) == total
            assert sum(1 for s in station.state.magazine_slots if s.status == PlateSlotStatus.PRINTING) == 0
            await station.wash_plate()  # frei gewordenes Fach füllt sich wieder mit einer sauberen Platte

    async def test_the_requested_plate_type_is_used(self, station):
        result = await station.swap_plate(target_plate_type=PlateType.HIGH_TEMP)

        assert result["status"] == "ok"
        assert station.state.bed_plate.plate_type == PlateType.HIGH_TEMP

    async def test_without_a_plate_on_the_bed_nothing_needs_to_be_stored(self, station):
        station.state.bed_plate = None
        for slot in station.state.magazine_slots:
            slot.status = PlateSlotStatus.READY  # kein freies Fach

        result = await station.swap_plate()

        assert result["status"] == "ok" and result["stored_dirty_slot"] is None
        assert station.state.bed_plate is not None

    async def test_refuses_when_there_is_no_free_slot_for_the_old_plate(self, station):
        for slot in station.state.magazine_slots:
            slot.status = PlateSlotStatus.READY

        result = await station.swap_plate()

        assert result["status"] == "error" and "leeres" in result["message"].lower()
        assert station.state.door_state == DoorState.CLOSED

    async def test_only_slots_with_a_height_are_used(self, station):
        from backend.app.services.plate_station_service import MagazineSlot

        station.state.magazine_slots.append(
            MagazineSlot(plate_changer.SLOT_COUNT + 1, "Fach 5", PlateType.TEXTURED_PEI, PlateSlotStatus.EMPTY)
        )
        for slot in station.state.magazine_slots[: plate_changer.SLOT_COUNT]:
            slot.status = PlateSlotStatus.READY  # 1-4 voll: das 5. Fach darf nicht einspringen

        result = await station.swap_plate()

        assert result["status"] == "error"


class TestPartsStayOnThePlate:
    async def test_the_plate_goes_into_the_rack_with_its_parts(self, station):
        result = await station.swap_plate()

        stored = next(s for s in station.state.magazine_slots if s.slot_id == result["stored_dirty_slot"])
        assert result["with_parts"] is True and result["stored_slot_status"] == "full"
        assert stored.status == PlateSlotStatus.FULL and stored.last_action == "stored_with_parts"
        assert station.get_status()["magazine"]["full_count"] == 1

    async def test_a_plate_without_parts_is_simply_dirty(self, station):
        result = await station.swap_plate(with_parts=False)

        stored = next(s for s in station.state.magazine_slots if s.slot_id == result["stored_dirty_slot"])
        assert result["with_parts"] is False and stored.status == PlateSlotStatus.DIRTY

    async def test_parts_that_do_not_fit_under_the_next_plate_are_refused_before_anything_moves(self, station):
        # frei ist nur Fach 4, unter der Deckplatte: dort passen höchstens 17 mm
        result = await station.swap_plate(part_height_mm=25.0)

        assert result["status"] == "error" and "17.0" in result["message"]
        assert station.state.door_state == DoorState.CLOSED and station.state.bed_plate is not None

    async def test_low_parts_fit_into_the_top_slot(self, station):
        result = await station.swap_plate(part_height_mm=15.0)

        assert result["status"] == "ok" and result["stored_dirty_slot"] == 4

    async def test_taller_parts_use_a_lower_free_slot(self, station):
        await station.swap_plate(part_height_mm=10.0)  # Fach 1 wird frei, Fach 4 ist jetzt belegt

        result = await station.swap_plate(part_height_mm=28.0)

        assert result["status"] == "ok" and result["stored_dirty_slot"] == 1

    async def test_the_height_is_ignored_when_there_are_no_parts(self, station):
        result = await station.swap_plate(with_parts=False, part_height_mm=400.0)

        assert result["status"] == "ok"

    async def test_a_plate_with_parts_is_not_washed_until_they_are_taken_off(self, station):
        stored = (await station.swap_plate())["stored_dirty_slot"]

        by_slot = await station.wash_plate(slot_id=stored)
        automatic = await station.wash_plate()

        assert by_slot["status"] == "error" and "Teile" in by_slot["message"]
        assert automatic["status"] == "error"  # nichts Schmutziges, die volle Platte zählt nicht
        assert next(s for s in station.state.magazine_slots if s.slot_id == stored).status == PlateSlotStatus.FULL

    async def test_unloading_the_parts_makes_the_plate_ready_for_washing(self, station):
        stored = (await station.swap_plate())["stored_dirty_slot"]

        unloaded = station.unload_parts(stored)
        washed = await station.wash_plate()

        assert unloaded["status"] == "ok" and washed["status"] == "ok" and washed["slot_id"] == stored

    def test_unloading_needs_a_plate_with_parts(self, station):
        assert station.unload_parts(1)["status"] == "error"
        assert station.unload_parts(99)["status"] == "error"

    def test_the_parts_flag_survives_a_restart(self, tmp_path):
        path = tmp_path / "state.json"
        first = PlateStationService(state_file=path)
        first.state.bed_plate.has_parts = True
        first._save_state()

        assert PlateStationService(state_file=path).state.bed_plate.has_parts is True


class TestBlocked:
    async def test_a_blocked_swap_moves_nothing(self, station):
        result = await station.swap_plate(blocked_by=["Während eines Drucks gesperrt."])

        assert result["status"] == "error" and "Drucks" in result["message"]
        assert station.state.door_state == DoorState.CLOSED and station.state.is_swapping is False
        assert station.state.bed_plate is not None

    async def test_blocked_door_and_wash_move_nothing(self, station):
        assert (await station.open_door(blocked_by=["Not-Halt ist aktiv."]))["status"] == "error"
        assert (await station.wash_plate(blocked_by=["Not-Halt ist aktiv."]))["status"] == "error"
        assert station.state.door_state == DoorState.CLOSED


class _FailingDriver(SimulatedDriver):
    def __init__(self, fail_at: str):
        self.fail_at = fail_at
        self.aborted = False

    async def run_phase(self, phase):
        if phase.id == self.fail_at:
            raise RuntimeError("Endschalter nicht erreicht")

    async def abort(self):
        self.aborted = True


class TestFailure:
    async def test_a_failure_names_the_phase_stops_the_drives_and_keeps_the_state_truthful(self, tmp_path):
        driver = _FailingDriver("pull_fresh")
        srv = PlateStationService(state_file=tmp_path / "state.json", driver=driver)

        result = await srv.swap_plate()

        assert result["status"] == "error" and "pull_fresh" in result["message"]
        assert result["phases"][-1] == "lift_fresh"
        assert driver.aborted is True
        assert srv.state.error_message == result["message"]
        assert srv.state.is_swapping is False and srv.state.current_phase is None
        # Die alte Platte liegt schon im Fach, die frische ist noch nicht auf dem Bett.
        assert srv.state.bed_plate is None
        assert sum(1 for s in srv.state.magazine_slots if s.status == PlateSlotStatus.FULL) == 1
        assert srv.state.door_state == DoorState.OPEN  # nicht blind schließen, solange der Arm im Drucker stehen könnte


class TestOldStates:
    def test_an_old_state_with_five_slots_and_a_printing_slot_is_converted(self, tmp_path):
        path = tmp_path / "state.json"
        old = {
            "door_state": "closed",
            "door_angle_deg": 0.0,
            "active_plate_slot": 1,
            "magazine_slots": [
                {
                    "slot_id": 1,
                    "label": "Fach 1",
                    "plate_type": "textured_pei",
                    "status": "printing",
                    "wash_cycles": 12,
                    "last_action": "x",
                    "barcode": "PLT-PEI-01",
                },
                {
                    "slot_id": 2,
                    "label": "Fach 2",
                    "plate_type": "smooth_pei",
                    "status": "ready",
                    "wash_cycles": 8,
                    "last_action": "x",
                    "barcode": "PLT-SMT-02",
                },
                {
                    "slot_id": 3,
                    "label": "Fach 3",
                    "plate_type": "high_temp",
                    "status": "ready",
                    "wash_cycles": 4,
                    "last_action": "x",
                    "barcode": "PLT-HTP-03",
                },
                {
                    "slot_id": 4,
                    "label": "Fach 4",
                    "plate_type": "textured_pei",
                    "status": "empty",
                    "wash_cycles": 0,
                    "last_action": "x",
                    "barcode": "",
                },
                {
                    "slot_id": 5,
                    "label": "Fach 5",
                    "plate_type": "textured_pei",
                    "status": "empty",
                    "wash_cycles": 0,
                    "last_action": "x",
                    "barcode": "",
                },
            ],
        }
        path.write_text(json.dumps(old), encoding="utf-8")

        srv = PlateStationService(state_file=path)

        assert len(srv.state.magazine_slots) == plate_changer.SLOT_COUNT
        assert srv.state.bed_plate.barcode == "PLT-PEI-01" and srv.state.bed_plate.wash_cycles == 12
        assert srv.state.magazine_slots[0].status == PlateSlotStatus.EMPTY
        assert srv.state.active_plate_slot == 1

    def test_a_filled_fifth_slot_is_kept_rather_than_dropped(self, tmp_path):
        path = tmp_path / "state.json"
        slots = [
            {"slot_id": i, "label": f"Fach {i}", "plate_type": "textured_pei", "status": "ready" if i == 5 else "empty"}
            for i in range(1, 6)
        ]
        path.write_text(json.dumps({"magazine_slots": slots}), encoding="utf-8")

        srv = PlateStationService(state_file=path)

        assert len(srv.state.magazine_slots) == 5  # eine Platte würde sonst verschwinden

    def test_the_bed_plate_survives_a_restart(self, tmp_path):
        path = tmp_path / "state.json"
        first = PlateStationService(state_file=path)
        first.state.bed_plate = None
        first._save_state()

        assert PlateStationService(state_file=path).state.bed_plate is None

    def test_a_fresh_state_has_four_slots_and_a_plate_on_the_bed(self):
        state = PlateStationState()
        assert len(state.magazine_slots) == plate_changer.SLOT_COUNT
        assert state.bed_plate is not None and state.active_plate_slot is None


class TestApiGuards:
    @pytest.fixture
    def clean(self, tmp_path, monkeypatch):
        from backend.app.services.plate_station_service import plate_station_service

        monkeypatch.setattr(plate_station_service, "state_file", tmp_path / "state.json")
        monkeypatch.setattr(plate_station_service, "state", PlateStationState())
        monkeypatch.setattr(gpio_service, "is_estop_active", lambda: False)
        return plate_station_service

    @staticmethod
    def _printers(monkeypatch, states: dict[int, SimpleNamespace]):
        from backend.app.api.routes import plate_station_route as route

        monkeypatch.setattr(route.printer_manager, "get_all_statuses", lambda: states)
        monkeypatch.setattr(route.printer_manager, "get_status", lambda printer_id: states.get(printer_id))

    async def test_estop_blocks_every_movement(self, async_client: AsyncClient, clean, monkeypatch):
        monkeypatch.setattr(gpio_service, "is_estop_active", lambda: True)

        for path, body in [("door/open", None), ("door/close", None), ("swap", {}), ("wash", {})]:
            response = await async_client.post(f"/api/v1/fleet/plate-station/{path}", json=body)
            assert response.status_code == 400, path
            assert "Not-Halt" in response.json()["detail"]
        assert clean.state.door_state == DoorState.CLOSED

    async def test_a_running_print_blocks_swap_and_door_opening_but_not_closing_or_washing(
        self, async_client: AsyncClient, clean, monkeypatch
    ):
        self._printers(monkeypatch, {1: SimpleNamespace(state="RUNNING", temperatures={"bed": 60.0})})

        assert (await async_client.post("/api/v1/fleet/plate-station/swap", json={})).status_code == 400
        assert (await async_client.post("/api/v1/fleet/plate-station/door/open")).status_code == 400
        assert (await async_client.post("/api/v1/fleet/plate-station/door/close")).status_code == 200
        clean.state.magazine_slots[3].status = PlateSlotStatus.DIRTY
        assert (await async_client.post("/api/v1/fleet/plate-station/wash", json={"slot_id": 4})).status_code == 200

    async def test_a_hot_bed_blocks_the_swap(self, async_client: AsyncClient, clean, monkeypatch):
        self._printers(monkeypatch, {1: SimpleNamespace(state="FINISH", temperatures={"bed": 70.0})})

        response = await async_client.post("/api/v1/fleet/plate-station/swap", json={})

        assert response.status_code == 400 and "heiß" in response.json()["detail"]

    async def test_an_idle_cool_printer_allows_the_swap(self, async_client: AsyncClient, clean, monkeypatch):
        self._printers(monkeypatch, {1: SimpleNamespace(state="FINISH", temperatures={"bed": 28.0})})

        response = await async_client.post("/api/v1/fleet/plate-station/swap", json={})

        assert response.status_code == 200 and response.json()["status"] == "ok"

    async def test_several_printers_need_an_explicit_printer_id(self, async_client: AsyncClient, clean, monkeypatch):
        idle = SimpleNamespace(state="FINISH", temperatures={"bed": 28.0})
        self._printers(monkeypatch, {1: idle, 2: idle})

        ambiguous = await async_client.post("/api/v1/fleet/plate-station/swap", json={})
        explicit = await async_client.post("/api/v1/fleet/plate-station/swap?printer_id=1", json={})

        assert ambiguous.status_code == 400 and "printer_id" in ambiguous.json()["detail"]
        assert explicit.status_code == 200

    async def test_swap_and_unload_over_the_api(self, async_client: AsyncClient, clean):
        swap = await async_client.post("/api/v1/fleet/plate-station/swap", json={"part_height_mm": 12})
        assert swap.status_code == 200 and swap.json()["stored_slot_status"] == "full"
        slot = swap.json()["stored_dirty_slot"]

        unload = await async_client.post(f"/api/v1/fleet/plate-station/slots/{slot}/unload-parts")
        again = await async_client.post(f"/api/v1/fleet/plate-station/slots/{slot}/unload-parts")
        missing = await async_client.post("/api/v1/fleet/plate-station/slots/99/unload-parts")

        assert unload.status_code == 200 and unload.json()["slot"]["status"] == "dirty"
        assert again.status_code == 400 and missing.status_code == 404

    async def test_too_tall_parts_are_refused_by_the_api(self, async_client: AsyncClient, clean):
        response = await async_client.post("/api/v1/fleet/plate-station/swap", json={"part_height_mm": 25})

        assert response.status_code == 400 and "Platz" in response.json()["detail"]
        assert (
            await async_client.post("/api/v1/fleet/plate-station/swap", json={"part_height_mm": -1})
        ).status_code == 422

    async def test_the_status_reports_that_it_is_a_simulation_and_the_design_findings(
        self, async_client: AsyncClient, clean
    ):
        data = (await async_client.get("/api/v1/fleet/plate-station/status")).json()

        assert data["driver"]["simulated"] is True
        assert data["geometry"]["slot_z"] == list(plate_changer.SLOT_Z)
        assert data["geometry"]["slot_capacity_mm"] == list(plate_changer.SLOT_CAPACITY)
        assert data["design"]["fail"] == [] and "door_portal" in data["design"]["warn"]
        assert [p["id"] for p in data["phases"]] == [p.id for p in plate_changer.PHASES]
        assert data["bed_plate"]["name"] == "Gold PEI"
