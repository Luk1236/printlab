"""FastAPI-Routen für das automatisierte PrintLab Platten-, Tür- und Waschstationssystem.

Stellt Endpunkte bereit für:
- Statusabfrage (Tür, Magazin-Slots, Wechsler, Waschstation)
- Servogesteuertes Türöffnen & Türschließen
- Autonomen Plattenwechsel
- Autonomen Plattenwaschgang mit IPA
- Slot-Konfiguration & Barcode-Zuweisung

Bewegungen verlangen ``printers:control`` und sind gesperrt, solange der Not-Halt aktiv ist. Tür öffnen und Plattenwechsel
sind zusätzlich während eines Drucks und bei heißem Bett gesperrt (``plate_changer.interlock_problems``). Alle Antworten
sagen ehrlich, ob nur simuliert wurde (``driver.simulated``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled, get_current_user_optional
from backend.app.core.permissions import Permission
from backend.app.services import audit_log, plate_changer
from backend.app.services.gpio_hardware import gpio_service
from backend.app.services.plate_station_service import (
    PlateSlotStatus,
    PlateType,
    plate_station_service,
)
from backend.app.services.printer_manager import printer_manager

router = APIRouter(prefix="/fleet/plate-station", tags=["Plate Station & Hardware"])


class SwapRequest(BaseModel):
    desired_plate_type: PlateType | None = Field(
        default=None, description="Optionaler Ziel-Plattentyp (z.B. textured_pei, smooth_pei)"
    )
    with_parts: bool = Field(
        default=True,
        description="Liegen fertige Teile auf der Platte? Sie wandern mit der Platte ins Regal (Status full).",
    )
    part_height_mm: float | None = Field(
        default=None,
        ge=0,
        le=500,
        description="Höhe der Teile auf der Platte; sie müssen unter die nächste Platte im Regal passen.",
    )


class WashRequest(BaseModel):
    slot_id: int | None = Field(
        default=None, description="Optionaler Slot, der gewaschen werden soll (Standard: erste DIRTY Platte)"
    )


class SlotUpdateRequest(BaseModel):
    status: PlateSlotStatus = Field(..., description="Neuer Status: ready, dirty, empty, printing, washing")
    plate_type: PlateType | None = Field(default=None, description="Plattentyp")
    label: str | None = Field(default=None, description="Anzeigename")


def _bed_temp(state: Any) -> float | None:
    temperatures = getattr(state, "temperatures", None)
    raw = temperatures.get("bed") if isinstance(temperatures, dict) else None
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_printer(printer_id: int | None) -> tuple[int | None, str | None]:
    """Welcher Drucker gehört zur Station? Ohne Angabe der einzige bekannte; mehrere sind uneindeutig."""
    if printer_id is not None:
        return printer_id, None
    known = list(printer_manager.get_all_statuses())
    if len(known) == 1:
        return known[0], None
    if len(known) > 1:
        return None, "Mehrere Drucker bekannt: printer_id angeben."
    return None, None


def blockers(printer_id: int | None, *, check_printer: bool) -> tuple[int | None, list[str]]:
    """Gründe, die eine Bewegung jetzt verbieten. Ohne bekannten Drucker gilt nur der Not-Halt."""
    estop = gpio_service.is_estop_active()
    if not check_printer:
        return printer_id, plate_changer.interlock_problems(
            printer_state=None, bed_temp=None, estop_active=estop, check_printer=False
        )
    resolved, ambiguous = _resolve_printer(printer_id)
    if ambiguous:
        return None, [
            *plate_changer.interlock_problems(
                printer_state=None, bed_temp=None, estop_active=estop, check_printer=False
            ),
            ambiguous,
        ]
    if resolved is None:  # kein Drucker bekannt (z. B. Testbetrieb ohne Drucker)
        return None, plate_changer.interlock_problems(
            printer_state=None, bed_temp=None, estop_active=estop, check_printer=False
        )
    state = printer_manager.get_status(resolved)
    return resolved, plate_changer.interlock_problems(
        printer_state=getattr(state, "state", None),
        bed_temp=_bed_temp(state),
        estop_active=estop,
    )


def _finish(action: str, res: dict[str, Any], printer_id: int | None, user: Any) -> dict[str, Any]:
    ok = res.get("status") != "error"
    audit_log.record(
        action,
        ok,
        str(res.get("message", "")),
        printer_id,
        getattr(user, "username", None),
        {"simulated": plate_station_service.driver.simulated},
    )
    if not ok:
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.get("/status")
def get_station_status(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liefert den Live-Status von Tür, Magazin, Wechsler und Waschstation."""
    return plate_station_service.get_status()


@router.post("/door/open")
async def open_door(
    printer_id: int | None = Query(None, description="Drucker der Station (Standard: der einzige bekannte)"),
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Öffnet die Kammertür mit Sanftanlauf (nicht während eines Drucks)."""
    resolved, problems = blockers(printer_id, check_printer=True)
    return _finish(
        "plate_station_door_open", await plate_station_service.open_door(blocked_by=problems), resolved, user
    )


@router.post("/door/close")
async def close_door(
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Schließt die Kammertür und verifiziert den Endschalter (nur der Not-Halt sperrt)."""
    _resolved, problems = blockers(None, check_printer=False)
    return _finish("plate_station_door_close", await plate_station_service.close_door(blocked_by=problems), None, user)


@router.post("/swap")
async def execute_plate_swap(
    req: SwapRequest | None = None,
    printer_id: int | None = Query(None, description="Drucker der Station (Standard: der einzige bekannte)"),
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Führt den autonomen Plattenwechsel durch (Tür auf -> Alte Platte ablegen -> Frische Platte einlegen -> Tür zu)."""
    p_type = req.desired_plate_type if req else None
    with_parts = req.with_parts if req else True
    part_height = req.part_height_mm if req else None
    resolved, problems = blockers(printer_id, check_printer=True)
    res = await plate_station_service.swap_plate(
        target_plate_type=p_type, blocked_by=problems, with_parts=with_parts, part_height_mm=part_height
    )
    return _finish("plate_station_swap", res, resolved, user)


@router.post("/wash")
async def execute_plate_wash(
    req: WashRequest | None = None,
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Startet den automatisierten Reinigungszyklus (IPA-Auftrag + Bürstenwalzen + Trocknungsgebläse)."""
    s_id = req.slot_id if req else None
    _resolved, problems = blockers(None, check_printer=False)
    return _finish(
        "plate_station_wash", await plate_station_service.wash_plate(slot_id=s_id, blocked_by=problems), None, user
    )


@router.post("/slots/{slot_id}/unload-parts")
def unload_parts(
    slot_id: int,
    user=Depends(get_current_user_optional),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Meldet, dass die fertigen Teile von der Platte in diesem Fach entnommen wurden (full -> dirty)."""
    res = plate_station_service.unload_parts(slot_id)
    ok = res.get("status") != "error"
    audit_log.record(
        "plate_station_unload_parts",
        ok,
        str(res.get("message", "")),
        None,
        getattr(user, "username", None),
        {"slot": slot_id},
    )
    if not ok:
        raise HTTPException(status_code=404 if "nicht gefunden" in res["message"] else 400, detail=res["message"])
    return res


@router.post("/slots/{slot_id}")
def update_magazine_slot(
    slot_id: int,
    req: SlotUpdateRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Aktualisiert Status und Parameter eines Magazinfachs manuell oder per Sensor."""
    res = plate_station_service.update_slot(
        slot_id=slot_id, status=req.status, plate_type=req.plate_type, label=req.label
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res
