"""API für den Bauteil-Wächter."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.part_watcher import part_watcher

router = APIRouter(prefix="/printers", tags=["part-watcher"])


class PartWatcherUpdate(BaseModel):
    enabled: bool = False
    threshold: float = Field(default=1.0, ge=0.05, le=20.0)


@router.get("/{printer_id}/part-watcher")
async def get_part_watcher(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    return part_watcher.status(printer_id)


@router.put("/{printer_id}/part-watcher")
async def set_part_watcher(
    printer_id: int,
    data: PartWatcherUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(404, "Printer not found")
    return part_watcher.configure(printer_id, data.enabled, data.threshold)
