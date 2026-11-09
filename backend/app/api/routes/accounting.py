"""DATEV-Export & ZUGFeRD-Endpunkte (Phase 16).

Schnittstellen für Buchhaltung, Steuerberater und E-Rechnungs-Austausch.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services import einvoice, invoices
from backend.app.services.accounting_export import (
    KONTENRAHMEN,
    generate_datev_csv,
    generate_zugferd_facturx_pdf,
    get_accounting_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounting", tags=["accounting"])


@router.get("/kontenrahmen", response_model=dict[str, Any])
async def list_kontenrahmen(
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
) -> dict[str, Any]:
    """Liefert die unterstützen DATEV-Kontenrahmen (SKR03, SKR04) und Kontenmappings."""
    return {"kontenrahmen": KONTENRAHMEN}


@router.get("/datev-preview", response_model=dict[str, Any])
async def preview_datev_export(
    skr: str = Query("SKR03", pattern="^(SKR03|SKR04|skr03|skr04)$"),
    from_date: str | None = Query(None, description="Startdatum JJJJ-MM-TT"),
    to_date: str | None = Query(None, description="Enddatum JJJJ-MM-TT"),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
) -> dict[str, Any]:
    """Liefert die Kontroll- und Summenwerte für den anstehenden DATEV-Buchungsstapel."""
    all_invs = invoices.entries(limit=5000)
    summary = get_accounting_summary(all_invs)
    summary["selected_skr"] = skr.upper()
    summary["from_date"] = from_date
    summary["to_date"] = to_date
    return summary


@router.get("/datev-csv")
async def download_datev_csv(
    skr: str = Query("SKR03", pattern="^(SKR03|SKR04|skr03|skr04)$"),
    consultant: int = Query(1001, ge=1000, le=9999999),
    client: int = Query(10001, ge=1, le=99999),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
) -> Response:
    """Erzeugt und lädt den amtlichen DATEV EXTF Buchungsstapel (CSV) herunter."""
    all_invs = invoices.entries(limit=5000)
    csv_text = generate_datev_csv(
        invoices_list=all_invs,
        skr=skr,
        consultant_number=consultant,
        client_number=client,
        from_date=from_date,
        to_date=to_date,
    )

    filename = f"EXTF_Buchungsstapel_{skr.upper()}_{consultant}_{client}.csv"
    # DATEV bevorzugt Windows-1252 / ISO-8859-1 Codierung
    encoded_bytes = csv_text.encode("iso-8859-1", errors="replace")

    return Response(
        content=encoded_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/invoices/{invoice_id}/zugferd-pdf")
async def download_invoice_zugferd_pdf(
    invoice_id: str,
    lang: str = Query("de", pattern="^(de|en)$"),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
) -> Response:
    """Lädt die Rechnung als hybrides ZUGFeRD 2.2 / Factur-X PDF/A-3 Dokument herunter."""
    invoice = invoices.get(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden.")

    try:
        pdf_bytes = generate_zugferd_facturx_pdf(invoice, lang=lang)
    except einvoice.EInvoiceError as exc:
        raise HTTPException(
            status_code=422, detail={"message": "Pflichtangaben fehlen.", "issues": exc.issues}
        ) from exc

    filename = f"ZUGFeRD_{invoice.get('number', invoice_id)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
