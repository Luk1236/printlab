"""FastAPI-Routen für das automatisierte PrintLab Platten-, Tür- und Waschstationssystem.

Stellt Endpunkte bereit für:
- Statusabfrage (Tür, Magazin-Slots, Wechsler, Waschstation)
- Servogesteuertes Türöffnen & Türschließen
- Autonomen Plattenwechsel
- Autonomen Plattenwaschgang mit IPA
- Slot-Konfiguration & Barcode-Zuweisung
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.services.plate_station_service import (
    PlateSlotStatus,
    PlateType,
    plate_station_service,
)

router = APIRouter(prefix="/fleet/plate-station", tags=["Plate Station & Hardware"])


class SwapRequest(BaseModel):
    desired_plate_type: PlateType | None = Field(default=None, description="Optionaler Ziel-Plattentyp (z.B. textured_pei, smooth_pei)")


class WashRequest(BaseModel):
    slot_id: int | None = Field(default=None, description="Optionaler Slot, der gewaschen werden soll (Standard: erste DIRTY Platte)")


class SlotUpdateRequest(BaseModel):
    status: PlateSlotStatus = Field(..., description="Neuer Status: ready, dirty, empty, printing, washing")
    plate_type: PlateType | None = Field(default=None, description="Plattentyp")
    label: str | None = Field(default=None, description="Anzeigename")


@router.get("/status")
def get_station_status() -> dict[str, Any]:
    """Liefert den Live-Status von Tür, Magazin, Wechsler und Waschstation."""
    return plate_station_service.get_status()


@router.post("/door/open")
async def open_door() -> dict[str, Any]:
    """Öffnet die Kammertür mit Sanftanlauf."""
    res = await plate_station_service.open_door()
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/door/close")
async def close_door() -> dict[str, Any]:
    """Schließt die Kammertür und verifiziert den Endschalter."""
    res = await plate_station_service.close_door()
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/swap")
async def execute_plate_swap(req: SwapRequest | None = None) -> dict[str, Any]:
    """Führt den autonomen Plattenwechsel durch (Tür auf -> Alte Platte ablegen -> Frische Platte einlegen -> Tür zu)."""
    p_type = req.desired_plate_type if req else None
    res = await plate_station_service.swap_plate(target_plate_type=p_type)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/wash")
async def execute_plate_wash(req: WashRequest | None = None) -> dict[str, Any]:
    """Startet den automatisierten Reinigungszyklus (IPA-Auftrag + Bürstenwalzen + Trocknungsgebläse)."""
    s_id = req.slot_id if req else None
    res = await plate_station_service.wash_plate(slot_id=s_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/slots/{slot_id}")
def update_magazine_slot(slot_id: int, req: SlotUpdateRequest) -> dict[str, Any]:
    """Aktualisiert Status und Parameter eines Magazinfachs manuell oder per Sensor."""
    res = plate_station_service.update_slot(slot_id=slot_id, status=req.status, plate_type=req.plate_type, label=req.label)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message"))
    return res
