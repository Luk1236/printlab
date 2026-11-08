"""Unit-Tests für DATEV-Export & ZUGFeRD 2.2 / Factur-X (Phase 16)."""

import pytest
from httpx import AsyncClient

from backend.app.services.accounting_export import (
    KONTENRAHMEN,
    generate_datev_csv,
    generate_zugferd_facturx_pdf,
    get_accounting_summary,
)


def test_kontenrahmen_definitions():
    """Prüft die Standard-Kontenrahmen SKR03 und SKR04."""
    assert "SKR03" in KONTENRAHMEN
    assert "SKR04" in KONTENRAHMEN
    assert KONTENRAHMEN["SKR03"]["erloese_19"] == "8400"
    assert KONTENRAHMEN["SKR04"]["erloese_19"] == "4400"


def test_generate_datev_csv():
    """Prüft den Aufbau des DATEV EXTF Buchungsstapels."""
    sample_invoices = [
        {
            "id": "inv-001",
            "number": "R-2026-0001",
            "status": "paid",
            "issued": "2026-11-08",
            "customer": "Musterfirma GmbH",
            "description": "3D-Druck Prototypen",
            "gross_amount_cents": 11900,
            "net_amount_cents": 10000,
            "vat_percent": 19.0,
        },
        {
            "id": "inv-002",
            "number": "R-2026-0002",
            "status": "open",
            "issued": "2026-11-09",
            "customer": "TechLab KG",
            "description": "Funktionsbauteile PA-CF",
            "gross_amount_cents": 5950,
            "net_amount_cents": 5000,
            "vat_percent": 19.0,
        },
        {
            "id": "inv-003",
            "number": "R-2026-0003",
            "status": "cancelled",
            "issued": "2026-11-09",
            "gross_amount_cents": 23800,
            "vat_percent": 19.0,
        },
    ]

    # Export SKR03
    csv_skr03 = generate_datev_csv(sample_invoices, skr="SKR03", consultant_number=1234, client_number=5678)
    assert '"EXTF";700;21;"Buchungsstapel"' in csv_skr03
    assert ";1234;5678;" in csv_skr03
    assert '"Umsatz (ohne Soll/Haben-Kz)"' in csv_skr03

    lines = csv_skr03.splitlines()
    assert len(lines) >= 4
    # Buchungszeile 1: 119,00 € auf Konto 8400 (SKR03 19%)
    assert '"119,00";"S";"EUR"' in csv_skr03
    assert ';"10000";"8400";' in csv_skr03
    assert "Musterfirma GmbH" in csv_skr03

    # Export SKR04
    csv_skr04 = generate_datev_csv(sample_invoices, skr="SKR04")
    assert ';"10000";"4400";' in csv_skr04

    # Summary
    summary = get_accounting_summary(sample_invoices)
    assert summary["invoice_count"] == 2
    assert summary["total_gross_eur"] == 178.50
    assert summary["total_net_eur"] == 150.00


def test_zugferd_facturx_pdf_embedding():
    """Prüft die ZUGFeRD-Generierung mit XML-Einbettung."""
    mock_company = {
        "name": "PrintLab 3D Systems",
        "address": "Industrieweg 1\n80331 München\nDE",
        "tax_id": "DE123456789",
        "email": "rechnung@printlab.local",
        "phone": "+49 89 123456",
        "iban": "DE89370400440532013000",
        "bic": "BYLADEM1001",
        "vat_percent": 19.0,
        "vat_note": "",
        "footer": "Amtsgericht München HRB 12345",
    }
    mock_invoice = {
        "id": "inv-test-zugferd",
        "number": "R-2026-0099",
        "issued": "2026-11-08",
        "service_date": "2026-11-08",
        "due": "2026-11-22",
        "currency": "EUR",
        "customer": "Industriekunde AG",
        "customer_address": "Industriestr. 10\n10115 Berlin\nDE",
        "subtotal": 100.0,
        "net": 100.0,
        "vat": 19.0,
        "vat_percent": 19.0,
        "gross": 119.0,
        "items": [
            {
                "description": "3D-Druck Sensorhalter",
                "quantity": 1,
                "unit": "Stück",
                "unit_price": 100.0,
                "total": 100.0,
            }
        ],
    }

    pdf_bytes = generate_zugferd_facturx_pdf(mock_invoice, company=mock_company, lang="de")
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"factur-x.xml" in pdf_bytes
    assert b"/EmbeddedFile" in pdf_bytes
    assert b"/AFRelationship /Alternative" in pdf_bytes


@pytest.mark.asyncio
async def test_accounting_api_routes(async_client: AsyncClient):
    """Prüft die API-Routen unter /api/v1/accounting/."""
    # 1. Kontenrahmen
    kr_resp = await async_client.get("/api/v1/accounting/kontenrahmen")
    assert kr_resp.status_code == 200
    assert "SKR03" in kr_resp.json()["kontenrahmen"]

    # 2. Preview
    prev_resp = await async_client.get("/api/v1/accounting/datev-preview?skr=SKR03")
    assert prev_resp.status_code == 200
    assert "invoice_count" in prev_resp.json()

    # 3. CSV Download
    csv_resp = await async_client.get("/api/v1/accounting/datev-csv?skr=SKR03&consultant=1001&client=10001")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert b"EXTF" in csv_resp.content
