"""Plattenwechsler (Baugruppe 3) für den Bambu Lab P2S: Maße, Wechselzyklus, Konstruktionsprüfung, Sperren.

Einzige Quelle für Maße und Ablauf. Die Plattenstation (``plate_station_service``) fährt die Phasen ab, die 3D-Ansicht
(``werkzeuge/automation_hardware``) trägt eine Kopie davon und ein Test hält beide gleich. Alle Maße in mm, Ursprung ist die
Bodenmitte des Druckers, X nach rechts, Y nach vorne (Tür), Z nach oben. Die Maße stammen aus
``werkzeuge/automation_hardware/TUER_MAGAZIN_WASCHSTATION.md`` und sind nicht am Gerät nachgemessen.

Die Konstruktionsprüfung (``design_checks``) rechnet nur nach, ob die dort genannten Maße zueinander passen. Sie ersetzt
keine Messung am echten Gerät.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# --- Drucker (Bambu Lab P2S laut Herstellerangabe) --------------------------------------------------------------------
PRINTER_HALF_W = 196.0
PRINTER_HALF_D = 203.0
PRINTER_HEIGHT = 478.0
PLATE_EDGE = 257.0
PLATE_HALF = PLATE_EDGE / 2

DOOR_HINGE = (-176.5, 205.0)
DOOR_WIDTH = 353.0
DOOR_Z = (68.0, 442.0)
DOOR_OPEN_DEG = 115.0

# --- Plattenlager und Wechsler ----------------------------------------------------------------------------------------
SLOT_Z = (185.0, 220.0, 255.0, 290.0)  # Plattenoberkante je Fach
SLOT_COUNT = len(SLOT_Z)
Z_SWAP = 220.0  # Übergabehöhe am Heizbett (= Fach 2)
WASH_Z = 44.0
HOME_Z = 310.0
MAG_X = 360.0
TRANSFER_Y = 355.0
RAIL_Y = 575.0
PROFILE = 20.0  # Alu-Profil 2020
# Kompakt-Turm (Baugruppe 2 und 4): Außenkanten der vier 2020-Steher. Lichte Weite zwischen den Stehern 266 mm, damit die
# 257-mm-Platte nach vorne (+Y) hindurchfährt. Die erste Auslegung (X 220 bis 500) ließ nur 240 mm frei: Die Platte passte
# weder ins Regal noch zwischen den vorderen Stehern hindurch.
TOWER_X = (207.0, 513.0)
TOWER_Y = (-145.0, 145.0)
TOWER_CLEAR_X = TOWER_X[1] - TOWER_X[0] - 2 * PROFILE  # 266 mm
PLATE_GUIDE = 258.5  # Führungsmaß der Fachleisten (Platte 257 mm + 0,75 mm je Seite)
PARK_Y = 540.0  # Greiferbacke geparkt
PARK_Z = 220.0
JAW_OFFSET = PLATE_HALF + 6.0  # Backe sitzt 6 mm hinter der Plattenvorderkante: Plattenmitte Y + 134,5
Y_GRIP = JAW_OFFSET  # Backe bei Plattenmitte Y = 0

# Linearführungen (Länge der Schiene, Länge des Wagens)
CARRIAGE_LEN = {"MGN12H": 45.4, "MGN9H": 39.9}
RAIL_X = ("MGN12H", 600.0)
RAIL_Z = ("MGN12H", 300.0)
RAIL_Y_ARM = ("MGN9H", 500.0)  # 440 mm reichten nicht: 440 - 39,9 = 400,1 mm < 405,5 mm Hub

# Mindestabstände der Prüfung (Auslegungswerte, anpassbar)
MIN_CLEARANCE = 15.0
MIN_MARGIN = 5.0

# Teile bleiben auf der Platte und wandern mit ihr ins Regal. Darüber liegt die nächste Platte (oder die Deckplatte).
PLATE_THICKNESS = 0.5
RACK_LID_Z = 312.0  # Unterkante der Deckplatte des Turms
PART_GAP = 5.0  # Luft zwischen Teil und Platte darüber
WANTED_PART_HEIGHT = 30.0  # Annahme für die Prüfung (wie das Beispielteil der 3D-Ansicht), nach Bedarf anpassen

PRINT_STATES_BLOCKING = frozenset({"PREPARE", "SLICING", "RUNNING", "PAUSE"})
MAX_SWAP_BED_TEMP = 36.0  # wie cooldown_guard.DEFAULT_MAX_SWAP_TEMP


@dataclass(frozen=True)
class Phase:
    """Ein Abschnitt des Wechselzyklus. ``t0``/``t1`` sind Anteile der Gesamtdauer (für die 3D-Ansicht)."""

    id: str
    label: str
    t0: float
    t1: float
    detail: str
    magnet: bool | None = None  # None = unverändert


PHASES: tuple[Phase, ...] = (
    Phase("door_open", "Tür öffnet", 0.00, 0.08, "Servo öffnet die Glastür auf 115°", None),
    Phase(
        "bed_down",
        "Bett fährt auf Wechselhöhe",
        0.08,
        0.22,
        "Bett senkt sich auf Z 220, die Teile bleiben auf der Platte",
        None,
    ),
    Phase(
        "to_printer",
        "Shuttle vor den Drucker",
        0.22,
        0.28,
        "Shuttle X 360 → 0, Arm fährt vor",
        None,
    ),
    Phase(
        "pull_old",
        "Alte Platte herausziehen",
        0.28,
        0.38,
        "Magnet an, Platte samt Teilen bis Y = 355 in den Übergabekorridor",
        True,
    ),
    Phase("to_rack", "Zum Plattenregal", 0.38, 0.48, "X 0 → 360, Z auf das leere Fach", None),
    Phase("store_old", "Alte Platte ablegen", 0.48, 0.56, "Platte samt Teilen ins Fach schieben, Magnet aus", False),
    Phase("lift_fresh", "Zur frischen Platte", 0.56, 0.62, "Arm löst, Z auf das Fach mit der frischen Platte", None),
    Phase("pull_fresh", "Frische Platte holen", 0.62, 0.72, "Magnet an, Platte bis Y = 355 herausziehen", True),
    Phase("to_printer_fresh", "Zurück zum Drucker", 0.72, 0.82, "X 360 → 0, Z auf Wechselhöhe 220", None),
    Phase(
        "place_fresh", "Platte auf das Bett legen", 0.82, 0.90, "Platte auf das Heizbett schieben, Magnet aus", False
    ),
    Phase(
        "park_close",
        "Parken, Tür schließt",
        0.90,
        1.00,
        "Arm zurück auf Y = 540, Shuttle zum Turm, Tür zu, Bett auf Ruhe-Z",
        None,
    ),
)


def phase_at(t: float) -> Phase:
    """Phase zum Zyklusanteil ``t`` (0..1)."""
    t = min(1.0, max(0.0, t))
    for phase in PHASES:
        if t < phase.t1:
            return phase
    return PHASES[-1]


def slot_capacity(index: int) -> float:
    """Höchste Teilehöhe auf der Platte in Fach ``index`` (0-basiert): bis zur nächsten Platte bzw. Deckplatte, minus Luft."""
    if index + 1 < SLOT_COUNT:
        return SLOT_Z[index + 1] - PLATE_THICKNESS - SLOT_Z[index] - PART_GAP
    return RACK_LID_Z - SLOT_Z[index] - PART_GAP


SLOT_CAPACITY = tuple(slot_capacity(i) for i in range(SLOT_COUNT))


# --- Geometrie -----------------------------------------------------------------------------------------------------------
def door_tip_y_max() -> float:
    """Größte Y-Ausladung der Tür beim Öffnen (bei 90°, wenn die Tür gerade nach vorne zeigt)."""
    return DOOR_HINGE[1] + DOOR_WIDTH


def door_tip(angle_deg: float) -> tuple[float, float]:
    """Türkante (XY) bei ``angle_deg``: 0° geschlossen (Tür liegt entlang +X), 90° steht nach vorne."""
    phi = math.radians(angle_deg)
    return (DOOR_HINGE[0] + DOOR_WIDTH * math.cos(phi), DOOR_HINGE[1] + DOOR_WIDTH * math.sin(phi))


def _segment_box_distance(
    p: tuple[float, float], q: tuple[float, float], box: tuple[float, float, float, float]
) -> float:
    """Kürzester Abstand zwischen Strecke p-q und achsparallelem Rechteck (x0, y0, x1, y1); 0 bei Überschneidung."""
    x0, y0, x1, y1 = box
    best = math.inf
    steps = 400
    for i in range(steps + 1):
        k = i / steps
        x, y = p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k
        dx = max(x0 - x, 0.0, x - x1)
        dy = max(y0 - y, 0.0, y - y1)
        best = min(best, math.hypot(dx, dy))
    return best


def door_gap(angle_deg: float, box: tuple[float, float, float, float]) -> float:
    """Abstand der Türfläche (Scharnier bis Kante) zu einem Rechteck in der Draufsicht."""
    return _segment_box_distance(DOOR_HINGE, door_tip(angle_deg), box)


def door_sweep_gap(box: tuple[float, float, float, float]) -> float:
    """Kleinster Abstand der Tür zu einem Rechteck über den ganzen Öffnungsweg 0° bis 115°."""
    return min(door_gap(a / 2, box) for a in range(0, int(DOOR_OPEN_DEG * 2) + 1))


def portal_front_box() -> tuple[float, float, float, float]:
    """Vorderes Profil des Portals (Querträger und Steher): X −162..525, Y Schiene ± halbes Profil."""
    return (-162.0, RAIL_Y - PROFILE / 2, 525.0, RAIL_Y + PROFILE / 2)


def plate_box(center_x: float, center_y: float) -> tuple[float, float, float, float]:
    return (center_x - PLATE_HALF, center_y - PLATE_HALF, center_x + PLATE_HALF, center_y + PLATE_HALF)


# --- Konstruktionsprüfung ------------------------------------------------------------------------------------------------
def _check(
    cid: str, label: str, value: float, recommended: float, unit: str, note: str, *, hard: float
) -> dict[str, Any]:
    """``fail``: unter ``hard`` (passt nicht oder Berührung). ``warn``: unter ``recommended`` (knapp). Sonst ``ok``."""
    status = "fail" if value < hard else "warn" if value < recommended else "ok"
    return {
        "id": cid,
        "label": label,
        "value": round(value, 1),
        "limit": recommended,
        "unit": unit,
        "margin": round(value - recommended, 1),
        "status": status,
        "note": note,
    }


def design_checks() -> list[dict[str, Any]]:
    """Rechnet die Maße der Baugruppe 3 gegeneinander nach. ``status``: ok, warn (knapp) oder fail (passt nicht)."""
    y_travel = PARK_Y - Y_GRIP
    z_travel = max(SLOT_Z) - WASH_Z
    plate_mass_kg = (PLATE_EDGE / 10) ** 2 * 0.05 * 7.85 / 1000  # 0,5 mm Stahl, ohne Beschichtung
    door_to_portal = door_sweep_gap(portal_front_box())
    # Die Platte verlässt den Drucker erst, wenn die Tür ganz offen ist (Phase "door_open" vor "pull_old").
    door_to_plate = min(door_gap(DOOR_OPEN_DEG, plate_box(0.0, y)) for y in (0.0, TRANSFER_Y))
    return [
        _check(
            "door_portal",
            "Tür ↔ Portalprofil (Draufsicht, ganzer Öffnungsweg)",
            door_to_portal,
            MIN_CLEARANCE,
            "mm",
            "Die 17 mm der Doku gelten bis zur Schienenmitte (Y 575), die Profilvorderkante liegt bei Y 565: "
            "Schiene auf Y ≥ 583 setzen oder die Türöffnung am Gerät auf unter 90° begrenzen.",
            hard=3.0,
        ),
        _check(
            "door_plate",
            "Tür (115°) ↔ Platte im Übergabekorridor",
            door_to_plate,
            MIN_CLEARANCE,
            "mm",
            "Platte bei X 0, am Drucker und im Korridor Y 355. Die Tür muss ganz offen sein, bevor die Platte den "
            "Drucker verlässt: bei halber Öffnung schneidet sie den Korridor.",
            hard=3.0,
        ),
        _check(
            "plate_front",
            "Plattenhinterkante ↔ Druckerfront im Korridor",
            (TRANSFER_Y - PLATE_HALF) - DOOR_HINGE[1],
            MIN_CLEARANCE,
            "mm",
            "Platte bei Y 355: Hinterkante bei 226,5, Druckerfront bei 205.",
            hard=3.0,
        ),
        _check(
            "tower_gap",
            "Turm ↔ rechte Druckerwand",
            TOWER_X[0] - PRINTER_HALF_W,
            MIN_CLEARANCE,
            "mm",
            f"Turm ab X {TOWER_X[0]:.0f}, Druckerwand bei X {PRINTER_HALF_W:.0f}. Turm und Drucker getrennt aufstellen, "
            "nicht verschrauben. Für 15 mm Turm und Wechsler-Mitte (MAG_X) um 4 mm nach rechts setzen.",
            hard=3.0,
        ),
        _check(
            "tower_passage",
            "Platte ↔ Turmsteher (Durchfahrt nach vorne, je Seite)",
            (TOWER_CLEAR_X - PLATE_EDGE) / 2,
            3.0,
            "mm",
            f"Lichte Weite {TOWER_CLEAR_X:.0f} mm zwischen den Stehern, Platte {PLATE_EDGE:.0f} mm; die Fachleisten führen "
            f"auf {PLATE_GUIDE} mm. Mit dem ersten Turm (X 220 bis 500) blieben 240 mm: Die Platte passte nicht hindurch.",
            hard=1.0,
        ),
        _check(
            "x_stroke",
            "Reserve Verfahrweg X (Schiene − Wagen − Hub)",
            RAIL_X[1] - CARRIAGE_LEN[RAIL_X[0]] - MAG_X,
            MIN_MARGIN,
            "mm",
            f"Hub {MAG_X:.0f} mm auf {RAIL_X[0]} {RAIL_X[1]:.0f} mm.",
            hard=0.0,
        ),
        _check(
            "y_stroke",
            "Reserve Verfahrweg Y-Arm (Schiene − Wagen − Hub)",
            RAIL_Y_ARM[1] - CARRIAGE_LEN[RAIL_Y_ARM[0]] - y_travel,
            MIN_MARGIN,
            "mm",
            f"Hub {y_travel:.1f} mm auf {RAIL_Y_ARM[0]} {RAIL_Y_ARM[1]:.0f} mm; mit 440 mm fehlten 5,4 mm.",
            hard=0.0,
        ),
        _check(
            "z_stroke",
            "Reserve Verfahrweg Z (Schiene − Wagen − Hub)",
            RAIL_Z[1] - CARRIAGE_LEN[RAIL_Z[0]] - z_travel,
            MIN_MARGIN,
            "mm",
            f"Hub {z_travel:.0f} mm (Waschhöhe 44 bis Fach 4 bei 290) auf {RAIL_Z[0]} {RAIL_Z[1]:.0f} mm.",
            hard=0.0,
        ),
        _check(
            "jaw_ceiling",
            "Backe in Fach 4 ↔ Deckplatte des Turms",
            312.0 - (max(SLOT_Z) + 8.0),
            MIN_CLEARANCE,
            "mm",
            "Backenoberkante 8 mm über der Plattenoberkante, Deckplatte ab Z 312.",
            hard=3.0,
        ),
        _check(
            "part_height",
            "Höhe der Teile auf der Platte im niedrigsten Fach",
            min(SLOT_CAPACITY),
            WANTED_PART_HEIGHT,
            "mm",
            f"Fach 1 bis 3: je {SLOT_CAPACITY[0]:.1f} mm (35-mm-Raster minus Platte und {PART_GAP:.0f} mm Luft), "
            f"Fach 4 unter der Deckplatte: {SLOT_CAPACITY[-1]:.1f} mm. Höhere Teile: Raster vergrößern, Fächer streichen "
            f"oder das oberste Fach nicht für Platten mit Teilen nutzen. Gewünscht angenommen: {WANTED_PART_HEIGHT:.0f} mm.",
            hard=0.0,
        ),
        _check(
            "magnet_reserve",
            "Haltekraft Magnet ÷ Plattengewicht",
            80.0 / (plate_mass_kg * 9.81),
            5.0,
            "×",
            f"80 N Nennkraft, Platte rund {plate_mass_kg * 1000:.0f} g. Nennwert: Eine dünne Platte nutzt nur einen Bruchteil davon, "
            "am Gerät mit der Federwaage prüfen.",
            hard=1.0,
        ),
    ]


def design_summary() -> dict[str, Any]:
    checks = design_checks()
    return {
        "checks": checks,
        "fail": [c["id"] for c in checks if c["status"] == "fail"],
        "warn": [c["id"] for c in checks if c["status"] == "warn"],
    }


# --- Sperren --------------------------------------------------------------------------------------------------------------
def interlock_problems(
    *,
    printer_state: str | None,
    bed_temp: float | None,
    estop_active: bool,
    check_printer: bool = True,
) -> list[str]:
    """Gründe, warum jetzt kein Wechsel erlaubt ist (leer = frei).

    ``check_printer=False`` prüft nur den Not-Halt (Waschen, Tür schließen). Eine unbekannte Betttemperatur sperrt nicht,
    ein unbekannter Druckerzustand schon.
    """
    problems: list[str] = []
    if estop_active:
        problems.append("Not-Halt ist aktiv.")
    if not check_printer:
        return problems
    state = (printer_state or "").upper()
    if not state or state == "UNKNOWN":
        problems.append("Druckerzustand ist unbekannt (Drucker nicht verbunden?).")
    elif state in PRINT_STATES_BLOCKING:
        problems.append("Während eines Drucks gesperrt.")
    if bed_temp is not None and bed_temp > MAX_SWAP_BED_TEMP:
        problems.append(f"Druckbett ist noch zu heiß ({bed_temp:.1f} °C > {MAX_SWAP_BED_TEMP:.0f} °C).")
    return problems


# --- Kopie für die 3D-Ansicht ---------------------------------------------------------------------------------------------
VIEWER_MARKER = re.compile(r'(<script id="plate-changer-data" type="application/json">)(.*?)(</script>)', re.DOTALL)


def viewer_payload() -> dict[str, Any]:
    """Alles, was die 3D-Ansicht aus diesem Modul braucht."""
    return {
        "phases": [asdict(p) for p in PHASES],
        "checks": design_checks(),
        "door": {"hinge": list(DOOR_HINGE), "width": DOOR_WIDTH, "open_deg": DOOR_OPEN_DEG},
        "portal_front": list(portal_front_box()),
        "plate_half": PLATE_HALF,
        "slot_capacity": list(SLOT_CAPACITY),
        "tower": {"x": list(TOWER_X), "y": list(TOWER_Y), "profile": PROFILE, "guide": PLATE_GUIDE},
    }


def viewer_json() -> str:
    return json.dumps(viewer_payload(), ensure_ascii=False, indent=2, sort_keys=True)


def sync_viewer_html(path: Path, *, write: bool) -> bool:
    """Trägt die aktuellen Daten in die 3D-Ansicht ein. Gibt True zurück, wenn die Datei schon aktuell war."""
    html = path.read_text(encoding="utf-8")
    match = VIEWER_MARKER.search(html)
    if not match:
        raise ValueError(f'{path.name}: Block <script id="plate-changer-data"> fehlt.')
    current = json.loads(match.group(2))
    if current == json.loads(viewer_json()):
        return True
    if write:
        new = html[: match.start(2)] + "\n" + viewer_json() + "\n" + html[match.end(2) :]
        path.write_text(new, encoding="utf-8")
    return False
