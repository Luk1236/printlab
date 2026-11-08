"""Wartungs-, Reinigungs- und Düsenwechsel-Workflow für Bambu Lab 3D-Drucker.

Fährt den Druckkopf in ergonomische Wartungspositionen (Bett absenken, Werkzeugkopf
nach vorne Mitte, Kammerlicht an, Heizelemente sicher steuern), leitet interaktiv
durch die Cold-Pull-Düsenreinigung und automatisiert Reinigungsfahrten (Carbon-X-Stangen,
Z-Spindeln Schmieren, Wiper-Test) inklusive automatischem Verschleißzähler-Reset.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.services.printer_manager import printer_manager
from backend.app.services.wear_tracker import get_wear_overview, reset_wear_component

logger = logging.getLogger(__name__)

# Standard-Wartungsposition für P1/X1/A1-Drucker
DEFAULT_BED_LOWER_Z_MM = 180.0
DEFAULT_TOOLHEAD_FRONT_X_MM = 128.0
DEFAULT_TOOLHEAD_FRONT_Y_MM = 30.0

COLD_PULL_TEMPS: dict[str, tuple[int, int]] = {
    # Material -> (heat_temp_c, pull_temp_c)
    "PLA": (240, 85),
    "PETG": (250, 90),
    "ABS": (260, 95),
    "ASA": (260, 95),
    "PA": (280, 100),
    "PA-CF": (285, 105),
    "NYLON": (280, 100),
    "CLEANING": (240, 90),
}


def build_service_position_gcode(
    lower_bed_mm: float = DEFAULT_BED_LOWER_Z_MM,
    front_x_mm: float = DEFAULT_TOOLHEAD_FRONT_X_MM,
    front_y_mm: float = DEFAULT_TOOLHEAD_FRONT_Y_MM,
    preheat_nozzle_c: int = 0,
) -> str:
    """Erzeugt das G-Code-Makro für die ergonomische Düsenwechsel-Wartungsposition."""
    clamped_z = max(50.0, min(240.0, float(lower_bed_mm)))
    clamped_x = max(10.0, min(240.0, float(front_x_mm)))
    clamped_y = max(15.0, min(240.0, float(front_y_mm)))

    lines = [
        "; === PrintLab Düsenwechsel- & Wartungsposition ===",
        "M106 P1 S0 ; Bauteillüfter AUS",
        "M106 P2 S0 ; Zusatzlüfter AUS",
        "M140 S0 ; Heizbett AUS",
    ]

    if preheat_nozzle_c > 0:
        clamped_temp = min(300, max(50, preheat_nozzle_c))
        lines.append(f"M104 S{clamped_temp} ; Düse für Wechsel/Hot-Tightening vorheizen")
    else:
        lines.append("M104 S0 ; Düsenheizung AUS (Sicherheit)")

    lines.extend([
        "G90 ; Absolute Positionierung",
        f"G1 Z{clamped_z:.1f} F1200 ; Druckbett absenken für freie Zugänglichkeit",
        f"G1 X{clamped_x:.1f} Y{clamped_y:.1f} F3000 ; Werkzeugkopf nach vorne Mitte verfahren",
    ])
    return "\n".join(lines)


def move_to_service_position(
    printer_id: str,
    preheat_nozzle_c: int = 0,
    lower_bed_mm: float = DEFAULT_BED_LOWER_Z_MM,
) -> dict[str, Any]:
    """Verfährt Werkzeugkopf und Bett in die optimale Düsenwechsel-Position und aktiviert Licht."""
    gcode = build_service_position_gcode(
        lower_bed_mm=lower_bed_mm,
        preheat_nozzle_c=preheat_nozzle_c,
    )

    client = printer_manager.get_client(printer_id)
    sent_to_printer = False
    if client and getattr(client, "state", None) and getattr(client.state, "connected", False):
        try:
            client.set_chamber_light(True)
            client.send_gcode(gcode)
            sent_to_printer = True
            logger.info("[%s] In Wartungsposition gefahren (Z=%.1f, Düse=%d°C).", printer_id, lower_bed_mm, preheat_nozzle_c)
        except Exception as exc:
            logger.warning("[%s] Fehler beim Senden des Wartungs-G-Codes: %s", printer_id, exc)

    safety_notes = []
    if preheat_nozzle_c > 0:
        safety_notes.append(
            f"ACHTUNG: Düse heizt auf {preheat_nozzle_c}°C vor. Verbrennungsgefahr! Hitzebeständige Pinzette/Handschuhe nutzen."
        )
    else:
        safety_notes.append(
            "Heizelemente sind abgeschaltet. Bitte warten Sie, bis die Düsentemperatur unter 45°C liegt, bevor Sie Hotend berühren."
        )

    steps = [
        "1. Frontabdeckung des Werkzeugkopfs vorsichtig nach vorne abziehen (magnetisch gehalten).",
        "2. Zwei Steckverbinder (Hotend-Lüfter & Heizelement/Thermistor) vorsichtig abstecken.",
        "3. Silikonsocke abziehen und die zwei Torx-Befestigungsschrauben lösen.",
        "4. Altes Hotend entnehmen, neues Hotend einsetzen und Schrauben handfest über Kreuz anziehen.",
        "5. Kabel wieder anstecken, Silikonsocke aufsetzen und Frontabdeckung montieren.",
    ]

    return {
        "success": True,
        "printer_id": printer_id,
        "action": "service_position",
        "sent_to_printer": sent_to_printer,
        "nozzle_target_temp_c": preheat_nozzle_c,
        "bed_z_pos_mm": lower_bed_mm,
        "toolhead_pos": {"x": DEFAULT_TOOLHEAD_FRONT_X_MM, "y": DEFAULT_TOOLHEAD_FRONT_Y_MM},
        "chamber_light_on": True,
        "gcode_sent": gcode,
        "safety_instructions": safety_notes,
        "steps": steps,
    }


def exit_service_position(printer_id: str, perform_home: bool = True) -> dict[str, Any]:
    """Verlässt die Wartungsposition, schaltet Heizer ab und referenziert die Achsen."""
    lines = ["M104 S0 ; Düse AUS", "M140 S0 ; Bett AUS"]
    if perform_home:
        lines.append("G28 ; Home aller Achsen")
    gcode = "\n".join(lines)

    client = printer_manager.get_client(printer_id)
    sent_to_printer = False
    if client and getattr(client, "state", None) and getattr(client.state, "connected", False):
        try:
            client.send_gcode(gcode)
            sent_to_printer = True
        except Exception as exc:
            logger.warning("[%s] Fehler beim Verlassen der Wartungsposition: %s", printer_id, exc)

    return {
        "success": True,
        "printer_id": printer_id,
        "action": "exit_service_position",
        "sent_to_printer": sent_to_printer,
        "homed": perform_home,
        "message": "Wartungsmodus beendet. Drucker befindet sich wieder in Park-/Ausgangsposition.",
    }


def cold_pull_routine(
    printer_id: str,
    step: str = "heat",
    filament_type: str = "PLA",
) -> dict[str, Any]:
    """Führt schrittweise eine Cold-Pull Düsenreinigung zur Beseitigung von Verstopfungen durch."""
    clean_mat = filament_type.strip().upper()
    heat_temp, pull_temp = COLD_PULL_TEMPS.get(clean_mat, COLD_PULL_TEMPS["PLA"])
    client = printer_manager.get_client(printer_id)
    step_lower = step.strip().lower()

    if step_lower == "heat":
        gcode = f"M104 S{heat_temp}\nG90\nG1 Z150 F1200\nG1 X128 Y30 F3000"
        if client and getattr(client, "state", None) and getattr(client.state, "connected", False):
            client.send_gcode(gcode)
        return {
            "printer_id": printer_id,
            "step": "heat",
            "target_temp_c": heat_temp,
            "status_message": f"Düse heizt auf {heat_temp}°C auf.",
            "next_action": "Sobald die Temperatur erreicht ist: Reinigungs-Filament manuell ca. 20-30 mm in den Extruder vorschieben, bis sauberer Strang austritt. Anschließend Schritt 'cooldown' starten.",
            "is_completed": False,
        }

    elif step_lower == "cooldown":
        gcode = f"M104 S0\nM106 P1 S255 ; Bauteillüfter 100% zur schnellen Abkühlung auf {pull_temp}°C"
        if client and getattr(client, "state", None) and getattr(client.state, "connected", False):
            client.send_gcode(gcode)
        return {
            "printer_id": printer_id,
            "step": "cooldown",
            "target_temp_c": pull_temp,
            "status_message": f"Heizung aus. Lüfter kühlt die Düse auf {pull_temp}°C ab.",
            "next_action": f"Warten Sie, bis die Düse ca. {pull_temp}°C erreicht hat. Das Filament umschließt nun alle Schmutzpartikel. Starten Sie dann Schritt 'pull'.",
            "is_completed": False,
        }

    elif step_lower == "pull":
        gcode = f"M106 P1 S0\nM104 S{pull_temp}"
        if client and getattr(client, "state", None) and getattr(client.state, "connected", False):
            client.send_gcode(gcode)
        return {
            "printer_id": printer_id,
            "step": "pull",
            "target_temp_c": pull_temp,
            "status_message": f"Zieltemperatur ({pull_temp}°C) gehalten.",
            "next_action": "Extruder-Hebel drücken / entriegeln und das Filament mit einem festen, ruckartigen Zug senkrecht nach oben herausziehen!",
            "is_completed": False,
        }

    elif step_lower == "inspect":
        return {
            "printer_id": printer_id,
            "step": "inspect",
            "target_temp_c": 0,
            "status_message": "Cold-Pull abgeschlossen.",
            "next_action": "Prüfen Sie die Spitze des herausgezogenen Strangs. Bei Verunreinigungen Vorgang wiederholen. Wenn sauber, Wartung als erledigt quittieren.",
            "is_completed": True,
        }

    raise ValueError(f"Unbekannter Cold-Pull-Schritt '{step}'. Gültig sind: heat, cooldown, pull, inspect.")


def cleaning_motion_routine(
    printer_id: str,
    routine: str = "carbon_rods",
    cycles: int = 3,
) -> dict[str, Any]:
    """Führt sanfte Bewegungszyklen zur Reinigung der Achsen oder zum Verteilen von Schmiermittel aus."""
    client = printer_manager.get_client(printer_id)
    r_clean = routine.strip().lower()
    clamped_cycles = max(1, min(10, int(cycles)))

    lines = ["G90 ; Absolute Positionierung"]

    if r_clean == "carbon_rods":
        # Druckkopf über die X-Achse verfahren
        lines.append("G1 Y128 F3000")
        for _ in range(clamped_cycles):
            lines.append("G1 X20 F3500")
            lines.append("G1 X235 F3500")
        lines.append("G1 X128 F3000")
        instructions = (
            "Der Werkzeugkopf bewegt sich sanft über die Carbon-X-Stangen. "
            "Wischen Sie die Stangen mit einem fusselfreien, in 99% Isopropanol getränkten Tuch gründlich ab. "
            "WICHTIG: Niemals Schmieröl oder Fett auf Carbon-Stangen auftragen!"
        )

    elif r_clean == "z_lead_screws":
        # Druckbett auf und ab verfahren zur Fettverteilung
        for _ in range(clamped_cycles):
            lines.append("G1 Z220 F1200")
            lines.append("G1 Z20 F1200")
        lines.append("G1 Z180 F1200")
        instructions = (
            "Das Druckbett fährt auf und ab. Tragen Sie frisches Schmierfett (z.B. PTFE- oder Silikonfett) "
            "gleichmäßig auf die drei Z-Gewindespindeln auf. Die Bewegung verteilt das Fett über die Muttern."
        )

    elif r_clean == "nozzle_wipe":
        # Über den Silikon-Wiper / Rutsche fahren
        lines.append("G1 Z5 F1200")
        for _ in range(clamped_cycles):
            lines.append("G1 X18 Y250 F4000")
            lines.append("G1 X28 Y250 F4000")
        lines.append("G1 X128 Y128 F3000")
        instructions = (
            "Druckkopf fährt über die Abstreiflippe (Nozzle Wiper). "
            "Prüfen Sie den Silikonabstreifer auf Risse oder Abnutzung und tauschen Sie ihn ggf. aus."
        )
    else:
        raise ValueError(
            f"Unbekannte Reinigungsroutine '{routine}'. Gültig sind: carbon_rods, z_lead_screws, nozzle_wipe."
        )

    gcode = "\n".join(lines)
    sent_to_printer = False
    if client and getattr(client, "state", None) and getattr(client.state, "connected", False):
        try:
            client.send_gcode(gcode)
            sent_to_printer = True
        except Exception as exc:
            logger.warning("[%s] Fehler bei Reinigungsroutine %s: %s", printer_id, r_clean, exc)

    return {
        "success": True,
        "printer_id": printer_id,
        "routine": r_clean,
        "cycles": clamped_cycles,
        "sent_to_printer": sent_to_printer,
        "gcode_sent": gcode,
        "instructions": instructions,
    }


def complete_maintenance_task(
    printer_id: str,
    component: str,
    notes: str = "",
) -> dict[str, Any]:
    """Quittiert eine abgeschlossene Wartung und setzt den Verschleißzähler in wear_tracker zurück."""
    comp_map = {
        "nozzle": "nozzle",
        "hotend": "nozzle",
        "düsenwechsel": "nozzle",
        "carbon_rods": "steel_rods",
        "stangen": "steel_rods",
        "z_spindle": "z_spindle",
        "z_spindeln": "z_spindle",
        "ptfe": "ptfe",
        "carbon_filter": "carbon_filter",
    }
    comp_clean = component.strip().lower()
    wear_key = comp_map.get(comp_clean, comp_clean)

    reset_ok = reset_wear_component(printer_id, wear_key)
    wear_data = get_wear_overview(printer_id)

    return {
        "success": reset_ok,
        "printer_id": printer_id,
        "component": wear_key,
        "notes": notes,
        "message": f"Wartungsaufgabe für '{wear_key}' erfolgreich quittiert und Verschleißzähler auf 0 zurückgesetzt.",
        "wear_status": wear_data,
    }
