"""Monats-Report: Zahlenwerk und PDF eines Kalendermonats (Angebote/Rechnungen/Fertigung)."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.settings import DEFAULT_SETTINGS, get_setting
from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.user import User
from backend.app.services import company_profile, monthly_report, monthly_report_pdf

router = APIRouter(prefix="/monthly-report", tags=["monthly-report"])


async def _rates(db: AsyncSession) -> dict[str, float]:
    rates = {}
    for key in ("default_filament_cost", "energy_cost_per_kwh", "printer_power_watts"):
        raw = await get_setting(db, key)
        try:
            rates[key] = float(raw) if raw is not None else float(getattr(DEFAULT_SETTINGS, key))
        except (TypeError, ValueError):
            rates[key] = float(getattr(DEFAULT_SETTINGS, key))
    return rates


@router.get("/{year}/{month}")
async def get_report(
    year: int,
    month: int,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
    db: AsyncSession = Depends(get_db),
):
    """Zahlenwerk des Monats: Rechnungen, Angebote, Fertigung, Gewinn der Nachkalkulation."""
    report = await monthly_report.collect(db, year, month, await _rates(db))
    return report


@router.get("/{year}/{month}/pdf")
async def get_report_pdf(
    year: int,
    month: int,
    lang: str = "de",
    _: User | None = RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
    db: AsyncSession = Depends(get_db),
):
    """Monats-Report als A4-PDF (de/en), Briefkopf aus den Firmendaten."""
    if not 1 <= month <= 12:
        raise HTTPException(422, "Monat muss zwischen 1 und 12 liegen.")
    report = await monthly_report.collect(db, year, month, await _rates(db))
    company = {**company_profile.read(), "_logo_path": company_profile.logo_path()}
    pdf = monthly_report_pdf.render(report, company, lang="de" if lang.startswith("de") else "en")
    name = f"PrintLab-Monatsreport-{year}-{month:02d}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
