"""Angebote: Nummernkreis, Firmendaten und PDF."""

import pytest

from backend.app.services import company_profile, quote_history, quote_pdf

ENTRY_BODY = {
    "customer": "Müller GmbH",
    "description": "Gehäuse für Sensor, 20 Stück",
    "material": 12.5,
    "energy": 1.2,
    "labor": 10,
    "subtotal": 23.7,
    "markup": 4.74,
    "total": 28.44,
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_history, "HISTORY_PATH", tmp_path / "quote_history.json")
    monkeypatch.setattr(company_profile, "COMPANY_PATH", tmp_path / "company.json")


class TestQuoteNumbers:
    def test_numbers_count_up_within_the_year(self):
        first = quote_history.add(ENTRY_BODY)
        second = quote_history.add(ENTRY_BODY)
        year = first["number"].split("-")[1]
        assert first["number"] == f"A-{year}-0001"
        assert second["number"] == f"A-{year}-0002"

    def test_prefix_is_used(self):
        assert quote_history.add(ENTRY_BODY, prefix="PL")["number"].startswith("PL-")

    def test_deleting_the_last_quote_does_not_reuse_its_number(self):
        quote_history.add(ENTRY_BODY)
        last = quote_history.add(ENTRY_BODY)
        quote_history.delete(last["id"])
        assert quote_history.add(ENTRY_BODY)["number"].endswith("-0003")

    def test_counter_of_a_past_year_starts_over(self):
        quote_history.HISTORY_PATH.with_name("quote_counter.json").write_text('{"year": 2000, "seq": 77}')
        assert quote_history.add(ENTRY_BODY)["number"].endswith("-0001")

    def test_counter_of_the_current_year_continues(self):
        first = quote_history.add(ENTRY_BODY)
        year = int(first["number"].split("-")[1])
        quote_history.HISTORY_PATH.with_name("quote_counter.json").write_text(f'{{"year": {year}, "seq": 41}}')
        assert quote_history.add(ENTRY_BODY)["number"].endswith("-0042")

    def test_old_history_without_counter_does_not_go_backwards(self):
        entry = quote_history.add(ENTRY_BODY)
        quote_history.HISTORY_PATH.with_name("quote_counter.json").unlink()
        assert quote_history.add(ENTRY_BODY)["number"] > entry["number"]

    def test_get_finds_an_entry(self):
        entry = quote_history.add(ENTRY_BODY)
        assert quote_history.get(entry["id"])["customer"] == "Müller GmbH"
        assert quote_history.get("gibt-es-nicht") is None


class TestCompanyProfile:
    def test_defaults_without_a_file(self):
        data = company_profile.read()
        assert data["number_prefix"] == "A" and data["vat_percent"] == 0 and data["valid_days"] == 14

    def test_write_and_read_back(self):
        saved = company_profile.write(
            {"name": "PrintLab Muster", "vat_percent": "19", "valid_days": 30, "iban": "DE00"}
        )
        assert saved["vat_percent"] == 19.0 and saved["valid_days"] == 30
        assert company_profile.read()["name"] == "PrintLab Muster"

    def test_partial_update_keeps_other_fields(self):
        company_profile.write({"name": "A", "email": "a@b.de"})
        company_profile.write({"name": "B"})
        assert company_profile.read()["email"] == "a@b.de"

    def test_unknown_fields_are_dropped(self):
        company_profile.write({"name": "A", "boese": "x"})
        assert "boese" not in company_profile.read()

    def test_prefix_is_reduced_to_letters_and_digits(self):
        assert company_profile.write({"number_prefix": "A/B-1"})["number_prefix"] == "AB1"
        assert company_profile.write({"number_prefix": "!!!"})["number_prefix"] == "A"

    @pytest.mark.parametrize(
        "bad",
        [
            {"vat_percent": 50},
            {"vat_percent": "abc"},
            {"vat_percent": -1},
            {"valid_days": 1000},
            {"valid_days": "x"},
            {"name": "x" * 500},
        ],
    )
    def test_invalid_values_are_refused(self, bad):
        with pytest.raises(ValueError):
            company_profile.write(bad)

    def test_not_an_object_is_refused(self):
        with pytest.raises(ValueError):
            company_profile.write(["x"])

    def test_control_characters_are_removed(self):
        assert company_profile.write({"name": "A\x00B\x07"})["name"] == "AB"

    def test_broken_file_gives_defaults(self):
        company_profile.COMPANY_PATH.write_text("{kaputt")
        assert company_profile.read()["number_prefix"] == "A"


class TestPdf:
    def entry(self):
        return quote_history.add(ENTRY_BODY)

    def test_renders_a_pdf_with_the_header_data(self):
        company = {
            **company_profile.DEFAULTS,
            "name": "PrintLab Muster",
            "address": "Musterweg 1\n12345 Musterstadt",
            "iban": "DE89 3704 0044 0532 0130 00",
            "vat_percent": 19.0,
        }
        pdf = quote_pdf.render(self.entry(), company, "de")
        assert pdf.startswith(b"%PDF") and len(pdf) > 1500

    def test_english_and_unknown_language(self):
        entry = self.entry()
        assert quote_pdf.render(entry, company_profile.DEFAULTS, "en").startswith(b"%PDF")
        assert quote_pdf.render(entry, company_profile.DEFAULTS, "xx").startswith(b"%PDF")

    def test_old_entry_without_number_and_odd_values_still_renders(self):
        entry = {"id": "abc123", "ts": "kaputt", "customer": "K", "currency": "CHF", "total": 5}
        assert quote_pdf.render(entry, company_profile.DEFAULTS).startswith(b"%PDF")

    def test_long_description_and_footer_do_not_crash(self):
        entry = {**self.entry(), "description": "Wort " * 60}
        company = {
            **company_profile.DEFAULTS,
            "footer": "Hinweis " * 50,
            "vat_note": "Kein Ausweis der Umsatzsteuer. " * 5,
        }
        assert quote_pdf.render(entry, company).startswith(b"%PDF")

    def test_money_format_by_language(self):
        assert quote_pdf.money(1234.5, "EUR", "de") == "1.234,50 EUR"
        assert quote_pdf.money(1234.5, "EUR", "en") == "1,234.50 EUR"
