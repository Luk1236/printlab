"""HTTP-Schicht-Tests der v2.0-Enterprise-Router (Fleet, Portal, Webhooks, Wear, Discovery).

Die Service-Logik ist in den Unit-Tests abgedeckt (test_v2_0_1_hardening.py);
hier werden die Endpunkte über die echte App geprüft: Routing, Fehler-Mapping
(400/404/429/503), Geheimnis-Maskierung und die Pydantic-Body-Validierung.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# api_prefix aus der Konfiguration ("/api/v1")
from backend.app.core.config import settings as app_settings

PREFIX = app_settings.api_prefix


@pytest.fixture(autouse=True)
def portal_rate_fresh():
    """Getrennte Rate-Limit-Fenster pro Test."""
    from backend.app.api.routes import customer_portal_route

    customer_portal_route._hits.clear()
    yield
    customer_portal_route._hits.clear()


CHECKOUT_URLS = {
    "success_url": "https://portal.example/done",
    "cancel_url": "https://portal.example/cancelled",
}


# ── Portal (/portal/*) ───────────────────────────────────────────────────────


class TestPortalRoutes:
    async def test_materials_are_public(self, async_client: AsyncClient):
        res = await async_client.get(f"{PREFIX}/portal/materials")
        assert res.status_code == 200
        assert "PLA" in res.json()["materials"]

    async def test_quote_roundtrip_and_checkout(self, async_client: AsyncClient):
        quoted = await async_client.post(f"{PREFIX}/portal/quote", json={"volume_cm3": 30.0})
        assert quoted.status_code == 200, quoted.text
        quote = quoted.json()

        checkout = await async_client.post(
            f"{PREFIX}/portal/checkout", json={"quote_id": quote["quote_id"], **CHECKOUT_URLS}
        )
        assert checkout.status_code == 200, checkout.text
        session = checkout.json()
        assert session["amount_cents"] == int(round(quote["pricing"]["gross_total_eur"] * 100))
        assert session["success_url"] == CHECKOUT_URLS["success_url"]
        assert session["cancel_url"] == CHECKOUT_URLS["cancel_url"]

    async def test_checkout_unknown_quote_is_404(self, async_client: AsyncClient):
        res = await async_client.post(f"{PREFIX}/portal/checkout", json={"quote_id": "SQ-NOPE", **CHECKOUT_URLS})
        assert res.status_code == 404
        assert "unbekannt oder abgelaufen" in res.json()["detail"]

    async def test_checkout_invalid_redirect_is_400(self, async_client: AsyncClient):
        res = await async_client.post(
            f"{PREFIX}/portal/checkout",
            json={"quote_id": "SQ-NOPE", "success_url": "ftp://x/d", "cancel_url": "https://x/c"},
        )
        assert res.status_code == 400
        assert "http" in res.json()["detail"]

    async def test_quote_validation_rejects_zero_volume(self, async_client: AsyncClient):
        res = await async_client.post(f"{PREFIX}/portal/quote", json={"volume_cm3": 0})
        assert res.status_code == 422

    async def test_quote_rate_limit_is_429(self, async_client, monkeypatch: pytest.MonkeyPatch):
        from backend.app.api.routes import customer_portal_route

        monkeypatch.setattr(customer_portal_route, "RATE_MAX_QUOTE_REQUESTS", 1)

        first = await async_client.post(f"{PREFIX}/portal/quote", json={"volume_cm3": 10.0})
        assert first.status_code == 200

        second = await async_client.post(f"{PREFIX}/portal/quote", json={"volume_cm3": 10.0})
        assert second.status_code == 429
        assert "Kalkulationen" in second.json()["detail"]

    async def test_checkout_rate_limit_is_429(self, async_client, monkeypatch, db_session):
        from backend.app.api.routes import customer_portal_route
        from backend.app.services import customer_portal as calc
        from backend.app.services.portal_quote_store import store_quote

        monkeypatch.setattr(customer_portal_route, "RATE_MAX_CHECKOUT_REQUESTS", 1)
        quote = calc.calculate_instant_quote(volume_cm3=30.0)
        await store_quote(db_session, quote)

        first = await async_client.post(
            f"{PREFIX}/portal/checkout", json={"quote_id": quote["quote_id"], **CHECKOUT_URLS}
        )
        assert first.status_code == 200

        second = await async_client.post(
            f"{PREFIX}/portal/checkout", json={"quote_id": quote["quote_id"], **CHECKOUT_URLS}
        )
        assert second.status_code == 429


# ── Fleet (/fleet/*) ─────────────────────────────────────────────────────────


class TestFleetRoutes:
    async def test_status_includes_registered_printers(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory()
        res = await async_client.get(f"{PREFIX}/fleet/status")
        assert res.status_code == 200, res.text
        payload = res.json()
        ids = [p["id"] for p in payload["printers"]]
        assert printer.id in ids
        entry = next(p for p in payload["printers"] if p["id"] == printer.id)
        assert entry["state"] == "OFFLINE"  # keine Verbindung im Unit-Test
        assert entry["plate_clear"] is False
        assert entry["total_operating_hours"] == 0.0

    async def test_dispatch_returns_candidates(self, async_client: AsyncClient, printer_factory):
        await printer_factory()
        res = await async_client.post(
            f"{PREFIX}/fleet/dispatch",
            json={"name": "Halter", "material": "PLA", "filament_grams": 12.0},
        )
        assert res.status_code == 200, res.text
        result = res.json()
        assert result["status"] in ("DISPATCHED", "WAITING_FOR_RESOURCES")
        assert isinstance(result["candidates"], list) and result["candidates"]

    async def test_dispatch_validates_body(self, async_client: AsyncClient):
        res = await async_client.post(f"{PREFIX}/fleet/dispatch", json={"filament_grams": "abc", "color": 7.5})
        assert res.status_code == 422

    async def test_fitness_of_unknown_printer(self, async_client: AsyncClient):
        res = await async_client.post(
            f"{PREFIX}/fleet/fitness/999999",
            json={"material": "PLA"},
        )
        assert res.status_code == 200
        assert res.json()["reasons"] == ["Drucker nicht gefunden"]


# ── Verschleiß (/maintenance/wear/*) ────────────────────────────────────────


class TestMaintenanceWearRoutes:
    async def test_status_of_unknown_printer_is_empty_overview(self, async_client: AsyncClient):
        res = await async_client.get(f"{PREFIX}/maintenance/wear/p2s_never_used")
        assert res.status_code == 200
        body = res.json()
        assert body["overall_status"] == "OK"
        assert len(body["components"]) == 5

    async def test_reset_rejects_invalid_component(self, async_client: AsyncClient):
        res = await async_client.post(f"{PREFIX}/maintenance/wear/p1/reset?component=turbo")
        assert res.status_code == 400
        assert "Ungültige Komponente" in res.json()["detail"]

    async def test_reset_unknown_printer_is_404(self, async_client: AsyncClient):
        res = await async_client.post(f"{PREFIX}/maintenance/wear/ghost/reset?component=nozzle")
        assert res.status_code == 404


# ── Home-Assistant-Discovery (/discovery/homeassistant/*) ────────────────────


class TestDiscoveryRoutes:
    async def test_entities_for_registered_printer(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="P2S Hinten")
        res = await async_client.get(f"{PREFIX}/discovery/homeassistant/{printer.id}")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["entity_count"] >= 4
        assert body["printer_name"] == "P2S Hinten"
        assert body["device"]["name"].startswith("PrintLab")


# ── Webhooks (/webhooks/outbound/*) ─────────────────────────────────────────


@pytest.fixture()
def isolated_webhook_store(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from backend.app.services import outbound_webhooks, secret_codec

    monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", tmp_path / "wh.json")
    # Der Codec-Dienst-Schlüssel darf bei Routentests nicht die echte
    # service_secrets.key im Datenordner erzeugen.
    monkeypatch.setattr(secret_codec, "KEY_FILE", tmp_path / "service_secrets.key")
    secret_codec.reset_cached_cipher()
    yield
    secret_codec.reset_cached_cipher()


class TestWebhooksOutboundRoutes:
    async def test_create_and_list_masks_secret(self, async_client: AsyncClient, isolated_webhook_store):
        created = await async_client.post(
            f"{PREFIX}/webhooks/outbound",
            json={
                "url": "https://discord.com/api/webhooks/1",
                "secret": "hushhush",
                "events": ["print.completed"],
                "format_type": "discord",
            },
        )
        assert created.status_code == 200, created.text
        hook = created.json()["webhook"]
        assert hook["secret"] == "***"
        assert hook["secret_configured"] is True
        assert "hushhush" not in created.text

        listed_response = await async_client.get(f"{PREFIX}/webhooks/outbound")
        assert listed_response.status_code == 200
        assert "hushhush" not in listed_response.text
        listed = listed_response.json()
        assert len(listed) == 1
        assert listed[0]["id"] == hook["id"]
        assert listed[0]["secret"] == "***"

    async def test_delete_then_404(self, async_client: AsyncClient, isolated_webhook_store):
        created = await async_client.post(
            f"{PREFIX}/webhooks/outbound", json={"url": "https://discord.com/api/webhooks/2"}
        )
        hook_id = created.json()["webhook"]["id"]

        deleted = await async_client.delete(f"{PREFIX}/webhooks/outbound/{hook_id}")
        assert deleted.status_code == 200
        assert (await async_client.get(f"{PREFIX}/webhooks/outbound")).json() == []

        again = await async_client.delete(f"{PREFIX}/webhooks/outbound/{hook_id}")
        assert again.status_code == 404

    async def test_invalid_events_rejected_with_400(self, async_client: AsyncClient, isolated_webhook_store):
        res = await async_client.post(
            f"{PREFIX}/webhooks/outbound",
            json={"url": "https://discord.com/api/webhooks/3", "events": ["print.complted"]},
        )
        assert res.status_code == 400
        assert "Unbekanntes Ereignis" in res.json()["detail"]

    async def test_invalid_url_rejected_with_400(self, async_client: AsyncClient, isolated_webhook_store):
        res = await async_client.post(
            f"{PREFIX}/webhooks/outbound",
            json={"url": "http://169.254.169.254/steal"},
        )
        assert res.status_code == 400
        assert "Cloud-Instanz-Metadaten" in res.json()["detail"]

    async def test_test_route_validates_event(self, async_client: AsyncClient, isolated_webhook_store):
        res = await async_client.post(f"{PREFIX}/webhooks/outbound/test", json={"event": "print.complted"})
        assert res.status_code == 400
        assert "Unbekanntes Ereignis" in res.json()["detail"]
