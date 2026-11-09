"""Predictive Maintenance & Verschleißteil-Tracking API für PrintLab (Phase 18).

Verfolgt Betriebsstunden von Düsen, Schläuchen, Spindeln, Stangen und Filtern,
berechnet Abrasiv-Verschleißprognosen (CF/GF) und überwacht AMS-Taupunkt
und Trocknungszustände hygroskopischer Materialien.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.humidity_guard import evaluate_ams_humidity
from backend.app.services.wear_predictor import predict_job_wear
from backend.app.services.wear_tracker import get_wear_overview, reset_wear_component

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


class WearForecastRequest(BaseModel):
    printer_id: str = Field(..., description="Drucker-ID oder Seriennummer")
    filament_type: str = Field(..., description="Verwendetes Filament (z. B. PA-CF, PETG, PLA)")
    print_time_hours: float = Field(..., gt=0.0, description="Geschätzte Druckzeit in Stunden")
    nozzle_type: str = Field(default="nozzle_hardened_steel", description="nozzle_hardened_steel, nozzle_brass, etc.")


class AmsDryingGuardRequest(BaseModel):
    temp_c: float = Field(22.0, description="Aktuelle AMS-Temperatur in °C")
    humidity_pct: float = Field(..., ge=0.0, le=100.0, description="Relative Luftfeuchtigkeit im AMS in %")
    loaded_filaments: list[str] = Field(default_factory=list, description="Liste der geladenen Filamenttypen")


class PreflightCheckRequest(BaseModel):
    printer_id: str = Field(...)
    filament_type: str = Field(...)
    print_time_hours: float = Field(..., gt=0.0)
    ams_temp_c: float = Field(default=22.0)
    ams_humidity_pct: float = Field(default=25.0)
    nozzle_type: str = Field(default="nozzle_hardened_steel")


# --- Wear Tracking Endpoints ---


@router.get("/wear/{printer_id}")
async def get_printer_wear_status(
    printer_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liefert den detaillierten Verschleißzustand aller Baugruppen."""
    return get_wear_overview(printer_id)


@router.post("/wear/{printer_id}/reset")
async def reset_printer_component(
    printer_id: str,
    component: str = Query(..., description="nozzle, ptfe, z_spindle, steel_rods, oder carbon_filter"),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Setzt den Zähler einer gewarteten oder ersetzten Komponente auf 0 zurück."""
    valid_components = {"nozzle", "ptfe", "z_spindle", "steel_rods", "carbon_filter"}
    clean_comp = component.strip().lower()
    if clean_comp not in valid_components:
        raise HTTPException(
            400,
            f"Ungültige Komponente '{component}'. Gültig sind: {', '.join(sorted(valid_components))}",
        )

    ok = reset_wear_component(printer_id, clean_comp)
    if not ok:
        raise HTTPException(404, f"Drucker '{printer_id}' oder Komponente nicht gefunden.")

    logger.info("[WearTracker] Komponente '%s' für Drucker '%s' zurückgesetzt.", clean_comp, printer_id)
    return {
        "success": True,
        "message": f"Wartungszähler für '{clean_comp}' erfolgreich zurückgesetzt.",
        "wear_status": get_wear_overview(printer_id),
    }


# --- Phase 18: Abrasive Wear Predictor & AMS Humidity Guard ---


@router.post("/wear/forecast", response_model=dict[str, Any])
async def forecast_job_wear(
    req: WearForecastRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Berechnet die voraussichtliche Abnutzung und Verschleißreserven für einen Auftrag."""
    return predict_job_wear(
        printer_id=req.printer_id,
        filament_type=req.filament_type,
        print_time_hours=req.print_time_hours,
        nozzle_type=req.nozzle_type,
    )


@router.post("/ams/drying-guard", response_model=dict[str, Any])
async def check_ams_humidity_and_drying(
    req: AmsDryingGuardRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Berechnet Taupunkt, Kondensationsrisiko und Trocknungsempfehlungen für AMS-Spulen."""
    return evaluate_ams_humidity(
        temp_c=req.temp_c,
        humidity_pct=req.humidity_pct,
        loaded_filaments=req.loaded_filaments,
    )


@router.post("/preflight-check", response_model=dict[str, Any])
async def execute_job_preflight_check(
    req: PreflightCheckRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Umfassender Preflight-Check vor dem Druckstart (Materialfeuchte + Düsenverschleiß)."""
    wear_res = predict_job_wear(
        printer_id=req.printer_id,
        filament_type=req.filament_type,
        print_time_hours=req.print_time_hours,
        nozzle_type=req.nozzle_type,
    )
    humidity_res = evaluate_ams_humidity(
        temp_c=req.ams_temp_c,
        humidity_pct=req.ams_humidity_pct,
        loaded_filaments=[req.filament_type],
    )

    passed = wear_res["can_safely_print"] and not humidity_res["overall_drying_recommended"]
    critical_warnings = []
    if not wear_res["can_safely_print"]:
        critical_warnings.extend(wear_res["recommendations"])
    if humidity_res["overall_drying_recommended"]:
        critical_warnings.append(
            f"Material '{req.filament_type}' ist mit {req.ams_humidity_pct}% zu feucht. Vor Druckstart trocknen!"
        )

    return {
        "preflight_passed": passed,
        "can_start_immediately": passed,
        "critical_warnings": critical_warnings,
        "wear_prediction": wear_res,
        "humidity_analysis": humidity_res,
    }
