"""Predictive Maintenance & Verschleißteil-Tracking API für PrintLab.

Verfolgt Betriebsstunden von Düsen, Schläuchen, Spindeln, Stangen und Filtern
und bietet Schnittstellen zum Quittieren und Zurücksetzen nach Wartungsarbeiten.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.wear_tracker import get_wear_overview, reset_wear_component

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maintenance/wear", tags=["maintenance"])


@router.get("/{printer_id}")
async def get_printer_wear_status(
    printer_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liefert den detaillierten Verschleißzustand aller Baugruppen."""
    return get_wear_overview(printer_id)


@router.post("/{printer_id}/reset")
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
