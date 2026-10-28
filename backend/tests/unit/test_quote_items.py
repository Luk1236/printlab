"""Zusätzliche Positionen im Angebot (Beschreibung, Menge, Einzelpreis)."""

import pytest

from backend.app.services import company_profile, invoices, quote_history, quote_pdf

BODY = {
    "customer": "Kunde",
    "material": 1,
    "energy": 1,
    "labor": 1,
    "subtotal": 3,
    "markup": 0.6,
    "total": 3.6,
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_history, "HISTORY_PATH", tmp_path / "quote_history.json")
    monkeypatch.setattr(invoices, "INVOICES_PATH", tmp_path / "invoices.json")


def item(description="Versand", quantity=2, unit_price=4.5):
    return {"description": description, "quantity": quantity, "unit_price": unit_price}


class TestItems:
    def test_items_add_to_the_total_without_markup(self):
        entry = quote_history.add({**BODY, "items": [item(), item("Konstruktion", 1.5, 40)]})
        assert entry["extras"] == 69.0
        assert entry["total"] == 72.6
        assert [i["amount"] for i in entry["items"]] == [9.0, 60.0]
        assert quote_history.get(entry["id"])["items"][0]["description"] == "Versand"

    def test_no_items_leaves_the_entry_unchanged(self):
        entry = quote_history.add({**BODY, "items": []})
        assert "items" not in entry and "extras" not in entry and entry["total"] == 3.6
        assert "items" not in quote_history.add(BODY)

    @pytest.mark.parametrize(
        ("bad", "message"),
        [
            ([item(description="  ")], "Position 1: Beschreibung fehlt"),
            ([item(), item(quantity=0)], "Position 2: Menge"),
            ([item(quantity="viel")], "Position 1: Menge"),
            ([item(unit_price=-1)], "Position 1: Preis"),
            ([item(unit_price=None)], "Position 1: Preis"),
            ("kaputt", "müssen eine Liste sein"),
            ([item()] * 21, "Höchstens 20"),
            (["x"], "Beschreibung fehlt"),
        ],
    )
    def test_invalid_items_are_rejected(self, bad, message):
        with pytest.raises(ValueError, match=message):
            quote_history.add({**BODY, "items": bad})
        assert quote_history.entries() == []

    def test_description_is_cut_and_a_free_item_is_allowed(self):
        entry = quote_history.add({**BODY, "items": [item("x" * 200, 1, 0)]})
        assert len(entry["items"][0]["description"]) == 80
        assert entry["total"] == 3.6

    def test_the_invoice_keeps_items_and_total(self):
        entry = quote_history.add({**BODY, "items": [item()]})
        invoice = invoices.create_from_quote(entry["id"], company_profile.DEFAULTS)
        assert invoice["total"] == 12.6 and invoice["extras"] == 9.0 and invoice["items"][0]["amount"] == 9.0

    def test_pdf_renders_items_for_quote_and_invoice(self):
        entry = quote_history.add({**BODY, "items": [item("Versand", 2, 4.5)]})
        invoice = invoices.create_from_quote(entry["id"], company_profile.DEFAULTS)
        plain = quote_pdf.render({**entry, "items": []}, company_profile.DEFAULTS)
        with_items = quote_pdf.render(entry, company_profile.DEFAULTS, "en")
        assert with_items.startswith(b"%PDF") and with_items != plain
        assert quote_pdf.render(invoice, company_profile.DEFAULTS, "de", kind="invoice").startswith(b"%PDF")

    def test_a_broken_item_in_a_stored_entry_does_not_break_the_pdf(self):
        entry = {**BODY, "id": "x", "items": ["kaputt", {"description": "A"}, {"quantity": "x"}]}
        assert quote_pdf.render(entry, company_profile.DEFAULTS).startswith(b"%PDF")
