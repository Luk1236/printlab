"""Nachkalkulation: Ist-Kosten der mit einem Angebot verknüpften Druckjobs gegen den Angebotspreis.

Material und Energie kommen aus dem Archiv (``cost``, ``energy_cost``); fehlt ein Wert, wird er wie beim Angebot aus Gramm,
Druckdauer und den Sätzen der Einstellungen geschätzt. Die Arbeitszeit lässt sich nicht messen und bleibt wie im Angebot.
Zusätzliche Positionen (Versand usw.) zählen zum Erlös, aber nicht zu den Ist-Kosten.
"""

from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def compute(quote: dict[str, Any], archives: list[dict[str, Any]], rates: dict[str, float]) -> dict[str, Any]:
    """``rates``: ``material_per_kg``, ``energy_per_kwh``, ``power_watts``; ``archives``: Zeilen aus dem Archiv."""
    lines: list[dict[str, Any]] = []
    grams_total = seconds_total = material_total = energy_total = 0.0
    for archive in archives:
        grams = _num(archive.get("filament_used_grams")) or 0.0
        seconds = _num(archive.get("print_time_seconds")) or 0.0
        material = _num(archive.get("cost"))
        estimated_material = material is None
        if material is None:
            material = grams / 1000.0 * rates.get("material_per_kg", 0.0)
        energy = _num(archive.get("energy_cost"))
        estimated_energy = energy is None
        if energy is None:
            energy = seconds / 3600.0 * rates.get("power_watts", 0.0) / 1000.0 * rates.get("energy_per_kwh", 0.0)
        grams_total += grams
        seconds_total += seconds
        material_total += material
        energy_total += energy
        lines.append(
            {
                "archive_id": archive.get("id"),
                "filename": str(archive.get("filename") or ""),
                "status": str(archive.get("status") or ""),
                "grams": round(grams, 1),
                "minutes": round(seconds / 60.0, 1),
                "material": round(material, 2),
                "energy": round(energy, 2),
                "estimated": estimated_material or estimated_energy,
            }
        )
    labor_quoted = _num(quote.get("labor")) or 0.0
    work_minutes = _num(quote.get("work_minutes"))
    if work_minutes is not None and work_minutes > 0:
        # Zeitbuchung: die gemessene Arbeitszeit ersetzt den Angebotsansatz
        labor = work_minutes / 60.0 * float(rates.get("labor_rate_per_hour", 0.0) or 0.0)
        labor_measured = True
    else:
        labor = labor_quoted
        labor_measured = False
    quoted_cost = _num(quote.get("subtotal")) or 0.0
    revenue = _num(quote.get("total")) or 0.0
    actual_cost = material_total + energy_total + labor
    return {
        "quote_id": quote.get("id"),
        "currency": quote.get("currency", "EUR"),
        "linked": len(lines),
        "lines": lines,
        "grams": round(grams_total, 1),
        "minutes": round(seconds_total / 60.0, 1),
        "material": round(material_total, 2),
        "energy": round(energy_total, 2),
        "labor": round(labor, 2),
        "labor_measured": labor_measured,
        "work_minutes": work_minutes,
        "actual_cost": round(actual_cost, 2),
        "quoted_cost": round(quoted_cost, 2),
        "deviation": round(actual_cost - quoted_cost, 2),
        "revenue": round(revenue, 2),
        "profit": round(revenue - actual_cost, 2),
    }
