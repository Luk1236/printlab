"""Unit-Tests für E-Commerce & ERP Webhook-Brücke (Phase 24)."""

import base64
import hashlib
import hmac
import json
import pytest
from httpx import AsyncClient

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


def test_signature_verifications() -> None:
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
    assert verify_sap_erp_token("sap_bearer_printlab_token_9999") is True
    assert verify_sap_erp_token("Bearer sap_bearer_printlab_token_9999") is True
    assert verify_sap_erp_token("Bearer wrong_token") is False


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
            {"material_id": "MAT-PA-CF-01", "description": "Lagerbock", "quantity": 10, "filament_type": "PA-CF", "priority": "HIGH"},
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
async def test_ecommerce_api_endpoints(async_client: AsyncClient) -> None:
    # 1. Config GET
    cfg = await async_client.get("/api/v1/integrations/ecommerce/config")
    assert cfg.status_code == 200
    assert cfg.json()["enabled"] is True

    # 2. Shopify Webhook (ohne Header im Testmodus)
    s_resp = await async_client.post(
        "/api/v1/integrations/ecommerce/shopify/webhook",
        content=json.dumps(SAMPLE_SHOPIFY_ORDER),
        headers={"Content-Type": "application/json"},
    )
    assert s_resp.status_code == 200
    assert s_resp.json()["source"] == "shopify"

    # 3. WooCommerce Webhook
    w_resp = await async_client.post(
        "/api/v1/integrations/ecommerce/woocommerce/webhook",
        content=json.dumps(SAMPLE_WOOCOMMERCE_ORDER),
        headers={"Content-Type": "application/json"},
    )
    assert w_resp.status_code == 200
    assert w_resp.json()["source"] == "woocommerce"

    # 4. SAP Order POST
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
        headers={"Authorization": "Bearer sap_bearer_printlab_token_9999"},
    )
    assert sap_resp.status_code == 200
    assert sap_resp.json()["source"] == "sap_erp"
