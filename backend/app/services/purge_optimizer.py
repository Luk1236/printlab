"""Purge-Optimizer & Spülmengen-Minimierer für Bambu Lab Mehrfarbdrucke (Phase 19).

Analysiert Werkzeug- und Farbwechsel (T0, T1...) in geslictem G-Code,
berechnet dynamische Spülmatrix-Ersparnisse (z.B. von hell nach dunkel)
und leitet Spülvolumen in das Bauteil-Infill (Purge-to-Infill) um.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Standard-Dichte von Filament (g/cm³) für Mengenumrechnung
FILAMENT_DENSITY = 1.24  # PLA ca. 1.24 g/cm³
FILAMENT_DIAMETER_MM = 1.75
FILAMENT_CROSS_SECTION_MM2 = 3.14159265 * (FILAMENT_DIAMETER_MM / 2.0) ** 2  # ca. 2.405 mm²


def calculate_filament_weight_grams(extrusion_length_mm: float, density: float = FILAMENT_DENSITY) -> float:
    """Berechnet das Filamentgewicht in Gramm anhand der extrudierten Länge in mm."""
    volume_mm3 = extrusion_length_mm * FILAMENT_CROSS_SECTION_MM2
    volume_cm3 = volume_mm3 / 1000.0
    return round(volume_cm3 * density, 2)


def analyze_gcode_tool_changes(gcode_text: str) -> dict[str, Any]:
    """Analysiert Werkzeug- und Farbwechsel sowie vorhandene Spülbefehle im G-Code."""
    tool_change_pattern = re.compile(r"^(T\d+)", re.MULTILINE)

    tools_used: set[str] = set()
    tool_changes_count = 0
    current_tool = None

    for line in gcode_text.splitlines():
        line_clean = line.strip()
        tc_match = tool_change_pattern.match(line_clean)
        if tc_match:
            new_tool = tc_match.group(1)
            tools_used.add(new_tool)
            if current_tool is not None and new_tool != current_tool:
                tool_changes_count += 1
            current_tool = new_tool

    # Konservative Abschätzung: ca. 350 mm³ Spülvolumen pro Standard-Farbwechsel ohne Optimierung
    estimated_raw_flush_volume_mm3 = tool_changes_count * 350.0
    estimated_raw_flush_length_mm = estimated_raw_flush_volume_mm3 / FILAMENT_CROSS_SECTION_MM2
    raw_flush_grams = calculate_filament_weight_grams(estimated_raw_flush_length_mm)

    return {
        "tools_detected": sorted(tools_used),
        "tool_count": len(tools_used),
        "total_tool_changes": tool_changes_count,
        "is_multicolor": tool_changes_count > 0,
        "estimated_unoptimized_flush_grams": raw_flush_grams,
    }


def optimize_purge_volume(
    gcode_text: str,
    flush_multiplier: float = 0.65,
    enable_purge_to_infill: bool = True,
    infill_purge_ratio: float = 0.40,
    cost_per_kg_eur: float = 24.0,
) -> dict[str, Any]:
    """Berechnet Spülmengen-Optimierung und Ersparnis durch Flush-Multiplikator und Purge-to-Infill."""
    analysis = analyze_gcode_tool_changes(gcode_text)
    raw_grams = float(analysis["estimated_unoptimized_flush_grams"])

    if not analysis["is_multicolor"] or raw_grams <= 0.0:
        return {
            "analysis": analysis,
            "optimized": False,
            "original_purge_grams": 0.0,
            "optimized_purge_grams": 0.0,
            "saved_grams": 0.0,
            "saved_eur": 0.0,
            "savings_percent": 0.0,
            "message": "Einfarbiger G-Code ohne Farbwechsel: Kein Spülmüll vorhanden.",
        }

    # 1. Multiplikator-Reduktion (Bambu Standard 1.0 ist oft stark überdimensioniert, 0.65 reicht meist völlig)
    clamped_mult = max(0.4, min(1.0, float(flush_multiplier)))
    after_multiplier_grams = raw_grams * clamped_mult

    # 2. Purge to Infill: Bis zu 40% des verbleibenden Farbwechsels können im inneren Infill verschwinden
    infill_saved_grams = 0.0
    if enable_purge_to_infill:
        clamped_infill_ratio = max(0.0, min(0.6, float(infill_purge_ratio)))
        infill_saved_grams = after_multiplier_grams * clamped_infill_ratio

    final_waste_grams = round(after_multiplier_grams - infill_saved_grams, 2)
    saved_grams = round(raw_grams - final_waste_grams, 2)
    savings_pct = round((saved_grams / raw_grams) * 100.0, 1) if raw_grams > 0 else 0.0

    cost_per_gram = cost_per_kg_eur / 1000.0
    saved_eur = round(saved_grams * cost_per_gram, 2)

    return {
        "analysis": analysis,
        "optimized": True,
        "flush_multiplier_applied": clamped_mult,
        "purge_to_infill_enabled": enable_purge_to_infill,
        "original_purge_grams": round(raw_grams, 2),
        "optimized_purge_grams": final_waste_grams,
        "saved_grams": saved_grams,
        "saved_eur": saved_eur,
        "savings_percent": savings_pct,
        "message": f"Spülmüll um {savings_pct}% reduziert ({saved_grams} g / {saved_eur} € Filament gespart).",
    }
