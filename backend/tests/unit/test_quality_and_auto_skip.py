"""Unit- & API-Tests für Phase 14: B2B-Qualitätszertifikate & Auto-Skip einzelner Bauteile."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from backend.app.models.archive import PrintArchive
from backend.app.services.auto_skip_objects import (
    PlateObjectBound,
    execute_skip_objects,
    match_defect_to_object,
)
from backend.app.services.quality_certificate import (
    calculate_quality_score,
    generate_quality_certificate_pdf,
)


def test_quality_score_calculation_and_grading():
    """Prüft ISO-9001-konforme Qualitätsindex- und Güteklassen-Berechnung."""
    # Perfekter Druck
    score_perf, grade_perf = calculate_quality_score(
        first_layer_score=99.0, temperature_deviation_c=0.5, anomaly_count=0
    )
    assert score_perf >= 98.0
    assert "Klasse A+" in grade_perf

    # Druck mit leichten Abzügen (First layer 92%, 1 Anomalie, 2.8°C Schwankung)
    score_mid, grade_mid = calculate_quality_score(first_layer_score=92.0, temperature_deviation_c=2.8, anomaly_count=1)
    assert 80.0 <= score_mid < 90.0
    assert "Klasse A" in grade_mid or "Klasse B" in grade_mid

    # Abgebrochener Druck
    score_abort, grade_abort = calculate_quality_score(completed_normally=False)
    assert score_abort == 0.0
    assert grade_abort == "ABGEBROCHEN"


def test_quality_certificate_pdf_generation():
    """Generiert ein DIN-A4-PDF und prüft PDF-Header, Mindestgröße und Struktur."""
    cert_data = {
        "certificate_number": "QC-TEST-001",
        "part_name": "Adaptergehäuse V2",
        "order_number": "PO-99120",
        "customer_name": "AutoTech GmbH",
        "printer_name": "Bambu Lab P2S",
        "printer_serial": "01P2S-12345",
        "material": "PETG-CF",
        "color_hex": "1A1A1A",
        "filament_grams": 62.4,
        "first_layer_score": 99.1,
        "anomaly_count": 0,
        "avg_nozzle_temp": 255.0,
        "avg_bed_temp": 70.0,
        "total_layers": 512,
    }
    pdf_bytes = generate_quality_certificate_pdf(cert_data)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 2000  # Vollständiges A4 PDF mit QR-Code


def test_match_defect_to_object_bounding_box():
    """Prüft Zuordnung von Kamerakoordinaten zu platzierten Bauteilen."""
    objects = [
        PlateObjectBound(object_id=1, name="Gehäuse_Links", min_x_mm=20.0, min_y_mm=20.0, max_x_mm=80.0, max_y_mm=80.0),
        PlateObjectBound(
            object_id=2, name="Gehäuse_Rechts", min_x_mm=140.0, min_y_mm=20.0, max_x_mm=200.0, max_y_mm=80.0
        ),
        PlateObjectBound(object_id=3, name="Deckel", min_x_mm=80.0, min_y_mm=120.0, max_x_mm=160.0, max_y_mm=200.0),
    ]

    # Exakter Treffer in Objekt 2
    matched = match_defect_to_object(160.0, 50.0, objects)
    assert matched is not None
    assert matched.object_id == 2
    assert matched.name == "Gehäuse_Rechts"

    # Naher Treffer bei Objekt 3
    matched_near = match_defect_to_object(78.0, 125.0, objects, tolerance_mm=5.0)
    assert matched_near is not None
    assert matched_near.object_id == 3

    # Weit entfernter Punkt -> kein Treffer
    assert match_defect_to_object(250.0, 250.0, objects) is None


def test_execute_skip_objects_logic():
    """Prüft Validierung und Aufruf des Bambu MQTT skip_objects Kommandos."""
    mock_client = MagicMock()
    mock_client.state = SimpleNamespace(state="RUNNING", connected=True)
    mock_client.skip_objects.return_value = True

    with patch("backend.app.services.auto_skip_objects.printer_manager.get_client", return_value=mock_client):
        res = execute_skip_objects(printer_id=1, object_ids=[2], reason="Spaghetti erkannt")
        assert res["success"] is True
        assert res["skipped_objects"] == [2]
        mock_client.skip_objects.assert_called_once_with([2])

    # Wenn Drucker nicht druckt (IDLE)
    mock_idle = MagicMock()
    mock_idle.state = SimpleNamespace(state="IDLE", connected=True)
    with patch("backend.app.services.auto_skip_objects.printer_manager.get_client", return_value=mock_idle):
        res_idle = execute_skip_objects(printer_id=1, object_ids=[2])
        assert res_idle["success"] is False
        assert "druckt aktuell nicht" in res_idle["error"]


@pytest.mark.asyncio
async def test_quality_api_routes(async_client: AsyncClient, db_session):
    """Prüft die API-Endpunkte unter /api/v1/quality."""
    # 1. Preview Score
    prev_resp = await async_client.post(
        "/api/v1/quality/certificate/preview",
        json={"first_layer_score": 97.0, "temp_dev_c": 0.5, "anomaly_count": 0},
    )
    assert prev_resp.status_code == 200
    assert prev_resp.json()["status"] == "PASS"

    # 2. Certificate PDF
    pdf_resp = await async_client.post(
        "/api/v1/quality/certificate/pdf",
        json={"part_name": "Sensorhalter", "order_number": "PO-100", "first_layer_score": 98.0},
    )
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF-")

    # 3. Archive PDF
    archive = PrintArchive(
        filename="Prüfteil.gcode.3mf",
        file_path="archives/pruefteil.gcode.3mf",
        file_size=1024,
        print_name="Prüfteil",
        filament_type="PETG",
        filament_color="FFFFFF",
        print_time_seconds=7200,
        total_layers=300,
        filament_used_grams=45.0,
    )
    db_session.add(archive)
    await db_session.commit()

    arc_resp = await async_client.get(f"/api/v1/quality/certificate/{archive.id}/pdf")
    assert arc_resp.status_code == 200
    assert arc_resp.headers["content-type"] == "application/pdf"

    # 4. Detect and skip
    mock_client = MagicMock()
    mock_client.state = SimpleNamespace(state="RUNNING", connected=True)
    mock_client.skip_objects.return_value = True

    with patch("backend.app.services.auto_skip_objects.printer_manager.get_client", return_value=mock_client):
        detect_resp = await async_client.post(
            "/api/v1/quality/printers/1/detect-and-skip",
            json={
                "defect_x_mm": 50.0,
                "defect_y_mm": 50.0,
                "objects": [
                    {
                        "object_id": 1,
                        "name": "Teil_A",
                        "min_x_mm": 20.0,
                        "min_y_mm": 20.0,
                        "max_x_mm": 80.0,
                        "max_y_mm": 80.0,
                    }
                ],
                "reason": "Bettablösung",
            },
        )
        assert detect_resp.status_code == 200
        assert detect_resp.json()["success"] is True
        assert detect_resp.json()["matched_object"]["object_id"] == 1
