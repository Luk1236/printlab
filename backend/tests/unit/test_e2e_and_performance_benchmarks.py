"""Phase 11: E2E Integration & Performance Benchmarks (v2.0.38).

Prüft:
1. WebSocket High-Concurrency Fan-out (100 parallele Clients + Slow-Client-Isolierung).
2. Per-User WebSocket Routing & Metrik-Telemetrie.
3. Flotten-Load-Balancer Durchsatz-Benchmark über 50 simulierte Farm-Drucker.
4. End-to-End Pipeline: 3D-Mesh-Analyse -> Sofort-Kalkulation -> Lieferschein-PDF & Thermo-Versandetikett.
5. End-to-End API Integration: Fleet Overview, Batch Commands, Telemetry Sync & Metrics Endpoint.
"""

from __future__ import annotations

import asyncio
import struct
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.websocket import ConnectionManager, ws_manager
from backend.app.models.printer import Printer
from backend.app.services.customer_portal import calculate_instant_quote
from backend.app.services.delivery_note_service import (
    generate_delivery_note_pdf,
    generate_thermal_label_pdf,
)
from backend.app.services.fleet_load_balancer import dispatch_job_to_fleet
from backend.app.services.mesh_analysis import analyze_mesh_data


def _build_cube_binary_stl(size: float = 20.0) -> bytes:
    """Erzeugt ein valides binäres STL eines Würfels (12 Dreiecke) für E2E-Tests."""
    s = size
    v = [
        (0.0, 0.0, 0.0),
        (s, 0.0, 0.0),
        (s, s, 0.0),
        (0.0, s, 0.0),
        (0.0, 0.0, s),
        (s, 0.0, s),
        (s, s, s),
        (0.0, s, s),
    ]
    triangles = [
        (v[0], v[2], v[1]),
        (v[0], v[3], v[2]),
        (v[4], v[5], v[6]),
        (v[4], v[6], v[7]),
        (v[0], v[1], v[5]),
        (v[0], v[5], v[4]),
        (v[2], v[3], v[7]),
        (v[2], v[7], v[6]),
        (v[0], v[4], v[7]),
        (v[0], v[7], v[3]),
        (v[1], v[2], v[6]),
        (v[1], v[6], v[5]),
    ]
    buf = bytearray(80)  # 80-Byte Header
    buf.extend(struct.pack("<I", len(triangles)))
    for t0, t1, t2 in triangles:
        buf.extend(struct.pack("<12fH", 0.0, 0.0, 0.0, *t0, *t1, *t2, 0))
    return bytes(buf)


@pytest.mark.asyncio
async def test_websocket_concurrent_fanout_and_slow_client_isolation():
    """100 gesunde Clients + 2 blockierende/fehlerhafte Clients müssen parallel bedient werden."""
    manager = ConnectionManager(send_timeout=0.05)

    healthy_clients = []
    for _ in range(100):
        ws = MagicMock()
        ws.accept = AsyncMock()

        async def _fast_send(_data: str):
            await asyncio.sleep(0.005)

        ws.send_text = AsyncMock(side_effect=_fast_send)
        await manager.connect(ws)
        healthy_clients.append(ws)

    # 1 Client wirft sofort ConnectionResetError, 1 Client hängt über das Timeout hinaus
    broken_client = MagicMock()
    broken_client.accept = AsyncMock()
    broken_client.send_text = AsyncMock(side_effect=ConnectionResetError("Socket closed"))
    await manager.connect(broken_client)

    stalled_client = MagicMock()
    stalled_client.accept = AsyncMock()

    async def _hung_send(_data: str):
        await asyncio.sleep(5.0)

    stalled_client.send_text = AsyncMock(side_effect=_hung_send)
    await manager.connect(stalled_client)

    assert len(manager.active_connections) == 102

    t0 = time.perf_counter()
    await manager.broadcast({"type": "printer_status", "printer_id": 1, "data": {"state": "RUNNING"}})
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # Paralleles Fanout + 50ms Timeout darf trotz 100 Clients + Hänger < 1000ms dauern (sequenziell wären es >5500ms)
    assert elapsed_ms < 1000.0, f"Broadcast zu langsam: {elapsed_ms:.1f}ms"
    assert len(manager.active_connections) == 100
    assert broken_client not in manager.active_connections
    assert stalled_client not in manager.active_connections

    metrics = manager.get_metrics()
    assert metrics["active_connections"] == 100
    assert metrics["total_broadcasts"] == 1
    assert metrics["total_messages_sent"] == 100
    assert metrics["dropped_connections"] == 2
    assert metrics["last_broadcast_ms"] > 0.0


@pytest.mark.asyncio
async def test_websocket_per_user_broadcast_isolation():
    """Prüft gezieltes User-Routing via printlab_principal_user_id unter Last."""
    manager = ConnectionManager(send_timeout=0.1)

    user1_ws = MagicMock()
    user1_ws.accept = AsyncMock()
    user1_ws.send_text = AsyncMock()
    user1_ws.state = SimpleNamespace(printlab_principal_user_id=10)

    user2_ws = MagicMock()
    user2_ws.accept = AsyncMock()
    user2_ws.send_text = AsyncMock()
    user2_ws.state = SimpleNamespace(printlab_principal_user_id=20)

    await manager.connect(user1_ws)
    await manager.connect(user2_ws)

    await manager.broadcast_to_user(10, {"type": "queue_item_acked", "queue_item_id": 99})

    user1_ws.send_text.assert_awaited_once()
    user2_ws.send_text.assert_not_awaited()


def test_fleet_load_balancer_50_printers_benchmark():
    """Benchmark: Dispatch-Entscheidung über 50 Farm-Drucker in unter 50ms."""
    fleet = []
    for i in range(1, 51):
        fleet.append(
            {
                "id": i,
                "name": f"Farm-P2S-{i:02d}",
                "model": "Bambu Lab P2S",
                "connected": True,
                "state": "IDLE" if i % 3 != 0 else "RUNNING",
                "plate_clear": i % 3 != 0,
                "bed_temp": 24.0 + (i % 15),
                "nozzle_diameter": 0.4,
                "is_hardened_nozzle": i % 2 == 0,
                "ams_slots": [
                    {
                        "slot_id": "0-0",
                        "material": "PETG" if i % 4 == 0 else "PLA",
                        "color": "FF5500" if i == 28 else "000000",
                        "remaining_percent": 85.0,
                        "remaining_grams": 850.0,
                    }
                ],
                "total_operating_hours": float(i * 12),
            }
        )

    job = {
        "name": "Gehaerteter-Halter.3mf",
        "material": "PETG",
        "color": "FF5500",
        "filament_grams": 120.0,
        "nozzle_diameter": 0.4,
        "requires_hardened_nozzle": True,
    }

    t0 = time.perf_counter()
    result = dispatch_job_to_fleet(job, fleet)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert elapsed_ms < 50.0, f"Load Balancer zu langsam für 50 Drucker: {elapsed_ms:.2f}ms"
    assert result["status"] == "DISPATCHED"
    assert result["selected_printer_id"] == 28
    assert len(result["candidates"]) == 50


def test_e2e_mesh_to_quote_to_pdf_and_thermal_labels_benchmark():
    """End-to-End Pipeline: STL-Analyse -> Sofort-Kalkulation -> DIN A4 Lieferschein & Thermo-Labels."""
    t0 = time.perf_counter()
    stl_bytes = _build_cube_binary_stl(20.0)

    # 1. 3D-Mesh-Analyse (20x20x20mm Würfel = 8.0 cm³)
    analysis = analyze_mesh_data(stl_bytes, "wuerfel_20mm.stl")
    mesh = analysis.to_dict()
    assert mesh["filename"] == "wuerfel_20mm.stl"
    assert abs(mesh["volume_cm3"] - 8.0) < 0.1
    assert mesh["dimensions_mm"]["x"] == pytest.approx(20.0, abs=0.1)
    assert mesh["fits_bed"] is True

    # 2. Sofort-Kalkulation auf Basis der echten Mesh-Geometrie
    quote = calculate_instant_quote(
        volume_cm3=analysis.volume_cm3,
        filament_type="PLA",
        infill_percent=20,
        layer_height=0.2,
        quantity=5,
    )
    quote["filename"] = "wuerfel_20mm.stl"
    quote["customer_name"] = "Industriebedarf Nord GmbH"
    quote["customer_address"] = "Werkstraße 12\n20457 Hamburg"
    quote["analysis"] = mesh
    assert quote["quantity"] == 5
    assert quote["pricing"]["gross_total_eur"] > 0

    # 3. DIN A4 Lieferschein-PDF + 2 Thermo-Versandetiketten (100x150 & 62x29)
    delivery_pdf = generate_delivery_note_pdf(quote)
    label_100x150 = generate_thermal_label_pdf(quote, format_size="100x150")
    label_62x29 = generate_thermal_label_pdf(quote, format_size="62x29")

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert delivery_pdf.startswith(b"%PDF-")
    assert label_100x150.startswith(b"%PDF-")
    assert label_62x29.startswith(b"%PDF-")
    assert elapsed_ms < 1500.0, f"E2E-Dokumentenpipeline zu langsam: {elapsed_ms:.1f}ms"


@pytest.mark.asyncio
async def test_e2e_fleet_api_and_metrics_workflow(async_client: AsyncClient, db_session: AsyncSession):
    """End-to-End API-Durchstich: Drucker anlegen -> WS-Broadcast -> Fleet Overview -> Batch Command -> Metrics."""
    ws_manager.reset_metrics()

    p = Printer(
        id=10,
        name="E2E-Bambu-X1C",
        serial_number="E2E-X1C-010",
        ip_address="192.168.10.10",
        access_code="87654321",
        model="X1C",
        location="Halle 1",
        is_active=True,
    )
    db_session.add(p)
    await db_session.commit()

    # Simuliere einen verbundenen WebSocket-Client und einen Status-Broadcast
    dummy_ws = MagicMock()
    dummy_ws.accept = AsyncMock()
    dummy_ws.send_text = AsyncMock()
    await ws_manager.connect(dummy_ws)
    await ws_manager.send_printer_status(10, {"state": "RUNNING", "progress": 77})
    await ws_manager.disconnect(dummy_ws)

    mock_status = MagicMock(
        connected=True,
        state="RUNNING",
        subtask_name="E2E_Part.gcode",
        gcode_file="E2E_Part.gcode",
        progress=77,
        remaining_time=12,
        layer_num=150,
        total_layers=200,
        hms_errors=[],
    )
    mock_client = MagicMock(connected=True, pause_print=MagicMock(return_value=True))

    with (
        patch("backend.app.api.routes.fleet.printer_manager.get_status", return_value=mock_status),
        patch("backend.app.api.routes.fleet.printer_manager.get_client", return_value=mock_client),
    ):
        # 1. Fleet Overview abrufen
        ov_resp = await async_client.get("/api/v1/fleet/overview")
        assert ov_resp.status_code == 200
        ov = ov_resp.json()
        assert ov["printing_count"] == 1
        assert ov["active_jobs"][0]["progress"] == 77

        # 2. Batch-Pause für Standort "Halle 1"
        cmd_resp = await async_client.post(
            "/api/v1/fleet/command",
            json={"action": "pause", "location": "Halle 1"},
        )
        assert cmd_resp.status_code == 200
        assert cmd_resp.json()["succeeded"] == [10]

        # 3. Fleet & WebSocket Metriken prüfen
        met_resp = await async_client.get("/api/v1/fleet/metrics")
        assert met_resp.status_code == 200
        met = met_resp.json()
        assert met["total_ws_broadcasts"] >= 1
        assert met["total_ws_messages_sent"] >= 1
        assert met["last_broadcast_ms"] >= 0.0
