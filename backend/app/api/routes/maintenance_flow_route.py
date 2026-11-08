"""API-Router für Drucker-Reinigung, Düsenwechsel & Service-Positionen."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.maintenance_service_flow import (
    cleaning_motion_routine,
    cold_pull_routine,
    complete_maintenance_task,
    exit_service_position,
    move_to_service_position,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maintenance/printers", tags=["maintenance-flow"])


class ServicePositionRequest(BaseModel):
    preheat_nozzle_c: int = Field(0, ge=0, le=300, description="Optionale Vorheiztemperatur (z.B. 130°C für Hot-Swap)")
    lower_bed_mm: float = Field(180.0, ge=20.0, le=245.0, description="Z-Höhe für das Absenken des Betts")


class ExitServicePositionRequest(BaseModel):
    perform_home: bool = Field(True, description="Nach Wartung G28 Homing durchführen")


class ColdPullRequest(BaseModel):
    step: str = Field("heat", description="Schritt: heat, cooldown, pull, inspect")
    filament_type: str = Field("PLA", max_length=32, description="Material: PLA, PETG, ABS, PA-CF, CLEANING")


class CleaningMotionRequest(BaseModel):
    routine: str = Field("carbon_rods", description="Routine: carbon_rods, z_lead_screws, nozzle_wipe")
    cycles: int = Field(3, ge=1, le=10, description="Anzahl der Verfahrzyklen")


class CompleteTaskRequest(BaseModel):
    component: str = Field(..., description="nozzle, ptfe, z_spindle, steel_rods, carbon_filter")
    notes: str = Field("", max_length=500, description="Optionale Notizen zur durchgeführten Wartung")


@router.post("/{printer_id}/service-position", response_model=dict[str, Any])
async def enter_printer_service_position(
    printer_id: str,
    req: ServicePositionRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Verfährt Druckkopf und Bett in die ergonomische Wartungsposition für Düsenwechsel."""
    return move_to_service_position(
        printer_id=printer_id,
        preheat_nozzle_c=req.preheat_nozzle_c,
        lower_bed_mm=req.lower_bed_mm,
    )


@router.post("/{printer_id}/exit-service-position", response_model=dict[str, Any])
async def leave_printer_service_position(
    printer_id: str,
    req: ExitServicePositionRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Beendet die Wartungsposition und referenziert die Achsen."""
    return exit_service_position(
        printer_id=printer_id,
        perform_home=req.perform_home,
    )


@router.post("/{printer_id}/cold-pull", response_model=dict[str, Any])
async def execute_cold_pull_step(
    printer_id: str,
    req: ColdPullRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Führt einen Schritt der interaktiven Cold-Pull-Düsenreinigung aus."""
    try:
        return cold_pull_routine(
            printer_id=printer_id,
            step=req.step,
            filament_type=req.filament_type,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/{printer_id}/cleaning-motion", response_model=dict[str, Any])
async def execute_cleaning_motion(
    printer_id: str,
    req: CleaningMotionRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Startet automatisierte Verfahrbewegungen zur Reinigung (Carbon-Stangen, Spindeln)."""
    try:
        return cleaning_motion_routine(
            printer_id=printer_id,
            routine=req.routine,
            cycles=req.cycles,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/{printer_id}/complete-task", response_model=dict[str, Any])
async def finish_maintenance_task(
    printer_id: str,
    req: CompleteTaskRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Quittiert eine abgeschlossene Reinigung/Wartung und setzt den Verschleißzähler zurück."""
    return complete_maintenance_task(
        printer_id=printer_id,
        component=req.component,
        notes=req.notes,
    )
