"""Angebotskalkulator (Roadmap „Gewerbliches“).

Rechnet Material-, Energie- und Arbeitsanteil zu einem Angebotspreis zusammen.
Material geht aus der Gramm-Menge und dem eingestellten €/kg (oder einer
vorgegebenen Rate, z. B. aus einem Spool) hervor, Energie aus Druckdauer ×
Durchschnittsleistung × €/kWh, Arbeit aus der eingetragenen Handarbeitszeit ×
Stundenlohn; auf die Summe kommt der Aufschlag-Prozentsatz — jeweils die in
den Einstellungen hinterlegten Werte.

Preisliste: stehende Materialtarife aus ``data/price_list.json`` (siehe
``services/price_list.py``); der Kalkulator nutzt sie mit ``material=``.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.settings import DEFAULT_SETTINGS, get_setting
from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.services import (
    company_profile,
    einvoice,
    invoices,
    price_list,
    quote_actuals,
    quote_history,
    quote_pdf,
)
from backend.app.utils.money import as_float, money, to_decimal

router = APIRouter(prefix="/quote", tags=["quote"])


async def _float_setting(db: AsyncSession, key: str) -> float:
    raw = await get_setting(db, key)
    try:
        return float(raw) if raw is not None else getattr(DEFAULT_SETTINGS, key)
    except (TypeError, ValueError):
        return getattr(DEFAULT_SETTINGS, key)


@router.get("/price-list")
async def get_price_list(
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    return {"entries": price_list.read_list()}


@router.put("/price-list")
async def set_price_list(
    entries: list[dict],
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    return price_list.write_list(entries)


@router.get("/history")
async def get_quote_history(
    customer: str | None = Query(None, max_length=80),
    limit: int = Query(100, ge=1, le=1000),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    """Gespeicherte Angebote (neueste zuerst), optional nach Kunde gefiltert, plus Summen je Kunde."""
    return {"entries": quote_history.entries(customer, limit), "customers": quote_history.totals_by_customer()}


@router.post("/history")
async def save_quote(
    payload: dict,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    try:
        company = company_profile.read()
        return quote_history.add(payload, prefix=company["number_prefix"], number_format=company["number_format"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/history/{entry_id}/archives")
async def link_quote_archives(
    entry_id: str,
    payload: dict,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
    db: AsyncSession = Depends(get_db),
):
    """Druckjobs aus dem Archiv mit dem Angebot verknüpfen (ersetzt die bisherige Liste)."""
    from sqlalchemy import select

    from backend.app.models.archive import PrintArchive

    ids = payload.get("archive_ids", [])
    try:
        entry = quote_history.set_archives(entry_id, ids)
        if entry is None:
            raise HTTPException(404, "Angebot nicht gefunden.")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    known = set((await db.scalars(select(PrintArchive.id).where(PrintArchive.id.in_(entry["archive_ids"])))).all())
    unknown = [i for i in entry["archive_ids"] if i not in known]
    if unknown:
        quote_history.set_archives(entry_id, [i for i in entry["archive_ids"] if i in known])
        raise HTTPException(400, f"Archiv {unknown[0]} nicht gefunden.")
    return entry


@router.get("/history/{entry_id}/actuals")
async def quote_actual_costs(
    entry_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
    db: AsyncSession = Depends(get_db),
):
    """Nachkalkulation: Ist-Kosten der verknüpften Druckjobs gegen den Angebotspreis."""
    from sqlalchemy import select

    from backend.app.models.archive import PrintArchive

    entry = quote_history.get(entry_id)
    if entry is None:
        raise HTTPException(404, "Angebot nicht gefunden.")
    ids = [i for i in entry.get("archive_ids", []) if isinstance(i, int)]
    rows = (await db.scalars(select(PrintArchive).where(PrintArchive.id.in_(ids)))).all() if ids else []
    by_id = {row.id: row for row in rows}
    archives = [
        {
            "id": row.id,
            "filename": row.print_name or row.filename,
            "status": row.status,
            "filament_used_grams": row.filament_used_grams,
            "print_time_seconds": row.print_time_seconds,
            "cost": row.cost,
            "energy_cost": row.energy_cost,
        }
        for row in (by_id[i] for i in ids if i in by_id)
    ]
    rates = {
        "material_per_kg": await _float_setting(db, "default_filament_cost"),
        "energy_per_kwh": await _float_setting(db, "energy_cost_per_kwh"),
        "power_watts": await _float_setting(db, "printer_power_watts"),
        "labor_rate_per_hour": await _float_setting(db, "labor_rate_per_hour"),
    }
    result = quote_actuals.compute(entry, archives, rates)
    result["missing_ids"] = [i for i in ids if i not in by_id]
    return result


@router.put("/history/{entry_id}/work-minutes")
async def set_quote_work_minutes(
    entry_id: str,
    payload: dict,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    """Zeitbuchung: gebuchte Arbeitszeit in Minuten (leer/None entfernt sie wieder)."""
    minutes = payload.get("work_minutes") if isinstance(payload, dict) else None
    if minutes is not None:
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            raise HTTPException(422, "Arbeitszeit muss eine ganze Zahl in Minuten sein.") from None
        if not 0 <= minutes <= 20000:
            raise HTTPException(422, "Arbeitszeit muss zwischen 0 und 20000 Minuten liegen.")
    entry = quote_history.set_work_minutes(entry_id, minutes)
    if entry is None:
        raise HTTPException(404, "Angebot nicht gefunden.")
    return entry


@router.get("/company")
async def get_company(
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    """Firmendaten für den Briefkopf der Angebote."""
    return company_profile.read()


@router.put("/company")
async def set_company(
    payload: dict,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    try:
        return company_profile.write(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/company/logo")
async def get_company_logo(
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    path = company_profile.logo_path()
    if path is None:
        raise HTTPException(404, "Kein Logo hinterlegt.")
    return FileResponse(path, media_type="image/png")


@router.put("/company/logo")
async def set_company_logo(
    file: UploadFile = File(...),
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Logo für den Briefkopf hochladen (PNG oder JPEG, höchstens 2 MB); wird als sauberes PNG abgelegt."""
    data = await file.read(company_profile.MAX_LOGO_BYTES + 1)
    try:
        company_profile.save_logo(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"has_logo": True}


@router.delete("/company/logo")
async def delete_company_logo(
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    return {"deleted": company_profile.delete_logo()}


@router.get("/history/{entry_id}/pdf")
async def quote_pdf_for_entry(
    entry_id: str,
    lang: str = Query("de", pattern="^(de|en)$"),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    """Gespeichertes Angebot als PDF mit dem Briefkopf aus den Firmendaten."""
    entry = quote_history.get(entry_id)
    if entry is None:
        raise HTTPException(404, "Angebot nicht gefunden.")
    company = {**company_profile.read(), "_logo_path": company_profile.logo_path()}
    pdf = quote_pdf.render(entry, company, lang)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", str(entry.get("number") or entry_id))
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Angebot-{name}.pdf"'},
    )


@router.get("/invoices")
async def list_invoices(
    status: str | None = Query(None, pattern="^(open|paid|cancelled)$"),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    """Rechnungen (neueste zuerst), Summen je Währung und die überfälligen offenen Rechnungen."""
    return {
        "invoices": invoices.entries(status),
        "totals": invoices.totals(),
        "overdue_ids": [i["id"] for i in invoices.overdue()],
    }


@router.post("/history/{entry_id}/invoice")
async def create_invoice(
    entry_id: str,
    payload: dict | None = None,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    """Aus einem gespeicherten Angebot eine Rechnung mit eigener, lückenloser Nummer erstellen."""
    try:
        return invoices.create_from_quote(entry_id, company_profile.read(), (payload or {}).get("service_date"))
    except invoices.InvoiceError as exc:
        raise HTTPException(409 if "schon eine" in str(exc) else 400, str(exc)) from exc


def _invoice_action(action, *args):
    try:
        return action(*args)
    except invoices.InvoiceError as exc:
        raise HTTPException(404 if "nicht gefunden" in str(exc) else 400, str(exc)) from exc


@router.post("/invoices/{invoice_id}/paid")
async def mark_invoice_paid(
    invoice_id: str,
    payload: dict | None = None,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    return _invoice_action(invoices.mark_paid, invoice_id, (payload or {}).get("paid_at"))


@router.post("/invoices/{invoice_id}/reopen")
async def reopen_invoice(
    invoice_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    return _invoice_action(invoices.reopen, invoice_id)


@router.post("/invoices/{invoice_id}/cancel")
async def cancel_invoice(
    invoice_id: str,
    payload: dict | None = None,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    """Stornieren (Rechnungen werden nie gelöscht; die Nummer bleibt vergeben)."""
    return _invoice_action(invoices.cancel, invoice_id, (payload or {}).get("reason", ""))


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(
    invoice_id: str,
    lang: str = Query("de", pattern="^(de|en)$"),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    invoice = invoices.get(invoice_id)
    if invoice is None:
        raise HTTPException(404, "Rechnung nicht gefunden.")
    company = {**company_profile.read(), "_logo_path": company_profile.logo_path()}
    pdf = quote_pdf.render(invoice, company, lang, kind="invoice")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", str(invoice.get("number") or invoice_id))
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Rechnung-{name}.pdf"'},
    )


@router.get("/invoices/{invoice_id}/einvoice/check")
async def check_invoice_einvoice(
    invoice_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    """Pflichtangaben für XRechnung prüfen, ohne eine Datei zu erzeugen."""
    invoice = invoices.get(invoice_id)
    if invoice is None:
        raise HTTPException(404, "Rechnung nicht gefunden.")
    issues = einvoice.validate(invoice, company_profile.read())
    return {"valid": not issues, "issues": issues}


@router.get("/invoices/{invoice_id}/einvoice")
async def download_invoice_einvoice(
    invoice_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    """Rechnung als XRechnung-XML (UBL) herunterladen.

    Fehlt eine Pflichtangabe, wird nichts erzeugt: die Antwort nennt alle
    fehlenden Angaben. Ob das Format für den eigenen Betrieb verlangt wird und
    welche Angaben Pflicht sind, klärt die Steuerberatung — dieses XML ist
    weder zertifiziert noch gegen den KoSIT-Validator geprüft.
    """
    invoice = invoices.get(invoice_id)
    if invoice is None:
        raise HTTPException(404, "Rechnung nicht gefunden.")
    try:
        xml = einvoice.build_xml(invoice, company_profile.read())
    except einvoice.EInvoiceError as exc:
        raise HTTPException(422, {"message": "Pflichtangaben fehlen.", "issues": exc.issues}) from exc
    return Response(
        xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{einvoice.filename(invoice)}"'},
    )


@router.delete("/history/{entry_id}")
async def delete_quote(
    entry_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_DELETE_ALL),
):
    if not quote_history.delete(entry_id):
        raise HTTPException(404, "Angebot nicht gefunden.")
    return {"success": True}


@router.get("/for-archive/{archive_id}")
async def quote_for_archive(
    archive_id: int,
    labor_minutes: float = Query(0, ge=0, description="Handarbeitszeit in Minuten"),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
    db: AsyncSession = Depends(get_db),
):
    """Angebot aus den Archiv-Metadaten (Zeit + Gramm) vorrechnen."""
    from fastapi import HTTPException
    from sqlalchemy import select

    from backend.app.models.archive import PrintArchive

    archive = await db.scalar(select(PrintArchive).where(PrintArchive.id == archive_id))
    if archive is None:
        raise HTTPException(404, "Archive not found")
    grams = float(archive.filament_used_grams or 0)
    minutes = float(archive.print_time_seconds or 0) / 60.0
    material_rate = await _float_setting(db, "default_filament_cost")
    energy_per_kwh = await _float_setting(db, "energy_cost_per_kwh")
    power_watts = await _float_setting(db, "printer_power_watts")
    labor_rate = await _float_setting(db, "labor_rate_per_hour")
    markup_percent = await _float_setting(db, "quote_markup_percent")

    # Geldbeträge in Cent rechnen, erst am Ende als float ausgeben (siehe utils/money.py).
    material_cost = money(to_decimal(grams) / 1000 * to_decimal(material_rate))
    energy_cost = money(to_decimal(minutes) / 60 * to_decimal(power_watts) / 1000 * to_decimal(energy_per_kwh))
    labor_cost = money(to_decimal(labor_minutes) / 60 * to_decimal(labor_rate))
    subtotal = money(material_cost + energy_cost + labor_cost)
    markup_amount = money(subtotal * to_decimal(markup_percent) / 100)
    currency_code = (await get_setting(db, "currency")) or "EUR"
    return {
        "archive_id": archive_id,
        "currency": currency_code,
        "grams": round(grams, 2),
        "duration_minutes": round(minutes, 1),
        "material": as_float(material_cost),
        "energy": as_float(energy_cost),
        "labor": as_float(labor_cost),
        "subtotal": as_float(subtotal),
        "markup": as_float(markup_amount),
        "total": as_float(subtotal + markup_amount),
    }


@router.get("")
async def quote(
    grams: float = Query(..., ge=0, description="Filament in Gramm"),
    duration_minutes: float = Query(..., ge=0, description="Druckdauer in Minuten"),
    labor_minutes: float = Query(0, ge=0, description="Handarbeitszeit in Minuten"),
    filament_cost_per_kg: float | None = Query(
        None, ge=0, description="Materialrate; Standard: Preisliste/Einstellung"
    ),
    material: str | None = Query(None, max_length=40, description="Materialname für die Preisliste (z. B. TPU)"),
    currency: str | None = Query(None, max_length=8, description="Währungskürzel für die Antwort"),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
    db: AsyncSession = Depends(get_db),
):
    default_rate = await _float_setting(db, "default_filament_cost")
    list_rate, _list_material = price_list.rate_for(material, default_rate)
    material_rate = filament_cost_per_kg if filament_cost_per_kg is not None else list_rate
    energy_per_kwh = await _float_setting(db, "energy_cost_per_kwh")
    power_watts = await _float_setting(db, "printer_power_watts")
    labor_rate = await _float_setting(db, "labor_rate_per_hour")
    markup_percent = await _float_setting(db, "quote_markup_percent")

    material_cost = money(to_decimal(grams) / 1000 * to_decimal(material_rate))
    energy_cost = money(to_decimal(duration_minutes) / 60 * to_decimal(power_watts) / 1000 * to_decimal(energy_per_kwh))
    labor_cost = money(to_decimal(labor_minutes) / 60 * to_decimal(labor_rate))
    subtotal = money(material_cost + energy_cost + labor_cost)
    markup_amount = money(subtotal * to_decimal(markup_percent) / 100)
    total = money(subtotal + markup_amount)

    currency_code = currency or (await get_setting(db, "currency")) or "EUR"
    return {
        "currency": currency_code,
        "inputs": {
            "grams": grams,
            "duration_minutes": duration_minutes,
            "labor_minutes": labor_minutes,
            "filament_cost_per_kg": material_rate,
            "energy_cost_per_kwh": energy_per_kwh,
            "printer_power_watts": power_watts,
            "labor_rate_per_hour": labor_rate,
            "markup_percent": markup_percent,
        },
        "material": as_float(material_cost),
        "energy": as_float(energy_cost),
        "labor": as_float(labor_cost),
        "subtotal": as_float(subtotal),
        "markup": as_float(markup_amount),
        "total": as_float(total),
    }
