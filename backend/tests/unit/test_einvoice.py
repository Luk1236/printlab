"""Tests für die E-Rechnung (XRechnung, UBL)."""

from decimal import Decimal
from xml.etree import ElementTree

import pytest

from backend.app.services import einvoice

NS = {
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}

COMPANY = {
    "name": "PrintLab Muster",
    "address": "Werkstr. 5\n12345 Stadt",
    "tax_id": "DE123456789",
    "email": "rechnung@example.org",
    "vat_percent": 19.0,
    "vat_note": "",
    "iban": "DE02 1203 0000 0000 2020 51",
}

INVOICE = {
    "id": "inv1",
    "number": "R-2026-0003",
    "issued": "2026-10-01",
    "due": "2026-10-15",
    "service_date": "2026-09-30",
    "customer": "Muster GmbH",
    "customer_address": "Hauptstr. 1\n54321 Dorf",
    "description": "Gehäuse PETG",
    "currency": "EUR",
    "total": 119.0,
    "items": [{"description": "Nacharbeit", "quantity": 2, "unit_price": 9.5, "amount": 19.0}],
    "extras": 19.0,
}


def _parse(xml: str):
    return ElementTree.fromstring(xml)


def _text(root, path: str) -> str:
    node = root.find(path, NS)
    return (node.text or "") if node is not None else ""


class TestValidate:
    def test_complete_invoice_is_valid(self):
        assert einvoice.validate(INVOICE, COMPANY) == []

    def test_reports_every_missing_mandatory_field(self):
        issues = einvoice.validate({}, {})
        joined = " ".join(issues)
        assert "Firmenname" in joined
        assert "Anschrift der Firma" in joined
        assert "Steuernummer" in joined
        assert "E-Mail" in joined
        assert "Kundenname" in joined
        assert "Rechnungsnummer" in joined
        assert "Fälligkeitsdatum" in joined

    def test_zero_vat_needs_exemption_note(self):
        company = {**COMPANY, "vat_percent": 0}
        assert any("Steuerbefreiung" in issue for issue in einvoice.validate(INVOICE, company))
        assert einvoice.validate(INVOICE, {**company, "vat_note": "Kleinunternehmer § 19 UStG"}) == []


class TestBuild:
    def test_well_formed_and_has_required_elements(self):
        root = _parse(einvoice.build_xml(INVOICE, COMPANY))
        assert _text(root, "cbc:CustomizationID") == einvoice.CUSTOMIZATION_ID
        assert _text(root, "cbc:ID") == "R-2026-0003"
        assert _text(root, "cbc:InvoiceTypeCode") == "380"
        assert _text(root, "cbc:DocumentCurrencyCode") == "EUR"
        assert _text(root, "cbc:BuyerReference") == "R-2026-0003"
        assert _text(root, ".//cac:AccountingSupplierParty//cbc:Name") == "PrintLab Muster"
        assert _text(root, ".//cac:AccountingCustomerParty//cbc:Name") == "Muster GmbH"

    def test_totals_and_vat_are_consistent(self):
        root = _parse(einvoice.build_xml(INVOICE, COMPANY))
        assert _text(root, ".//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount") == "119.00"
        assert _text(root, ".//cac:TaxTotal/cbc:TaxAmount") == "22.61"  # 19 %
        assert _text(root, ".//cac:LegalMonetaryTotal/cbc:PayableAmount") == "141.61"
        assert _text(root, ".//cac:TaxSubtotal/cac:TaxCategory/cbc:ID") == "S"

    def test_service_line_plus_extra_item(self):
        root = _parse(einvoice.build_xml(INVOICE, COMPANY))
        lines = root.findall("cac:InvoiceLine", NS)
        assert len(lines) == 2
        assert _text(lines[0], "cac:Item/cbc:Name") == "Gehäuse PETG"
        assert _text(lines[0], "cbc:LineExtensionAmount") == "100.00"
        assert _text(lines[1], "cac:Item/cbc:Name") == "Nacharbeit"
        assert _text(lines[1], "cbc:InvoicedQuantity") == "2.00"

    def test_zero_vat_uses_exempt_category_without_percent(self):
        company = {**COMPANY, "vat_percent": 0, "vat_note": "Kleinunternehmer § 19 UStG"}
        root = _parse(einvoice.build_xml(INVOICE, company))
        assert _text(root, ".//cac:TaxSubtotal/cac:TaxCategory/cbc:ID") == "E"
        assert _text(root, ".//cac:TaxSubtotal/cac:TaxCategory/cbc:Percent") == ""
        assert "Kleinunternehmer" in _text(root, ".//cac:TaxSubtotal/cac:TaxCategory/cbc:TaxExemptionReason")
        assert _text(root, ".//cac:LegalMonetaryTotal/cbc:PayableAmount") == "119.00"

    def test_payment_means_only_with_iban(self):
        root = _parse(einvoice.build_xml(INVOICE, COMPANY))
        assert _text(root, ".//cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID") == "DE02120300000000202051"
        without = _parse(einvoice.build_xml(INVOICE, {**COMPANY, "iban": ""}))
        assert without.find(".//cac:PaymentMeans", NS) is None

    def test_values_are_escaped(self):
        invoice = {**INVOICE, "customer": "Müller & Söhne <GmbH>"}
        xml = einvoice.build_xml(invoice, COMPANY)
        assert "Müller &amp; Söhne &lt;GmbH&gt;" in xml
        _parse(xml)  # bleibt wohlgeformt

    def test_missing_fields_raise_with_list(self):
        with pytest.raises(einvoice.EInvoiceError) as exc:
            einvoice.build_xml({}, {})
        assert exc.value.issues

    def test_filename_is_safe(self):
        assert einvoice.filename({"number": "R/2026 0003"}) == "XRechnung-R_2026_0003.xml"


class TestAddress:
    def test_two_line_address(self):
        assert einvoice._address("Werkstr. 5\n12345 Stadt") == {
            "street": "Werkstr. 5",
            "postal": "12345",
            "city": "Stadt",
            "country": "DE",
        }

    def test_single_line_with_comma_and_country(self):
        parsed = einvoice._address("Hauptstr. 1, 54321 Dorf, AT")
        assert parsed["postal"] == "54321"
        assert parsed["city"] == "Dorf"
        assert parsed["country"] == "AT"

    def test_street_only_stays_street(self):
        assert einvoice._address("Nur Straße")["street"] == "Nur Straße"


def test_money_rounds_half_up():
    assert einvoice._money("1.005") == Decimal("1.01")
    assert einvoice._money(None) == Decimal("0.00")
