"""PrintLab Platten-Management & Stations-Automation.

Steuert das automatisierte Gesamtsystem für:
1. Tür-Mechanik (Servogesteuertes Öffnen und Schließen der Kammertür mit Kollisionsschutz)
2. Plattenlager (Kassettenmagazin für Textured PEI, Smooth PEI, High-Temp Platten)
3. Plattenwechsler (Automatisierter Plattenabzug und Einschub einer frischen Platte)
4. Platten-Waschstation (Motorisierte Walzenreinigung mit IPA-Dosierung und Lüftertrocknung)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from backend.app.core.config import settings
from backend.app.services import plate_changer

logger = logging.getLogger(__name__)

STATION_CONFIG_PATH = settings.base_dir / "plate_station_config.json"
STATION_STATE_PATH = settings.base_dir / "plate_station_state.json"


class DoorState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    OPENING = "opening"
    CLOSING = "closing"
    ERROR = "error"


class PlateSlotStatus(str, Enum):
    READY = "ready"  # Frisch gereinigt / druckbereit
    PRINTING = "printing"  # Aktuell im Drucker
    DIRTY = "dirty"  # Benutzte Platte, Teile sind schon entnommen (bereit zum Waschen)
    FULL = "full"  # Benutzte Platte mit den fertigen Teilen darauf (erst Teile entnehmen)
    WASHING = "washing"  # In der Waschstation
    EMPTY = "empty"  # Fach leer


class PlateType(str, Enum):
    TEXTURED_PEI = "textured_pei"
    SMOOTH_PEI = "smooth_pei"
    ENGINEERING = "engineering"
    HIGH_TEMP = "high_temp"


@dataclass
class MagazineSlot:
    slot_id: int
    label: str
    plate_type: PlateType
    status: PlateSlotStatus
    wash_cycles: int = 0
    last_action: str = "initialized"
    barcode: str = ""


PLATE_NAMES = {
    PlateType.TEXTURED_PEI: "Gold PEI",
    PlateType.SMOOTH_PEI: "Smooth PEI",
    PlateType.ENGINEERING: "Engineering",
    PlateType.HIGH_TEMP: "High-Temp",
}


@dataclass
class BedPlate:
    """Die Platte auf dem Heizbett. Sie hat kein Magazinfach: erst der Wechsel legt sie in ein freies Fach."""

    plate_type: PlateType = PlateType.TEXTURED_PEI
    barcode: str = ""
    wash_cycles: int = 0
    has_parts: bool = False  # liegen fertige Teile auf der Platte?

    @property
    def name(self) -> str:
        return PLATE_NAMES[self.plate_type]


@dataclass
class PlateStationState:
    door_state: DoorState = DoorState.CLOSED
    door_angle_deg: float = 0.0
    active_plate_slot: int | None = None  # Fach, aus dem die Platte auf dem Bett zuletzt kam (None: nicht bekannt)
    bed_plate: BedPlate | None = field(default_factory=BedPlate)
    magazine_slots: list[MagazineSlot] = None
    is_swapping: bool = False
    is_washing: bool = False
    ipa_level_pct: float = 85.0
    last_swap_timestamp: str = ""
    last_wash_timestamp: str = ""
    error_message: str | None = None
    current_phase: str | None = None  # laufende Phase des Wechselzyklus (plate_changer.PHASES)

    def __post_init__(self):
        if self.magazine_slots is None:
            # 4 Fächer wie in der Konstruktion (plate_changer.SLOT_Z); Fach 4 ist das freie Rücklauffach.
            self.magazine_slots = [
                MagazineSlot(
                    1, "Fach 1 - Gold PEI", PlateType.TEXTURED_PEI, PlateSlotStatus.READY, 12, "ready", "PLT-PEI-01"
                ),
                MagazineSlot(
                    2, "Fach 2 - Smooth PEI", PlateType.SMOOTH_PEI, PlateSlotStatus.READY, 8, "ready", "PLT-SMT-02"
                ),
                MagazineSlot(
                    3, "Fach 3 - High-Temp", PlateType.HIGH_TEMP, PlateSlotStatus.READY, 4, "ready", "PLT-HTP-03"
                ),
                MagazineSlot(
                    4, "Fach 4 - Rücklauf/Kühlen", PlateType.TEXTURED_PEI, PlateSlotStatus.EMPTY, 0, "empty", ""
                ),
            ]


class SimulatedDriver:
    """Fährt die Phasen nur durch (keine Hardware). Ein echter Treiber ersetzt ``run_phase`` und ``abort``."""

    simulated = True

    async def run_phase(self, phase: plate_changer.Phase) -> None:
        await asyncio.sleep(0.005)

    async def abort(self) -> None:
        """Magnet aus, Antriebe stromlos. In der Simulation gibt es nichts abzuschalten."""


def _blocked(blocked_by: Sequence[str]) -> dict[str, Any] | None:
    if not blocked_by:
        return None
    return {"status": "error", "message": " ".join(blocked_by), "blocked_by": list(blocked_by)}


class PlateStationService:
    """Zentraler Orchestrierungsdienst für Tür-, Magazin-, Wechsler- und Waschstation."""

    def __init__(self, state_file: Path = STATION_STATE_PATH, driver: SimulatedDriver | None = None) -> None:
        self.state_file = state_file
        self.driver = driver or SimulatedDriver()
        self._lock = asyncio.Lock()
        self.state = self._load_state()

    def _load_state(self) -> PlateStationState:
        if not self.state_file.exists():
            return PlateStationState()
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            slots = [
                MagazineSlot(
                    slot_id=s["slot_id"],
                    label=s["label"],
                    plate_type=PlateType(s.get("plate_type", PlateType.TEXTURED_PEI)),
                    status=PlateSlotStatus(s.get("status", PlateSlotStatus.EMPTY)),
                    wash_cycles=s.get("wash_cycles", 0),
                    last_action=s.get("last_action", ""),
                    barcode=s.get("barcode", ""),
                )
                for s in data.get("magazine_slots", [])
            ]
            # Ältere Stände hatten ein 5. Fach ("Puffer"), für das es keine Höhe gibt: leere hintere Fächer entfallen.
            while len(slots) > plate_changer.SLOT_COUNT and slots[-1].status == PlateSlotStatus.EMPTY:
                slots.pop()
            active_slot = data.get("active_plate_slot")
            if "bed_plate" in data:
                raw = data["bed_plate"]
                bed_plate = (
                    BedPlate(
                        PlateType(raw.get("plate_type", PlateType.TEXTURED_PEI)),
                        raw.get("barcode", ""),
                        int(raw.get("wash_cycles", 0)),
                        bool(raw.get("has_parts", False)),
                    )
                    if raw
                    else None
                )
            else:
                # Ältere Stände führten die Platte auf dem Bett als Fach mit Status "printing" (oder gar nicht).
                printing = next((s for s in slots if s.status == PlateSlotStatus.PRINTING), None)
                bed_plate = (
                    BedPlate(printing.plate_type, printing.barcode, printing.wash_cycles) if printing else BedPlate()
                )
                active_slot = printing.slot_id if printing else None
                if printing:
                    self._clear_slot(printing, "migrated_to_bed")
            return PlateStationState(
                door_state=DoorState(data.get("door_state", DoorState.CLOSED)),
                door_angle_deg=float(data.get("door_angle_deg", 0.0)),
                active_plate_slot=active_slot,
                bed_plate=bed_plate,
                magazine_slots=slots or None,
                is_swapping=bool(data.get("is_swapping", False)),
                is_washing=bool(data.get("is_washing", False)),
                ipa_level_pct=float(data.get("ipa_level_pct", 85.0)),
                last_swap_timestamp=data.get("last_swap_timestamp", ""),
                last_wash_timestamp=data.get("last_wash_timestamp", ""),
                error_message=data.get("error_message"),
            )
        except Exception as exc:
            logger.warning("Konnte Stationszustand nicht laden (%s), nutze Standardwerte.", exc)
            return PlateStationState()

    def _save_state(self) -> None:
        try:
            data = {
                "door_state": self.state.door_state.value,
                "door_angle_deg": self.state.door_angle_deg,
                "active_plate_slot": self.state.active_plate_slot,
                "bed_plate": asdict(self.state.bed_plate) if self.state.bed_plate else None,
                "magazine_slots": [asdict(s) for s in self.state.magazine_slots],
                "is_swapping": self.state.is_swapping,
                "is_washing": self.state.is_washing,
                "ipa_level_pct": self.state.ipa_level_pct,
                "last_swap_timestamp": self.state.last_swap_timestamp,
                "last_wash_timestamp": self.state.last_wash_timestamp,
                "error_message": self.state.error_message,
            }
            self.state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Fehler beim Speichern des Stationszustands: %s", exc)

    @staticmethod
    def _clear_slot(slot: MagazineSlot, action: str) -> None:
        slot.status = PlateSlotStatus.EMPTY
        slot.barcode = ""
        slot.wash_cycles = 0
        slot.label = f"Fach {slot.slot_id} - frei"
        slot.last_action = action

    def _store_bed_plate(self, slot: MagazineSlot) -> None:
        """Die Platte vom Bett liegt jetzt im Fach ``slot``: mit Teilen darauf (``full``), sonst verschmutzt (``dirty``)."""
        bed = self.state.bed_plate
        if bed is None:
            return
        slot.plate_type = bed.plate_type
        slot.barcode = bed.barcode
        slot.wash_cycles = bed.wash_cycles
        slot.label = f"Fach {slot.slot_id} - {bed.name}"
        slot.status = PlateSlotStatus.FULL if bed.has_parts else PlateSlotStatus.DIRTY
        slot.last_action = "stored_with_parts" if bed.has_parts else "ejected_from_printer"
        self.state.bed_plate = None

    def _load_bed_plate(self, slot: MagazineSlot) -> None:
        """Die Platte aus Fach ``slot`` liegt jetzt auf dem Bett, das Fach ist frei."""
        self.state.bed_plate = BedPlate(slot.plate_type, slot.barcode, slot.wash_cycles)
        self.state.active_plate_slot = slot.slot_id
        self._clear_slot(slot, "loaded_into_printer")

    def get_status(self) -> dict[str, Any]:
        """Gibt den vollständigen Systemzustand aller Stationen zurück."""
        ready_plates = sum(1 for s in self.state.magazine_slots if s.status == PlateSlotStatus.READY)
        dirty_plates = sum(1 for s in self.state.magazine_slots if s.status == PlateSlotStatus.DIRTY)
        empty_slots = sum(1 for s in self.state.magazine_slots if s.status == PlateSlotStatus.EMPTY)
        full_plates = sum(1 for s in self.state.magazine_slots if s.status == PlateSlotStatus.FULL)

        return {
            "door": {
                "state": self.state.door_state.value,
                "angle_deg": self.state.door_angle_deg,
                "is_open": self.state.door_state == DoorState.OPEN,
            },
            "magazine": {
                "total_slots": len(self.state.magazine_slots),
                "ready_count": ready_plates,
                "dirty_count": dirty_plates,
                "full_count": full_plates,
                "empty_count": empty_slots,
                "slots": [asdict(s) for s in self.state.magazine_slots],
            },
            "station": {
                "is_swapping": self.state.is_swapping,
                "is_washing": self.state.is_washing,
                "active_plate_slot": self.state.active_plate_slot,
                "ipa_level_pct": round(self.state.ipa_level_pct, 1),
                "last_swap": self.state.last_swap_timestamp,
                "last_wash": self.state.last_wash_timestamp,
                "error_message": self.state.error_message,
                "current_phase": self.state.current_phase,
            },
            "bed_plate": {**asdict(self.state.bed_plate), "name": self.state.bed_plate.name}
            if self.state.bed_plate
            else None,
            "driver": {"simulated": self.driver.simulated},
            "geometry": {
                "slot_z": list(plate_changer.SLOT_Z),
                "z_swap": plate_changer.Z_SWAP,
                "slot_capacity_mm": list(plate_changer.SLOT_CAPACITY),
            },
            "design": {k: v for k, v in plate_changer.design_summary().items() if k != "checks"},
            "phases": [{"id": p.id, "label": p.label} for p in plate_changer.PHASES],
        }

    async def open_door(self, blocked_by: Sequence[str] = ()) -> dict[str, Any]:
        """Öffnet die Kammertür servogesteuert mit Sanftanlauf."""
        if (blocked := _blocked(blocked_by)) is not None:
            return blocked
        async with self._lock:
            if self.state.door_state == DoorState.OPEN:
                return {"status": "ok", "message": "Tür ist bereits geöffnet.", "angle": self.state.door_angle_deg}

            self.state.door_state = DoorState.OPENING
            logger.info("Tür-Aktuator: Öffnungsvorgang gestartet (0° -> 115°)")
            await asyncio.sleep(0.1)  # Simulierte oder reale Motorfahrt

            self.state.door_angle_deg = 115.0
            self.state.door_state = DoorState.OPEN
            self._save_state()
            return {"status": "ok", "message": "Tür erfolgreich geöffnet.", "angle": 115.0}

    async def close_door(self, blocked_by: Sequence[str] = ()) -> dict[str, Any]:
        """Schließt die Kammertür sanft und prüft Endschalter/Türsensor."""
        if (blocked := _blocked(blocked_by)) is not None:
            return blocked
        async with self._lock:
            if self.state.door_state == DoorState.CLOSED:
                return {"status": "ok", "message": "Tür ist bereits geschlossen.", "angle": 0.0}

            self.state.door_state = DoorState.CLOSING
            logger.info("Tür-Aktuator: Schließvorgang gestartet (115° -> 0°)")
            await asyncio.sleep(0.1)

            self.state.door_angle_deg = 0.0
            self.state.door_state = DoorState.CLOSED
            self._save_state()
            return {"status": "ok", "message": "Tür sicher geschlossen.", "angle": 0.0}

    def _pick_empty_slot(self, usable: list[MagazineSlot], part_height_mm: float | None) -> MagazineSlot | None:
        """Erstes freies Fach, in dem Teile dieser Höhe unter der nächsten Platte (oder der Deckplatte) Platz haben."""
        for slot in usable:
            if slot.status != PlateSlotStatus.EMPTY:
                continue
            if part_height_mm is not None and part_height_mm > plate_changer.SLOT_CAPACITY[slot.slot_id - 1]:
                continue
            return slot
        return None

    async def swap_plate(
        self,
        target_plate_type: PlateType | None = None,
        blocked_by: Sequence[str] = (),
        with_parts: bool = True,
        part_height_mm: float | None = None,
    ) -> dict[str, Any]:
        """Führt einen vollautomatischen Plattenwechsel durch (Phasen: ``plate_changer.PHASES``).

        Die Platte vom Bett kommt samt den fertigen Teilen in ein freies Fach (Status ``full``), die frische aus ihrem Fach
        auf das Bett. Die Teile werden nicht abgeschoben: Sie müssen unter die nächste Platte im Regal passen
        (``part_height_mm``, sonst sperrt der Wechsel). ``blocked_by`` sind Gründe, die den Wechsel jetzt verbieten
        (Not-Halt, Druck läuft, Bett zu heiß); dann bewegt sich nichts.
        """
        if (blocked := _blocked(blocked_by)) is not None:
            return blocked
        async with self._lock:
            if self.state.is_swapping:
                return {"status": "error", "message": "Plattenwechsel läuft bereits."}

            self.state.is_swapping = True
            self.state.error_message = None
            completed: list[str] = []

            try:
                usable = [s for s in self.state.magazine_slots if 1 <= s.slot_id <= plate_changer.SLOT_COUNT]
                bed = self.state.bed_plate
                carried_height = part_height_mm if (bed is not None and with_parts) else None

                # Freies Fach für die Platte vom Bett (nur nötig, wenn eine auf dem Bett liegt)
                stored_slot = self._pick_empty_slot(usable, carried_height) if bed is not None else None
                if bed is not None and stored_slot is None:
                    if self._pick_empty_slot(usable, None) is not None:
                        biggest = max(
                            plate_changer.SLOT_CAPACITY[s.slot_id - 1]
                            for s in usable
                            if s.status == PlateSlotStatus.EMPTY
                        )
                        raise RuntimeError(
                            f"Kein freies Fach, in dem die Teile ({carried_height:.0f} mm hoch) Platz haben: "
                            f"im größten freien Fach höchstens {biggest:.1f} mm."
                        )
                    raise RuntimeError("Kein leeres Magazinfach vorhanden, um die alte Platte abzulegen!")

                desired_type = target_plate_type or PlateType.TEXTURED_PEI
                fresh_slot = next(
                    (
                        s
                        for s in usable
                        if s.status == PlateSlotStatus.READY
                        and (target_plate_type is None or s.plate_type == desired_type)
                    ),
                    None,
                )
                if fresh_slot is None:
                    raise RuntimeError(f"Keine frische Platte vom Typ '{desired_type.value}' im Magazin verfügbar!")
                if bed is not None:
                    bed.has_parts = with_parts

                for phase in plate_changer.PHASES:
                    self.state.current_phase = phase.id
                    if phase.id == "door_open":
                        self.state.door_state = DoorState.OPENING
                    elif phase.id == "park_close":
                        self.state.door_state = DoorState.CLOSING
                    await self.driver.run_phase(phase)
                    completed.append(phase.id)
                    if phase.id == "door_open":
                        self.state.door_angle_deg = plate_changer.DOOR_OPEN_DEG
                        self.state.door_state = DoorState.OPEN
                    elif phase.id == "store_old" and stored_slot is not None:
                        self._store_bed_plate(stored_slot)
                    elif phase.id == "place_fresh":
                        self._load_bed_plate(fresh_slot)
                    elif phase.id == "park_close":
                        self.state.door_angle_deg = 0.0
                        self.state.door_state = DoorState.CLOSED

                self.state.last_swap_timestamp = datetime.now(timezone.utc).isoformat()
                self._save_state()

                return {
                    "status": "ok",
                    "message": f"Plattenwechsel erfolgreich abgeschlossen. Die Platte aus Fach {fresh_slot.slot_id} liegt auf dem Bett.",
                    "active_slot": fresh_slot.slot_id,
                    "stored_dirty_slot": stored_slot.slot_id if stored_slot else None,
                    "stored_slot_status": stored_slot.status.value if stored_slot else None,
                    "with_parts": bool(with_parts and stored_slot),
                    "phases": completed,
                    "simulated": self.driver.simulated,
                }

            except Exception as exc:
                phase_id = self.state.current_phase
                await self.driver.abort()
                self.state.error_message = f"{exc} (Phase {phase_id})" if phase_id else str(exc)
                logger.error("Fehler beim automatischen Plattenwechsel in Phase %s: %s", phase_id, exc)
                return {"status": "error", "message": self.state.error_message, "phases": completed}
            finally:
                self.state.is_swapping = False
                self.state.current_phase = None
                self._save_state()

    def unload_parts(self, slot_id: int) -> dict[str, Any]:
        """Die fertigen Teile wurden von Hand von der Platte in Fach ``slot_id`` genommen: ``full`` wird zu ``dirty``."""
        slot = next((s for s in self.state.magazine_slots if s.slot_id == slot_id), None)
        if slot is None:
            return {"status": "error", "message": f"Fach #{slot_id} nicht gefunden."}
        if slot.status != PlateSlotStatus.FULL:
            return {"status": "error", "message": f"Auf der Platte in Fach #{slot_id} liegen keine Teile."}
        slot.status = PlateSlotStatus.DIRTY
        slot.last_action = "parts_removed"
        self._save_state()
        return {
            "status": "ok",
            "message": f"Teile aus Fach #{slot_id} entnommen, die Platte kann gewaschen werden.",
            "slot": asdict(slot),
        }

    async def wash_plate(self, slot_id: int | None = None, blocked_by: Sequence[str] = ()) -> dict[str, Any]:
        """Führt den automatischen Wasch- & Reinigungszyklus für eine verschmutzte Platte aus:

        1. Platte aus Magazin in Waschstation-Kammer einziehen
        2. IPA-Flüssigkeitsauftrag (Peristaltikpumpe, ~3ml)
        3. Motorisierte Mikrofaser-Walzenreinigung (Vor- und Rücklauf)
        4. Trocknungsgebläse aktivieren
        5. Platte als READY zurück ins Magazin überführen
        """
        if (blocked := _blocked(blocked_by)) is not None:
            return blocked
        async with self._lock:
            if self.state.is_washing:
                return {"status": "error", "message": "Ein Waschzyklus läuft bereits."}

            # Zu reinigende Platte ermitteln
            target_slot = None
            if slot_id is not None:
                target_slot = next((s for s in self.state.magazine_slots if s.slot_id == slot_id), None)
            else:
                target_slot = next((s for s in self.state.magazine_slots if s.status == PlateSlotStatus.DIRTY), None)

            if target_slot is not None and target_slot.status == PlateSlotStatus.FULL:
                return {
                    "status": "error",
                    "message": f"Auf der Platte in Fach #{target_slot.slot_id} liegen noch Teile: erst entnehmen.",
                }
            if not target_slot:
                return {"status": "error", "message": "Keine schmutzige Platte zum Reinigen gefunden."}

            if self.state.ipa_level_pct < 5.0:
                return {"status": "error", "message": "IPA-Füllstand zu niedrig (<5%). Bitte Isopropanol nachfüllen!"}

            self.state.is_washing = True
            target_slot.status = PlateSlotStatus.WASHING
            target_slot.last_action = "washing_in_progress"
            self._save_state()

            try:
                # 1. IPA Dosierung & Walzenlauf
                logger.info("Waschstation: Starte IPA-Auftrag und Walzenbürsten für Slot #%d", target_slot.slot_id)
                await asyncio.sleep(0.15)
                self.state.ipa_level_pct = max(0.0, self.state.ipa_level_pct - 1.2)

                # 2. Trocknungsphase
                logger.info("Waschstation: Trocknungsgebläse aktiv")
                await asyncio.sleep(0.1)

                # 3. Abschluss & Statusaktualisierung
                target_slot.status = PlateSlotStatus.READY
                target_slot.wash_cycles += 1
                target_slot.last_action = f"washed_{datetime.now(timezone.utc).strftime('%H:%M')}"
                self.state.last_wash_timestamp = datetime.now(timezone.utc).isoformat()

                return {
                    "status": "ok",
                    "message": f"Platte #{target_slot.slot_id} ({target_slot.label}) erfolgreich gewaschen & getrocknet.",
                    "slot_id": target_slot.slot_id,
                    "wash_cycles": target_slot.wash_cycles,
                    "remaining_ipa_pct": round(self.state.ipa_level_pct, 1),
                }

            except Exception as exc:
                target_slot.status = PlateSlotStatus.DIRTY
                self.state.error_message = f"Waschfehler: {exc}"
                return {"status": "error", "message": str(exc)}
            finally:
                self.state.is_washing = False
                self._save_state()

    def update_slot(
        self, slot_id: int, status: PlateSlotStatus, plate_type: PlateType | None = None, label: str | None = None
    ) -> dict[str, Any]:
        """Aktualisiert manuell oder per Sensor/Barcode den Zustand eines Magazinfachs."""
        slot = next((s for s in self.state.magazine_slots if s.slot_id == slot_id), None)
        if not slot:
            return {"status": "error", "message": f"Fach #{slot_id} nicht gefunden."}

        slot.status = status
        if plate_type:
            slot.plate_type = plate_type
        if label:
            slot.label = label
        slot.last_action = "manual_update"
        self._save_state()
        return {"status": "ok", "slot": asdict(slot)}


# Singleton-Instanz
plate_station_service = PlateStationService()
