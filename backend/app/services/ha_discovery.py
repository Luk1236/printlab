"""Home Assistant MQTT Discovery Engine für PrintLab.

Veröffentlicht Sensoren, Schalter und Status-Entitäten automatisch im Home Assistant
MQTT Discovery Standardformat ('homeassistant/<component>/printlab_<id>/<sensor>/config'),
sodass PrintLab ohne manuelle YAML-Konfiguration direkt in Home Assistant erscheint.
"""

from __future__ import annotations

import json
from typing import Any

DISCOVERY_PREFIX = "homeassistant"


def build_device_info(printer_id: str, printer_name: str = "Bambu Lab P2S") -> dict[str, Any]:
    """Erzeugt den gemeinsamen Home Assistant 'device'-Block für diesen Drucker."""
    safe_id = str(printer_id or "default").replace(" ", "_").lower()
    return {
        "identifiers": [f"printlab_{safe_id}"],
        "name": f"PrintLab {printer_name}",
        "model": "Bambu Lab P2S / PrintLab",
        "manufacturer": "PrintLab",
        "sw_version": "1.27.0",
    }


def build_discovery_payloads(
    printer_id: str,
    printer_name: str = "Bambu Lab P2S",
    base_topic: str = "printlab",
) -> list[dict[str, Any]]:
    """Erzeugt alle Home Assistant MQTT Discovery Konfigurationen für Sensoren und Schalter.

    Liefert eine Liste von Dictionaries mit 'topic' und 'payload' (als JSON-Dict).
    """
    safe_id = str(printer_id or "default").replace(" ", "_").lower()
    device = build_device_info(printer_id, printer_name)
    state_topic = f"{base_topic}/printer/{safe_id}/state"
    cmd_topic = f"{base_topic}/printer/{safe_id}/command"

    entities = [
        # 1. Druckstatus Sensor
        {
            "component": "sensor",
            "object_id": "print_state",
            "config": {
                "name": f"{printer_name} Druckstatus",
                "state_topic": state_topic,
                "value_template": "{{ value_json.state }}",
                "unique_id": f"printlab_{safe_id}_print_state",
                "icon": "mdi:printer-3d",
                "device": device,
            },
        },
        # 2. Düsentemperatur Sensor
        {
            "component": "sensor",
            "object_id": "nozzle_temperature",
            "config": {
                "name": f"{printer_name} Düsentemperatur",
                "state_topic": state_topic,
                "value_template": "{{ value_json.nozzle_temp | round(1) }}",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "state_class": "measurement",
                "unique_id": f"printlab_{safe_id}_nozzle_temp",
                "device": device,
            },
        },
        # 3. Betttemperatur Sensor
        {
            "component": "sensor",
            "object_id": "bed_temperature",
            "config": {
                "name": f"{printer_name} Betttemperatur",
                "state_topic": state_topic,
                "value_template": "{{ value_json.bed_temp | round(1) }}",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "state_class": "measurement",
                "unique_id": f"printlab_{safe_id}_bed_temp",
                "device": device,
            },
        },
        # 4. Druckfortschritt Sensor (%)
        {
            "component": "sensor",
            "object_id": "print_progress",
            "config": {
                "name": f"{printer_name} Druckfortschritt",
                "state_topic": state_topic,
                "value_template": "{{ value_json.progress | default(0) | int }}",
                "unit_of_measurement": "%",
                "icon": "mdi:percent",
                "state_class": "measurement",
                "unique_id": f"printlab_{safe_id}_progress",
                "device": device,
            },
        },
        # 5. Restzeit Sensor (Minuten)
        {
            "component": "sensor",
            "object_id": "remaining_time",
            "config": {
                "name": f"{printer_name} Restzeit",
                "state_topic": state_topic,
                "value_template": "{{ value_json.remaining_minutes | default(0) | int }}",
                "unit_of_measurement": "min",
                "icon": "mdi:timer-sand",
                "unique_id": f"printlab_{safe_id}_remaining_time",
                "device": device,
            },
        },
        # 6. Schichtzähler Sensor (Layer)
        {
            "component": "sensor",
            "object_id": "current_layer",
            "config": {
                "name": f"{printer_name} Aktuelle Schicht",
                "state_topic": state_topic,
                "value_template": "{{ value_json.current_layer | default(0) }} / {{ value_json.total_layers | default(0) }}",
                "icon": "mdi:layers-triple",
                "unique_id": f"printlab_{safe_id}_layer",
                "device": device,
            },
        },
        # 7. Not-Halt Schalter
        {
            "component": "switch",
            "object_id": "emergency_stop",
            "config": {
                "name": f"{printer_name} Not-Halt",
                "state_topic": state_topic,
                "value_template": "{{ 'ON' if value_json.emergency_stop else 'OFF' }}",
                "command_topic": f"{cmd_topic}/emergency_stop",
                "payload_on": "STOP",
                "payload_off": "RESET",
                "icon": "mdi:alert-octagon",
                "unique_id": f"printlab_{safe_id}_emergency_stop",
                "device": device,
            },
        },
        # 8. Gehäusebeleuchtung Schalter
        {
            "component": "switch",
            "object_id": "chamber_light",
            "config": {
                "name": f"{printer_name} Gehäusebeleuchtung",
                "state_topic": state_topic,
                "value_template": "{{ 'ON' if value_json.chamber_light else 'OFF' }}",
                "command_topic": f"{cmd_topic}/chamber_light",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:lightbulb",
                "unique_id": f"printlab_{safe_id}_chamber_light",
                "device": device,
            },
        },
    ]

    results = []
    for ent in entities:
        topic = f"{DISCOVERY_PREFIX}/{ent['component']}/printlab_{safe_id}/{ent['object_id']}/config"
        results.append(
            {
                "topic": topic,
                "component": ent["component"],
                "object_id": ent["object_id"],
                "payload": ent["config"],
            }
        )
    return results


def build_telemetry_payload(
    state: str = "IDLE",
    nozzle_temp: float = 0.0,
    bed_temp: float = 0.0,
    progress: int = 0,
    remaining_minutes: int = 0,
    current_layer: int = 0,
    total_layers: int = 0,
    emergency_stop: bool = False,
    chamber_light: bool = False,
) -> str:
    """Formatiert einen Echtzeit-Telemetriedatensatz für Home Assistant als JSON-String."""
    data = {
        "state": state,
        "nozzle_temp": round(nozzle_temp, 1),
        "bed_temp": round(bed_temp, 1),
        "progress": progress,
        "remaining_minutes": remaining_minutes,
        "current_layer": current_layer,
        "total_layers": total_layers,
        "emergency_stop": bool(emergency_stop),
        "chamber_light": bool(chamber_light),
    }
    return json.dumps(data, ensure_ascii=False)
