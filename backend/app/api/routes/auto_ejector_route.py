"""API-Router für automatischen Druckbett-Auswurf & Ejektor-Steuerung (Phase 22)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.auto_ejector import (
    can_safely_eject,
    execute_part_ejection,
    get_ejector_config,
    get_material_eject_temp,
    update_ejector_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automation/ejector", tags=["auto-ejector"])


class EjectorConfigRequest(BaseModel):
    enabled: bool | None = None
    mode: str | None = Field(None, description="toolhead_sweep, gpio_servo, gpio_pneumatic")
    gpio_pin: int | None = Field(None, ge=1, le=40)
    gpio_pulse_seconds: float | None = Field(None, ge=0.1, le=10.0)
    max_bed_temp_c: float | None = Field(None, ge=15.0, le=80.0)
    auto_advance_queue: bool | None = None
    cooldown_check_enabled: bool | None = None


class TriggerEjectionRequest(BaseModel):
    printer_id: str = Field(..., description="ID oder Seriennummer des Ziel-Druckers")
    current_bed_temp_c: float = Field(25.0, description="Aktuell gemessene Druckbett-Temperatur")
    filament_type: str = Field("PLA", description="Gedrucktes Material (PLA, PETG, ABS...)")
    force: bool = Field(False, description="Erzwingt Auswurf ohne Temperaturabkühlung")


@router.get("/config", response_model=dict[str, Any])
async def get_config(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liefert die Ejektor-Einstellungen und Hardware-Betriebsmodi."""
    return get_ejector_config()


@router.put("/config", response_model=dict[str, Any])
async def set_config(
    req: EjectorConfigRequest,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
) -> dict[str, Any]:
    """Aktualisiert die Ejektor-Einstellungen (Schwellwert, Modus, GPIO)."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    return update_ejector_config(updates)


@router.post("/trigger", response_model=dict[str, Any])
async def trigger_ejection(
    req: TriggerEjectionRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Führt den Auswerfvorgang aus, wenn das Bett ausreichend abgekühlt ist."""
    return execute_part_ejection(
        printer_id=req.printer_id,
        current_bed_temp=req.current_bed_temp_c,
        filament_type=req.filament_type,
        force=req.force,
    )


@router.get("/status/{printer_id}", response_model=dict[str, Any])
async def check_ejection_readiness(
    printer_id: str,
    current_bed_temp_c: float = 25.0,
    filament_type: str = "PLA",
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Prüft die Auswurfbereitschaft und Rest-Abkühlzeit für das Bett."""
    safe, reason = can_safely_eject(current_bed_temp=current_bed_temp_c, filament_type=filament_type)
    target = get_material_eject_temp(filament_type)
    return {
        "printer_id": printer_id,
        "can_eject": safe,
        "current_bed_temp_c": current_bed_temp_c,
        "target_bed_temp_c": target,
        "temp_delta_c": max(0.0, round(current_bed_temp_c - target, 1)),
        "reason": reason,
    }
