"""Tests für den öffentlichen Angebots-Link: Merkmal, Ablauf, Antwort, Datenschutz."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.services import quote_share


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_share, "SHARES_PATH", tmp_path / "quote_shares.json")
    return tmp_path


QUOTE = {
    "id": "abc123",
    "ts": "2026-10-01T10:00:00+00:00",
    "number": "A-2026-0007",
    "customer": "Muster GmbH",
    "customer_address": "Hauptstr. 1, 12345 Stadt",
    "description": "Gehäuse",
    "currency": "EUR",
    "material": 4.20,
    "energy": 0.60,
    "labor": 15.00,
    "subtotal": 19.80,
    "markup": 5.95,
    "total": 25.75,
    "items": [{"description": "Schraube", "quantity": 4, "unit_price": 0.5, "amount": 2.0}],
    "extras": 2.0,
    "inputs": {"markup_percent": 30},
}


class TestTokens:
    def test_create_returns_token_and_expiry(self):
        entry = quote_share.create("abc123", 14, QUOTE)
        assert len(entry["token"]) >= 32
        assert entry["status"] == "open"
        expires = datetime.fromisoformat(entry["expires_at"])
        assert expires > datetime.now(timezone.utc) + timedelta(days=13)

    def test_new_link_revokes_the_previous_open_one(self):
        first = quote_share.create("abc123", 14, QUOTE)
        second = quote_share.create("abc123", 14, QUOTE)
        assert quote_share.get(first["token"])["status"] == "revoked"
        assert quote_share.get(second["token"])["status"] == "open"

    def test_missing_quote_is_rejected(self):
        with pytest.raises(quote_share.ShareError):
            quote_share.create("abc123", 14, None)

    def test_unknown_and_revoked_links_are_explained(self):
        with pytest.raises(quote_share.ShareError, match="unbekannt"):
            quote_share.open_entry("nope")
        entry = quote_share.create("abc123", 14, QUOTE)
        quote_share.revoke(entry["token"])
        with pytest.raises(quote_share.ShareError, match="zurückgezogen"):
            quote_share.open_entry(entry["token"])

    def test_answered_link_stays_readable_after_expiry(self):
        entry = quote_share.create("abc123", 14, QUOTE)
        quote_share.respond(entry["token"], "accepted")
        stored = quote_share.get(entry["token"])
        stored["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        quote_share._write([stored])
        loaded, answered = quote_share.open_entry(entry["token"])
        assert answered is True
        assert loaded["status"] == "accepted"

    def test_expired_link_is_refused(self):
        entry = quote_share.create("abc123", 14, QUOTE)
        stored = quote_share.get(entry["token"])
        stored["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        quote_share._write([stored])
        with pytest.raises(quote_share.ShareError, match="abgelaufen"):
            quote_share.open_entry(entry["token"])

    def test_list_hides_the_token(self):
        entry = quote_share.create("abc123", 14, QUOTE)
        listed = quote_share.list_for_quote("abc123")[0]
        assert "token" not in listed
        assert listed["token_tail"] == entry["token"][-6:]


class TestResponse:
    def test_accept_once(self):
        entry = quote_share.create("abc123", 14, QUOTE)
        result = quote_share.respond(entry["token"], "accepted", "Passt")
        assert result["status"] == "accepted"
        assert result["note"] == "Passt"
        assert quote_share.get(entry["token"])["responded_at"]

    def test_second_response_cannot_flip_it(self):
        entry = quote_share.create("abc123", 14, QUOTE)
        quote_share.respond(entry["token"], "declined")
        again = quote_share.respond(entry["token"], "accepted")
        assert again["status"] == "declined"

    def test_unknown_decision_is_rejected(self):
        entry = quote_share.create("abc123", 14, QUOTE)
        with pytest.raises(quote_share.ShareError):
            quote_share.respond(entry["token"], "maybe")


class TestPublicView:
    def test_internal_calculation_is_not_exposed(self):
        view = quote_share.public_view(QUOTE, {"name": "PrintLab", "valid_days": 14})
        flat = str(view)
        assert "markup_percent" not in flat
        assert "material" not in view and "labor" not in view and "subtotal" not in view
        assert view["total"] == 25.75
        assert view["valid_until"] == "2026-10-15"
        assert view["items"][0]["description"] == "Schraube"

    def test_no_validity_without_configured_days(self):
        view = quote_share.public_view(QUOTE, {"valid_days": 0})
        assert view["valid_until"] is None


class TestPage:
    def test_page_escapes_customer_input(self):
        from backend.app.api.routes import quote_share as route

        entry = quote_share.create("abc123", 14, QUOTE)
        hostile = {**QUOTE, "customer": "<script>alert(1)</script>"}
        html = route._render_quote(entry, quote_share.public_view(hostile, {"name": "Firma"}), entry["token"])
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_answered_page_shows_result_and_hides_buttons(self):
        from backend.app.api.routes import quote_share as route

        entry = quote_share.create("abc123", 14, QUOTE)
        quote_share.respond(entry["token"], "accepted")
        answered = quote_share.get(entry["token"])
        html = route._render_quote(answered, quote_share.public_view(QUOTE, {"name": "Firma"}), entry["token"])
        assert "Angenommen" in html
        assert "value='accepted'" not in html
