"""Öffentlicher Angebots-Link über die API: Seite ohne Anmeldung, Antwort per Formular."""

import pytest
from httpx import AsyncClient

from backend.app.services import company_profile, quote_history, quote_share


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_share, "SHARES_PATH", tmp_path / "quote_shares.json")
    monkeypatch.setattr(quote_history, "HISTORY_PATH", tmp_path / "quote_history.json")
    monkeypatch.setattr(company_profile, "COMPANY_PATH", tmp_path / "company.json")
    return tmp_path


@pytest.fixture()
def quote():
    return quote_history.add(
        {
            "customer": "Muster GmbH",
            "customer_address": "Hauptstr. 1\n12345 Stadt",
            "description": "Gehäuse",
            "currency": "EUR",
            "material": 4.0,
            "energy": 1.0,
            "labor": 10.0,
            "subtotal": 15.0,
            "markup": 5.0,
            "total": 20.0,
        }
    )


@pytest.mark.asyncio
async def test_public_page_and_acceptance(async_client: AsyncClient, quote):
    created = await async_client.post(f"/api/v1/quote/history/{quote['id']}/share", json={"days": 7})
    assert created.status_code == 200, created.text
    token = created.json()["token"]

    page = await async_client.get(f"/api/v1/quote/shared/{token}")
    assert page.status_code == 200
    assert "Muster GmbH" in page.text
    assert "value='accepted'" in page.text
    # Interne Kalkulation bleibt draußen.
    assert "Aufschlag" not in page.text

    answered = await async_client.post(f"/api/v1/quote/shared/{token}", data={"decision": "accepted", "note": "Passt"})
    assert answered.status_code == 303

    again = await async_client.get(f"/api/v1/quote/shared/{token}")
    assert "Angenommen" in again.text
    assert quote_share.get(token)["status"] == "accepted"


@pytest.mark.asyncio
async def test_revoked_link_is_explained(async_client: AsyncClient, quote):
    token = (await async_client.post(f"/api/v1/quote/history/{quote['id']}/share", json={})).json()["token"]
    revoked = await async_client.delete(f"/api/v1/quote/history/{quote['id']}/share")
    assert revoked.json() == {"revoked": True}
    page = await async_client.get(f"/api/v1/quote/shared/{token}")
    assert "zurückgezogen" in page.text


@pytest.mark.asyncio
async def test_unknown_link_is_friendly(async_client: AsyncClient):
    page = await async_client.get("/api/v1/quote/shared/does-not-exist")
    assert page.status_code == 200
    assert "funktioniert nicht" in page.text
