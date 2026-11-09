"""Intelligentes Einzelobjekt-Überspringen bei lokalem Druckfehler (Phase 14).

Ermöglicht es, bei Multi-Part-Drucken (z. B. 12 Bauteile auf einem Druckbett)
ein einzelnes fehlerhaftes Bauteil (Spaghetti, Warping, Bettablösung) gezielt
vom Bambu Lab Drucker via MQTT (`skip_objects`) überspringen zu lassen,
während alle übrigen Bauteile auf der Bauplatte ungestört fertiggedruckt werden.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.app.services.printer_manager import printer_manager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlateObjectBound:
    """Objekt-Begrenzung auf dem Druckbett (z. B. aus slice_info.config oder Auto-Nesting)."""

    object_id: int
    name: str
    min_x_mm: float
    min_y_mm: float
    max_x_mm: float
    max_y_mm: float

    def contains_point(self, x_mm: float, y_mm: float, tolerance_mm: float = 3.0) -> bool:
        return (self.min_x_mm - tolerance_mm) <= x_mm <= (self.max_x_mm + tolerance_mm) and (
            self.min_y_mm - tolerance_mm
        ) <= y_mm <= (self.max_y_mm + tolerance_mm)


def match_defect_to_object(
    defect_x_mm: float,
    defect_y_mm: float,
    objects_on_plate: list[PlateObjectBound],
    tolerance_mm: float = 5.0,
) -> PlateObjectBound | None:
    """Findet das Bauteil auf dem Druckbett, in dessen Bounding-Box die Fehlerkoordinaten liegen."""
    for obj in objects_on_plate:
        if obj.contains_point(defect_x_mm, defect_y_mm, tolerance_mm=tolerance_mm):
            return obj

    # Fallback: Nächstgelegenes Bauteil ermitteln, falls der Fehler knapp außerhalb lag (z.B. Spaghetti-Fransen)
    closest: PlateObjectBound | None = None
    min_dist_sq = float("inf")
    for obj in objects_on_plate:
        cx = (obj.min_x_mm + obj.max_x_mm) * 0.5
        cy = (obj.min_y_mm + obj.max_y_mm) * 0.5
        dist_sq = (defect_x_mm - cx) ** 2 + (defect_y_mm - cy) ** 2
        if dist_sq < min_dist_sq:
            min_dist_sq = dist_sq
            closest = obj

    # Nur zuordnen, wenn der Abstand zum Mittelpunkt unter 40 mm liegt
    if closest is not None and min_dist_sq <= (40.0**2):
        return closest

    return None


def execute_skip_objects(
    printer_id: int,
    object_ids: list[int],
    *,
    reason: str = "Automatischer Ausschluss wegen Schichtdefekt",
) -> dict[str, Any]:
    """Sendet den MQTT-Befehl ``skip_objects`` an den Drucker und protokolliert das Ereignis."""
    client = printer_manager.get_client(printer_id)
    if not client:
        return {
            "success": False,
            "printer_id": printer_id,
            "skipped_objects": [],
            "error": "Drucker ist nicht verbunden oder nicht gefunden.",
        }

    status = client.state
    if status.state not in ("RUNNING", "PAUSE"):
        return {
            "success": False,
            "printer_id": printer_id,
            "skipped_objects": [],
            "error": f"Drucker druckt aktuell nicht (Status: {status.state}).",
        }

    valid_ids = [int(oid) for oid in object_ids if int(oid) >= 0]
    if not valid_ids:
        return {
            "success": False,
            "printer_id": printer_id,
            "skipped_objects": [],
            "error": "Keine gültigen Objekt-IDs übergeben.",
        }

    ok = client.skip_objects(valid_ids)
    if ok:
        logger.warning(
            "[AutoSkip] Drucker %s: Bauteile %s erfolgreich übersprungen. Grund: %s",
            printer_id,
            valid_ids,
            reason,
        )
        return {
            "success": True,
            "printer_id": printer_id,
            "skipped_objects": valid_ids,
            "reason": reason,
            "message": f"Bauteil(e) {valid_ids} erfolgreich vom Drucklauf ausgeschlossen. Restliche Bauteile werden weitergedruckt.",
        }
    else:
        return {
            "success": False,
            "printer_id": printer_id,
            "skipped_objects": [],
            "error": "Bambu-MQTT-Client hat das skip_objects-Kommando abgelehnt.",
        }


def parse_objects_from_slice_info(slice_info_xml_or_dict: Any) -> list[PlateObjectBound]:
    """Liest die Objekt-IDs und Koordinaten aus slice_info.config oder einem Layout-Dict."""
    bounds: list[PlateObjectBound] = []
    if isinstance(slice_info_xml_or_dict, list):
        for item in slice_info_xml_or_dict:
            if isinstance(item, dict) and "object_id" in item:
                bounds.append(
                    PlateObjectBound(
                        object_id=int(item["object_id"]),
                        name=str(item.get("name", f"Objekt_{item['object_id']}")),
                        min_x_mm=float(item.get("min_x_mm", 0.0)),
                        min_y_mm=float(item.get("min_y_mm", 0.0)),
                        max_x_mm=float(item.get("max_x_mm", 10.0)),
                        max_y_mm=float(item.get("max_y_mm", 10.0)),
                    )
                )
    return bounds
