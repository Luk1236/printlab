"""Kundenportal Live-Tracking & Mengenstaffel-Routen (Phase 15).

Öffentliche und geschützte Schnittstellen zur Auftragsverfolgung,
Mengenrabatt-Kalkulation und Nachbearbeitungs-Optionen.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.customer_tracking import (
    POST_PROCESSING_CATALOG,
    VOLUME_TIERS,
    calculate_order_total,
    generate_tracking_token,
    resolve_mock_or_simulated_tracking,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portal", tags=["portal-tracking"])


class CalculateTiersRequest(BaseModel):
    base_unit_price_cents: int = Field(..., gt=0, description="Grundpreis für Einzelstück in Cent")
    quantity: int = Field(1, ge=1, le=100000, description="Gewünschte Stückzahl")
    selected_options: list[str] = Field(default_factory=list, description="IDs ausgewählter Optionen")
    option_quantities: dict[str, int] = Field(default_factory=dict, description="Individuelle Stückzahlen je Option")


class GenerateTokenRequest(BaseModel):
    order_id: str = Field(..., min_length=1, description="Eindeutige Auftragsnummer oder ID")
    salt: str = Field(default="", description="Optionaler Salt-Wert")


@router.get("/pricing/options", response_model=dict[str, Any])
async def get_pricing_options_catalog() -> dict[str, Any]:
    """Liefert den Katalog verfügbarer Nachbearbeitungs- und Express-Optionen."""
    return {
        "volume_tiers": VOLUME_TIERS,
        "post_processing_options": list(POST_PROCESSING_CATALOG.values()),
    }


@router.post("/pricing/calculate-tiers", response_model=dict[str, Any])
async def calculate_tiers_endpoint(req: CalculateTiersRequest) -> dict[str, Any]:
    """Berechnet gestaffelte Preise und Nachbearbeitungskosten."""
    result = calculate_order_total(
        base_unit_price_cents=req.base_unit_price_cents,
        quantity=req.quantity,
        selected_options=req.selected_options,
        option_quantities=req.option_quantities,
    )
    return result


@router.get("/tracking/{token}", response_model=dict[str, Any])
async def get_customer_tracking_status(token: str) -> dict[str, Any]:
    """Öffentlicher Endpunkt für Kunden zur Verfolgung des Druck- und Versandstatus."""
    if not token or len(token) < 6:
        raise HTTPException(status_code=400, detail="Ungültiger Tracking-Token")
    data = resolve_mock_or_simulated_tracking(token)
    return data


@router.post("/tracking/token", response_model=dict[str, str])
async def generate_order_tracking_token(
    req: GenerateTokenRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, str]:
    """Erzeugt einen sicheren Tracking-Token für einen Auftrag (nur Mitarbeiter, nicht der Kunde selbst)."""
    tok = generate_tracking_token(req.order_id, salt=req.salt)
    return {
        "order_id": req.order_id,
        "tracking_token": tok,
        "tracking_url": f"/track/{tok}",
    }
