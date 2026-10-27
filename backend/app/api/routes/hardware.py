"""API für Tür-Servo und Plattenwechsler (aus dem Bambu-Monitor) +
Magazin-Verwaltung, Hardware-Konfiguration und Audit-Log (Roadmap P2)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled, get_current_user_optional
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services import audit_log
from backend.app.services import auto_plate_change
from backend.app.services.hardware_extension import get_hardware
from backend.app.services.printer_manager import printer_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/printers", tags=["hardware"])

ACTIVE_STATES = frozenset({"PREPARE", "SLICING", "RUNNING", "PAUSE"})


async def _printer_or_404(printer_id: int, db: AsyncSession) -> Printer:
    """Existenz des Druckers prüfen (keine Bewegungs-Sperre: Konfig/Magazin
    sind reine Datei-/Zustandsänderungen und auch bei offline erlaubt)."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(404, "Printer not found")
    return printer


def _audit(action: str, ok: bool, message: str, printer_id: int, user=None,
           details: dict | None = None) -> None:
    audit_log.record(action, ok, message, printer_id, getattr(user, "username", None), details)


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
    return {
        **get_hardware().status(),
        "auto_plate_change": {
            **auto_plate_change.read_config(),
            "last_run": auto_plate_change.last_run(printer_id),
        },
    }


@router.get("/{printer_id}/hardware/audit-log")
async def get_hardware_audit_log(
    printer_id: int,
    limit: int = Query(50, ge=1, le=500),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """Neueste protokollierte Hardware-/Wartungsaktionen."""
    return audit_log.entries(limit=limit, printer_id=printer_id)


@router.put("/{printer_id}/hardware/magazine")
async def set_magazine_slots(
    printer_id: int,
    data: dict,
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Magazin-Fächer setzen: Status und Etikett je Fach.

    Erwartet ``slots: [{id, status?, label?}, ...]``; unbekannte Werte werden
    abgelehnt, unbeteiligte Fächer bleiben unverändert.
    """
    await _printer_or_404(printer_id, db)
    hw = get_hardware()
    slots_in = data.get("slots") if isinstance(data, dict) else None
    if not isinstance(slots_in, list) or not slots_in:
        raise HTTPException(400, "slots-Liste erwartet.")
    ok, message = await asyncio.to_thread(hw.edit_slots, slots_in)
    if not ok:
        raise HTTPException(400, message)
    entry = audit_log.record(
        "magazine_edit", True, message, printer_id, getattr(user, "username", None), {"slots": slots_in}
    )
    logger.info("[Hardware] Magazin-Edit Drucker %s (%s)", printer_id, entry["ts"])
    return {"success": True, "message": message, **hw.status(), "audit": entry}


@router.get("/{printer_id}/hardware/config")
async def get_hardware_config(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    """Hardware-Konfiguration (Befehle, Modus, Automatik) zum Anzeigen."""
    hw = get_hardware()
    return {**hw.config(), "auto_plate_change": auto_plate_change.read_config()}


@router.put("/{printer_id}/hardware/config")
async def set_hardware_config(
    printer_id: int,
    data: dict,
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Hardware-Konfiguration schreiben (Befehle, Modus, Timeout, Automatik)."""
    await _printer_or_404(printer_id, db)
    if not isinstance(data, dict) or not data:
        raise HTTPException(400, "Konfigurationstext erwartet.")
    merged = dict(data)
    if "auto_plate_change" in data:
        if isinstance(data["auto_plate_change"], dict):
            auto_plate_change.write_config(data["auto_plate_change"])
        merged.pop("auto_plate_change")
    hw = get_hardware()
    ok, message = await asyncio.to_thread(hw.update_config, merged)
    if not ok:
        raise HTTPException(400, message)
    audit_log.record(
        "hardware_config", True, message, printer_id, getattr(user, "username", None),
        {"keys": sorted(merged.keys())},
    )
    return {
        "success": True,
        "message": message,
        **hw.config(),
        "auto_plate_change": auto_plate_change.read_config(),
    }


@router.put("/{printer_id}/hardware/auto-plate-change")
async def update_auto_plate_change(
    printer_id: int,
    payload: dict,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
):
    """Automatik-Konfiguration (Plattenwechsel nach Druckende) setzen."""
    cfg = auto_plate_change.write_config(payload or {})
    return {
        "auto_plate_change": {
            **cfg,
            "last_run": auto_plate_change.last_run(printer_id),
        }
    }


@router.post("/{printer_id}/hardware/door/open")
async def open_door(
    printer_id: int,
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer_and_guard(printer_id, db)
    ok, message = await asyncio.to_thread(get_hardware().open_door)
    _audit("door_open", ok, message, printer_id, user)
    if not ok:
        raise HTTPException(400, message)
    return {"success": True, "message": message, **get_hardware().status()}


@router.post("/{printer_id}/hardware/door/close")
async def close_door(
    printer_id: int,
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer_and_guard(printer_id, db)
    ok, message = await asyncio.to_thread(get_hardware().close_door)
    _audit("door_close", ok, message, printer_id, user)
    if not ok:
        raise HTTPException(400, message)
    return {"success": True, "message": message, **get_hardware().status()}


@router.post("/{printer_id}/hardware/plate/change")
async def change_plate(
    printer_id: int,
    job: str = Query("", max_length=200, description="Name des fertigen Auftrags (optional)"),
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    await _printer_and_guard(printer_id, db)
    ok, message = await asyncio.to_thread(get_hardware().change_plate, job)
    _audit("plate_change", ok, message, printer_id, user, {"job": job})
    if not ok:
        raise HTTPException(400, message)
    return {"success": True, "message": message, **get_hardware().status()}


@router.post("/{printer_id}/hardware/magazine/refill")
async def refill_magazine(
    printer_id: int,
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    printer = await _printer_and_guard(printer_id, db)
    ok, message = await asyncio.to_thread(get_hardware().refill_magazine)
    _audit("magazine_refill", ok, message, printer_id, user)
    if not ok:
        raise HTTPException(400, message)
    logger.info("[Hardware] Magazin für Drucker %s aufgefüllt (%s)", printer.id, message)
    return {"success": True, "message": message, **get_hardware().status()}


@router.post("/{printer_id}/hardware/emergency-stop")
async def emergency_stop(
    printer_id: int,
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Not-Halt: funktioniert bewusst auch bei Druck/offline, ohne den normalen Guard."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(404, "Printer not found")
    ok, message = await asyncio.to_thread(get_hardware().emergency_stop)
    _audit("emergency_stop", ok, message, printer_id, user)
    if not ok:
        raise HTTPException(400, message)
    return {"success": True, "message": message, **get_hardware().status()}
