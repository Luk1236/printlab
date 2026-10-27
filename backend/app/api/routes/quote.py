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

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.settings import DEFAULT_SETTINGS, get_setting
from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.services import price_list

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

    material_cost = (grams / 1000.0) * material_rate
    energy_cost = (minutes / 60.0) * (power_watts / 1000.0) * energy_per_kwh
    labor_cost = (labor_minutes / 60.0) * labor_rate
    subtotal = material_cost + energy_cost + labor_cost
    markup_amount = subtotal * (markup_percent / 100.0)
    currency_code = (await get_setting(db, "currency")) or "EUR"
    return {
        "archive_id": archive_id,
        "currency": currency_code,
        "grams": round(grams, 2),
        "duration_minutes": round(minutes, 1),
        "material": round(material_cost, 2),
        "energy": round(energy_cost, 2),
        "labor": round(labor_cost, 2),
        "subtotal": round(subtotal, 2),
        "markup": round(markup_amount, 2),
        "total": round(subtotal + markup_amount, 2),
    }


@router.get("")
async def quote(
    grams: float = Query(..., ge=0, description="Filament in Gramm"),
    duration_minutes: float = Query(..., ge=0, description="Druckdauer in Minuten"),
    labor_minutes: float = Query(0, ge=0, description="Handarbeitszeit in Minuten"),
    filament_cost_per_kg: float | None = Query(None, ge=0, description="Materialrate; Standard: Preisliste/Einstellung"),
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

    material_cost = (grams / 1000.0) * material_rate
    energy_cost = (duration_minutes / 60.0) * (power_watts / 1000.0) * energy_per_kwh
    labor_cost = (labor_minutes / 60.0) * labor_rate
    subtotal = material_cost + energy_cost + labor_cost
    markup_amount = subtotal * (markup_percent / 100.0)
    total = subtotal + markup_amount

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
        "material": round(material_cost, 2),
        "energy": round(energy_cost, 2),
        "labor": round(labor_cost, 2),
        "subtotal": round(subtotal, 2),
        "markup": round(markup_amount, 2),
        "total": round(total, 2),
    }