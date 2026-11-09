"""E-Commerce & ERP Webhook-Integrationsbrücke für Shopify, WooCommerce und SAP (Phase 24).

Verarbeitet eingehende Bestell-Webhooks mit kryptographischer HMAC-Signaturprüfung,
extrahiert Bauteil-Positionen (SKUs, Stückzahlen, Farben) und leitet Druckaufträge
vollautomatisch in die PrintLab-Produktionswarteschlange weiter.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Es gibt bewusst keine Standard-Geheimnisse: Ein im Quelltext stehender Schlüssel ist öffentlich bekannt und
# erlaubt jedem, Bestellungen einzuspeisen. Ohne gesetztes Geheimnis lehnen die Empfänger alles ab.
_config: dict[str, Any] = {
    "enabled": True,
    "shopify_webhook_secret": os.environ.get("PRINTLAB_SHOPIFY_WEBHOOK_SECRET", ""),
    "woocommerce_webhook_secret": os.environ.get("PRINTLAB_WOOCOMMERCE_WEBHOOK_SECRET", ""),
    "sap_erp_api_token": os.environ.get("PRINTLAB_SAP_ERP_API_TOKEN", ""),
    "auto_queue_incoming_orders": True,
    "default_material": "PLA",
    "default_infill_percent": 15,
}


def get_bridge_config() -> dict[str, Any]:
    """Liefert die E-Commerce- und Webhook-Einstellungen (Secrets maskiert)."""
    cfg = dict(_config)
    for key in ("shopify_webhook_secret", "woocommerce_webhook_secret", "sap_erp_api_token"):
        cfg[key + "_set"] = bool(cfg[key])
        cfg[key] = "***" + cfg[key][-4:] if len(cfg[key]) >= 12 else ("***" if cfg[key] else "")
    return cfg


def update_bridge_config(new_config: dict[str, Any]) -> dict[str, Any]:
    """Aktualisiert Webhook-Tokens und Verhaltensparameter."""
    for k in (
        "shopify_webhook_secret",
        "woocommerce_webhook_secret",
        "sap_erp_api_token",
        "auto_queue_incoming_orders",
        "default_material",
    ):
        if k in new_config:
            _config[k] = new_config[k]
    return get_bridge_config()


def verify_shopify_signature(body_bytes: bytes, hmac_header: str, secret: str | None = None) -> bool:
    """Verifiziert die HMAC-SHA256 Signatur eines Shopify-Webhooks."""
    sec = secret or _config["shopify_webhook_secret"]
    if not sec:
        return False
    digest = hmac.new(sec.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    expected_hmac = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected_hmac, hmac_header.strip())


def verify_woocommerce_signature(body_bytes: bytes, signature_header: str, secret: str | None = None) -> bool:
    """Verifiziert die Base64 HMAC-SHA256 Signatur von WooCommerce."""
    sec = secret or _config["woocommerce_webhook_secret"]
    if not sec:
        return False
    digest = hmac.new(sec.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    expected_sig = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected_sig, signature_header.strip())


def verify_sap_erp_token(provided_token: str) -> bool:
    """Prüft das statische Bearer-Token von SAP ERP Anbindungen."""
    expected = _config["sap_erp_api_token"]
    if not expected:
        return False
    clean_token = provided_token.replace("Bearer ", "").strip()
    return hmac.compare_digest(expected, clean_token)


def process_shopify_order(payload: dict[str, Any]) -> dict[str, Any]:
    """Wandelt einen Shopify-Auftrag ('orders/create') in einen PrintLab Fertigungsauftrag um."""
    order_id = str(payload.get("id", "SHOPIFY-UNKNOWN"))
    order_number = str(payload.get("order_number", payload.get("name", order_id)))
    customer = payload.get("customer") or {}
    cust_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip() or "Shopify Kunde"
    cust_email = customer.get("email", "")

    items = []
    total_parts = 0
    for li in payload.get("line_items", []):
        qty = max(1, int(li.get("quantity", 1)))
        total_parts += qty
        items.append(
            {
                "line_item_id": str(li.get("id")),
                "sku": li.get("sku", "CUSTOM-3D-PART"),
                "title": li.get("title", "3D-Druck Bauteil"),
                "quantity": qty,
                "unit_price_eur": float(li.get("price", 0.0)),
                "filament_material": _config["default_material"],
                "requires_slice": True,
            }
        )

    return {
        "source": "shopify",
        "external_order_id": order_id,
        "order_reference": f"Shopify #{order_number}",
        "customer": {
            "name": cust_name,
            "email": cust_email,
        },
        "total_items_count": len(items),
        "total_parts_quantity": total_parts,
        "status": "QUEUED" if _config["auto_queue_incoming_orders"] else "PENDING_APPROVAL",
        "currency": payload.get("currency", "EUR"),
        "total_amount_eur": float(payload.get("total_price", 0.0)),
        "items": items,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def process_woocommerce_order(payload: dict[str, Any]) -> dict[str, Any]:
    """Wandelt einen WooCommerce-Auftrag ('order.created') in einen PrintLab Fertigungsauftrag um."""
    order_id = str(payload.get("id", "WC-UNKNOWN"))
    billing = payload.get("billing") or {}
    cust_name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip() or "WooCommerce Kunde"
    cust_email = billing.get("email", "")

    items = []
    total_parts = 0
    for li in payload.get("line_items", []):
        qty = max(1, int(li.get("quantity", 1)))
        total_parts += qty
        items.append(
            {
                "line_item_id": str(li.get("id")),
                "sku": li.get("sku", "WC-PART"),
                "title": li.get("name", "WooCommerce Bauteil"),
                "quantity": qty,
                "unit_price_eur": float(li.get("price", 0.0)),
                "filament_material": _config["default_material"],
                "requires_slice": True,
            }
        )

    return {
        "source": "woocommerce",
        "external_order_id": order_id,
        "order_reference": f"WC #{order_id}",
        "customer": {
            "name": cust_name,
            "email": cust_email,
        },
        "total_items_count": len(items),
        "total_parts_quantity": total_parts,
        "status": "QUEUED" if _config["auto_queue_incoming_orders"] else "PENDING_APPROVAL",
        "currency": payload.get("currency", "EUR"),
        "total_amount_eur": float(payload.get("total", 0.0)),
        "items": items,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def process_sap_erp_order(payload: dict[str, Any]) -> dict[str, Any]:
    """Wandelt einen SAP-B2B-Werksauftrag in einen PrintLab Fertigungsauftrag um."""
    sap_doc_num = str(payload.get("sap_sales_order_id", payload.get("doc_number", "SAP-450000")))
    plant_id = str(payload.get("plant_id", "WERK-01"))
    company = str(payload.get("company_code", "1000"))

    items = []
    total_parts = 0
    for mat in payload.get("materials", []):
        qty = max(1, int(mat.get("quantity", 1)))
        total_parts += qty
        items.append(
            {
                "material_number": mat.get("material_id", "MAT-001"),
                "description": mat.get("description", "Industrie-Bauteil"),
                "quantity": qty,
                "filament_material": mat.get("filament_type", "PA-CF"),
                "priority": mat.get("priority", "HIGH"),
            }
        )

    return {
        "source": "sap_erp",
        "external_order_id": sap_doc_num,
        "order_reference": f"SAP Doc {sap_doc_num} (Plant {plant_id})",
        "company_code": company,
        "total_items_count": len(items),
        "total_parts_quantity": total_parts,
        "status": "QUEUED",
        "required_delivery_date": payload.get("delivery_date", ""),
        "items": items,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def format_fulfillment_payload(
    order_id: str,
    tracking_number: str,
    carrier: str = "DHL",
    tracking_url: str = "",
) -> dict[str, Any]:
    """Formatiert das Rückmelde-Event für den Web-Shop oder das ERP-System."""
    return {
        "fulfillment": {
            "order_id": order_id,
            "status": "SUCCESS",
            "carrier": carrier,
            "tracking_number": tracking_number,
            "tracking_url": tracking_url
            or f"https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode={tracking_number}",
            "fulfilled_at": datetime.now(timezone.utc).isoformat(),
            "notify_customer": True,
        }
    }
