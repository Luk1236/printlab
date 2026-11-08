"""API-Router für KI-Druckbett-Räumungsprüfung (Phase 23)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.plate_clearance_detector import (
    acknowledge_bed_clear,
    get_bed_baseline,
    inspect_bed_clearance,
    set_bed_baseline,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plate-clearance", tags=["plate-clearance"])


class InspectPlateRequest(BaseModel):
    threshold: float = Field(0.85, ge=0.5, le=1.0, description="Mindest-Clearance-Score für Freigabe")
    mock_has_obstacle: bool = Field(False, description="Simuliert Hindernis auf der Platte für Tests")
    mock_obstacle_type: str = Field("finished_part", description="finished_part, tool, filament_blob")


class SetBaselineRequest(BaseModel):
    resolution: str = Field("1920x1080")
    mean_brightness: float = Field(128.5, ge=0.0, le=255.0)
    edge_density: float = Field(0.04, ge=0.0, le=1.0)


class OverridePlateRequest(BaseModel):
    operator_name: str = Field("Operator", min_length=1, max_length=64)
    notes: str = Field("", max_length=256)


@router.post("/inspect/{printer_id}", response_model=dict[str, Any])
async def inspect_plate(
    printer_id: str,
    req: InspectPlateRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Prüft das Druckbett per Kamera auf Fremdkörper und liefert Freigabestatus."""
    return inspect_bed_clearance(
        printer_id=printer_id,
        threshold=req.threshold,
        mock_has_obstacle=req.mock_has_obstacle,
        mock_obstacle_type=req.mock_obstacle_type,
    )


@router.post("/set-baseline/{printer_id}", response_model=dict[str, Any])
async def register_empty_baseline(
    printer_id: str,
    req: SetBaselineRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Registriert das aktuelle Bild als Referenz für eine saubere, leere Bauplatte."""
    return set_bed_baseline(printer_id=printer_id, baseline_info=req.model_dump())


@router.post("/override/{printer_id}", response_model=dict[str, Any])
async def override_plate(
    printer_id: str,
    req: OverridePlateRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Bediener-Quittierung zur manuellen Freigabe des Betts bei Fehlalarmen."""
    return acknowledge_bed_clear(
        printer_id=printer_id,
        operator_name=req.operator_name,
        notes=req.notes,
    )


@router.get("/status/{printer_id}", response_model=dict[str, Any])
async def get_clearance_status(
    printer_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liefert den Inspektions- und Referenzstatus für einen Drucker."""
    baseline = get_bed_baseline(printer_id)
    inspection = inspect_bed_clearance(printer_id=printer_id)
    return {
        "printer_id": printer_id,
        "has_baseline": baseline is not None,
        "baseline_info": baseline,
        "latest_inspection": inspection,
    }
