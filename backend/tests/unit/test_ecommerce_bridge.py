"""Unit-Tests für E-Commerce & ERP Webhook-Brücke (Phase 24)."""

import base64
import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient

from backend.app.services import ecommerce_bridge
from backend.app.services.ecommerce_bridge import (
    format_fulfillment_payload,
    get_bridge_config,
    process_sap_erp_order,
    process_shopify_order,
    process_woocommerce_order,
    verify_sap_erp_token,
    verify_shopify_signature,
    verify_woocommerce_signature,
)

TEST_SHOPIFY_SECRET = "test-shopify-secret-0123456789"
TEST_WOOCOMMERCE_SECRET = "test-woocommerce-secret-0123456789"
TEST_SAP_TOKEN = "test-sap-token-0123456789"


@pytest.fixture
def configured_secrets(monkeypatch):
    """Die Empfänger haben keine Standard-Geheimnisse; die Tests setzen eigene."""
    monkeypatch.setitem(ecommerce_bridge._config, "shopify_webhook_secret", TEST_SHOPIFY_SECRET)
    monkeypatch.setitem(ecommerce_bridge._config, "woocommerce_webhook_secret", TEST_WOOCOMMERCE_SECRET)
    monkeypatch.setitem(ecommerce_bridge._config, "sap_erp_api_token", TEST_SAP_TOKEN)


@pytest.fixture
def no_secrets(monkeypatch):
    for key in ("shopify_webhook_secret", "woocommerce_webhook_secret", "sap_erp_api_token"):
        monkeypatch.setitem(ecommerce_bridge._config, key, "")


def _sign(body: bytes, secret: str) -> str:
    return base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("utf-8")


SAMPLE_SHOPIFY_ORDER = {
    "id": 892173891,
    "order_number": 1042,
    "total_price": "89.50",
    "currency": "EUR",
    "customer": {
        "first_name": "Anna",
        "last_name": "Schmidt",
        "email": "anna.schmidt@example.com",
    },
    "line_items": [
        {"id": 11, "title": "Bambu Spool Holder", "sku": "SPOOL-HLD-01", "quantity": 2, "price": "24.50"},
        {"id": 12, "title": "Toolbox Insert", "sku": "TB-INS-02", "quantity": 1, "price": "40.50"},
    ],
}

SAMPLE_WOOCOMMERCE_ORDER = {
    "id": 5519,
    "total": "45.00",
    "currency": "EUR",
    "billing": {
        "first_name": "Maximilian",
        "last_name": "Mustermann",
        "email": "max@muster.de",
    },
    "line_items": [
        {"id": 201, "name": "Cable Clip Set", "sku": "CLIP-SET-10", "quantity": 3, "price": "15.00"},
    ],
}


def test_signature_verifications(configured_secrets) -> None:
    secret = "my_super_secret_test_key"
    payload_bytes = b'{"hello": "world"}'

    # 1. Shopify HMAC
    sig_digest = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    valid_sig = base64.b64encode(sig_digest).decode("utf-8")

    assert verify_shopify_signature(payload_bytes, valid_sig, secret=secret) is True
    assert verify_shopify_signature(payload_bytes, "invalid_sig", secret=secret) is False

    # 2. WooCommerce HMAC
    assert verify_woocommerce_signature(payload_bytes, valid_sig, secret=secret) is True
    assert verify_woocommerce_signature(payload_bytes, "wrong", secret=secret) is False

    # 3. SAP Bearer
    assert verify_sap_erp_token(TEST_SAP_TOKEN) is True
    assert verify_sap_erp_token(f"Bearer {TEST_SAP_TOKEN}") is True
    assert verify_sap_erp_token("Bearer wrong_token") is False


def test_without_a_configured_secret_everything_is_refused(no_secrets) -> None:
    """Kein Standard-Geheimnis: Ein leeres Geheimnis darf nie eine Signatur 'bestätigen'."""
    body = b"{}"
    assert verify_shopify_signature(body, _sign(body, "")) is False
    assert verify_woocommerce_signature(body, _sign(body, "")) is False
    assert verify_sap_erp_token("") is False
    assert verify_sap_erp_token("Bearer ") is False


def test_process_shopify_order() -> None:
    res = process_shopify_order(SAMPLE_SHOPIFY_ORDER)
    assert res["source"] == "shopify"
    assert res["external_order_id"] == "892173891"
    assert res["order_reference"] == "Shopify #1042"
    assert res["customer"]["name"] == "Anna Schmidt"
    assert res["total_parts_quantity"] == 3
    assert len(res["items"]) == 2
    assert res["items"][0]["sku"] == "SPOOL-HLD-01"


def test_process_woocommerce_order() -> None:
    res = process_woocommerce_order(SAMPLE_WOOCOMMERCE_ORDER)
    assert res["source"] == "woocommerce"
    assert res["order_reference"] == "WC #5519"
    assert res["total_parts_quantity"] == 3
    assert res["items"][0]["sku"] == "CLIP-SET-10"


def test_process_sap_erp_order() -> None:
    sap_payload = {
        "sap_sales_order_id": "450091823",
        "plant_id": "DE-01",
        "company_code": "1000",
        "delivery_date": "2026-11-20",
        "materials": [
            {
                "material_id": "MAT-PA-CF-01",
                "description": "Lagerbock",
                "quantity": 10,
                "filament_type": "PA-CF",
                "priority": "HIGH",
            },
        ],
    }
    res = process_sap_erp_order(sap_payload)
    assert res["source"] == "sap_erp"
    assert res["total_parts_quantity"] == 10
    assert res["items"][0]["filament_material"] == "PA-CF"


def test_format_fulfillment_payload() -> None:
    ful = format_fulfillment_payload("ORDER-99", tracking_number="00340434234234", carrier="DHL")
    assert ful["fulfillment"]["carrier"] == "DHL"
    assert ful["fulfillment"]["tracking_number"] == "00340434234234"
    assert "dhl.de" in ful["fulfillment"]["tracking_url"]


@pytest.mark.asyncio
async def test_ecommerce_api_endpoints(async_client: AsyncClient, configured_secrets) -> None:
    # 1. Config GET: Geheimnisse nie im Klartext
    cfg = await async_client.get("/api/v1/integrations/ecommerce/config")
    assert cfg.status_code == 200
    assert cfg.json()["enabled"] is True
    assert TEST_SHOPIFY_SECRET not in json.dumps(cfg.json())

    # 2. Shopify Webhook mit gültiger Signatur
    s_body = json.dumps(SAMPLE_SHOPIFY_ORDER).encode("utf-8")
    s_resp = await async_client.post(
        "/api/v1/integrations/ecommerce/shopify/webhook",
        content=s_body,
        headers={"Content-Type": "application/json", "X-Shopify-Hmac-Sha256": _sign(s_body, TEST_SHOPIFY_SECRET)},
    )
    assert s_resp.status_code == 200
    assert s_resp.json()["source"] == "shopify"

    # 3. WooCommerce Webhook mit gültiger Signatur
    w_body = json.dumps(SAMPLE_WOOCOMMERCE_ORDER).encode("utf-8")
    w_resp = await async_client.post(
        "/api/v1/integrations/ecommerce/woocommerce/webhook",
        content=w_body,
        headers={"Content-Type": "application/json", "X-WC-Webhook-Signature": _sign(w_body, TEST_WOOCOMMERCE_SECRET)},
    )
    assert w_resp.status_code == 200
    assert w_resp.json()["source"] == "woocommerce"

    # 4. SAP Order POST mit Bearer-Token
    sap_resp = await async_client.post(
        "/api/v1/integrations/ecommerce/sap-erp/order",
        json={
            "sap_sales_order_id": "450091823",
            "plant_id": "DE-01",
            "company_code": "1000",
            "delivery_date": "2026-11-20",
            "materials": [
                {"material_id": "MAT-01", "description": "Halter", "quantity": 5},
            ],
        },
        headers={"Authorization": f"Bearer {TEST_SAP_TOKEN}"},
    )
    assert sap_resp.status_code == 200
    assert sap_resp.json()["source"] == "sap_erp"


_SAP_BODY = {
    "sap_sales_order_id": "1",
    "materials": [{"material_id": "M", "description": "x", "quantity": 1}],
}


@pytest.mark.asyncio
async def test_webhooks_without_a_signature_are_refused(async_client: AsyncClient, configured_secrets) -> None:
    """Früher wurde die Signatur nur geprüft, wenn der Header da war: ohne Header kam jede Bestellung durch."""
    body = json.dumps(SAMPLE_SHOPIFY_ORDER)
    for url in ("shopify/webhook", "woocommerce/webhook"):
        resp = await async_client.post(
            f"/api/v1/integrations/ecommerce/{url}", content=body, headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 401, url
    resp = await async_client.post("/api/v1/integrations/ecommerce/sap-erp/order", json=_SAP_BODY)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhooks_with_a_wrong_signature_are_refused(async_client: AsyncClient, configured_secrets) -> None:
    body = json.dumps(SAMPLE_SHOPIFY_ORDER).encode("utf-8")
    resp = await async_client.post(
        "/api/v1/integrations/ecommerce/shopify/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Shopify-Hmac-Sha256": _sign(body, "falsches-geheimnis")},
    )
    assert resp.status_code == 401
    resp = await async_client.post(
        "/api/v1/integrations/ecommerce/sap-erp/order", json=_SAP_BODY, headers={"Authorization": "Bearer falsch"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhooks_are_closed_until_a_secret_is_configured(async_client: AsyncClient, no_secrets) -> None:
    body = json.dumps(SAMPLE_SHOPIFY_ORDER).encode("utf-8")
    # Auch die "Signatur" mit leerem Geheimnis darf nichts öffnen
    resp = await async_client.post(
        "/api/v1/integrations/ecommerce/shopify/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Shopify-Hmac-Sha256": _sign(body, "")},
    )
    assert resp.status_code == 401
    resp = await async_client.post(
        "/api/v1/integrations/ecommerce/sap-erp/order", json=_SAP_BODY, headers={"Authorization": "Bearer "}
    )
    assert resp.status_code == 401
