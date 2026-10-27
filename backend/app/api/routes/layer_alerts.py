"""API für Schicht-Hinweise (Pause bei Zielschicht)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.layer_alerts import layer_alerts

router = APIRouter(prefix="/printers", tags=["layer-alerts"])


class LayerAlertUpdate(BaseModel):
    enabled: bool = False
    layer: int = Field(default=0, ge=0, le=100000)


async def _printer(printer_id: int, db: AsyncSession) -> Printer:
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(404, "Printer not found")
    return printer


@router.get("/{printer_id}/layer-alert")
async def get_layer_alert(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    return layer_alerts.status(printer_id)


@router.put("/{printer_id}/layer-alert")
async def set_layer_alert(
    printer_id: int,
    data: LayerAlertUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer(printer_id, db)
    return layer_alerts.configure(printer_id, data.enabled, data.layer)
