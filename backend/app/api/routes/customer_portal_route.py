"""Kunden-Selfservice & Sofortkalkulations-Portal API für PrintLab.

Ermöglicht Sofort-Preiskalkulationen anhand von 3D-Modell-Parametern,
Materialdichten und Mengenstaffeln mit integrierter Stripe-Schnittstelle.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.services.customer_portal import (
    MATERIAL_PROFILES,
    calculate_instant_quote,
    create_stripe_checkout_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portal", tags=["portal"])


class QuoteRequest(BaseModel):
    volume_cm3: float = Field(..., gt=0.0, description="Nettovolumen des Modells in cm³")
    filament_type: str = Field("PLA", description="Materialtyp (PLA, PETG, ABS, ASA, TPU, PLA-CF)")
    infill_percent: int = Field(15, ge=5, le=100, description="Füllgrad in Prozent (5-100)")
    layer_height: float = Field(0.20, ge=0.08, le=0.40, description="Schichthöhe in mm")
    quantity: int = Field(1, ge=1, le=1000, description="Auftragsstückzahl")


class CheckoutRequest(BaseModel):
    quote_id: str = Field(..., description="Angebots-ID aus der Sofortkalkulation")
    success_url: str = Field(..., description="Erfolgs-Rückleitungs-URL")
    cancel_url: str = Field(..., description="Abbruch-Rückleitungs-URL")


@router.get("/materials")
async def list_available_materials() -> dict[str, Any]:
    """Liefert die verfügbaren Materialprofile mit Dichten und Grundpreisen."""
    return {"materials": MATERIAL_PROFILES}


@router.post("/quote")
async def create_quote(req: QuoteRequest) -> dict[str, Any]:
    """Berechnet ein Sofort-Angebot mit Kostenaufschlüsselung und Staffelrabatt."""
    return calculate_instant_quote(
        volume_cm3=req.volume_cm3,
        filament_type=req.filament_type,
        infill_percent=req.infill_percent,
        layer_height=req.layer_height,
        quantity=req.quantity,
    )


@router.post("/checkout")
async def initiate_checkout(req: CheckoutRequest) -> dict[str, Any]:
    """Erzeugt eine Stripe-Checkout-Session für das Angebot."""
    # Beispielhaftes Mock-/Live-Angebot für den Checkout
    mock_quote = {
        "quote_id": req.quote_id,
        "filament_type": "PLA",
        "quantity": 1,
        "pricing": {"gross_total_eur": 24.50},
    }
    return create_stripe_checkout_session(mock_quote, req.success_url, req.cancel_url)
