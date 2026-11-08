"""AMS Luftfeuchtigkeits- & Taupunkt-Trocknungswächter (Phase 18).

Überwacht die Feuchtigkeitsbedingungen im AMS, berechnet Taupunkt und
Kondensationsrisiko (Magnus-Formel) und gibt gezielte Trocknungsempfehlungen
für hygroskopische Filamente (PA, TPU, PVA, PETG) vor dem Druckstart aus.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Hygroskopie-Grenzwerte und Trocknungsempfehlungen je Material
DRYING_PROFILES: dict[str, dict[str, Any]] = {
    "PA": {
        "max_humidity_pct": 20.0,
        "drying_temp_c": 80,
        "drying_hours": 8,
        "hygroscopic_class": "EXTREME",
        "defect_risk": "Dampfblasen, Delamination, raue Oberfläche, verstopfte Düse",
    },
    "PA-CF": {
        "max_humidity_pct": 20.0,
        "drying_temp_c": 80,
        "drying_hours": 8,
        "hygroscopic_class": "EXTREME",
        "defect_risk": "Poröse Wände, spröde Schichthaftung, Faserbrüchigkeit",
    },
    "PA-GF": {
        "max_humidity_pct": 20.0,
        "drying_temp_c": 80,
        "drying_hours": 8,
        "hygroscopic_class": "EXTREME",
        "defect_risk": "Massiver Festigkeitsverlust durch Feuchtigkeit an Glasfaserübergängen",
    },
    "TPU": {
        "max_humidity_pct": 25.0,
        "drying_temp_c": 55,
        "drying_hours": 6,
        "hygroscopic_class": "HIGH",
        "defect_risk": "Starkes Stringing, Knistern an der Düse, Schaumbildung",
    },
    "PVA": {
        "max_humidity_pct": 15.0,
        "drying_temp_c": 50,
        "drying_hours": 10,
        "hygroscopic_class": "CRITICAL",
        "defect_risk": "Klebriges Filament, Verstopfung im Extruder, Auflösung im AMS",
    },
    "BVOH": {
        "max_humidity_pct": 15.0,
        "drying_temp_c": 50,
        "drying_hours": 10,
        "hygroscopic_class": "CRITICAL",
        "defect_risk": "Weichwerden im AMS-Feeder, Blockade",
    },
    "PETG": {
        "max_humidity_pct": 35.0,
        "drying_temp_c": 65,
        "drying_hours": 6,
        "hygroscopic_class": "MODERATE",
        "defect_risk": "Stringing, Fadenbildung, verminderte Glanztiefe",
    },
    "PETG-CF": {
        "max_humidity_pct": 30.0,
        "drying_temp_c": 65,
        "drying_hours": 6,
        "hygroscopic_class": "MODERATE",
        "defect_risk": "Fadenbildung, Schichtunterextrusion",
    },
    "PC": {
        "max_humidity_pct": 20.0,
        "drying_temp_c": 80,
        "drying_hours": 8,
        "hygroscopic_class": "HIGH",
        "defect_risk": "Blasenbildung, innere Spannungsrisse",
    },
    "ABS": {
        "max_humidity_pct": 35.0,
        "drying_temp_c": 70,
        "drying_hours": 5,
        "hygroscopic_class": "LOW",
        "defect_risk": "Leichtes Knistern bei langer Lagerung",
    },
    "ASA": {
        "max_humidity_pct": 35.0,
        "drying_temp_c": 70,
        "drying_hours": 5,
        "hygroscopic_class": "LOW",
        "defect_risk": "Geringes Risiko, vor UV-Einsatz Trocknung empfohlen",
    },
    "PLA": {
        "max_humidity_pct": 45.0,
        "drying_temp_c": 45,
        "drying_hours": 4,
        "hygroscopic_class": "LOW",
        "defect_risk": "Versprödung (Bruch im PTFE-Schlauch)",
    },
}


def calculate_dew_point(temp_c: float, humidity_pct: float) -> float:
    """Berechnet den Taupunkt in °C nach der Magnus-Formel."""
    t = float(temp_c)
    rh = max(0.1, min(100.0, float(humidity_pct)))
    # Magnus-Koeffizienten nach Arden Buck
    a = 17.625
    b = 243.04
    alpha = ((a * t) / (b + t)) + math.log(rh / 100.0)
    dew_point = (b * alpha) / (a - alpha)
    return round(dew_point, 2)


def get_drying_profile(filament_type: str) -> dict[str, Any]:
    """Sucht das passende Trocknungsprofil für einen Filamenttyp."""
    ft = (filament_type or "").upper().strip()
    for key in sorted(DRYING_PROFILES.keys(), key=len, reverse=True):
        if key in ft:
            return {"matched_key": key, **DRYING_PROFILES[key]}
    # Fallback für unbekanntes Standardmaterial
    return {
        "matched_key": "DEFAULT",
        "max_humidity_pct": 40.0,
        "drying_temp_c": 50,
        "drying_hours": 4,
        "hygroscopic_class": "MODERATE",
        "defect_risk": "Stringing oder unsaubere Extrusion bei Nässe",
    }


def evaluate_ams_humidity(
    temp_c: float,
    humidity_pct: float,
    loaded_filaments: list[str] | None = None,
) -> dict[str, Any]:
    """Analysiert AMS-Feuchtigkeitswerte, Taupunkt und Trocknungsbedarf der Spulen."""
    dew_point = calculate_dew_point(temp_c, humidity_pct)
    condensation_margin = round(temp_c - dew_point, 2)
    filaments = loaded_filaments or []

    spool_evaluations = []
    overall_drying_recommended = False
    critical_spools_count = 0

    for idx, mat in enumerate(filaments):
        profile = get_drying_profile(mat)
        max_h = float(profile["max_humidity_pct"])
        is_too_wet = (humidity_pct > max_h)

        status = "DRY"
        if humidity_pct > max_h + 15.0:
            status = "CRITICAL_WET"
            critical_spools_count += 1
            overall_drying_recommended = True
        elif is_too_wet:
            status = "NEEDS_DRYING"
            overall_drying_recommended = True

        spool_evaluations.append({
            "slot_index": idx,
            "filament_type": mat,
            "hygroscopic_class": profile["hygroscopic_class"],
            "max_allowed_humidity_pct": max_h,
            "current_humidity_pct": humidity_pct,
            "status": status,
            "recommended_drying_temp_c": profile["drying_temp_c"],
            "recommended_drying_hours": profile["drying_hours"],
            "defect_risk": profile["defect_risk"],
        })

    return {
        "ambient_temp_c": round(temp_c, 1),
        "humidity_pct": round(humidity_pct, 1),
        "dew_point_c": dew_point,
        "condensation_margin_c": condensation_margin,
        "condensation_risk": condensation_margin <= 3.0,
        "overall_drying_recommended": overall_drying_recommended,
        "critical_spools_count": critical_spools_count,
        "spools": spool_evaluations,
    }
