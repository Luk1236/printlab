"""Plattenwechsler, zweite Auslegung: gedruckter SCARA-Arm auf einer kurzen Schiene rechts neben dem Drucker.

Ersetzt das Portal (X/Y/Z mit 500-mm-Y-Träger, Baugruppe 3), das zu groß war. Turm mit Regal und Waschstation,
Türöffner und Tür bleiben (Maße aus ``plate_changer``). Alle Maße in mm, Ursprung Bodenmitte des Druckers, X rechts,
Y vorne (Tür), Z oben; Winkel in Grad.

Aufbau:
* Schiene in Y-Richtung bei X = ``ARM_X``: hinten die Home-Station (Parkplatz mit Referenzschalter), vorne die
  Arbeitsstellung. Von dort erreicht der Arm Bett, alle Fächer und die Wäsche, ohne zu verfahren.
* Z-Säule mit Trapezspindel trägt das Gewicht; zwei waagerechte Glieder (Schulter, Ellbogen) und ein Handgelenk drehen um
  senkrechte Achsen. So sehen die Servos (STS3215) nur Beschleunigungsmomente, keine Last gegen die Schwerkraft.
* Greifer: Gabel mit zwei Zinken knapp unter der Plattenebene, ein Hakenschlitten fährt auf der Gabel und zieht die Platte
  über die Kante auf die Gabel bzw. schiebt sie hinunter. Die Platte liegt beim Tragen ganz auf; nur an der Kante gehalten
  kippt sie (1,2 N·m gegen etwa 1,0 N·m Magnet) und die 0,5-mm-Federstahlplatte hängt rund 11 mm durch.

Wie ``plate_changer.design_checks`` rechnet ``design_checks`` nur nach, ob die Maße zueinander passen; gemessen ist nichts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.app.services import plate_changer as pc

# --- Schiene und Arm ----------------------------------------------------------------------------------------------------
ARM_X = 230.0  # Säulenmitte; die Tür überstreicht höchstens X = Scharnier + Türbreite = 176,5
COLUMN_R = 30.0  # halbe Breite von Säule und Schienenwagen
HOME_Y = 370.0  # Parkplatz an der Home-Station (hinten)
WORK_Y = 620.0  # Arbeitsstellung (vorne): weit genug vorne, dass die Platte auf dem Weg zum Turm vor der Säule bleibt
RAIL_LEN = WORK_Y - HOME_Y + 2 * COLUMN_R  # Schiene samt Wagen
L1 = 180.0  # Schulter bis Ellbogen
L2 = 180.0  # Ellbogen bis Handgelenk
LINK_W = 36.0  # Breite der Glieder (Servogehäuse)
LINK_H = 30.0  # Höhe der Glieder
LINK_DZ = 70.0  # Glieder liegen so viel über der Gabel: Sie schwenken über Platte und Teile hinweg
WRIST_R = 25.0  # Handgelenk mit Servo
PART_MAX_H = pc.SLOT_CAPACITY[0]  # höchstes Teil, das ein Fach aufnimmt

# Gabel: Zinken liegen 1 mm unter der Plattenunterseite; Handgelenk sitzt hinter der Gabel
FORK_TINE = 270.0  # Zinkenlänge, Platte 257 mm + Haken
FORK_HUB = 25.0  # Nabe zwischen Zinkenende und Handgelenkmitte
FORK_W = 180.0  # Breite über beide Zinken
FORK_REACH = FORK_TINE + FORK_HUB  # Zinkenspitze bis Handgelenkmitte
HOOK_STROKE = pc.PLATE_EDGE + 6.0  # Haken zieht die Platte ganz auf die Gabel

# Massen und Antriebe (Annahmen für die Rechnung)
M_PLATE_WITH_PARTS = 0.80  # kg, Platte (≈ 0,28) plus Teile
M_FORK = 0.25  # kg, Gabel mit Hakenschlitten und Servo
M_LINKS = 0.60  # kg, beide Glieder mit Servos
SERVO_RATED_NM = 10 * 0.0981  # STS3215 12 V: 10 kg·cm Dauermoment
SERVO_STALL_NM = 30 * 0.0981  # 30 kg·cm Haltemoment
ARM_ALPHA = 2.0  # rad/s², Schwenkbeschleunigung der Schulter
HOOK_PULLEY_R = 6.4  # mm, GT2 20 Zähne
CARRIAGE_MOMENT_LIMIT = 20.0  # N·m, zulässiges Kippmoment am MGN12H-Wagen der Z-Säule (Annahme, Datenblatt prüfen)
Z_LEAD = 2.0  # mm, Tr8x2 wie beim Portal (selbsthemmend bei trockener Messingmutter)

SAFE_GAP = 15.0  # empfohlener Abstand zwischen Arm, Platte und Gehäuse
MIN_GAP = 3.0


@dataclass(frozen=True)
class Pose:
    """Eine Arbeitsstellung: Zinkenspitze (Platte liegt zwischen Spitze und Spitze + 257 in +Y) und Z der Gabel."""

    name: str
    label: str
    tip: tuple[float, float]
    z: float
    carries_plate: bool

    @property
    def wrist(self) -> tuple[float, float]:
        return (self.tip[0], self.tip[1] + FORK_REACH)


BASE = (ARM_X, WORK_Y)
_BED_TIP_Y = pc.JAW_OFFSET  # Spitze 6 mm vor der Plattenkante, vor dem Bettrahmen
_BED_OUT_TIP_Y = pc.PRINTER_HALF_D + 2.0 + 5.0  # Plattenhinterkante 5 mm vor der Tür-Ebene
_TOWER_OUT_TIP_Y = pc.TOWER_Y[1] + 5.0  # Platte ganz vor der Turmfront


def poses() -> list[Pose]:
    out = [
        Pose("bed_grip", "Am Bett greifen", (0.0, _BED_TIP_Y), pc.Z_SWAP, False),
        Pose("bed_out", "Platte vor dem Drucker", (0.0, _BED_OUT_TIP_Y), pc.Z_SWAP, True),
        Pose("tower_out", "Platte vor dem Turm", (pc.MAG_X, _TOWER_OUT_TIP_Y), pc.Z_SWAP, True),
    ]
    for i, z in enumerate(pc.SLOT_Z):
        out.append(Pose(f"slot_{i + 1}", f"Fach {i + 1} (Z {z:.0f})", (pc.MAG_X, _BED_TIP_Y), z, False))
    out.append(Pose("wash", f"Waschstation (Z {pc.WASH_Z:.0f})", (pc.MAG_X, _BED_TIP_Y), pc.WASH_Z, False))
    return out


# --- Kinematik ----------------------------------------------------------------------------------------------------------
def ik(wrist: tuple[float, float], base: tuple[float, float] = BASE) -> tuple[float, float, tuple[float, float]] | None:
    """Schulter- und Ellbogenwinkel für eine Handgelenkstellung; Ellbogen auf der Seite weg vom Drucker (größeres X).

    Gibt ``None`` zurück, wenn die Stellung außerhalb der Reichweite liegt.
    """
    dx, dy = wrist[0] - base[0], wrist[1] - base[1]
    d = math.hypot(dx, dy)
    if d > L1 + L2 or d < abs(L1 - L2):
        return None
    a = math.atan2(dy, dx)
    b = math.acos(max(-1.0, min(1.0, (L1 * L1 + d * d - L2 * L2) / (2 * L1 * d))))
    best = None
    for sign in (1, -1):
        sh = a + sign * b
        elbow = (base[0] + L1 * math.cos(sh), base[1] + L1 * math.sin(sh))
        el = math.atan2(wrist[1] - elbow[1], wrist[0] - elbow[0]) - sh
        if best is None or elbow[0] > best[2][0]:
            best = (math.degrees(sh), math.degrees(el), elbow)
    return best


def reach(pose: Pose) -> float:
    return math.dist(BASE, pose.wrist)


# --- Geometrie für die Abstandsprüfung (Draufsicht) ----------------------------------------------------------------------
Box = tuple[float, float, float, float]

PRINTER_BOX: Box = (-pc.PRINTER_HALF_W, -pc.PRINTER_HALF_D, pc.PRINTER_HALF_W, pc.PRINTER_HALF_D + 2.0)
TOWER_BOX: Box = (pc.TOWER_X[0], pc.TOWER_Y[0], pc.TOWER_X[1], pc.TOWER_Y[1])


def plate_on_fork(tip: tuple[float, float]) -> Box:
    return (tip[0] - pc.PLATE_HALF, tip[1], tip[0] + pc.PLATE_HALF, tip[1] + pc.PLATE_EDGE)


def _point_box(x: float, y: float, box: Box) -> float:
    return math.hypot(max(box[0] - x, 0.0, x - box[2]), max(box[1] - y, 0.0, y - box[3]))


def _segment_box(p: tuple[float, float], q: tuple[float, float], box: Box, half_width: float = 0.0) -> float:
    steps = 120
    best = math.inf
    for i in range(steps + 1):
        k = i / steps
        best = min(best, _point_box(p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k, box))
    return best - half_width


def _circle_box(c: tuple[float, float], r: float, box: Box) -> float:
    return _point_box(c[0], c[1], box) - r


def arm_segments(pose_wrist: tuple[float, float]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    sol = ik(pose_wrist)
    if sol is None:
        return []
    elbow = sol[2]
    return [(BASE, elbow), (elbow, pose_wrist)]


def transfer_path(steps: int = 40) -> list[tuple[float, float]]:
    """Weg der Zinkenspitze mit Platte, Höhe bleibt Z 220: vor dem Drucker quer bis vor den Turm, dann gerade hinein.

    Ein schräger Weg streift die Druckerecke: Die Platte ragt hinter der Spitze 257 mm nach vorne, die Spitze selbst
    liegt aber nur 7 mm vor der Tür-Ebene.
    """
    a = (0.0, _BED_OUT_TIP_Y)
    b = (pc.MAG_X, _BED_OUT_TIP_Y)
    c = (pc.MAG_X, _TOWER_OUT_TIP_Y)
    path = [(a[0] + (b[0] - a[0]) * i / steps, a[1]) for i in range(steps + 1)]
    path += [(b[0], b[1] + (c[1] - b[1]) * i / steps) for i in range(1, steps + 1)]
    return path


def path_clearances() -> dict[str, float]:
    """Kleinste Abstände auf dem Plattenweg (Draufsicht): Platte zu Drucker, Turm und Säule; Glieder zu Drucker und Turm.

    Die Glieder liegen ``LINK_DZ`` über der Gabel und schwenken über Platte und Teile hinweg, sie werden deshalb nur gegen
    die Gehäuse geprüft (die bis über die Gliederhöhe reichen). Den Abstand nach oben über den Teilen gibt ``arm_over_parts``.
    """
    plate_printer = plate_tower = plate_column = arm_printer = arm_tower = math.inf
    for tip in transfer_path():
        plate = plate_on_fork(tip)
        plate_printer = min(plate_printer, _point_box_gap(plate, PRINTER_BOX))
        plate_tower = min(plate_tower, _point_box_gap(plate, TOWER_BOX))
        plate_column = min(plate_column, _circle_box(BASE, COLUMN_R, plate))
        segs = arm_segments((tip[0], tip[1] + FORK_REACH))
        if not segs:
            return {"unreachable": -1.0}
        for p, q in segs:
            arm_printer = min(arm_printer, _segment_box(p, q, PRINTER_BOX, LINK_W / 2))
            arm_tower = min(arm_tower, _segment_box(p, q, TOWER_BOX, LINK_W / 2))
    return {
        "plate_printer": plate_printer,
        "plate_tower": plate_tower,
        "plate_column": plate_column,
        "arm_printer": arm_printer,
        "arm_tower": arm_tower,
    }


def arm_over_parts() -> float:
    """Luft zwischen Unterkante der Glieder und dem höchsten Teil auf der getragenen Platte."""
    return LINK_DZ - LINK_H / 2 - (pc.PLATE_THICKNESS + PART_MAX_H)


def _point_box_gap(a: Box, b: Box) -> float:
    """Abstand zweier achsparalleler Rechtecke; 0 bei Berührung, negativ bei Überdeckung (Tiefe der Überdeckung)."""
    dx = max(b[0] - a[2], a[0] - b[2])
    dy = max(b[1] - a[3], a[1] - b[3])
    if dx < 0 and dy < 0:
        return max(dx, dy)
    return math.hypot(max(dx, 0.0), max(dy, 0.0))


def wait_pose() -> Pose:
    """Stellung, in der der Arm wartet, während die Tür schwenkt: Gabel leer vor dem Turm."""
    return Pose("wait", "Warten vor dem Turm (Tür schwenkt)", (pc.MAG_X, _TOWER_OUT_TIP_Y + 60.0), pc.Z_SWAP, False)


def arm_door_wait_clearance() -> float:
    """Abstand von Gliedern, Handgelenk und Gabel in der Wartestellung zur Tür über den ganzen Öffnungsweg."""
    pose = wait_pose()
    boxes = []
    for p, q in arm_segments(pose.wrist):
        boxes.append((min(p[0], q[0]) - LINK_W / 2, min(p[1], q[1]) - LINK_W / 2, max(p[0], q[0]) + LINK_W / 2,
                      max(p[1], q[1]) + LINK_W / 2))  # fmt: skip
    tip = pose.tip
    boxes.append((tip[0] - FORK_W / 2, tip[1], tip[0] + FORK_W / 2, tip[1] + FORK_REACH))
    return min(pc.door_sweep_gap(b) for b in boxes)


def door_clearance() -> float:
    """Abstand von Säule und eingeklapptem Arm (Parkstellung) zur Tür über ihren ganzen Öffnungsweg."""
    column = (ARM_X - COLUMN_R, HOME_Y - COLUMN_R, ARM_X + COLUMN_R, WORK_Y + COLUMN_R)
    return pc.door_sweep_gap(column)


def arm_in_front(pose: Pose, front: float) -> float:
    """Wie weit Glieder und Handgelenk vor einer Front (Y) bleiben; nur Gabel und Haken dürfen hinein."""
    segs = arm_segments(pose.wrist)
    worst = math.inf
    for p, q in segs:
        for k in range(21):
            y = p[1] + (q[1] - p[1]) * k / 20
            worst = min(worst, y - front - LINK_W / 2)
    worst = min(worst, pose.wrist[1] - front - WRIST_R)
    return worst


# --- Momente ------------------------------------------------------------------------------------------------------------
def shoulder_torque_nm() -> float:
    """Beschleunigungsmoment der Schulter bei voller Ausladung mit Platte (Glieder als Stab)."""
    r = (L1 + L2) / 1000
    inertia = (M_PLATE_WITH_PARTS + M_FORK) * r * r + M_LINKS * r * r / 3
    return inertia * ARM_ALPHA


def gravity_arm_nm() -> float:
    """Moment, das ein Knickarm an der Schulter gegen die Schwerkraft bräuchte (zum Vergleich, deshalb SCARA)."""
    r = 0.35
    return (M_PLATE_WITH_PARTS + M_FORK) * 9.81 * r + M_LINKS * 9.81 * r / 2


def carriage_moment_nm() -> float:
    """Kippmoment am Z-Wagen bei größter Reichweite der Aufgaben."""
    r = max(reach(p) for p in poses()) / 1000
    return (M_PLATE_WITH_PARTS + M_FORK) * 9.81 * (r + FORK_REACH / 2000) + M_LINKS * 9.81 * r / 2


def hook_force_n() -> float:
    """Zugkraft des Hakens mit dem Dauermoment des Servos."""
    return SERVO_RATED_NM / (HOOK_PULLEY_R / 1000)


def z_travel() -> float:
    zs = [p.z for p in poses()]
    return max(zs) - min(zs)


# --- Prüfung ------------------------------------------------------------------------------------------------------------
def design_checks() -> list[dict[str, Any]]:
    worst = max(poses(), key=reach)
    tightest = min(poses(), key=reach)
    clear = path_clearances()
    front_printer = pc.PRINTER_HALF_D + 2.0
    in_printer = min(arm_in_front(p, front_printer) for p in poses() if p.name.startswith("bed"))
    in_tower = min(arm_in_front(p, pc.TOWER_Y[1]) for p in poses() if p.name.startswith(("slot", "wash", "tower")))
    check = pc._check  # noqa: SLF001 - gleiche Bewertung wie beim Portal
    return [
        check(
            "arm_reach",
            "Reichweite Arm ↔ fernste Stellung",
            L1 + L2 - reach(worst),
            20.0,
            "mm",
            f"Fernste Stellung: {worst.label} ({reach(worst):.0f} mm von der Säule), Arm {L1 + L2:.0f} mm.",
            hard=0.0,
        ),
        check(
            "arm_fold",
            "Kleinste Reichweite (Arm nicht ganz eingeklappt)",
            reach(tightest) - abs(L1 - L2) - 2 * WRIST_R,
            10.0,
            "mm",
            f"Nächste Stellung: {tightest.label} ({reach(tightest):.0f} mm); Handgelenk darf nicht an die Säule.",
            hard=0.0,
        ),
        check(
            "arm_door",
            "Säule und Schiene ↔ Tür (ganzer Öffnungsweg)",
            door_clearance(),
            SAFE_GAP,
            "mm",
            f"Säule bei X {ARM_X:.0f} ± {COLUMN_R:.0f}, die Tür überstreicht höchstens "
            f"X {pc.DOOR_HINGE[0] + pc.DOOR_WIDTH:.1f}.",
            hard=MIN_GAP,
        ),
        check(
            "arm_door_wait",
            "Arm in Wartestellung ↔ Tür (ganzer Öffnungsweg)",
            arm_door_wait_clearance(),
            SAFE_GAP,
            "mm",
            "Während die Tür auf- und zuschwenkt, wartet der Arm mit leerer Gabel vor dem Turm.",
            hard=MIN_GAP,
        ),
        check(
            "arm_outside_printer",
            "Glieder und Handgelenk ↔ Tür-Ebene (nur Gabel im Drucker)",
            in_printer,
            SAFE_GAP,
            "mm",
            "In den Drucker ragen nur Zinken und Haken; Glieder und Handgelenk bleiben davor.",
            hard=0.0,
        ),
        check(
            "path_printer",
            "Platte auf dem Weg zum Turm ↔ Druckerfront",
            clear["plate_printer"],
            5.0,
            "mm",
            "Platte wird erst ganz aus dem Drucker gezogen, dann quer zum Turm gefahren.",
            hard=0.0,
        ),
        check(
            "path_tower",
            "Platte auf dem Weg ↔ Turmfront",
            clear["plate_tower"],
            5.0,
            "mm",
            "Zur Turmfront geht es erst gerade hinein, wenn die Platte vor dem Fach steht.",
            hard=0.0,
        ),
        check(
            "path_column",
            "Platte auf dem Weg ↔ Säule",
            clear["plate_column"],
            SAFE_GAP,
            "mm",
            f"Säule bei Y {WORK_Y:.0f}: Die Platte reicht auf der Gabel bis Y {_BED_OUT_TIP_Y + pc.PLATE_EDGE:.0f}.",
            hard=MIN_GAP,
        ),
        check(
            "arm_outside_tower",
            "Glieder und Handgelenk ↔ Turmfront (nur Gabel im Fach)",
            in_tower,
            SAFE_GAP,
            "mm",
            "Beim Greifen im Fach und in der Wäsche bleiben Glieder und Handgelenk vor der Turmfront.",
            hard=0.0,
        ),
        check(
            "arm_over_parts",
            "Glieder ↔ höchstes Teil auf der getragenen Platte",
            arm_over_parts(),
            SAFE_GAP,
            "mm",
            f"Glieder {LINK_DZ:.0f} mm über der Gabel, Teile bis {PART_MAX_H:.1f} mm hoch (Fachhöhe).",
            hard=MIN_GAP,
        ),
        check(
            "path_arm_housing",
            "Glieder auf dem Weg ↔ Drucker und Turm",
            min(clear["arm_printer"], clear["arm_tower"]),
            SAFE_GAP,
            "mm",
            "Draufsicht; Drucker und Turm reichen höher als die Glieder.",
            hard=0.0,
        ),
        check(
            "fork_tower",
            "Gabel ↔ Turmsteher (je Seite)",
            (pc.TOWER_CLEAR_X - FORK_W) / 2,
            SAFE_GAP,
            "mm",
            f"Gabel {FORK_W:.0f} mm breit, lichte Weite zwischen den Stehern {pc.TOWER_CLEAR_X:.0f} mm.",
            hard=MIN_GAP,
        ),
        check(
            "hook_stroke",
            "Zinkenlänge ↔ Hakenweg",
            FORK_TINE - HOOK_STROKE,
            3.0,
            "mm",
            f"Haken zieht die Platte {HOOK_STROKE:.0f} mm weit auf die Gabel.",
            hard=0.0,
        ),
        check(
            "servo_shoulder",
            "Dauermoment STS3215 ÷ Schulter beim Beschleunigen",
            SERVO_RATED_NM / shoulder_torque_nm(),
            2.0,
            "×",
            f"{shoulder_torque_nm():.2f} N·m bei {ARM_ALPHA:.0f} rad/s² mit Platte. Ein Knickarm bräuchte gegen die "
            f"Schwerkraft {gravity_arm_nm():.1f} N·m, das 4-Fache des Dauermoments: deshalb SCARA mit Spindel.",
            hard=1.0,
        ),
        check(
            "carriage_moment",
            "Zulässiges Kippmoment ÷ Moment am Z-Wagen",
            CARRIAGE_MOMENT_LIMIT / carriage_moment_nm(),
            2.0,
            "×",
            f"{carriage_moment_nm():.1f} N·m bei größter Reichweite; zulässig {CARRIAGE_MOMENT_LIMIT:.0f} N·m angenommen.",
            hard=1.0,
        ),
        check(
            "hook_force",
            "Zugkraft des Hakens",
            hook_force_n(),
            50.0,
            "N",
            "Dauermoment über ein GT2-Rad mit 20 Zähnen. Die Abzugskraft der Platte vom Magnetbett ist nicht gemessen.",
            hard=20.0,
        ),
    ]


def design_summary() -> dict[str, Any]:
    checks = design_checks()
    return {
        "checks": checks,
        "fail": [c["id"] for c in checks if c["status"] == "fail"],
        "warn": [c["id"] for c in checks if c["status"] == "warn"],
        "z_travel": z_travel(),
        "rail_len": RAIL_LEN,
    }
