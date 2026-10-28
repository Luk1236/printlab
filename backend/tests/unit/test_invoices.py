"""Rechnungen aus Angeboten: lückenlose Nummern, ein Angebot = eine Rechnung, nur stornieren, nie löschen."""

from datetime import date

import pytest

from backend.app.services import invoices, quote_history

BODY = {
    "customer": "Müller GmbH",
    "customer_address": "Musterweg 3\n12345 Musterstadt",
    "description": "Gehäuse",
    "material": 1,
    "energy": 1,
    "labor": 1,
    "subtotal": 3,
    "markup": 0.6,
    "total": 3.6,
}
COMPANY = {"invoice_prefix": "RE", "invoice_format": "{prefix}-{year}-{seq4}", "payment_days": 14}
TODAY = date(2026, 10, 28)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_history, "HISTORY_PATH", tmp_path / "quote_history.json")
    monkeypatch.setattr(invoices, "INVOICES_PATH", tmp_path / "invoices.json")


def quote():
    return quote_history.add(BODY)


class TestCreate:
    def test_takes_over_the_quote_and_computes_dates(self):
        q = quote()
        inv = invoices.create_from_quote(q["id"], COMPANY, today=TODAY)
        assert inv["number"].startswith("RE-") and inv["number"].endswith("-0001")
        assert inv["status"] == "open" and inv["quote_id"] == q["id"] and inv["quote_number"] == q["number"]
        assert inv["issued"] == "2026-10-28" and inv["service_date"] == "2026-10-28" and inv["due"] == "2026-11-11"
        assert inv["customer"] == "Müller GmbH" and inv["customer_address"].startswith("Musterweg")
        assert inv["total"] == 3.6 and inv["currency"] == "EUR"

    def test_numbers_are_gapless_and_never_reused(self):
        first = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        second = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        invoices.cancel(second["id"])
        third = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        assert [i["number"][-4:] for i in (first, second, third)] == ["0001", "0002", "0003"]

    def test_one_invoice_per_quote_but_again_after_a_cancellation(self):
        q = quote()
        first = invoices.create_from_quote(q["id"], COMPANY, today=TODAY)
        with pytest.raises(invoices.InvoiceError, match="schon eine Rechnung"):
            invoices.create_from_quote(q["id"], COMPANY, today=TODAY)
        invoices.cancel(first["id"])
        again = invoices.create_from_quote(q["id"], COMPANY, today=TODAY)
        assert again["number"] != first["number"]

    def test_unknown_quote_and_bad_service_date(self):
        with pytest.raises(invoices.InvoiceError, match="nicht gefunden"):
            invoices.create_from_quote("gibt-es-nicht", COMPANY)
        with pytest.raises(invoices.InvoiceError, match="Leistungsdatum"):
            invoices.create_from_quote(quote()["id"], COMPANY, service_date="gestern")

    def test_explicit_service_date(self):
        inv = invoices.create_from_quote(quote()["id"], COMPANY, service_date="2026-10-20", today=TODAY)
        assert inv["service_date"] == "2026-10-20" and inv["issued"] == "2026-10-28"

    def test_defaults_without_company_settings(self):
        inv = invoices.create_from_quote(quote()["id"], {}, today=TODAY)
        assert inv["due"] == inv["issued"] and inv["number"].startswith("R")


class TestStatus:
    def test_pay_reopen_and_cancel_rules(self):
        inv = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        paid = invoices.mark_paid(inv["id"], "2026-11-01")
        assert paid["status"] == "paid" and paid["paid_at"] == "2026-11-01"
        with pytest.raises(invoices.InvoiceError, match="bezahlte"):
            invoices.cancel(inv["id"])
        assert invoices.reopen(inv["id"])["status"] == "open"
        cancelled = invoices.cancel(inv["id"], "Fehler beim Kunden")
        assert cancelled["status"] == "cancelled" and cancelled["cancel_reason"] == "Fehler beim Kunden"
        with pytest.raises(invoices.InvoiceError, match="stornierte"):
            invoices.mark_paid(inv["id"])
        with pytest.raises(invoices.InvoiceError, match="stornierte"):
            invoices.reopen(inv["id"])

    def test_bad_payment_date_and_unknown_invoice(self):
        inv = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        with pytest.raises(invoices.InvoiceError, match="Zahlungsdatum"):
            invoices.mark_paid(inv["id"], "irgendwann")
        with pytest.raises(invoices.InvoiceError, match="nicht gefunden"):
            invoices.mark_paid("gibt-es-nicht")

    def test_there_is_no_delete(self):
        assert not hasattr(invoices, "delete")


class TestOverviews:
    def test_overdue_and_totals(self):
        late = invoices.create_from_quote(quote()["id"], COMPANY, today=date(2026, 9, 1))
        fresh = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        paid = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        invoices.mark_paid(paid["id"])
        gone = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        invoices.cancel(gone["id"])
        assert [i["id"] for i in invoices.overdue(TODAY)] == [late["id"]]
        assert fresh["id"] not in [i["id"] for i in invoices.overdue(TODAY)]
        assert invoices.totals() == {"EUR": {"open": 7.2, "overdue": 3.6, "paid": 3.6}}

    def test_list_filter_and_get(self):
        a = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        b = invoices.create_from_quote(quote()["id"], COMPANY, today=TODAY)
        invoices.mark_paid(b["id"])
        assert [i["id"] for i in invoices.entries()] == [b["id"], a["id"]]
        assert [i["id"] for i in invoices.entries("paid")] == [b["id"]]
        assert invoices.get(a["id"])["number"] == a["number"] and invoices.get("x") is None
        assert invoices.for_quote(a["quote_id"])["id"] == a["id"]

    def test_broken_file_is_empty(self, tmp_path):
        invoices.INVOICES_PATH.write_text("{kaputt")
        assert invoices.entries() == []
