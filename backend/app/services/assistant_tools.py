"""Agentic Tool-Calling Engine für den lokalen KI-Assistenten.

Ermöglicht dem KI-Assistenten, nicht nur passiv zu antworten, sondern strukturierte
Aktionen (Function Calls) vorzuschlagen und auszuführen:
- Status & Telemetrie abfragen
- Not-Aus & Sicherheitsbefehle ausführen
- Temperaturen (Bett/Düse) steuern
- HMS-Wissensdatenbank durchsuchen
- Verschleiß- und Wartungsstatus prüfen
- Sofortkalkulation für Druckaufträge berechnen
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Registrierte Funktions-Definitionen im standardisierten OpenAI/Ollama-Format
AVAILABLE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_printer_status",
            "description": "Liest den aktuellen Zustand, Temperaturen (Düse/Bett), Druckfortschritt und Fehlercodes des Druckers aus.",
            "parameters": {
                "type": "object",
                "properties": {
                    "printer_id": {
                        "type": "string",
                        "description": "Optionale ID des Druckers (Standard: erster verbundener Drucker).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "emergency_stop",
            "description": "Löst sofort einen Hardware-Not-Halt aus, bricht alle Bewegungen ab und stoppt den Druck.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Begründung für den Not-Halt (z. B. 'Fehldruck', 'Kollisionsgefahr').",
                    }
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_temperatures",
            "description": "Setzt die Ziel-Temperaturen für das Druckbett und/oder die Düse (Vorheizen).",
            "parameters": {
                "type": "object",
                "properties": {
                    "bed_temp": {
                        "type": "number",
                        "description": "Zieltemperatur des Druckbetts in °C (z. B. 55 für PLA, 70 für PETG, 0 zum Abkühlen).",
                    },
                    "nozzle_temp": {
                        "type": "number",
                        "description": "Zieltemperatur der Düse in °C (z. B. 210 für PLA, 0 zum Abkühlen).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hms_knowledge",
            "description": "Durchsucht die Bambu Lab HMS-Fehler- und Wartungsdatenbank nach Lösungen für Fehlercodes oder Symptome.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff oder HMS-Fehlercode (z. B. '0300-0100', 'Düse verstopft', 'Bett haftet nicht').",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wear_status",
            "description": "Prüft die Restlebensdauer und den Verschleißzustand von Düse, PTFE-Schläuchen, Z-Spindeln und Kohlefilter.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_quick_quote",
            "description": "Berechnet schnell die kalkulatorischen Kosten und den Kundenpreis für einen Druckauftrag basierend auf Zeit und Materialgewicht.",
            "parameters": {
                "type": "object",
                "properties": {
                    "print_time_hours": {
                        "type": "number",
                        "description": "Geschätzte Druckdauer in Stunden.",
                    },
                    "filament_grams": {
                        "type": "number",
                        "description": "Filamentverbrauch in Gramm.",
                    },
                    "material": {
                        "type": "string",
                        "description": "Filament-Typ (z. B. 'PLA', 'PETG', 'ABS', 'TPU').",
                    },
                },
                "required": ["print_time_hours", "filament_grams"],
            },
        },
    },
]


def _emergency_stop_all(reason: str) -> dict[str, Any]:
    """Not-Halt auf allen bereits laufenden Hardware-Instanzen (je Drucker + gemeinsame Altinstanz).

    Wichtig: keine neue ``HardwareExtension`` anlegen — die wäre nicht die Instanz, die die Mechanik steuert,
    und der Not-Halt liefe ins Leere. Erfolg wird nur gemeldet, wenn mindestens eine Instanz ihn bestätigt.
    """
    from backend.app.services import hardware_extension as hwmod

    instances = list(hwmod._per_printer.values())
    if hwmod._hardware is not None:
        instances.append(hwmod._hardware)
    if not instances:
        instances.append(hwmod.get_hardware())

    confirmed, errors = 0, []
    for hw in instances:
        try:
            ok, msg = hw.emergency_stop()
        except Exception as exc:  # ein defekter Kanal darf die anderen nicht verhindern
            ok, msg = False, f"{type(exc).__name__}: {exc}"
        if ok:
            confirmed += 1
        else:
            errors.append(msg)

    logger.warning("KI-Not-Halt (%s): %d/%d bestätigt", reason, confirmed, len(instances))
    if confirmed == 0:
        return {
            "status": "error",
            "action": "EMERGENCY_STOP_FAILED",
            "message": f"Not-Halt NICHT bestätigt ({'; '.join(errors) or 'keine Rückmeldung'}). Sofort Hand-Not-Aus betätigen!",
        }
    return {
        "status": "success",
        "action": "EMERGENCY_STOP_TRIGGERED",
        "message": f"Not-Halt ausgelöst ({confirmed}/{len(instances)} Kanäle bestätigt): {reason}",
        "errors": errors,
    }


def get_tool_definitions() -> list[dict[str, Any]]:
    """Gibt die Liste aller verfügbaren Werkzeugdefinitionen für den LLM-Aufruf zurück."""
    return AVAILABLE_TOOLS


def execute_tool(tool_name: str, arguments: dict[str, Any] | str) -> dict[str, Any]:
    """Führt ein vom KI-Assistenten aufgerufenes Werkzeug sicher aus und liefert das Ergebnis zurück."""
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            args = {}
    else:
        args = arguments or {}

    logger.info("KI-Tool aufgerufen: '%s' mit Argumenten: %s", tool_name, args)

    if tool_name == "get_printer_status":
        # Noch nicht an printer_manager angebunden: lieber ehrlich "nicht verfügbar" als erfundene Messwerte,
        # auf die das Modell dann Entscheidungen stützt.
        return {
            "status": "unavailable",
            "message": "Live-Telemetrie ist für den Assistenten noch nicht angebunden. Bitte Druckerkarte prüfen.",
        }

    elif tool_name == "emergency_stop":
        reason = str(args.get("reason") or "Not-Halt durch KI-Assistent angefordert")
        return _emergency_stop_all(reason)

    elif tool_name == "set_temperatures":
        # Bewusst nicht ausgeführt: Heizbefehle brauchen eine Bestätigung durch einen Menschen und eine
        # MQTT-Anbindung; vorher keine Erfolgsmeldung vortäuschen.
        return {
            "status": "unavailable",
            "message": "Temperaturen kann der Assistent nicht setzen. Bitte am Drucker oder in der Druckerkarte einstellen.",
        }

    elif tool_name == "search_hms_knowledge":
        query = str(args.get("query", ""))
        from backend.app.services.hms_knowledge import search_knowledge

        results = search_knowledge(query, limit=3)
        return {
            "status": "success",
            "query": query,
            "matches_found": len(results),
            "results": results,
        }

    elif tool_name == "get_wear_status":
        from backend.app.services.wear_tracker import get_wear_overview

        overview = get_wear_overview()
        return {
            "status": "success",
            "wear_overview": overview,
        }

    elif tool_name == "calculate_quick_quote":
        hours = float(args.get("print_time_hours", 1.0))
        grams = float(args.get("filament_grams", 50.0))
        material = str(args.get("material", "PLA")).upper()

        cost_per_kg = 25.0 if material in ("PLA", "PETG") else 35.0
        mat_cost = (grams / 1000.0) * cost_per_kg
        machine_hourly_rate = 6.50
        mach_cost = hours * machine_hourly_rate
        net_total = round(mat_cost + mach_cost + 2.50, 2)  # 2.50 Rüstkosten
        vat = round(net_total * 0.19, 2)
        gross_total = round(net_total + vat, 2)

        return {
            "status": "success",
            "calculation": {
                "print_time_hours": hours,
                "filament_grams": grams,
                "material": material,
                "material_cost": round(mat_cost, 2),
                "machine_cost": round(mach_cost, 2),
                "net_total_eur": net_total,
                "vat_19_eur": vat,
                "gross_total_eur": gross_total,
            },
        }

    else:
        return {
            "status": "error",
            "message": f"Unbekanntes Werkzeug: '{tool_name}'",
        }
