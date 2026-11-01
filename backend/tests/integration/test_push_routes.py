"""Browser-Meldungen über die API: Schlüssel, Abo, Abmelden und Testversand."""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _keys() -> tuple[str, str]:
    private = ec.generate_private_key(ec.SECP256R1())
    p256dh = (
        base64.urlsafe_b64encode(private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
        .rstrip(b"=")
        .decode()
    )
    auth = base64.urlsafe_b64encode(b"0123456789abcdef").rstrip(b"=").decode()
    return p256dh, auth


@pytest.mark.asyncio
async def test_subscribe_status_and_unsubscribe(async_client):
    key_response = await async_client.get("/api/v1/push/key")
    assert key_response.status_code == 200
    public_key = key_response.json()["public_key"]
    assert len(base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))) == 65

    p256dh, auth = _keys()
    endpoint = "https://push.example.com/subscription/abc"
    response = await async_client.post(
        "/api/v1/push/subscribe",
        json={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
    )
    assert response.status_code == 200, response.text

    status = await async_client.get("/api/v1/push/status")
    assert status.status_code == 200
    assert status.json()["subscriptions"] == 1
    assert status.json()["configured"] is True

    response = await async_client.post("/api/v1/push/unsubscribe", json={"endpoint": endpoint})
    assert response.status_code == 200
    status = await async_client.get("/api/v1/push/status")
    assert status.json()["subscriptions"] == 0


@pytest.mark.asyncio
async def test_rejects_broken_subscription_keys(async_client):
    response = await async_client.post(
        "/api/v1/push/subscribe",
        json={"endpoint": "https://push.example.com/x", "keys": {"p256dh": "A" * 30, "auth": "B" * 20}},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_test_endpoint_reports_delivery_counts(async_client, db_session, monkeypatch):
    from backend.app.services import web_push

    p256dh, auth = _keys()
    await async_client.post(
        "/api/v1/push/subscribe",
        json={"endpoint": "https://push.example.com/subscription/def", "keys": {"p256dh": p256dh, "auth": auth}},
    )

    async def fake_deliver(subscriptions, title, body, url="/"):
        assert len(subscriptions) == 1
        assert title == "PrintLab"
        return 1, 0

    monkeypatch.setattr(web_push, "deliver", fake_deliver)
    response = await async_client.post("/api/v1/push/test")
    assert response.status_code == 200
    assert response.json() == {"sent": 1, "failed": 0}
