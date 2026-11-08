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
from backend.app.core.websocket import ws_manager
from backend.app.models.printer import Printer
from backend.app.schemas.fleet import (
    AutoNestRequest,
    BatchSplitRequest,
    FleetCommandRequest,
    FleetCommandResponse,
    FleetCommandResultItem,
    FleetJobSummary,
    FleetMetricsResponse,
    FleetOverviewResponse,
    GcodeM486Request,
    OrientationCheckRequest,
)
from backend.app.services.auto_nesting import (
    NestingPart,
    inject_m486_object_markers,
    pack_parts_onto_plates,
    split_batch_across_fleet,
    suggest_optimal_orientation,
)
from backend.app.services.fleet_load_balancer import (
    MIN_DISPATCH_SCORE,
    calculate_printer_fitness,
    dispatch_job_to_fleet,
)
from backend.app.services.printer_manager import printer_manager
from backend.app.services.wear_tracker import get_printer_wear

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fleet", tags=["fleet"])

# Operativer Wartungsstatus fr Flotten-Workflows
_maintenance_printers: set[int] = set()


def _is_printer_in_maintenance(p: Printer) -> bool:
    return p.id in _maintenance_printers or bool(getattr(p, "in_maintenance", False))


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


@router.get("/overview", response_model=FleetOverviewResponse)
async def get_fleet_overview(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
) -> FleetOverviewResponse:
    """Aggregierte Echtzeit-Übersicht aller aktiven Drucker, Jobs und Betriebszustände."""
    result = await db.execute(select(Printer).where(Printer.is_active.is_(True)))
    printers = list(result.scalars().all())

    total = len(printers)
    online = 0
    printing = 0
    paused = 0
    idle = 0
    in_maintenance = 0
    hms_errors = 0
    active_jobs: list[FleetJobSummary] = []
    locations: dict[str, int] = {}

    for p in printers:
        loc = p.location or "Standard"
        locations[loc] = locations.get(loc, 0) + 1

        if _is_printer_in_maintenance(p):
            in_maintenance += 1

        status = printer_manager.get_status(p.id)
        if not status:
            idle += 1
            continue

        if getattr(status, "connected", False):
            online += 1

        state = str(getattr(status, "state", "IDLE") or "IDLE").upper()
        if state in ("PREPARE", "SLICING", "RUNNING"):
            printing += 1
            active_jobs.append(
                FleetJobSummary(
                    printer_id=p.id,
                    printer_name=p.name or f"Drucker {p.id}",
                    model=getattr(p, "model", None),
                    location=p.location,
                    state=state,
                    subtask_name=getattr(status, "subtask_name", None) or getattr(status, "gcode_file", None),
                    gcode_file=getattr(status, "gcode_file", None),
                    progress=int(getattr(status, "progress", 0) or 0),
                    remaining_time_minutes=getattr(status, "remaining_time", None),
                    current_layer=int(getattr(status, "layer_num", 0) or 0),
                    total_layers=int(getattr(status, "total_layers", 0) or 0),
                )
            )
        elif state == "PAUSE":
            paused += 1
        elif state in ("IDLE", "FINISH", "FAILED"):
            idle += 1

        if getattr(status, "hms_errors", None):
            hms_errors += 1

    return FleetOverviewResponse(
        total_printers=total,
        online_printers=online,
        printing_count=printing,
        paused_count=paused,
        idle_count=idle,
        maintenance_count=in_maintenance,
        hms_error_count=hms_errors,
        active_jobs=active_jobs,
        locations=locations,
    )


@router.post("/command", response_model=FleetCommandResponse)
async def execute_fleet_command(
    req: FleetCommandRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
) -> FleetCommandResponse:
    """Führt Batch-Befehle (pause, resume, stop, emergency_stop, lights, maintenance) über die Flotte aus."""
    query = select(Printer).where(Printer.is_active.is_(True))
    if req.printer_ids:
        query = query.where(Printer.id.in_(req.printer_ids))
    if req.location:
        query = query.where(Printer.location == req.location)

    result = await db.execute(query)
    printers = list(result.scalars().all())

    succeeded: list[int] = []
    failed: list[FleetCommandResultItem] = []
    skipped: list[FleetCommandResultItem] = []

    for p in printers:
        client = printer_manager.get_client(p.id)
        status = printer_manager.get_status(p.id)
        state = str(getattr(status, "state", "IDLE") or "IDLE").upper() if status else "OFFLINE"

        try:
            if req.action == "pause":
                if state != "RUNNING":
                    skipped.append(
                        FleetCommandResultItem(
                            printer_id=p.id, name=p.name, reason=f"Drucker nicht im Status RUNNING ({state})"
                        )
                    )
                    continue
                if not client or not getattr(client, "connected", False):
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Nicht mit Drucker verbunden")
                    )
                    continue
                if client.pause_print():
                    succeeded.append(p.id)
                else:
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Pause-Kommando abgelehnt")
                    )

            elif req.action == "resume":
                if state != "PAUSE":
                    skipped.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason=f"Drucker nicht pausiert ({state})")
                    )
                    continue
                if not client or not getattr(client, "connected", False):
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Nicht mit Drucker verbunden")
                    )
                    continue
                if client.resume_print():
                    succeeded.append(p.id)
                else:
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Resume-Kommando abgelehnt")
                    )

            elif req.action in ("stop", "emergency_stop"):
                if state not in ("PREPARE", "SLICING", "RUNNING", "PAUSE"):
                    skipped.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason=f"Kein aktiver Drucklauf ({state})")
                    )
                    continue
                if not client or not getattr(client, "connected", False):
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Nicht mit Drucker verbunden")
                    )
                    continue
                ok = client.stop_print()
                if req.action == "emergency_stop":
                    client.send_gcode("M112\n")
                if ok:
                    succeeded.append(p.id)
                else:
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Stopp-Kommando fehlgeschlagen")
                    )

            elif req.action == "chamber_light_on":
                if not client or not getattr(client, "connected", False):
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Nicht mit Drucker verbunden")
                    )
                    continue
                if client.set_chamber_light(True):
                    succeeded.append(p.id)
                else:
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Lichtsteuerung fehlgeschlagen")
                    )

            elif req.action == "chamber_light_off":
                if not client or not getattr(client, "connected", False):
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Nicht mit Drucker verbunden")
                    )
                    continue
                if client.set_chamber_light(False):
                    succeeded.append(p.id)
                else:
                    failed.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Lichtsteuerung fehlgeschlagen")
                    )

            elif req.action == "maintenance_enter":
                if _is_printer_in_maintenance(p):
                    skipped.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Bereits im Wartungsmodus")
                    )
                    continue
                _maintenance_printers.add(p.id)
                printer_manager.disconnect_printer(p.id)
                succeeded.append(p.id)

            elif req.action == "maintenance_exit":
                if not _is_printer_in_maintenance(p):
                    skipped.append(
                        FleetCommandResultItem(printer_id=p.id, name=p.name, reason="Nicht im Wartungsmodus")
                    )
                    continue
                _maintenance_printers.discard(p.id)
                await printer_manager.connect_printer(p)
                succeeded.append(p.id)

        except Exception as ex:
            logger.exception("Fehler beim Flottenkommando %s fuer Drucker %s: %s", req.action, p.id, ex)
            failed.append(FleetCommandResultItem(printer_id=p.id, name=p.name, reason=str(ex)))

    return FleetCommandResponse(
        action=req.action,
        total_targeted=len(printers),
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
    )


@router.post("/sync", response_model=dict[str, Any])
async def sync_fleet_telemetry(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fragt synchrone Telemetrie-Aktualisierungen für alle aktiven Drucker an."""
    result = await db.execute(select(Printer).where(Printer.is_active.is_(True)))
    printers = list(result.scalars().all())

    requested = 0
    for p in printers:
        if printer_manager.request_status_update(p.id):
            requested += 1

    return {"total_printers": len(printers), "updates_requested": requested}


@router.get("/metrics", response_model=FleetMetricsResponse)
async def get_fleet_metrics(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> FleetMetricsResponse:
    """Liefert Echtzeit-Metriken des WebSocket-Fanouts und der Flotten-Steuerung."""
    ws = ws_manager.get_metrics()
    return FleetMetricsResponse(
        active_ws_connections=ws["active_connections"],
        total_ws_broadcasts=ws["total_broadcasts"],
        total_ws_messages_sent=ws["total_messages_sent"],
        dropped_ws_connections=ws["dropped_connections"],
        last_broadcast_ms=ws["last_broadcast_ms"],
        avg_broadcast_ms=ws["avg_broadcast_ms"],
        max_broadcast_ms=ws["max_broadcast_ms"],
        maintenance_printers_count=len(_maintenance_printers),
    )


@router.post("/auto-nest", response_model=dict[str, Any])
async def auto_nest_parts(
    req: AutoNestRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Berechnet eine kollisionsfreie 2D-Multi-Plate-Plattenbelegung (Guillotine Bin-Packing mit 90°-Drehung)."""
    parts = [
        NestingPart(
            part_id=p.part_id,
            name=p.name,
            width_mm=p.width_mm,
            depth_mm=p.depth_mm,
            height_mm=p.height_mm,
            copies=p.copies,
            allow_rotation=p.allow_rotation,
            filament_grams_per_copy=p.filament_grams_per_copy,
            print_minutes_per_copy=p.print_minutes_per_copy,
        )
        for p in req.parts
    ]
    return pack_parts_onto_plates(
        parts,
        bed_width_mm=req.bed_width_mm,
        bed_depth_mm=req.bed_depth_mm,
        bed_height_mm=req.bed_height_mm,
        margin_mm=req.margin_mm,
        spacing_mm=req.spacing_mm,
    )


@router.post("/batch-split", response_model=dict[str, Any])
async def split_batch_order(
    req: BatchSplitRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Packt eine Großserie auf mehrere Platten und verteilt sie parallel über alle geeigneten Farm-Drucker."""
    parts = [
        NestingPart(
            part_id=p.part_id,
            name=p.name,
            width_mm=p.width_mm,
            depth_mm=p.depth_mm,
            height_mm=p.height_mm,
            copies=p.copies,
            allow_rotation=p.allow_rotation,
            filament_grams_per_copy=p.filament_grams_per_copy,
            print_minutes_per_copy=p.print_minutes_per_copy,
        )
        for p in req.parts
    ]
    nesting = pack_parts_onto_plates(
        parts,
        bed_width_mm=req.bed_width_mm,
        bed_depth_mm=req.bed_depth_mm,
        bed_height_mm=req.bed_height_mm,
        margin_mm=req.margin_mm,
        spacing_mm=req.spacing_mm,
    )
    printers = await _gather_fleet_state(db)
    split = split_batch_across_fleet(
        nesting,
        printers,
        job_requirements={
            "material": req.material,
            "color": req.color,
            "nozzle_diameter": req.nozzle_diameter,
            "requires_hardened_nozzle": req.requires_hardened_nozzle,
        },
    )
    return {"nesting": nesting, "fleet_split": split}


@router.post("/orientation-check", response_model=dict[str, Any])
async def evaluate_part_orientation(
    req: OrientationCheckRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Empfiehlt die optimale 3D-Druckausrichtung anhand von Auflagefläche, Bauhöhe und Überhang."""
    return suggest_optimal_orientation(
        (req.width_mm, req.depth_mm, req.height_mm),
        overhang_ratio_by_axis=req.overhang_ratio_by_axis,
    )


@router.post("/gcode-m486", response_model=dict[str, Any])
async def process_gcode_m486(
    req: GcodeM486Request,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Analysiert G-Code und injiziert fehlende M486-Objektmarker für Einzelobjekt-Ausschluss."""
    return inject_m486_object_markers(req.gcode, req.object_names)

