"""API für Tür-Servo und Plattenwechsler (aus dem Bambu-Monitor)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.hardware_extension import get_hardware
from backend.app.services.printer_manager import printer_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/printers", tags=["hardware"])

ACTIVE_STATES = frozenset({"PREPARE", "SLICING", "RUNNING", "PAUSE"})


async def _printer_and_guard(printer_id: int, db: AsyncSession) -> Printer:
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(404, "Printer not found")
    # Im Simulationsmodus wird keine echte Hardware bewegt; dann darf man auch
    # ohne verbundenen Drucker testen. Im Befehlsmodus gelten die harten Sperren.
    if get_hardware().status()["mode"] == "simulated":
        return printer
    client = printer_manager.get_client(printer_id)
    if client is None or not client.state.connected:
        raise HTTPException(400, "Printer not connected")
    if client.state.state == "unknown":
        raise HTTPException(400, "Printer state unknown")
    if client.state.state in ACTIVE_STATES:
        raise HTTPException(400, "Locked while printing")
    return printer


@router.get("/{printer_id}/hardware")
async def get_hardware_status(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """Zustand von Tür und Magazin (auch bei nicht verbundenem Drucker)."""
    return get_hardware().status()


@router.post("/{printer_id}/hardware/door/open")
async def open_door(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer_and_guard(printer_id, db)
    ok, message = await asyncio.to_thread(get_hardware().open_door)
    if not ok:
        raise HTTPException(400, message)
    return {"success": True, "message": message, **get_hardware().status()}


@router.post("/{printer_id}/hardware/door/close")
async def close_door(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer_and_guard(printer_id, db)
    ok, message = await asyncio.to_thread(get_hardware().close_door)
    if not ok:
        raise HTTPException(400, message)
    return {"success": True, "message": message, **get_hardware().status()}


@router.post("/{printer_id}/hardware/plate/change")
async def change_plate(
    printer_id: int,
    job: str = Query("", max_length=200, description="Name des fertigen Auftrags (optional)"),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer_and_guard(printer_id, db)
    ok, message = await asyncio.to_thread(get_hardware().change_plate, job)
    if not ok:
        raise HTTPException(400, message)
    return {"success": True, "message": message, **get_hardware().status()}


@router.post("/{printer_id}/hardware/magazine/refill")
async def refill_magazine(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    printer = await _printer_and_guard(printer_id, db)
    ok, message = await asyncio.to_thread(get_hardware().refill_magazine)
    if not ok:
        raise HTTPException(400, message)
    logger.info("[Hardware] Magazin für Drucker %s aufgefüllt (%s)", printer.id, message)
    return {"success": True, "message": message, **get_hardware().status()}


@router.post("/{printer_id}/hardware/emergency-stop")
async def emergency_stop(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Not-Halt: funktioniert bewusst auch bei Druck/offline, ohne den normalen Guard."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(404, "Printer not found")
    ok, message = await asyncio.to_thread(get_hardware().emergency_stop)
    if not ok:
        raise HTTPException(400, message)
    return {"success": True, "message": message, **get_hardware().status()}
