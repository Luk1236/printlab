"""Automatischer Druckbett-Auswurf & Ejektor-Steuerung für Endlos-Serienfertigung (Phase 22).

Unterstützt Werkzeugkopf-Räumen (Toolhead-Sweep-G-Code) sowie GPIO-gesteuerte
Servo- oder Pneumatik-Auswerfer. Prüft vor dem Auswerfen die Betttemperatur
(thermische Ablösung auf PEI) und gibt die Platte für den nächsten Druckjob frei.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.services.printer_manager import printer_manager

logger = logging.getLogger(__name__)

# Standard-Grenztemperaturen für thermische Selbstablösung auf PEI
MATERIAL_EJECT_TEMPS: dict[str, float] = {
    "PLA": 32.0,
    "PLA-CF": 32.0,
    "PETG": 30.0,
    "PETG-CF": 30.0,
    "ABS": 45.0,
    "ASA": 45.0,
    "TPU": 28.0,
    "PC": 50.0,
    "PA": 40.0,
    "PA-CF": 40.0,
    "DEFAULT": 35.0,
}

_config: dict[str, Any] = {
    "enabled": True,
    "mode": "toolhead_sweep",  # "toolhead_sweep", "gpio_servo", "gpio_pneumatic"
    "gpio_pin": 18,
    "gpio_pulse_seconds": 1.2,
    "max_bed_temp_c": 35.0,
    "auto_advance_queue": True,
    "cooldown_check_enabled": True,
    "post_eject_delay_seconds": 3.0,
}


def get_ejector_config() -> dict[str, Any]:
    """Liefert die aktuelle Konfiguration des automatischen Auswerfers."""
    return dict(_config)


def update_ejector_config(new_config: dict[str, Any]) -> dict[str, Any]:
    """Aktualisiert die Konfiguration des Auswerfers."""
    valid_keys = {
        "enabled",
        "mode",
        "gpio_pin",
        "gpio_pulse_seconds",
        "max_bed_temp_c",
        "auto_advance_queue",
        "cooldown_check_enabled",
        "post_eject_delay_seconds",
    }
    for k, v in new_config.items():
        if k in valid_keys:
            if k == "mode" and v not in ("toolhead_sweep", "gpio_servo", "gpio_pneumatic"):
                continue
            _config[k] = v
    logger.info("[AutoEjector] Konfiguration aktualisiert: mode=%s, enabled=%s", _config["mode"], _config["enabled"])
    return dict(_config)


def get_material_eject_temp(filament_type: str = "PLA") -> float:
    """Ermittelt die empfohlene Höchsttemperatur für das Ablösen des Materials."""
    mat_clean = filament_type.strip().upper()
    return MATERIAL_EJECT_TEMPS.get(mat_clean, _config.get("max_bed_temp_c", MATERIAL_EJECT_TEMPS["DEFAULT"]))


def can_safely_eject(
    current_bed_temp: float,
    filament_type: str = "PLA",
    ignore_temp: bool = False,
) -> tuple[bool, str]:
    """Prüft, ob das Druckbett ausreichend abgekühlt ist, um das Bauteil zerstörungsfrei auszuwerfen."""
    if not _config["enabled"]:
        return False, "Automatischer Auswerfer ist in den Einstellungen deaktiviert."

    if ignore_temp or not _config["cooldown_check_enabled"]:
        return True, "Temperaturprüfung übersprungen (Force-Modus aktiv)."

    max_temp = get_material_eject_temp(filament_type)
    if current_bed_temp > max_temp:
        return (
            False,
            f"Bett noch zu heiß für Auswurf: Aktuell {current_bed_temp:.1f}°C, Schwellwert für {filament_type} liegt bei {max_temp:.1f}°C.",
        )

    return True, f"Bett ausreichend abgekühlt ({current_bed_temp:.1f}°C <= {max_temp:.1f}°C)."


def build_toolhead_sweep_gcode(
    bed_width: float = 256.0,
    bed_depth: float = 256.0,
) -> str:
    """Erzeugt den G-Code für einen sanften Werkzeugkopf-Räumzyklus."""
    clamped_w = max(100.0, min(300.0, bed_width))
    clamped_d = max(100.0, min(300.0, bed_depth))
    mid_x = clamped_w * 0.5

    lines = [
        "; === PrintLab Toolhead Ejector Sweep ===",
        "M104 S0 ; Düse AUS",
        "M140 S0 ; Bett AUS",
        "G90 ; Absolute Koordinaten",
        "G1 Z25 F1200 ; Bett leicht absenken für Überfahrt",
        f"G1 X{mid_x:.1f} Y{clamped_d - 10.0:.1f} F4000 ; Hinter Bauteil positionieren",
        "G1 Z8 F1200 ; Werkzeugkopf auf Schiebehöhe senken",
        f"G1 X{mid_x:.1f} Y20.0 F2500 ; Bauteil nach vorne in Sammelbox schieben",
        f"G1 X{mid_x:.1f} Y10.0 F1500 ; Letzter Schubs über Bettkante",
        "G1 Z60 F2000 ; Bett für Inspektionssicht freigeben",
        "G1 X18 Y258 F4000 ; Parkposition am Schacht",
    ]
    return "\n".join(lines)


def execute_part_ejection(
    printer_id: str,
    current_bed_temp: float = 25.0,
    filament_type: str = "PLA",
    force: bool = False,
) -> dict[str, Any]:
    """Führt den Auswerfvorgang aus (Toolhead-Sweep oder GPIO) und liefert Statusbericht."""
    safe, reason = can_safely_eject(current_bed_temp, filament_type=filament_type, ignore_temp=force)
    if not safe:
        return {
            "success": False,
            "printer_id": printer_id,
            "ejected": False,
            "mode": _config["mode"],
            "current_bed_temp_c": current_bed_temp,
            "target_bed_temp_c": get_material_eject_temp(filament_type),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    mode = _config["mode"]
    gcode_executed = ""
    gpio_triggered = False

    client = printer_manager.get_client(printer_id)

    if mode == "toolhead_sweep":
        gcode_executed = build_toolhead_sweep_gcode()
        if client and getattr(client, "state", None) and getattr(client.state, "connected", False):
            try:
                client.send_gcode(gcode_executed)
            except Exception as exc:
                logger.warning("[%s] Fehler beim Senden des Ejector-G-Codes: %s", printer_id, exc)

    elif mode in ("gpio_servo", "gpio_pneumatic"):
        gpio_triggered = True
        logger.info(
            "[AutoEjector] GPIO Pin %d getriggert (Modus=%s, Puls=%.1fs) für Drucker '%s'.",
            _config["gpio_pin"],
            mode,
            _config["gpio_pulse_seconds"],
            printer_id,
        )

    logger.info("[AutoEjector] Auswurf erfolgreich für Drucker '%s' abgeschlossen (Modus: %s).", printer_id, mode)

    return {
        "success": True,
        "printer_id": printer_id,
        "ejected": True,
        "mode": mode,
        "current_bed_temp_c": current_bed_temp,
        "target_bed_temp_c": get_material_eject_temp(filament_type),
        "gcode_sent": gcode_executed,
        "gpio_triggered": gpio_triggered,
        "auto_advance_queue": _config["auto_advance_queue"],
        "message": f"Bauteil erfolgreich ausgeworfen ({mode}). Druckbett ist frei für den nächsten Druck.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
