"""Unit-Tests für Lieferschein- und Thermo-Etiketten-Generierung."""

from __future__ import annotations

import pytest

from backend.app.services.delivery_note_service import (
    generate_delivery_note_pdf,
    generate_thermal_label_pdf,
)


@pytest.fixture
def sample_order():
    return {
        "quote_id": "SQ-TEST1234",
        "customer_name": "Musterfirma GmbH",
        "customer_address": "Musterweg 12\n12345 Musterstadt",
        "filename": "halterung_v2.stl",
        "filament_type": "PETG",
        "material_name": "Bambu PETG HF (Schwarz)",
        "infill_percent": 25,
        "layer_height_mm": 0.20,
        "quantity": 4,
        "single_weight_grams": 35.5,
        "total_weight_grams": 142.0,
    }


def test_generate_delivery_note_pdf(sample_order):
    pdf_bytes = generate_delivery_note_pdf(sample_order)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    # PDF Magic Bytes
    assert pdf_bytes.startswith(b"%PDF-")


def test_generate_thermal_label_100x150(sample_order):
    pdf_bytes = generate_thermal_label_pdf(sample_order, format_size="100x150")
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 800
    assert pdf_bytes.startswith(b"%PDF-")


def test_generate_thermal_label_62x29(sample_order):
    pdf_bytes = generate_thermal_label_pdf(sample_order, format_size="62x29")
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 500
    assert pdf_bytes.startswith(b"%PDF-")
