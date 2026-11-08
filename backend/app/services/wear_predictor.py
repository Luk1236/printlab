"""Abrasive Filament Wear Predictor & Component Lifetime Forecasting (Phase 18).

Berechnet die beschleunigte Abnutzung durch abrasive Füllstoffe (Carbonfaser,
Glasfaser, Glow, Holz) auf Düsen, Extruder-Zahnräder und PTFE-Führungsschläuche.
Ermöglicht verlässliche Preflight-Checks vor dem Start langer Druckaufträge.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.services.wear_tracker import get_wear_overview

logger = logging.getLogger(__name__)

# Abrasivitäts-Faktoren (Abnutzungsmultiplikator ggü. Standard-PLA)
ABRASIVE_FACTORS: dict[str, float] = {
    "PLA": 1.0,
    "PETG": 1.1,
    "ABS": 1.0,
    "ASA": 1.0,
    "TPU": 0.8,
    "PC": 1.2,
    "PLA-CF": 5.0,
    "PETG-CF": 5.0,
    "PA-CF": 6.0,
    "PA-GF": 6.0,
    "PLA-GF": 5.0,
    "PETG-GF": 5.0,
    "GLOW": 4.0,
    "WOOD": 2.0,
    "METAL": 4.5,
}

# Standzeiten für Baugruppen (in Betriebsstunden)
COMPONENT_NOMINAL_HOURS: dict[str, float] = {
    "nozzle_hardened_steel": 1500.0,
    "nozzle_brass": 250.0,
    "nozzle_stainless": 500.0,
    "extruder_gears_hardened": 2000.0,
    "ptfe_tubes": 800.0,
}


def get_material_abrasive_factor(filament_type: str) -> float:
    """Ermittelt den Abrasivitätsfaktor eines Materials (Standard: 1.0)."""
    ft = (filament_type or "").upper().strip()
    # Sortiere nach Schlüssellänge absteigend (z.B. "PLA-CF" vor "PLA")
    for key in sorted(ABRASIVE_FACTORS.keys(), key=len, reverse=True):
        if key in ft:
            return ABRASIVE_FACTORS[key]
    return 1.0


def is_abrasive_material(filament_type: str) -> bool:
    """Prüft, ob ein Material als abrasiv gilt (CF, GF, Glow, etc.)."""
    return get_material_abrasive_factor(filament_type) >= 2.0


def predict_job_wear(
    printer_id: str,
    filament_type: str,
    print_time_hours: float,
    nozzle_type: str = "nozzle_hardened_steel",
) -> dict[str, Any]:
    """Berechnet die voraussichtliche Bauteilabnutzung für einen anstehenden Druck."""
    hours = max(0.01, float(print_time_hours))
    factor = get_material_abrasive_factor(filament_type)
    effective_wear_hours = hours * factor

    current_wear = get_wear_overview(printer_id)
    components_list = current_wear.get("components", [])
    components_by_id = {c["id"]: c for c in components_list if isinstance(c, dict) and "id" in c}

    # Nozzle Wear
    nom_nozzle = COMPONENT_NOMINAL_HOURS.get(nozzle_type, 1500.0)
    current_nozzle_used = float(components_by_id.get("nozzle", {}).get("used_hours", 0.0))
    nozzle_remaining_before = max(0.0, nom_nozzle - current_nozzle_used)
    nozzle_remaining_after = max(0.0, nozzle_remaining_before - effective_wear_hours)
    nozzle_wear_pct_before = min(100.0, (current_nozzle_used / nom_nozzle) * 100.0)
    nozzle_wear_pct_after = min(100.0, ((current_nozzle_used + effective_wear_hours) / nom_nozzle) * 100.0)

    # PTFE Tube Wear
    nom_ptfe = COMPONENT_NOMINAL_HOURS["ptfe_tubes"]
    current_ptfe_used = float(components_by_id.get("ptfe", {}).get("used_hours", 0.0))
    ptfe_remaining_before = max(0.0, nom_ptfe - current_ptfe_used)
    ptfe_remaining_after = max(0.0, ptfe_remaining_before - (hours * min(factor, 3.0)))

    # Extruder Gear Wear
    nom_extruder = COMPONENT_NOMINAL_HOURS["extruder_gears_hardened"]
    extruder_wear_hours = hours * min(factor, 4.0)

    # Kann der Druck sicher beendet werden?
    can_safely_print = (nozzle_remaining_before >= effective_wear_hours)
    warning_level = "OK"
    recommendations: list[str] = []

    if not can_safely_print:
        warning_level = "CRITICAL"
        recommendations.append(
            f"Düse erreicht voraussichtlich Lebensdauerende während des Drucks ({nozzle_remaining_before:.1f}h Restzeit vs. {effective_wear_hours:.1f}h Äquivalentzeit). Düse vor Start tauschen!"
        )
    elif nozzle_wear_pct_after >= 85.0:
        warning_level = "WARNING"
        recommendations.append(
            f"Düse ist nach diesem Druck zu {nozzle_wear_pct_after:.1f}% verschlissen. Nächste Wartung zeitnah planen."
        )

    if is_abrasive_material(filament_type) and "brass" in nozzle_type.lower():
        warning_level = "CRITICAL"
        can_safely_print = False
        recommendations.append(
            f"Abrasives Material '{filament_type}' darf NICHT mit Messingdüse gedruckt werden. Auf gehärteten Stahl umrüsten!"
        )

    return {
        "printer_id": str(printer_id),
        "filament_type": filament_type,
        "is_abrasive": is_abrasive_material(filament_type),
        "abrasive_multiplier": factor,
        "print_time_hours": hours,
        "effective_wear_hours": round(effective_wear_hours, 2),
        "can_safely_print": can_safely_print,
        "warning_level": warning_level,
        "nozzle": {
            "type": nozzle_type,
            "nominal_life_hours": nom_nozzle,
            "wear_percent_before": round(nozzle_wear_pct_before, 1),
            "wear_percent_after": round(nozzle_wear_pct_after, 1),
            "remaining_hours_after": round(nozzle_remaining_after, 1),
        },
        "ptfe": {
            "nominal_life_hours": nom_ptfe,
            "remaining_hours_after": round(ptfe_remaining_after, 1),
        },
        "extruder": {
            "nominal_life_hours": nom_extruder,
            "wear_delta_hours": round(extruder_wear_hours, 2),
        },
        "recommendations": recommendations,
    }
