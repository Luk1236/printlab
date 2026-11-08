"""API-Router für HX711-Wägezelle und Handscanner 'Scan-to-Action' (Phase 21)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.handheld_scanner import (
    assign_spool_to_printer_slot,
    process_barcode_input,
)
from backend.app.services.spool_scale_hx711 import (
    calibrate_scale,
    get_scale_status,
    read_spool_net_weight,
    tare_scale,
    verify_job_filament_preflight,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hardware", tags=["hardware-scale-scanner"])


class CalibrateScaleRequest(BaseModel):
    known_weight_grams: float = Field(..., gt=0.0, description="Referenzgewicht auf der Waage in Gramm")


class ReadSpoolRequest(BaseModel):
    spool_type: str = Field("bambu_reusable", description="Spulentyp (bambu_reusable, polymaker, prusament, cardboard...)")
    custom_tare_grams: float | None = Field(None, ge=0.0, description="Individuelles Leergewicht des Spulenkörpers")


class VerifyScalePreflightRequest(BaseModel):
    required_grams: float = Field(..., gt=0.0, description="Für den Druckauftrag benötigtes Filament in Gramm")
    spool_type: str = Field("bambu_reusable")
    safety_margin_grams: float = Field(10.0, ge=0.0)


class ScannerInputRequest(BaseModel):
    raw_barcode: str = Field(..., min_length=1, max_length=256, description="Gescannter Barcode, QR-Code oder RFID-Text")


class AssignSpoolRequest(BaseModel):
    spool_id: str = Field(..., min_length=1)
    printer_id: str = Field(..., min_length=1)
    tray_slot: int = Field(0, ge=0, le=15, description="AMS Slot 0..15 oder 254 für extern")


# --- HX711 Spool Scale Endpoints ---

@router.get("/scale/status", response_model=dict[str, Any])
async def get_hx711_scale_status(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liefert Status, GPIO-Pins und Kalibrierung der HX711 Spulen-Wägezelle."""
    return get_scale_status()


@router.post("/scale/tare", response_model=dict[str, Any])
async def tare_hx711_scale(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Nullt die Wägezelle mit aufgelegtem Wiegeteller."""
    return tare_scale()


@router.post("/scale/calibrate", response_model=dict[str, Any])
async def calibrate_hx711_scale(
    req: CalibrateScaleRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Kalibriert den Messfaktor anhand eines bekannten Gewichts (z.B. 500g Eichgewicht)."""
    try:
        return calibrate_scale(known_weight_grams=req.known_weight_grams)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/scale/read-spool", response_model=dict[str, Any])
async def read_spool_weight_measurement(
    req: ReadSpoolRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liest das Bruttogewicht und berechnet das Netto-Filamentgewicht nach Abzug der Spulentara."""
    return read_spool_net_weight(
        spool_type=req.spool_type,
        custom_tare_grams=req.custom_tare_grams,
    )


@router.post("/scale/verify-preflight", response_model=dict[str, Any])
async def verify_scale_filament_preflight(
    req: VerifyScalePreflightRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Prüft vor dem Druckstart, ob die gewogene Spule genügend Material für den Auftrag hat."""
    return verify_job_filament_preflight(
        required_grams=req.required_grams,
        spool_type=req.spool_type,
        safety_margin_grams=req.safety_margin_grams,
    )


# --- Handheld Scanner Endpoints ---

@router.post("/scanner/scan", response_model=dict[str, Any])
async def receive_scanner_input(
    req: ScannerInputRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Verarbeitet Scans von Barcode-/QR-Handscannern ('Scan-to-Action')."""
    try:
        return process_barcode_input(req.raw_barcode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/scanner/assign-spool-to-slot", response_model=dict[str, Any])
async def assign_scanned_spool(
    req: AssignSpoolRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Verknüpft eine gescannte Spule direkt mit dem Ziel-Drucker und AMS-Slot."""
    return assign_spool_to_printer_slot(
        spool_id=req.spool_id,
        printer_id=req.printer_id,
        tray_slot=req.tray_slot,
    )
