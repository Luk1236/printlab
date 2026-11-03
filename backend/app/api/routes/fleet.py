"""Enterprise Fleet Management & Dispatch API für PrintLab 2.0.

Ermöglicht intelligentes Load Balancing von 3D-Druckaufträgen über die gesamte
Druckerflotte basierend auf Verfügbarkeit, Düsenart, AMS-Filament und Auslastung.

Datenquellen (bewusst echt statt hartkodiert):
- Live-Telemetrie: ``printer_manager.get_status`` (``PrinterState``) —
  Betttemperatur steckt in ``state.temperatures["bed"]``, die AMS-Trays in
  ``state.raw_data["ams"]`` (dict oder list, wie überall im Code gelesen).
- Düsentyp und Betriebsstunden: ``wear_tracker`` (Düsentyp, akkumulierte Stunden).
- ``remain`` im AMS-Tray ist ein Prozentsatz (0–100, siehe AMS-Gewichtssync in
  ``inventory.py``): er wird gegen die angenommene Spulenkapazität in Gramm
  übersetzt, damit der Load Balancer mit realen Bedarfen vergleichen kann.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.fleet_load_balancer import (
    MIN_DISPATCH_SCORE,
    calculate_printer_fitness,
    dispatch_job_to_fleet,
)
from backend.app.services.printer_manager import printer_manager
from backend.app.services.wear_tracker import get_printer_wear

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fleet", tags=["fleet"])


class DispatchJobRequest(BaseModel):
    """Auftragsdaten für Fitness-/Dispatch-Berechnungen.

    Ein Pydantic-Modell statt eines rohen dicts: Die Endpunkte sind für echte
    Steuerungsentscheidungen gedacht, und ein manipulierter Payload ("abc" in
    filament_grams) soll nicht erst im Balancer als Fallback landen dürfen.
    """

    name: str = Field("", max_length=200, description="Angezeigter Auftragsname")
    material: str = Field("PLA", max_length=32, description="Gewünschtes Filament (AMS-Kürzel)")
    color: str = Field("", max_length=32, description="Gewünschte Farbe als Hex-Wert")
    filament_grams: float = Field(30.0, ge=0.0, le=20_000.0, description="Bedarf in Gramm")
    nozzle_diameter: float = Field(0.4, ge=0.15, le=1.2, description="Benötigte Düse in mm")
    requires_hardened_nozzle: bool = Field(False, description="Abrasives Filament (gehärtete Düse nötig)")

    def to_fitness_payload(self) -> dict[str, Any]:
        return self.model_dump()


# Standard-Bambu-Spule: 1 kg. Das AMS meldet keinen absoluten Spulenbestand,
# nur einen Prozentsatz — die Umrechnung braucht eine dokumentierte Annahme.
ASSUMED_SPOOL_CAPACITY_G = 1000.0

# Statusarten (PrinterState.state): IDLE/STANDBY/READY → Bett frei; FINISH →
# Bauteil liegt auf; RUNNING/PAUSE → Druck aktiv. Alles andere (Fehlerzustände,
# Kalibrierung) wird als belegt behandelt — lieber nicht auswählen als falsch
# auswählen.
_READY_STATES = frozenset({"IDLE", "READY", "STANDBY"})
_OCCUPIED_STATES = frozenset({"FINISH", "RUNNING", "PAUSE", "SLICE", "HAZARD"})


def _first_nozzle_diameter(state: Any) -> float:
    """Erste gültige Düsengröße als float; ``PrinterState.nozzles`` ist str-basiert."""
    nozzles = getattr(state, "nozzles", None)
    if nozzles:
        for nozzle in nozzles:
            raw = str(getattr(nozzle, "nozzle_diameter", "") or "")
            try:
                diameter = float(raw)
            except ValueError:
                continue
            if diameter > 0.0:
                return diameter
    return 0.4


def _trays_from_raw_data(state: Any) -> list[dict[str, Any]]:
    """Liest die AMS-Trays aus ``state.raw_data['ams']`` (dict- oder list-Form)."""
    raw_data = getattr(state, "raw_data", None)
    if not isinstance(raw_data, dict):
        return []

    ams_raw = raw_data.get("ams") or []
    # Beide Speicherformen im Code: {"ams": [...]} (deep-merged Status) oder [...]
    if isinstance(ams_raw, dict):
        ams_raw = ams_raw.get("ams") or []
    if not isinstance(ams_raw, list):
        return []

    trays: list[dict[str, Any]] = []
    for unit in ams_raw:
        if not isinstance(unit, dict):
            continue
        unit_id = unit.get("id")
        tray_list = unit.get("tray") or []
        if isinstance(tray_list, dict):
            tray_list = [tray_list]
        for tray in tray_list:
            if not isinstance(tray, dict):
                continue
            material = str(tray.get("tray_type") or "").strip().upper()
            if not material:
                # Leerer Slot (Firmware meldet tray_type "") — kein Match-Kandidat.
                continue
            try:
                remaining_percent = float(tray.get("remain"))
            except (TypeError, ValueError):
                remaining_percent = None
            if remaining_percent is None or not (0.0 <= remaining_percent <= 100.0):
                remaining_percent = 0.0
            trays.append(
                {
                    "slot_id": f"{unit_id}-{tray.get('id')}",
                    "material": material,
                    "color": str(tray.get("tray_color") or "").lstrip("#").upper()[:6],
                    "remaining_percent": round(remaining_percent, 1),
                    "remaining_grams": round(ASSUMED_SPOOL_CAPACITY_G * remaining_percent / 100.0, 1),
                }
            )
    return trays


async def _gather_fleet_state(db: AsyncSession) -> list[dict[str, Any]]:
    """Sammelt Live-Telemetrie und Konfiguration aller registrierten Drucker."""
    result = await db.execute(select(Printer))
    db_printers = result.scalars().all()

    fleet: list[dict[str, Any]] = []
    for p in db_printers:
        state = printer_manager.get_status(p.id)
        connected = bool(state and state.connected)
        state_name = str(state.state).upper() if state else "OFFLINE"

        temperatures = getattr(state, "temperatures", None)
        raw_bed_temp = temperatures.get("bed") if isinstance(temperatures, dict) else None
        try:
            bed_temp = float(raw_bed_temp)
        except (TypeError, ValueError):
            bed_temp = 25.0

        wear = get_printer_wear(str(p.id))
        is_hardened = wear.get("nozzle_type", "hardened_steel") == "hardened_steel"
        tracked_hours = round(
            wear.get("nozzle_hours", 0.0)
            + wear.get("ptfe_hours", 0.0)
            + wear.get("z_spindle_hours", 0.0)
            + wear.get("steel_rods_hours", 0.0),
            1,
        )

        if state_name in _READY_STATES:
            plate_clear = True
        elif state_name in _OCCUPIED_STATES:
            plate_clear = False
        else:
            # Unbekannt/Fehlerzustand: als belegt behandeln (kein Autodispatch).
            plate_clear = False

        fleet.append(
            {
                "id": p.id,
                "name": p.name or f"Drucker {p.id}",
                "model": getattr(p, "model", "Bambu Lab P2S"),
                "connected": connected,
                "state": state_name,
                "plate_clear": plate_clear,
                "bed_temp": bed_temp,
                "nozzle_diameter": _first_nozzle_diameter(state),
                "is_hardened_nozzle": is_hardened,
                "ams_slots": _trays_from_raw_data(state),
                "total_operating_hours": tracked_hours,
            }
        )

    return fleet


@router.get("/status")
async def get_fleet_status(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Liefert die Flottenübersicht mit Bereitschaft und Attributen."""
    printers = await _gather_fleet_state(db)
    return {"count": len(printers), "printers": printers}


@router.post("/dispatch")
async def dispatch_job(
    job: DispatchJobRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Ermittelt den am besten geeigneten Drucker für einen Druckauftrag."""
    printers = await _gather_fleet_state(db)
    dispatch_result = dispatch_job_to_fleet(job.to_fitness_payload(), printers)
    return dispatch_result


@router.post("/fitness/{printer_id}")
async def evaluate_printer_fitness(
    printer_id: int,
    job: DispatchJobRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Berechnet den Eignungs-Score eines spezifischen Druckers für einen Auftrag."""
    printers = await _gather_fleet_state(db)
    target = next((p for p in printers if p["id"] == printer_id), None)
    if not target:
        return {"printer_id": printer_id, "score": 0.0, "reasons": ["Drucker nicht gefunden"]}

    score, reasons = calculate_printer_fitness(target, job.to_fitness_payload())
    return {
        "printer_id": printer_id,
        "name": target["name"],
        "fitness_score": score,
        "can_start_immediately": score >= MIN_DISPATCH_SCORE,
        "reasons": reasons,
    }
