"""API-Router für E-Commerce & ERP Webhook-Integrationen (Phase 24)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.ecommerce_bridge import (
    format_fulfillment_payload,
    get_bridge_config,
    process_sap_erp_order,
    process_shopify_order,
    process_woocommerce_order,
    update_bridge_config,
    verify_sap_erp_token,
    verify_shopify_signature,
    verify_woocommerce_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/ecommerce", tags=["ecommerce-integrations"])


class BridgeConfigUpdate(BaseModel):
    shopify_webhook_secret: str | None = None
    woocommerce_webhook_secret: str | None = None
    sap_erp_api_token: str | None = None
    auto_queue_incoming_orders: bool | None = None
    default_material: str | None = None


class SapOrderRequest(BaseModel):
    sap_sales_order_id: str = Field(..., description="SAP Belegnummer")
    plant_id: str = Field("1000", description="Werkskennung")
    company_code: str = Field("1000")
    delivery_date: str = Field("", description="Wunschlieferdatum (ISO)")
    materials: list[dict[str, Any]] = Field(..., min_length=1)


class FulfillmentEventRequest(BaseModel):
    order_id: str
    tracking_number: str
    carrier: str = "DHL"
    tracking_url: str = ""


@router.get("/config", response_model=dict[str, Any])
async def get_config(
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
) -> dict[str, Any]:
    """Liefert die Konfiguration der E-Commerce-Brücke."""
    return get_bridge_config()


@router.put("/config", response_model=dict[str, Any])
async def update_config(
    req: BridgeConfigUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
) -> dict[str, Any]:
    """Aktualisiert Webhook-Secrets und Standardparameter."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    return update_bridge_config(updates)


@router.post("/shopify/webhook", response_model=dict[str, Any])
async def handle_shopify_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(None),
) -> dict[str, Any]:
    """Empfängt Bestellungen aus Shopify ('orders/create') mit Signaturprüfung."""
    body_bytes = await request.body()
    if x_shopify_hmac_sha256:
        valid = verify_shopify_signature(body_bytes, x_shopify_hmac_sha256)
        if not valid:
            raise HTTPException(401, "Ungültige Shopify Webhook HMAC-SHA256 Signatur.")

    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        raise HTTPException(400, "Ungültiges JSON-Format im Webhook-Body.")

    return process_shopify_order(payload)


@router.post("/woocommerce/webhook", response_model=dict[str, Any])
async def handle_woocommerce_webhook(
    request: Request,
    x_wc_webhook_signature: str | None = Header(None),
) -> dict[str, Any]:
    """Empfängt Bestellungen aus WooCommerce ('order.created') mit Signaturprüfung."""
    body_bytes = await request.body()
    if x_wc_webhook_signature:
        valid = verify_woocommerce_signature(body_bytes, x_wc_webhook_signature)
        if not valid:
            raise HTTPException(401, "Ungültige WooCommerce Webhook Signatur.")

    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        raise HTTPException(400, "Ungültiges JSON-Format im Webhook-Body.")

    return process_woocommerce_order(payload)


@router.post("/sap-erp/order", response_model=dict[str, Any])
async def handle_sap_order(
    req: SapOrderRequest,
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    """Empfängt Fertigungsaufträge aus SAP ERP Systemen über Bearer-Token."""
    if authorization:
        if not verify_sap_erp_token(authorization):
            raise HTTPException(401, "Ungültiges SAP ERP API Bearer-Token.")

    return process_sap_erp_order(req.model_dump())


@router.post("/fulfillment/preview", response_model=dict[str, Any])
async def preview_fulfillment_payload(
    req: FulfillmentEventRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Erzeugt das Rückmelde-Event für den Web-Shop mit Sendungsverfolgung."""
    return format_fulfillment_payload(
        order_id=req.order_id,
        tracking_number=req.tracking_number,
        carrier=req.carrier,
        tracking_url=req.tracking_url,
    )
