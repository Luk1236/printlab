"""Enterprise Fleet Management & Dynamisches Load Balancing mit AMS-Matching für PrintLab 2.0.

Ermöglicht das automatische Verteilen anstehender 3D-Druckaufträge auf eine Flotte
von Bambu Lab Druckern (P2S, P1S, X1C, A1) anhand von:
- Drucker-Verfügbarkeit (Bereit, Tür geschlossen, Bett frei & abgekühlt)
- Passende Düsenkonfiguration (z. B. 0.4 mm gehärteter Stahl für abrasive Filamente)
- AMS-Spulen-Matching (Material, Farbe und verbleibende Gramm auf der Spule)
- Betriebsstunden- und Auslastungs-Balancing
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Ab diesem Fitness-Score gilt ein Drucker als sofort startbereit. Eine
# Konstante statt doppelter 60.0-Magie in Routen und Dispatcher.
MIN_DISPATCH_SCORE = 60.0


def _as_float(value: Any, fallback: float) -> float:
    """Robustes float-Parsing: ungültige oder nicht endliche Werte bekommen den Fallback.

    Der Dispatcher wird aus API-Payloads gespeist; ``"abc"`` in
    ``filament_grams`` darf keinen 500er werfen, sondern fällt auf den
    dokumentierten Standard zurück.
    """
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def calculate_printer_fitness(
    printer: dict[str, Any],
    job: dict[str, Any],
) -> tuple[float, list[str]]:
    """Berechnet einen Fitness-Score (0.0 bis 100.0) für einen Drucker bezüglich eines Druckauftrags.

    Returns:
        (score, match_reasons)
    """
    reasons: list[str] = []
    score = 0.0

    # 1. Grundvoraussetzung: Verbindung & Status
    connected = bool(printer.get("connected", True))
    state = str(printer.get("state", "IDLE")).upper()
    if not connected:
        return 0.0, ["Drucker ist offline oder nicht verbunden"]
    if state not in ("IDLE", "READY", "STANDBY"):
        return 0.0, [f"Drucker ist aktuell beschäftigt ({state})"]

    score += 30.0
    reasons.append(f"Drucker ist bereit ({state})")

    # 2. Bauplatten-Zustand (Leerbett & Abkühlung)
    plate_clear = bool(printer.get("plate_clear", True))
    bed_temp = _as_float(printer.get("bed_temp"), 25.0)
    if not plate_clear:
        return 0.0, ["Druckbett ist noch mit einem vorherigen Bauteil belegt"]
    if bed_temp > 40.0:
        score -= 10.0
        reasons.append(f"Bett noch warm ({bed_temp:.1f} °C, kühlt ab)")
    else:
        score += 15.0
        reasons.append("Druckbett ist frei und abgekühlt")

    # 3. Düsen-Kompatibilität
    req_nozzle = _as_float(job.get("nozzle_diameter"), 0.4)
    printer_nozzle = _as_float(printer.get("nozzle_diameter"), 0.4)
    req_hardened = bool(job.get("requires_hardened_nozzle", False))
    is_hardened = bool(printer.get("is_hardened_nozzle", True))

    if abs(req_nozzle - printer_nozzle) > 0.01:
        return 0.0, [f"Düsengröße inkompatibel ({printer_nozzle}mm vorhanden, {req_nozzle}mm gefordert)"]
    if req_hardened and not is_hardened:
        return 0.0, ["Abrasives Filament erfordert gehärtete Stahldüse (nur Messing vorhanden)"]

    score += 20.0
    reasons.append(f"Düse kompatibel ({printer_nozzle} mm{' gehärtet' if is_hardened else ''})")

    # 4. AMS-Material- und Farb-Matching
    req_mat = str(job.get("material", "PLA")).upper()
    req_color = str(job.get("color", "")).lower()
    req_weight = _as_float(job.get("filament_grams"), 30.0)

    ams_slots = printer.get("ams_slots", [])
    if not isinstance(ams_slots, list):
        ams_slots = []
    matched_slot: dict[str, Any] | None = None

    for slot in ams_slots:
        if not isinstance(slot, dict):
            continue
        slot_mat = str(slot.get("material", "")).upper()
        slot_remain = _as_float(slot.get("remaining_grams"), 0.0)
        if slot_mat == req_mat and slot_remain >= req_weight:
            slot_color = str(slot.get("color", "")).lower()
            if not req_color or slot_color == req_color:
                matched_slot = slot
                break
            elif not matched_slot:
                matched_slot = slot  # Material passt, Farbe weicht leicht ab

    if matched_slot:
        score += 25.0
        reasons.append(
            f"Passendes Filament in AMS Slot {matched_slot.get('slot_id', 1)} "
            f"({matched_slot.get('material')} {matched_slot.get('color', '')}, {matched_slot.get('remaining_grams', 0):.0f}g vorhanden)"
        )
    else:
        score -= 20.0
        reasons.append(f"Kein exakt passendes Filament für {req_mat} im AMS geladen (manueller Wechsel nötig)")

    # 5. Betriebsstunden-Balancing (bevorzuge weniger abgenutzte Drucker leicht)
    total_hours = _as_float(printer.get("total_operating_hours"), 100.0)
    if total_hours < 200.0:
        score += 10.0
    elif total_hours < 500.0:
        score += 5.0

    return max(0.0, min(100.0, score)), reasons


def dispatch_job_to_fleet(
    job: dict[str, Any],
    printers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Wählt den optimalen Drucker aus der Flotte für einen Druckauftrag aus."""
    if not printers:
        return {
            "selected_printer_id": None,
            "status": "NO_PRINTERS_AVAILABLE",
            "message": "Keine Drucker in der Flotte registriert.",
            "candidates": [],
        }

    scored_candidates: list[dict[str, Any]] = []

    for p in printers:
        score, reasons = calculate_printer_fitness(p, job)
        scored_candidates.append(
            {
                "printer_id": p.get("id"),
                "name": p.get("name", "Bambu Lab P2S"),
                "fitness_score": score,
                "reasons": reasons,
                "can_start_immediately": score >= 60.0,
            }
        )

    scored_candidates.sort(key=lambda x: x["fitness_score"], reverse=True)
    best = scored_candidates[0]

    if best["fitness_score"] >= MIN_DISPATCH_SCORE:
        return {
            "selected_printer_id": best["printer_id"],
            "status": "DISPATCHED",
            "message": f"Druckauftrag '{job.get('name', 'Unbenannt')}' an '{best['name']}' zugewiesen (Score: {best['fitness_score']:.1f}/100).",
            "candidates": scored_candidates,
        }
    else:
        return {
            "selected_printer_id": None,
            "status": "WAITING_FOR_RESOURCES",
            "message": "Aktuell kein Drucker sofort startbereit. Bester Kandidat benötigt Vorbereitung (z. B. Plattenleerung oder Filamentladung).",
            "candidates": scored_candidates,
        }
