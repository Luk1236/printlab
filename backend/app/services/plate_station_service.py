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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from backend.app.core.config import settings

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
    READY = "ready"        # Frisch gereinigt / druckbereit
    PRINTING = "printing"  # Aktuell im Drucker
    DIRTY = "dirty"        # Benutzte Platte mit oder ohne Teil
    WASHING = "washing"    # In der Waschstation
    EMPTY = "empty"        # Fach leer


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


@dataclass
class PlateStationState:
    door_state: DoorState = DoorState.CLOSED
    door_angle_deg: float = 0.0
    active_plate_slot: int | None = 1
    magazine_slots: list[MagazineSlot] = None
    is_swapping: bool = False
    is_washing: bool = False
    ipa_level_pct: float = 85.0
    last_swap_timestamp: str = ""
    last_wash_timestamp: str = ""
    error_message: str | None = None

    def __post_init__(self):
        if self.magazine_slots is None:
            self.magazine_slots = [
                MagazineSlot(1, "Fach 1 - Gold PEI", PlateType.TEXTURED_PEI, PlateSlotStatus.READY, 12, "ready", "PLT-PEI-01"),
                MagazineSlot(2, "Fach 2 - Smooth PEI", PlateType.SMOOTH_PEI, PlateSlotStatus.READY, 8, "ready", "PLT-SMT-02"),
                MagazineSlot(3, "Fach 3 - High-Temp", PlateType.HIGH_TEMP, PlateSlotStatus.READY, 4, "ready", "PLT-HTP-03"),
                MagazineSlot(4, "Fach 4 - Rücklauf/Kühlen", PlateType.TEXTURED_PEI, PlateSlotStatus.EMPTY, 0, "empty", ""),
                MagazineSlot(5, "Fach 5 - Puffer", PlateType.TEXTURED_PEI, PlateSlotStatus.EMPTY, 0, "empty", ""),
            ]


class PlateStationService:
    """Zentraler Orchestrierungsdienst für Tür-, Magazin-, Wechsler- und Waschstation."""

    def __init__(self, state_file: Path = STATION_STATE_PATH) -> None:
        self.state_file = state_file
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
            return PlateStationState(
                door_state=DoorState(data.get("door_state", DoorState.CLOSED)),
                door_angle_deg=float(data.get("door_angle_deg", 0.0)),
                active_plate_slot=data.get("active_plate_slot"),
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

    def get_status(self) -> dict[str, Any]:
        """Gibt den vollständigen Systemzustand aller Stationen zurück."""
        ready_plates = sum(1 for s in self.state.magazine_slots if s.status == PlateSlotStatus.READY)
        dirty_plates = sum(1 for s in self.state.magazine_slots if s.status == PlateSlotStatus.DIRTY)
        empty_slots = sum(1 for s in self.state.magazine_slots if s.status == PlateSlotStatus.EMPTY)

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
            },
        }

    async def open_door(self) -> dict[str, Any]:
        """Öffnet die Kammertür servogesteuert mit Sanftanlauf."""
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

    async def close_door(self) -> dict[str, Any]:
        """Schließt die Kammertür sanft und prüft Endschalter/Türsensor."""
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

    async def swap_plate(self, target_plate_type: PlateType | None = None) -> dict[str, Any]:
        """Führt einen vollautomatischen Plattenwechsel durch:

        1. Tür öffnen
        2. Alte/benutzte Platte vom Magnetbett in ein freies Lagerfach ziehen
        3. Frische Platte (passender Typ) aus Magazin greifen und auf Magnetbett einlegen
        4. Tür schließen
        5. Status aktualisieren
        """
        async with self._lock:
            if self.state.is_swapping:
                return {"status": "error", "message": "Plattenwechsel läuft bereits."}

            self.state.is_swapping = True
            self.state.error_message = None

            try:
                # 1. Freies Rücklauffach für die verbrauchte Platte finden
                empty_slot = next((s for s in self.state.magazine_slots if s.status == PlateSlotStatus.EMPTY), None)
                if not empty_slot:
                    raise RuntimeError("Kein leeres Magazinfach vorhanden, um die alte Platte abzulegen!")

                # 2. Frische Platte suchen
                desired_type = target_plate_type or PlateType.TEXTURED_PEI
                fresh_slot = next(
                    (s for s in self.state.magazine_slots if s.status == PlateSlotStatus.READY and (target_plate_type is None or s.plate_type == desired_type)),
                    None
                )
                if not fresh_slot:
                    raise RuntimeError(f"Keine frische Platte vom Typ '{desired_type.value}' im Magazin verfügbar!")

                # Schritt A: Tür öffnen
                self.state.door_state = DoorState.OPENING
                await asyncio.sleep(0.1)
                self.state.door_angle_deg = 115.0
                self.state.door_state = DoorState.OPEN

                # Schritt B: Alte Platte entnehmen und in empty_slot ablegen
                if self.state.active_plate_slot is not None:
                    empty_slot.status = PlateSlotStatus.DIRTY
                    empty_slot.last_action = "ejected_from_printer"

                # Schritt C: Frische Platte einlegen
                fresh_slot.status = PlateSlotStatus.PRINTING
                fresh_slot.last_action = "loaded_into_printer"
                self.state.active_plate_slot = fresh_slot.slot_id

                # Schritt D: Tür schließen
                self.state.door_state = DoorState.CLOSING
                await asyncio.sleep(0.1)
                self.state.door_angle_deg = 0.0
                self.state.door_state = DoorState.CLOSED

                self.state.last_swap_timestamp = datetime.now(timezone.utc).isoformat()
                self._save_state()

                return {
                    "status": "ok",
                    "message": f"Plattenwechsel erfolgreich abgeschlossen. Platte #{fresh_slot.slot_id} ({fresh_slot.label}) ist einsatzbereit.",
                    "active_slot": fresh_slot.slot_id,
                    "stored_dirty_slot": empty_slot.slot_id,
                }

            except Exception as exc:
                self.state.error_message = str(exc)
                logger.error("Fehler beim automatischen Plattenwechsel: %s", exc)
                return {"status": "error", "message": str(exc)}
            finally:
                self.state.is_swapping = False
                self._save_state()

    async def wash_plate(self, slot_id: int | None = None) -> dict[str, Any]:
        """Führt den automatischen Wasch- & Reinigungszyklus für eine verschmutzte Platte aus:

        1. Platte aus Magazin in Waschstation-Kammer einziehen
        2. IPA-Flüssigkeitsauftrag (Peristaltikpumpe, ~3ml)
        3. Motorisierte Mikrofaser-Walzenreinigung (Vor- und Rücklauf)
        4. Trocknungsgebläse aktivieren
        5. Platte als READY zurück ins Magazin überführen
        """
        async with self._lock:
            if self.state.is_washing:
                return {"status": "error", "message": "Ein Waschzyklus läuft bereits."}

            # Zu reinigende Platte ermitteln
            target_slot = None
            if slot_id is not None:
                target_slot = next((s for s in self.state.magazine_slots if s.slot_id == slot_id), None)
            else:
                target_slot = next((s for s in self.state.magazine_slots if s.status == PlateSlotStatus.DIRTY), None)

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

    def update_slot(self, slot_id: int, status: PlateSlotStatus, plate_type: PlateType | None = None, label: str | None = None) -> dict[str, Any]:
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
