"""Tests for the saved quote history per customer."""

import pytest

from backend.app.services import quote_history


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_history, "HISTORY_PATH", tmp_path / "quote_history.json")


def quote(**over):
    base = {
        "customer": "Müller GmbH",
        "material": 2.2,
        "energy": 0.5,
        "labor": 5,
        "subtotal": 7.7,
        "markup": 1.54,
        "total": 9.24,
    }
    base.update(over)
    return base


class TestAdd:
    def test_saves_and_lists_newest_first(self):
        first = quote_history.add(quote(description="Halter"))
        second = quote_history.add(quote(customer="Meier", total=3))
        listed = quote_history.entries()
        assert [e["id"] for e in listed] == [second["id"], first["id"]]
        assert first["description"] == "Halter" and first["currency"] == "EUR"

    @pytest.mark.parametrize(
        "bad", [{"customer": "  "}, {"total": "abc"}, {"total": -1}, {"total": float("nan")}, {"total": True}]
    )
    def test_invalid_input_is_rejected(self, bad):
        with pytest.raises(ValueError):
            quote_history.add(quote(**bad))

    def test_missing_amount_is_rejected(self):
        payload = quote()
        del payload["energy"]
        with pytest.raises(ValueError):
            quote_history.add(payload)

    def test_text_fields_are_capped_and_inputs_filtered(self):
        entry = quote_history.add(
            quote(customer="x" * 500, description="d" * 500, inputs={"grams": 10, "evil": "<b>", "n": float("nan")})
        )
        assert len(entry["customer"]) == 80 and len(entry["description"]) == 200
        assert entry["inputs"] == {"grams": 10}

    def test_history_is_capped(self, monkeypatch):
        monkeypatch.setattr(quote_history, "MAX_ENTRIES", 3)
        for i in range(5):
            quote_history.add(quote(customer=f"K{i}"))
        assert [e["customer"] for e in quote_history.entries()] == ["K4", "K3", "K2"]


class TestQueries:
    def test_filter_by_customer_is_case_insensitive(self):
        quote_history.add(quote(customer="Müller GmbH"))
        quote_history.add(quote(customer="Meier"))
        assert [e["customer"] for e in quote_history.entries("müller")] == ["Müller GmbH"]

    def test_totals_by_customer(self):
        quote_history.add(quote(customer="A", total=10))
        quote_history.add(quote(customer="A", total=5.5))
        quote_history.add(quote(customer="B", total=20))
        rows = quote_history.totals_by_customer()
        assert rows[0] == {"customer": "B", "currency": "EUR", "count": 1, "total": 20.0}
        assert rows[1] == {"customer": "A", "currency": "EUR", "count": 2, "total": 15.5}

    def test_currencies_are_not_mixed(self):
        quote_history.add(quote(customer="A", total=10, currency="EUR"))
        quote_history.add(quote(customer="A", total=10, currency="USD"))
        assert len(quote_history.totals_by_customer()) == 2

    def test_delete(self):
        entry = quote_history.add(quote())
        assert quote_history.delete(entry["id"]) is True
        assert quote_history.delete(entry["id"]) is False
        assert quote_history.entries() == []

    def test_corrupt_file_reads_as_empty(self, tmp_path):
        (tmp_path / "quote_history.json").write_text("not json", encoding="utf-8")
        assert quote_history.entries() == []
