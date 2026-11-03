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
import math
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

# Faktor für explizit als abrasiv gekennzeichnete Drucke ohne bekanntes Material:
# konservativ zwischen WOOD (2.0) und CF-Staubschutz, aber nicht max(aller) —
# ein PLA-Druck mit Abrasiv-Hinweis ist kein PLA-CF-Druck.
DEFAULT_ABRASIVE_MULTIPLIER = 3.0


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


def get_wear_overview(printer_id: str = "default") -> dict[str, Any]:
    """Erzeugt eine detaillierte Übersicht über den Gesundheitszustand aller Verschleißteile."""
    with _lock:
        return _overview_from_data(_read_data(), printer_id)


def _overview_from_data(data: dict[str, Any], printer_id: str = "default") -> dict[str, Any]:
    """Baut die Gesundheitsübersicht aus einem beladenen Datendict.

    Reine Funktion, damit ``record_print_usage`` Vorher/Nachher-Vergleiche
    anstellen kann, ohne den Schreib-/Lese-Lock erneut anzufassen
    (``threading.Lock`` ist nicht reentrant).
    """
    printer_data = data.get(printer_id, {})
    current: dict[str, Any] = {
        "nozzle_hours": float(printer_data.get("nozzle_hours", 0.0)),
        "ptfe_hours": float(printer_data.get("ptfe_hours", 0.0)),
        "z_spindle_hours": float(printer_data.get("z_spindle_hours", 0.0)),
        "steel_rods_hours": float(printer_data.get("steel_rods_hours", 0.0)),
        "carbon_filter_hours": float(printer_data.get("carbon_filter_hours", 0.0)),
        "nozzle_type": printer_data.get("nozzle_type", "hardened_steel"),
    }
    nozzle_type = current["nozzle_type"]
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


def record_print_usage(
    printer_id: str = "default",
    print_time_hours: float = 0.5,
    filament_type: str = "PLA",
    is_abrasive: bool = False,
) -> dict[str, Any]:
    """Bucht Druckstunden auf die Verschleißkomponenten auf.

    Der Düsenverschliss wird über den Abrasivitäts-Multiplikator geführt: passt
    das Material auf ein bekanntes Muster (PLA-CF, GLOW, …), zählt dessen Faktor;
    ist der Druck nur pauschal als abrasiv gekennzeichnet, greift
    ``DEFAULT_ABRASIVE_MULTIPLIER``. Defekte Eingaben (NaN/inf, negative Zeit)
    werden abgewiesen, statt den Zähler korrumpieren zu können.

    Schiebt die Buchung einen Baustein über eine Schwelle (OK → WARN/CRITICAL),
    wird zusätzlich das ``maintenance.wear_alert``-Event verteilt — nur bei
    Statuswechsel, nicht bei jedem Druck.
    """
    fil_upper = str(filament_type or "PLA").upper()

    try:
        hours = float(print_time_hours)
    except (TypeError, ValueError):
        hours = 0.0
    if not math.isfinite(hours) or hours < 0.0:
        logger.warning("Verschleißbuchung ignoriert unbrauchbare Druckdauer %r.", print_time_hours)
        hours = 0.0

    mult = 1.0
    matched = False
    for pattern, m in ABRASIVE_MULTIPLIERS.items():
        if pattern in fil_upper:
            mult = max(mult, m)
            matched = True
    if is_abrasive and not matched:
        mult = max(mult, DEFAULT_ABRASIVE_MULTIPLIER)

    alert_payload: dict[str, Any] | None = None
    with _lock:
        data = _read_data()
        previous_overall = _overview_from_data(data, printer_id)["overall_status"]

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

        new_overview = _overview_from_data(data, printer_id)
        if (
            hours > 0
            and previous_overall != new_overview["overall_status"]
            and new_overview["overall_status"] in ("WARN", "CRITICAL")
        ):
            alert_payload = {
                "printer_id": printer_id,
                "overall_status": new_overview["overall_status"],
                "reason": "Verschleißgrenze durch Druckbetrieb erreicht",
                "components": [
                    {
                        "id": c["id"],
                        "name": c["name"],
                        "status": c["status"],
                        "used_hours": c["used_hours"],
                        "remaining_hours": c["remaining_hours"],
                        "health_percent": c["health_percent"],
                    }
                    for c in new_overview["components"]
                    if c["status"] != "OK"
                ],
            }

    if alert_payload is not None:
        try:
            from backend.app.services import outbound_webhooks

            outbound_webhooks.dispatch_event("maintenance.wear_alert", alert_payload)
        except Exception as exc:  # Alarm ist Zusatznutzen; Buchung darf nicht brechen
            logger.warning("wear_alert-Webhook fehlgeschlagen: %s", exc)

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


def get_printer_wear(printer_id: str = "default") -> dict[str, Any]:
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
