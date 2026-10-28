"""API für den Erste-Schicht-Inspektor."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.first_layer_inspector import first_layer_inspector

router = APIRouter(prefix="/printers", tags=["first-layer-inspector"])


class FirstLayerUpdate(BaseModel):
    enabled: bool = False
    pause_on_warning: bool | None = None


@router.get("/{printer_id}/first-layer-inspector")
async def get_first_layer(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    return first_layer_inspector.status(printer_id)


@router.put("/{printer_id}/first-layer-inspector")
async def set_first_layer(
    printer_id: int,
    data: FirstLayerUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(404, "Printer not found")
    return first_layer_inspector.configure(printer_id, data.enabled, data.pause_on_warning)
