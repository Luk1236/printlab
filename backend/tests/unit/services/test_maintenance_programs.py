"""Tests für die portierten Wartungsprogramme (Öl/Gewindestangen)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services import maintenance_programs as mp


async def _kein_schlafen(_seconds: float) -> None:
    """Beschleunigt die Ablaufprüfung; die Pausen sind hier nicht relevant."""
    return None


class FakeClient:
    def __init__(self, state: str = "IDLE", nozzle: float = 25.0, bed: float = 25.0,
                 connected: bool = True, fail_at: int | None = None):
        self.state = SimpleNamespace(
            connected=connected,
            state=state,
            temperatures={"nozzle": nozzle, "bed": bed},
        )
        self.commands: list[str] = []
        self.fail_at = fail_at

    def send_gcode(self, gcode: str) -> bool:
        if self.fail_at is not None and len(self.commands) + 1 >= self.fail_at:
            return False
        self.commands.append(gcode)
        return True


class TestPlan:
    def test_oel_zwei_durchgaenge_mit_pause(self):
        plan = mp.build_plan("oil", runs=2)
        assert sum(1 for kind, _ in plan if kind == "home") == 2
        assert sum(1 for kind, value in plan if kind == "pause" and value == 60) == 1
        # X und Y werden je einmal hin und zurück gefahren.
        assert sum(1 for kind, _ in plan if kind == "xy") == 12
        assert plan[0] == ("home", None)

    def test_gewindestangen_pausen_und_bewegungen(self):
        plan = mp.build_plan("rods")
        assert sum(1 for kind, value in plan if kind == "pause" and value == 30) == 2
        z = [value for kind, value in plan if kind == "z"]
        assert z.count("+") == z.count("-") + 15  # 3 Startschritte + 12 für die Ölpause
        assert mp.estimate_seconds(plan) > 300

    def test_unbekanntes_programm(self):
        with pytest.raises(ValueError):
            mp.build_plan("spuelen")


class TestGuard:
    def test_bereit(self):
        ok, _ = mp.check_ready(FakeClient().state, "P2S")
        assert ok

    def test_falsches_modell(self):
        ok, message = mp.check_ready(FakeClient().state, "X1C")
        assert not ok
        assert "P2S" in message

    def test_nicht_verbunden(self):
        ok, _ = mp.check_ready(FakeClient(connected=False).state, "P2S")
        assert not ok

    def test_zustand_unbekannt(self):
        ok, _ = mp.check_ready(FakeClient(state="unknown").state, "P2S")
        assert not ok

    def test_waehrend_druck(self):
        ok, message = mp.check_ready(FakeClient(state="RUNNING").state, "P2S")
        assert not ok
        assert "Druck" in message

    def test_zu_heiss(self):
        ok, message = mp.check_ready(FakeClient(nozzle=170, bed=70).state, "P2S")
        assert not ok
        assert "heiß" in message


class TestService:
    @pytest.mark.asyncio
    async def test_oel_laeuft_durch(self):
        client = FakeClient()
        service = mp.MaintenanceProgramService(sleep=_kein_schlafen)
        ok, message = service.start(1, "oil", client, "P2S", runs=1)
        assert ok, message
        await service.wait(1, timeout=5)
        status = service.status(1)
        assert status["phase"] == "done"
        assert status["percent"] == 100
        assert client.commands[0] == "G28"
        assert any("G1 X" in command for command in client.commands)
        assert any("G1 Y" in command for command in client.commands)

    @pytest.mark.asyncio
    async def test_stopp(self):
        client = FakeClient()
        service = mp.MaintenanceProgramService(sleep=_kein_schlafen)
        assert service.start(1, "rods", client, "P2S")[0]
        assert service.stop(1)[0]
        await service.wait(1, timeout=5)
        status = service.status(1)
        assert status["phase"] == "stopped"
        assert not status["active"]

    @pytest.mark.asyncio
    async def test_fehler_wird_gemeldet(self):
        client = FakeClient(fail_at=3)
        service = mp.MaintenanceProgramService(sleep=_kein_schlafen)
        assert service.start(1, "oil", client, "P2S", runs=1)[0]
        await service.wait(1, timeout=5)
        status = service.status(1)
        assert status["phase"] == "error"
        assert status["error"]

    def test_start_verweigert_waehrend_druck(self):
        service = mp.MaintenanceProgramService(sleep=_kein_schlafen)
        ok, message = service.start(1, "oil", FakeClient(state="RUNNING"), "P2S")
        assert not ok
        assert "Druck" in message

    @pytest.mark.asyncio
    async def test_zweiter_start_abgelehnt(self):
        service = mp.MaintenanceProgramService(sleep=_kein_schlafen)
        assert service.start(1, "oil", FakeClient(), "P2S")[0]
        ok, message = service.start(1, "rods", FakeClient(), "P2S")
        assert not ok
        assert "bereits" in message
        service.stop(1)
        await service.wait(1, timeout=5)
