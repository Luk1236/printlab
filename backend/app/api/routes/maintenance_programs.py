"""API für die Wartungsprogramme (Öl und Gewindestangen)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.maintenance_programs import PROGRAMS, service
from backend.app.services.printer_manager import printer_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/printers", tags=["maintenance-programs"])


async def _get_printer(printer_id: int, db: AsyncSession) -> Printer:
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(404, "Printer not found")
    return printer


@router.get("/{printer_id}/maintenance-programs")
async def get_program_status(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """Aktueller Stand des Wartungsprogramms auf diesem Drucker."""
    return service.status(printer_id)


@router.post("/{printer_id}/maintenance-programs/{program}/start")
async def start_program(
    printer_id: int,
    program: str,
    runs: int | None = Query(None, ge=1, le=3, description="Durchgänge (1–3)"),
    platte_frei: bool = Query(False, description="Bestätigung, dass die Druckplatte leer ist"),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Startet ein Wartungsprogramm. Es wird nichts geheizt und kein Filament verwendet."""
    printer = await _get_printer(printer_id, db)
    key = program.strip().lower()
    if key not in PROGRAMS:
        raise HTTPException(400, f"Unknown maintenance program: {program}")
    if not platte_frei:
        raise HTTPException(400, "Bitte zuerst bestätigen, dass die Druckplatte frei ist.")
    client = printer_manager.get_client(printer_id)
    if client is None:
        raise HTTPException(400, "Printer not connected")
    model = printer.model or printer_manager.get_model(printer_id)
    ok, message = service.start(printer_id, key, client, model, runs)
    if not ok:
        raise HTTPException(400, message)
    logger.info("[Wartung] Drucker %s: %s gestartet", printer_id, key)
    return {"success": True, "message": message, **service.status(printer_id)}


@router.post("/{printer_id}/maintenance-programs/stop")
async def stop_program(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    """Bricht das laufende Wartungsprogramm ab."""
    ok, message = service.stop(printer_id)
    if not ok:
        raise HTTPException(400, message)
    return {"success": True, "message": message, **service.status(printer_id)}
