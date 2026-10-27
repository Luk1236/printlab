"""API für die Spaghetti-/Abbruch-Erkennung (nur Warnung)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.spaghetti_check import spaghetti_check

router = APIRouter(prefix="/printers", tags=["spaghetti-check"])


class SpaghettiCheckUpdate(BaseModel):
    enabled: bool = False
    max_components: int = Field(default=25, ge=1, le=1000)
    min_changed_percent: float = Field(default=0.5, ge=0.0, le=100.0)


@router.get("/{printer_id}/spaghetti-check")
async def get_spaghetti_check(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    return spaghetti_check.read_config()


@router.put("/{printer_id}/spaghetti-check")
async def set_spaghetti_check(
    printer_id: int,
    data: SpaghettiCheckUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    if result.scalar_one_or_none() is None:
        from fastapi import HTTPException

        raise HTTPException(404, "Printer not found")
    spaghetti_check.read_config()  # ensure file exists for next reads
    return spaghetti_check.write_config(data.model_dump())