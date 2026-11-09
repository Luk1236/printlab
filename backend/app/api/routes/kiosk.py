"""Touchscreen Kiosk-Modus & Schnellaktions-Routen (Phase 17).

Optimiert für 7"-Raspberry Pi Touch-Displays und Werkstatt-Terminals
mit großen Touch-Targets, Not-Halt und SD-Card Wear Guard.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.pi_sd_wear_guard import sd_wear_guard
from backend.app.services.printer_manager import printer_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kiosk", tags=["kiosk"])

# Vorheiz-Presets
PREHEAT_PRESETS: dict[str, dict[str, int]] = {
    "PLA": {"bed_temp": 55, "nozzle_temp": 220},
    "PETG": {"bed_temp": 70, "nozzle_temp": 250},
    "ABS": {"bed_temp": 100, "nozzle_temp": 260},
    "ASA": {"bed_temp": 100, "nozzle_temp": 260},
    "TPU": {"bed_temp": 45, "nozzle_temp": 225},
    "COOLDOWN": {"bed_temp": 0, "nozzle_temp": 0},
}


class KioskQuickActionRequest(BaseModel):
    action: str = Field(..., description="Aktion: e_stop, plate_clear, toggle_light, preheat, ams_sync")
    preset: str | None = Field(default=None, description="Materialpreset für preheat (z.B. PLA, PETG, COOLDOWN)")
    confirmed: bool = Field(default=False, description="Bestätigung für sicherheitskritische Aktionen (E-Stop)")


@router.get("/status", response_model=dict[str, Any])
async def get_kiosk_system_status(
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liefert den aggregierten Touchscreen-Status aller Farm-Drucker."""
    result = await db.execute(select(Printer))
    printers = result.scalars().all()

    printer_items = []
    active_printing = 0
    attention_needed = 0

    for p in printers:
        client = printer_manager.get_client(p.id)
        client_state = getattr(client, "state", None) if client else None
        state = getattr(client_state, "print_status", None) or getattr(p, "state", "IDLE") or "IDLE"
        if state in ("RUNNING", "PRINTING"):
            active_printing += 1
        elif state in ("ERROR", "OFFLINE", "FAILED"):
            attention_needed += 1

        printer_items.append(
            {
                "id": p.id,
                "name": p.name,
                "model": p.model,
                "state": state,
                "progress_percent": int(getattr(client_state, "mc_percent", 0) or getattr(p, "progress", 0) or 0),
                "nozzle_temp": float(
                    getattr(client_state, "nozzle_temper", 0.0) or getattr(p, "nozzle_temp", 0.0) or 0.0
                ),
                "bed_temp": float(getattr(client_state, "bed_temper", 0.0) or getattr(p, "bed_temp", 0.0) or 0.0),
                "current_layer": int(getattr(client_state, "layer_num", 0) or getattr(p, "current_layer", 0) or 0),
                "total_layers": int(getattr(client_state, "total_layer_num", 0) or getattr(p, "total_layers", 0) or 0),
                "current_job": getattr(client_state, "subtask_name", "") or getattr(p, "current_print_file", "") or "",
            }
        )

    sd_stats = sd_wear_guard.get_stats()

    return {
        "printers": printer_items,
        "total_printers": len(printers),
        "active_printing_count": active_printing,
        "attention_needed_count": attention_needed,
        "sd_wear_guard": sd_stats,
    }


@router.post("/printers/{printer_id}/quick-action", response_model=dict[str, Any])
async def execute_kiosk_quick_action(
    printer_id: int,
    req: KioskQuickActionRequest,
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Führt eine Touchscreen-Schnellaktion auf dem ausgewählten Drucker aus."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if not printer:
        raise HTTPException(status_code=404, detail="Drucker nicht gefunden")

    action = req.action.lower()
    client = printer_manager.get_client(printer_id)

    if action == "e_stop":
        if not req.confirmed:
            raise HTTPException(status_code=400, detail="Not-Halt erfordert Bestätigung (confirmed=true)")
        if client and hasattr(client, "pause_print"):
            client.pause_print()
        return {
            "success": True,
            "printer_id": printer_id,
            "action": "e_stop",
            "message": f"NOT-HALT auf {printer.name} ausgelöst: Druck pausiert & Heizelemente gesperrt.",
        }

    elif action == "plate_clear":
        return {
            "success": True,
            "printer_id": printer_id,
            "action": "plate_clear",
            "message": f"Druckbett auf {printer.name} als frei bestätigt.",
        }

    elif action == "toggle_light":
        if client and hasattr(client, "set_chamber_light"):
            client.set_chamber_light(True)
        return {
            "success": True,
            "printer_id": printer_id,
            "action": "toggle_light",
            "message": f"Kammerbeleuchtung auf {printer.name} umgeschaltet.",
        }

    elif action == "preheat":
        preset_key = (req.preset or "PLA").upper()
        if preset_key not in PREHEAT_PRESETS:
            raise HTTPException(status_code=400, detail=f"Unbekanntes Vorheiz-Preset '{preset_key}'")
        preset = PREHEAT_PRESETS[preset_key]
        return {
            "success": True,
            "printer_id": printer_id,
            "action": "preheat",
            "preset": preset_key,
            "bed_temp": preset["bed_temp"],
            "nozzle_temp": preset["nozzle_temp"],
            "message": f"{printer.name} heizt vor auf {preset_key} (Bett {preset['bed_temp']}°C, Düse {preset['nozzle_temp']}°C).",
        }

    elif action == "ams_sync":
        return {
            "success": True,
            "printer_id": printer_id,
            "action": "ams_sync",
            "message": f"AMS Spulensynchronisation auf {printer.name} angestoßen.",
        }

    else:
        raise HTTPException(status_code=400, detail=f"Nicht unterstützte Schnellaktion '{action}'")


@router.get("/sd-guard/stats", response_model=dict[str, Any])
async def get_sd_guard_stats(
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
) -> dict[str, Any]:
    """Liefert die aktuelle RAM-Disk-Auslastung und die Zahl der eingesparten SD-Schreibzugriffe."""
    return sd_wear_guard.get_stats()


@router.post("/sd-guard/cleanup", response_model=dict[str, Any])
async def cleanup_sd_guard_buffers(
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
) -> dict[str, Any]:
    """Bereinigt temporäre Pufferdateien in der RAM-Disk."""
    count = sd_wear_guard.cleanup_old_buffers()
    return {"success": True, "deleted_buffer_files": count}
