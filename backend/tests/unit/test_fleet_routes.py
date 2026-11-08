"""Tests for the Fleet Management API routes (overview, batch commands, telemetry sync)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.fleet import _maintenance_printers
from backend.app.models.printer import Printer


@pytest.fixture
def mock_printers():
    _maintenance_printers.clear()
    p1 = Printer(
        id=1,
        name="Voron 2.4",
        serial_number="VORON-001",
        ip_address="192.168.1.10",
        access_code="12345678",
        model="Voron",
        location="Farm A",
        is_active=True,
    )
    p2 = Printer(
        id=2,
        name="Bambu X1C",
        serial_number="X1C-002",
        ip_address="192.168.1.11",
        access_code="12345678",
        model="X1C",
        location="Farm A",
        is_active=True,
    )
    p3 = Printer(
        id=3,
        name="Bambu P1S",
        serial_number="P1S-003",
        ip_address="192.168.1.12",
        access_code="12345678",
        model="P1S",
        location="Farm B",
        is_active=True,
    )
    return [p1, p2, p3]


@pytest.mark.asyncio
async def test_get_fleet_overview(async_client: AsyncClient, db_session: AsyncSession, mock_printers):
    _maintenance_printers.add(3)
    for p in mock_printers:
        db_session.add(p)
    await db_session.commit()

    mock_status_1 = MagicMock(
        connected=True,
        state="RUNNING",
        subtask_name="Benchy.gcode",
        gcode_file="Benchy.gcode",
        progress=45,
        remaining_time=25,
        layer_num=100,
        total_layers=220,
        hms_errors=[],
    )
    mock_status_2 = MagicMock(
        connected=True,
        state="PAUSE",
        subtask_name=None,
        gcode_file=None,
        progress=0,
        remaining_time=None,
        layer_num=0,
        total_layers=0,
        hms_errors=[],
    )

    def get_status_side_effect(pid):
        if pid == 1:
            return mock_status_1
        if pid == 2:
            return mock_status_2
        return None

    with patch("backend.app.api.routes.fleet.printer_manager.get_status", side_effect=get_status_side_effect):
        response = await async_client.get("/api/v1/fleet/overview")

        assert response.status_code == 200
        data = response.json()
        assert data["total_printers"] == 3
        assert data["online_printers"] == 2
        assert data["printing_count"] == 1
        assert data["paused_count"] == 1
        assert data["maintenance_count"] == 1
        assert len(data["active_jobs"]) == 1
        assert data["active_jobs"][0]["printer_name"] == "Voron 2.4"
        assert data["active_jobs"][0]["progress"] == 45
        assert data["locations"] == {"Farm A": 2, "Farm B": 1}


@pytest.mark.asyncio
async def test_fleet_command_pause_and_resume(async_client: AsyncClient, db_session: AsyncSession, mock_printers):
    for p in mock_printers:
        db_session.add(p)
    await db_session.commit()

    mock_client_1 = MagicMock(
        connected=True,
        pause_print=MagicMock(return_value=True),
        resume_print=MagicMock(return_value=True),
    )
    mock_client_2 = MagicMock(
        connected=True,
        pause_print=MagicMock(return_value=True),
        resume_print=MagicMock(return_value=True),
    )

    mock_status_1 = MagicMock(connected=True, state="RUNNING")
    mock_status_2 = MagicMock(connected=True, state="PAUSE")

    with (
        patch(
            "backend.app.api.routes.fleet.printer_manager.get_client",
            side_effect=lambda pid: mock_client_1 if pid == 1 else (mock_client_2 if pid == 2 else None),
        ),
        patch(
            "backend.app.api.routes.fleet.printer_manager.get_status",
            side_effect=lambda pid: mock_status_1 if pid == 1 else (mock_status_2 if pid == 2 else None),
        ),
    ):
        # 1. Pause command
        resp_pause = await async_client.post("/api/v1/fleet/command", json={"action": "pause"})
        assert resp_pause.status_code == 200
        data_pause = resp_pause.json()
        assert data_pause["action"] == "pause"
        assert data_pause["succeeded"] == [1]
        assert any(s["printer_id"] == 2 for s in data_pause["skipped"])
        mock_client_1.pause_print.assert_called_once()

        # 2. Resume command
        resp_resume = await async_client.post("/api/v1/fleet/command", json={"action": "resume"})
        assert resp_resume.status_code == 200
        data_resume = resp_resume.json()
        assert data_resume["action"] == "resume"
        assert data_resume["succeeded"] == [2]
        assert any(s["printer_id"] == 1 for s in data_resume["skipped"])
        mock_client_2.resume_print.assert_called_once()


@pytest.mark.asyncio
async def test_fleet_command_emergency_stop(async_client: AsyncClient, db_session: AsyncSession, mock_printers):
    for p in mock_printers:
        db_session.add(p)
    await db_session.commit()

    mock_client = MagicMock(
        connected=True,
        stop_print=MagicMock(return_value=True),
        send_gcode=MagicMock(return_value=True),
    )
    mock_status = MagicMock(connected=True, state="RUNNING")

    with (
        patch("backend.app.api.routes.fleet.printer_manager.get_client", return_value=mock_client),
        patch("backend.app.api.routes.fleet.printer_manager.get_status", return_value=mock_status),
    ):
        resp = await async_client.post("/api/v1/fleet/command", json={"action": "emergency_stop", "printer_ids": [1]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "emergency_stop"
        assert data["succeeded"] == [1]
        mock_client.stop_print.assert_called_once()
        mock_client.send_gcode.assert_called_with("M112\n")


@pytest.mark.asyncio
async def test_fleet_command_chamber_light_and_maintenance(
    async_client: AsyncClient, db_session: AsyncSession, mock_printers
):
    for p in mock_printers:
        db_session.add(p)
    await db_session.commit()

    mock_client = MagicMock(connected=True, set_chamber_light=MagicMock(return_value=True))

    with (
        patch("backend.app.api.routes.fleet.printer_manager.get_client", return_value=mock_client),
        patch(
            "backend.app.api.routes.fleet.printer_manager.get_status",
            return_value=MagicMock(connected=True, state="IDLE"),
        ),
        patch("backend.app.api.routes.fleet.printer_manager.disconnect_printer") as mock_disc,
        patch("backend.app.api.routes.fleet.printer_manager.connect_printer", new_callable=AsyncMock) as mock_conn,
    ):
        # 1. Chamber light
        resp_light = await async_client.post(
            "/api/v1/fleet/command", json={"action": "chamber_light_on", "printer_ids": [1, 2]}
        )
        assert resp_light.status_code == 200
        assert resp_light.json()["succeeded"] == [1, 2]
        assert mock_client.set_chamber_light.call_count == 2

        # 2. Maintenance enter
        resp_maint = await async_client.post(
            "/api/v1/fleet/command", json={"action": "maintenance_enter", "printer_ids": [1]}
        )
        assert resp_maint.status_code == 200
        assert resp_maint.json()["succeeded"] == [1]
        mock_disc.assert_called_with(1)

        # 3. Maintenance exit
        resp_exit = await async_client.post(
            "/api/v1/fleet/command", json={"action": "maintenance_exit", "printer_ids": [1]}
        )
        assert resp_exit.status_code == 200
        assert resp_exit.json()["succeeded"] == [1]
        mock_conn.assert_awaited_once()


@pytest.mark.asyncio
async def test_fleet_sync_telemetry(async_client: AsyncClient, db_session: AsyncSession, mock_printers):
    for p in mock_printers:
        db_session.add(p)
    await db_session.commit()

    with patch("backend.app.api.routes.fleet.printer_manager.request_status_update", return_value=True) as mock_req:
        resp = await async_client.post("/api/v1/fleet/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_printers"] == 3
        assert data["updates_requested"] == 3
        assert mock_req.call_count == 3
