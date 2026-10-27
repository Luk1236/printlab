"""API für die Kamera-Einmessung über die vier Plattenecken."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services import plate_calibration

router = APIRouter(prefix="/printers", tags=["plate-calibration"])


class PlateCalibrationPoints(BaseModel):
    points: list


async def _printer_exists(printer_id: int, db: AsyncSession) -> None:
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(404, "Printer not found")


@router.get("/{printer_id}/plate-calibration")
async def get_plate_calibration(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    return plate_calibration.status(printer_id)


@router.put("/{printer_id}/plate-calibration")
async def set_plate_calibration(
    printer_id: int,
    data: PlateCalibrationPoints,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer_exists(printer_id, db)
    try:
        return plate_calibration.set_points(printer_id, data.points)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/{printer_id}/plate-calibration")
async def clear_plate_calibration(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer_exists(printer_id, db)
    return plate_calibration.clear(printer_id)


@router.get("/{printer_id}/plate-calibration/preview")
async def preview_plate_calibration(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Live-Snapshot in die Plattenaufsicht übertragen (JPEG)."""
    from backend.app.main import _capture_snapshot_for_notification

    await _printer_exists(printer_id, db)
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(404, "Printer not found")
    if not plate_calibration.status(printer_id)["calibrated"]:
        raise HTTPException(400, "Keine Einmessung gespeichert.")
    snapshot = await _capture_snapshot_for_notification(printer_id, printer, logging.getLogger(__name__))
    if not snapshot:
        raise HTTPException(503, "Kein Kamerabild verfügbar.")
    warped = plate_calibration.warp_bytes(printer_id, snapshot)
    if warped is None:
        raise HTTPException(500, "Warp fehlgeschlagen — Einmessung prüfen.")
    return Response(content=warped, media_type="image/jpeg")