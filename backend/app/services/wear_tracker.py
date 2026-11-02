"""Verschleißteil- und Predictive-Maintenance-Tracker für Bambu Lab P2S.

Erfasst präzise Betriebsstunden und berechnet die Abnutzung von Verschleißteilen:
- Düse (Messing vs. gehärteter Stahl mit Abrasiv-Faktor für Carbon/Glow-Filamente)
- PTFE-Führungsschläuche (AMS & Druckkopf)
- Z-Gewindespindeln (Schmierintervall)
- P2S-Stahlführungsstangen (Reinigungs- & Ölintervall)
- Aktivkohlefilter (Filterabnutzung bei ABS/ASA/PA)
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

WEAR_FILE = settings.base_dir / "wear_tracking.json"
_lock = threading.Lock()

# Nenn-Lebensdauern in Betriebsstunden
LIFESPANS = {
    "nozzle_brass": 250.0,
    "nozzle_hardened_steel": 1500.0,
    "ptfe_tubes": 800.0,
    "z_leadscrews": 100.0,
    "steel_rods": 75.0,
    "carbon_filter": 300.0,
}

# Abrasivitäts-Multiplikatoren nach Material
ABRASIVE_MULTIPLIERS = {
    "PLA-CF": 5.0,
    "PETG-CF": 5.0,
    "PA-CF": 6.0,
    "GLOW": 4.0,
    "WOOD": 2.0,
}


def _read_data() -> dict[str, Any]:
    if not WEAR_FILE.is_file():
        return {}
    try:
        return json.loads(WEAR_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Konnte wear_tracking.json nicht laden: %s", exc)
        return {}


def _write_data(data: dict[str, Any]) -> None:
    try:
        WEAR_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = WEAR_FILE.with_name(WEAR_FILE.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(WEAR_FILE)
    except Exception as exc:
        logger.error("Fehler beim Speichern von wear_tracking.json: %s", exc)


def get_printer_wear(printer_id: str = "default") -> dict[str, float]:
    """Liefert die akkumulierten Betriebsstunden der Komponenten für den Drucker."""
    with _lock:
        data = _read_data()
        printer_data = data.get(printer_id, {})
        return {
            "nozzle_hours": float(printer_data.get("nozzle_hours", 0.0)),
            "ptfe_hours": float(printer_data.get("ptfe_hours", 0.0)),
            "z_spindle_hours": float(printer_data.get("z_spindle_hours", 0.0)),
            "steel_rods_hours": float(printer_data.get("steel_rods_hours", 0.0)),
            "carbon_filter_hours": float(printer_data.get("carbon_filter_hours", 0.0)),
            "nozzle_type": printer_data.get("nozzle_type", "hardened_steel"),
        }


def record_print_usage(
    printer_id: str = "default",
    print_time_hours: float = 0.5,
    filament_type: str = "PLA",
    is_abrasive: bool = False,
) -> dict[str, Any]:
    """Bucht Druckstunden auf die Verschleißkomponenten auf."""
    hours = max(0.0, float(print_time_hours))
    fil_upper = filament_type.upper()

    mult = 1.0
    for pattern, m in ABRASIVE_MULTIPLIERS.items():
        if pattern in fil_upper or is_abrasive:
            mult = max(mult, m)

    with _lock:
        data = _read_data()
        if printer_id not in data:
            data[printer_id] = {
                "nozzle_hours": 0.0,
                "ptfe_hours": 0.0,
                "z_spindle_hours": 0.0,
                "steel_rods_hours": 0.0,
                "carbon_filter_hours": 0.0,
                "nozzle_type": "hardened_steel",
            }
        p = data[printer_id]

        # Düsenabnutzung mit Abrasiv-Faktor
        p["nozzle_hours"] = round(p.get("nozzle_hours", 0.0) + (hours * mult), 2)
        p["ptfe_hours"] = round(p.get("ptfe_hours", 0.0) + hours, 2)
        p["z_spindle_hours"] = round(p.get("z_spindle_hours", 0.0) + hours, 2)
        p["steel_rods_hours"] = round(p.get("steel_rods_hours", 0.0) + hours, 2)

        # Aktivkohlefilter nur bei ABS/ASA/PA belasten
        if any(voc in fil_upper for voc in ("ABS", "ASA", "PA", "NYLON")):
            p["carbon_filter_hours"] = round(p.get("carbon_filter_hours", 0.0) + hours, 2)

        _write_data(data)

    return get_wear_overview(printer_id)


def reset_wear_component(printer_id: str = "default", component_key: str = "nozzle") -> bool:
    """Setzt den Zähler einer gewarteten oder getauschten Komponente zurück."""
    with _lock:
        data = _read_data()
        if printer_id not in data:
            return False
        p = data[printer_id]
        key_map = {
            "nozzle": "nozzle_hours",
            "ptfe": "ptfe_hours",
            "z_spindle": "z_spindle_hours",
            "steel_rods": "steel_rods_hours",
            "carbon_filter": "carbon_filter_hours",
        }
        field = key_map.get(component_key)
        if field and field in p:
            p[field] = 0.0
            _write_data(data)
            return True
        return False


def get_wear_overview(printer_id: str = "default") -> dict[str, Any]:
    """Erzeugt eine detaillierte Übersicht über den Gesundheitszustand aller Verschleißteile."""
    current = get_printer_wear(printer_id)
    nozzle_type = current.get("nozzle_type", "hardened_steel")
    nozzle_limit = LIFESPANS["nozzle_hardened_steel"] if nozzle_type == "hardened_steel" else LIFESPANS["nozzle_brass"]

    components = [
        {
            "id": "nozzle",
            "name": f"Druckdüse ({'Gehärteter Stahl' if nozzle_type == 'hardened_steel' else 'Messing'})",
            "used_hours": current["nozzle_hours"],
            "max_hours": nozzle_limit,
            "unit": "h",
        },
        {
            "id": "ptfe",
            "name": "PTFE-Führungsschläuche",
            "used_hours": current["ptfe_hours"],
            "max_hours": LIFESPANS["ptfe_tubes"],
            "unit": "h",
        },
        {
            "id": "z_spindle",
            "name": "Z-Gewindespindeln (Schmierung)",
            "used_hours": current["z_spindle_hours"],
            "max_hours": LIFESPANS["z_leadscrews"],
            "unit": "h",
        },
        {
            "id": "steel_rods",
            "name": "Stahlführungsstangen (Reinigung & Öl)",
            "used_hours": current["steel_rods_hours"],
            "max_hours": LIFESPANS["steel_rods"],
            "unit": "h",
        },
        {
            "id": "carbon_filter",
            "name": "Aktivkohlefilter (VOC/Filterzeit)",
            "used_hours": current["carbon_filter_hours"],
            "max_hours": LIFESPANS["carbon_filter"],
            "unit": "h",
        },
    ]

    overview: list[dict[str, Any]] = []
    has_warning = False
    has_critical = False

    for c in components:
        ratio = min(1.0, max(0.0, c["used_hours"] / c["max_hours"]))
        health_pct = round((1.0 - ratio) * 100.0, 1)

        if health_pct <= 5.0:
            status = "CRITICAL"
            has_critical = True
        elif health_pct <= 20.0:
            status = "WARN"
            has_warning = True
        else:
            status = "OK"

        overview.append(
            {
                "id": c["id"],
                "name": c["name"],
                "used_hours": c["used_hours"],
                "remaining_hours": round(max(0.0, c["max_hours"] - c["used_hours"]), 1),
                "max_hours": c["max_hours"],
                "health_percent": health_pct,
                "status": status,
            }
        )

    overall_status = "CRITICAL" if has_critical else ("WARN" if has_warning else "OK")

    return {
        "printer_id": printer_id,
        "overall_status": overall_status,
        "components": overview,
    }
