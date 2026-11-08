"""Kunden-Selfservice & Sofortkalkulations-Portal API für PrintLab.

Ermöglicht Sofort-Preiskalkulationen anhand von 3D-Modell-Parametern,
Materialdichten und Mengenstaffeln mit integrierter Stripe-Schnittstelle.

Bewusst öffentliche Endpunkte (Kunden-Selfservice, wie bei den Angebots-Links
in ``quote_share.py``): ``/materials`` und ``/quote`` sind reine Kalkulations-
Lesen ohne PII. ``/checkout`` ist ebenfalls öffentlich, rechnet aber ausschließlich
Kalkulationen ab, die dieser Server selbst erzeugt und gespeichert hat — der
Zahlbetrag kommt nie aus dem Request, und ungültige Rückleitungs-URLs werden
abgelehnt.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.services import company_profile
from backend.app.services.customer_portal import (
    MATERIAL_PROFILES,
    calculate_instant_quote,
    create_stripe_checkout_session,
    validate_redirect_url,
)
from backend.app.services.delivery_note_service import (
    generate_delivery_note_pdf,
    generate_thermal_label_pdf,
)
from backend.app.services.mesh_analysis import analyze_mesh_data
from backend.app.services.portal_quote_store import get_quote, store_quote

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portal", tags=["portal"])

# Rate-Limit (Muster aus quote_share.py): öffentliche Kalkulation ist billig,
# erzeugt aber Registry-Einträge; Checkouts sind teuer (Stripe-Sessions) und
# lohnenswertes Angriffsziel. Grenzen gelten pro IP und Fenster.
RATE_WINDOW_SECONDS = 60.0
RATE_MAX_QUOTE_REQUESTS = 20
RATE_MAX_CHECKOUT_REQUESTS = 6
RATE_MAX_ANALYZE_REQUESTS = 30
_hits: dict[str, dict[str, list[float]]] = {}


def _allow_client(request: Request, kind: str, max_requests: int) -> bool:
    """Rollendes Fenster pro Client-IP und Endpunktart; 429 bei Überschreitung."""
    host = (request.client.host if request.client else "") or "local"
    now = time.time()
    window = _hits.setdefault(host, {}).setdefault(kind, [])
    recent = [t for t in window if now - t < RATE_WINDOW_SECONDS]
    if len(recent) >= max_requests:
        _hits[host][kind] = recent
        return False
    recent.append(now)
    _hits[host][kind] = recent

    # Deckel gegen unbegrenztes IP-Wachstum (NAT-Fluten, gepingte Scans):
    # Entries ohne Aktivität im Fenster fliegen ab 5000 IPs.
    if len(_hits) > 5000:
        for ip in list(_hits):
            active = _hits[ip]
            if not active or all(
                now - (timestamps[-1] if timestamps else 0) >= RATE_WINDOW_SECONDS for timestamps in active.values()
            ):
                _hits.pop(ip, None)
    return True


class QuoteRequest(BaseModel):
    volume_cm3: float = Field(..., gt=0.0, le=200_000.0, description="Nettovolumen des Modells in cm³")
    filament_type: str = Field("PLA", description="Materialtyp (PLA, PETG, ABS, ASA, TPU, PLA-CF)")
    infill_percent: int = Field(15, ge=5, le=100, description="Füllgrad in Prozent (5-100)")
    layer_height: float = Field(0.20, ge=0.08, le=0.40, description="Schichthöhe in mm")
    quantity: int = Field(1, ge=1, le=1000, description="Auftragsstückzahl")


class CheckoutRequest(BaseModel):
    quote_id: str = Field(..., min_length=1, max_length=64, description="Angebots-ID aus der Sofortkalkulation")
    success_url: str = Field(..., max_length=2000, description="Erfolgs-Rückleitungs-URL")
    cancel_url: str = Field(..., max_length=2000, description="Abbruch-Rückleitungs-URL")


@router.get("/materials")
async def list_available_materials() -> dict[str, Any]:
    """Liefert die verfügbaren Materialprofile mit Dichten und Grundpreisen."""
    return {"materials": MATERIAL_PROFILES}


@router.post("/quote")
async def create_quote(req: QuoteRequest, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Berechnet ein Sofort-Angebot mit Kostenaufschlüsselung und Staffelrabatt.

    Die Kalkulation wird serverseitig in der Quote-Registry (SQLite) gespeichert
    und ist damit checkout-fähig (TTL 60 Minuten). Rate-Limited gegen
    Registry-Flood.
    """
    if not _allow_client(request, "quote", RATE_MAX_QUOTE_REQUESTS):
        raise HTTPException(429, "Zu viele Kalkulationen in kurzer Zeit. Bitte einen Moment warten.")
    quote = calculate_instant_quote(
        volume_cm3=req.volume_cm3,
        filament_type=req.filament_type,
        infill_percent=req.infill_percent,
        layer_height=req.layer_height,
        quantity=req.quantity,
    )
    await store_quote(db, quote)
    return quote


@router.post("/checkout")
async def initiate_checkout(
    req: CheckoutRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Erzeugt eine Stripe-Checkout-Session für eine zuvor kalkulierte Angebots-ID.

    Der Zahlbetrag stammt ausschließlich aus der serverseitig gespeicherten
    Kalkulation (SQLite-Registry, überlebt einen Backend-Neustart); unbekannte
    oder abgelaufene Angebote werden mit 404 abgewiesen und ungültige
    Rückleitungs-URLs mit 400.
    """
    if not _allow_client(request, "checkout", RATE_MAX_CHECKOUT_REQUESTS):
        raise HTTPException(429, "Zu viele Checkout-Anfragen in kurzer Zeit. Bitte einen Moment warten.")

    # Format-Prüfung vor der Suche (400 schlägt 404): ungültige URLs sind ein
    # Clientfehler, unabhängig vom Angebotszustand.
    try:
        validate_redirect_url(req.success_url, "success_url")
        validate_redirect_url(req.cancel_url, "cancel_url")
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    quote = await get_quote(db, req.quote_id)
    if quote is None:
        raise HTTPException(
            404,
            f"Angebot '{req.quote_id}' ist unbekannt oder abgelaufen. Bitte neu kalkulieren.",
        )

    try:
        return create_stripe_checkout_session(
            quote,
            success_url=req.success_url,
            cancel_url=req.cancel_url,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/analyze-model")
async def analyze_model(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Analysiert eine 3D-Modelldatei (STL, 3MF, OBJ) und liefert Geometriedaten."""
    if not _allow_client(request, "analyze", RATE_MAX_ANALYZE_REQUESTS):
        raise HTTPException(429, "Zu viele Analyse-Anfragen. Bitte kurz warten.")
    if not file.filename:
        raise HTTPException(400, "Keine Datei übergeben.")
    content = await file.read()
    try:
        result = analyze_mesh_data(content, file.filename)
        return result.to_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/quote-from-model")
async def create_quote_from_model(
    request: Request,
    file: UploadFile = File(...),
    filament_type: str = Form("PLA"),
    infill_percent: int = Form(15),
    layer_height: float = Form(0.20),
    quantity: int = Form(1),
    customer_name: str = Form(""),
    customer_address: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Analysiert das 3D-Modell und erzeugt sofort ein verbindliches Angebot."""
    if not _allow_client(request, "quote", RATE_MAX_QUOTE_REQUESTS):
        raise HTTPException(429, "Zu viele Kalkulationen in kurzer Zeit. Bitte einen Moment warten.")
    if not file.filename:
        raise HTTPException(400, "Keine Datei übergeben.")
    content = await file.read()
    try:
        analysis = analyze_mesh_data(content, file.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    quote = calculate_instant_quote(
        volume_cm3=analysis.volume_cm3,
        filament_type=filament_type,
        infill_percent=infill_percent,
        layer_height=layer_height,
        quantity=quantity,
    )
    quote["filename"] = file.filename
    quote["customer_name"] = customer_name.strip()
    quote["customer_address"] = customer_address.strip()
    quote["analysis"] = analysis.to_dict()

    await store_quote(db, quote)
    return quote


@router.get("/quote/{quote_id}")
async def get_stored_quote(quote_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Liefert die Details einer bestehenden Kalkulation."""
    quote = await get_quote(db, quote_id)
    if not quote:
        raise HTTPException(404, f"Angebot '{quote_id}' nicht gefunden oder abgelaufen.")
    return quote


@router.get("/delivery-note/{quote_id}/pdf")
async def download_delivery_note_pdf(
    quote_id: str,
    lang: str = "de",
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Erzeugt ein druckfähiges Lieferschein-PDF für den Druckauftrag."""
    quote = await get_quote(db, quote_id)
    if not quote:
        raise HTTPException(404, f"Angebot '{quote_id}' nicht gefunden.")
    company = company_profile.read()
    pdf_bytes = generate_delivery_note_pdf(quote, company=company, lang=lang)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Lieferschein_{quote_id}.pdf"'},
    )


@router.get("/shipping-label/{quote_id}/pdf")
async def download_shipping_label_pdf(
    quote_id: str,
    format: str = "100x150",
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Erzeugt ein Thermo-Versand- oder Paket-Etikett (PDF) mit Barcode/QR-Code."""
    quote = await get_quote(db, quote_id)
    if not quote:
        raise HTTPException(404, f"Angebot '{quote_id}' nicht gefunden.")
    company = company_profile.read()
    pdf_bytes = generate_thermal_label_pdf(quote, company=company, format_size=format)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Paket_Etikett_{quote_id}.pdf"'},
    )
