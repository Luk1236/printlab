"""Tests für den EPC-QR-Code (GiroCode) Service."""

from decimal import Decimal

import pytest

from backend.app.services import girocode


class TestGiroCode:
    def test_build_epc_qr_payload_valid(self):
        payload = girocode.build_epc_qr_payload(
            name="PrintLab Werkstatt",
            iban="DE02 1203 0000 0000 2020 51",
            amount=119.50,
            bic="GENODEF1M01",
            purpose="Rechnung R-2026-0004",
        )
        lines = payload.split("\n")
        assert len(lines) == 12
        assert lines[0] == "BCD"
        assert lines[1] == "002"
        assert lines[2] == "1"
        assert lines[3] == "SCT"
        assert lines[4] == "GENODEF1M01"
        assert lines[5] == "PrintLab Werkstatt"
        assert lines[6] == "DE02120300000000202051"
        assert lines[7] == "EUR119.50"
        assert lines[10] == "Rechnung R-2026-0004"

    def test_build_epc_qr_payload_validation_empty_iban(self):
        with pytest.raises(ValueError, match="IBAN darf"):
            girocode.build_epc_qr_payload(
                name="PrintLab",
                iban="",
                amount=50.0,
            )

    def test_build_epc_qr_payload_validation_empty_name(self):
        with pytest.raises(ValueError, match="Name des Empfängers"):
            girocode.build_epc_qr_payload(
                name="",
                iban="DE02120300000000202051",
                amount=50.0,
            )

    def test_generate_girocode_svg(self):
        if not girocode.QRCODE_AVAILABLE:
            pytest.skip("qrcode Modul nicht verfügbar")
        svg = girocode.generate_girocode_svg(
            name="PrintLab",
            iban="DE02120300000000202051",
            amount=Decimal("49.90"),
            purpose="Test",
        )
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_generate_girocode_data_uri(self):
        if not girocode.QRCODE_AVAILABLE:
            pytest.skip("qrcode Modul nicht verfügbar")
        data_uri = girocode.generate_girocode_data_uri(
            name="PrintLab",
            iban="DE02120300000000202051",
            amount=49.90,
            purpose="Test",
        )
        assert data_uri.startswith("data:image/png;base64,")
        assert len(data_uri) > 100

    def test_girocode_for_invoice_helper(self):
        if not girocode.QRCODE_AVAILABLE:
            pytest.skip("qrcode Modul nicht verfügbar")
        invoice = {"number": "R-2026-0010", "total": 238.0}
        company = {"name": "Muster 3D", "iban": "DE02 1203 0000 0000 2020 51", "bic": "GENODEF1M01"}
        uri = girocode.girocode_for_invoice(invoice, company)
        assert uri.startswith("data:image/png;base64,")
