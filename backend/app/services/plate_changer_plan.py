"""Bauteil- und Bewegungsplan des Plattenwechslers: Antriebe, Fahrzeiten, Stromversorgung, Pinbelegung, Referenzfahrt.

Ergänzt ``plate_changer`` (Maße, Ablauf, Konstruktionsprüfung) um alles, was für den Bau und die spätere Inbetriebnahme fehlt.
Alle Maße kommen aus ``plate_changer``; hier stehen nur die zusätzlichen Auslegungswerte. **Alles Annahmen und Rechnung, nichts ist
am Gerät gemessen.** Annahmen sind als solche benannt (``ASSUMPTION``), damit man sie beim Aufbau durch Messwerte ersetzt.
Beschrieben in ``werkzeuge/automation_hardware/TUER_MAGAZIN_WASCHSTATION.md``, Abschnitte 5 bis 9.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.app.services import plate_changer as pc

G = 9.81  # m/s²
STEPS_PER_REV = 200  # 1,8°-Motor
MICROSTEPS = 16  # TMC2209 im StealthChop-Betrieb
REQUIRED_TORQUE_MARGIN = 2.0  # verlangtes Verhältnis nutzbares Moment / benötigtes Moment

# Fahrzeit-Annahmen (am Gerät messen)
DOOR_SERVO_DEG_PER_S = 66.7  # gpio_mechanik: 2° je 0,03 s
DOOR_SERVO_SWING_DEG = 144.0  # Servo-Weg Tür zu (10°) bis offen (154°), siehe gpio_mechanik
BED_Z_SPEED = 10.0  # mm/s Druckerbett (ASSUMPTION: Herstellerangabe fehlt)
BED_REST_Z = pc.HOME_Z  # Bett in Ruhe, siehe 3D-Ansicht
MAGNET_S = 0.4  # Anzugs-/Abfallzeit des Elektromagneten
SETTLE_S = 0.2  # Beruhigung nach jeder Bewegung


@dataclass(frozen=True)
class Axis:
    """Eine Bewegungsachse des Wechslers (alle Werte Auslegung, nicht gemessen)."""

    id: str
    name: str
    drive: str  # "belt" oder "spindle"
    travel_mm: float  # genutzter Verfahrweg
    mm_per_rev: float  # Riemen: Pulleyumfang; Spindel: Steigung
    v_max: float  # mm/s
    accel: float  # mm/s²
    moving_mass_kg: float  # ASSUMPTION: bewegte Masse samt allem, was mitfährt
    motors: int
    motor_torque_nm: float  # ASSUMPTION: nutzbares Moment je Motor bei der Solldrehzahl, 12 V, 1,2 A
    spindle_mean_dia_mm: float = 0.0
    friction: float = 0.0  # Gewindereibung (Spindel)
    efficiency: float = 1.0  # Wirkungsgrad (Spindel)

    @property
    def steps_per_mm(self) -> float:
        return STEPS_PER_REV * MICROSTEPS / self.mm_per_rev

    @property
    def resolution_um(self) -> float:
        return 1000.0 / self.steps_per_mm

    @property
    def rpm(self) -> float:
        return self.v_max / self.mm_per_rev * 60.0

    @property
    def step_rate_hz(self) -> float:
        return self.v_max * self.steps_per_mm

    def required_torque_nm(self) -> float:
        """Moment je Motor beim Beschleunigen (Riemen: mit 2 % Führungsreibung; Spindel: gegen Gewicht und Beschleunigung)."""
        mass = self.moving_mass_kg / self.motors
        if self.drive == "belt":
            force = mass * (self.accel / 1000.0 + 0.02 * G)
            return force * (self.mm_per_rev / 1000.0) / (2 * math.pi)
        force = mass * (self.accel / 1000.0 + G)
        return force * (self.mm_per_rev / 1000.0) / (2 * math.pi * self.efficiency)

    @property
    def torque_ratio(self) -> float:
        return self.motor_torque_nm / self.required_torque_nm()

    def lead_angle_deg(self) -> float:
        return math.degrees(math.atan(self.mm_per_rev / (math.pi * self.spindle_mean_dia_mm)))

    def self_locking(self) -> bool:
        """Selbsthemmend, wenn der Reibwinkel über dem Steigungswinkel liegt: Die Last fällt dann ohne Strom nicht herunter."""
        return self.drive == "spindle" and math.degrees(math.atan(self.friction)) > self.lead_angle_deg()


X_AXIS = Axis("x", "X Querträger", "belt", pc.MAG_X, 40.0, 250.0, 800.0, 2.2, 1, 0.15)
Y_AXIS = Axis("y", "Y Greiferarm", "belt", pc.PARK_Y - pc.Y_GRIP, 40.0, 200.0, 600.0, 1.0, 1, 0.15)
# Tr8x2: Die Steigung 8 mm der ersten Auslegung ist nicht selbsthemmend, der Querträger fiele bei Not-Halt auf Platte oder Regal.
Z_AXIS = Axis(
    "z", "Z Hub (2 Spindeln)", "spindle", max(pc.SLOT_Z) - pc.WASH_Z, 2.0, 15.0, 60.0, 3.5, 2, 0.15, 7.0, 0.15, 0.25
)
AXES = (X_AXIS, Y_AXIS, Z_AXIS)
LEGACY_Z_LEAD_MM = 8.0  # Tr8x8 der ersten Auslegung, nur für den Vergleich im Plan

Z_TOP_ENDSTOP = max(pc.SLOT_Z) + 2.0  # Z-Referenz oben: 2 mm über Fach 4
Z_SOFT_MIN = 40.0
Z_SOFT_MAX = Z_TOP_ENDSTOP
X_SOFT_MIN = -5.0
X_SOFT_MAX = pc.MAG_X + 5.0


def move_time(distance_mm: float, v_max: float, accel: float) -> float:
    """Fahrzeit mit Trapezprofil (bei kurzem Weg Dreieck)."""
    d = abs(distance_mm)
    if d == 0:
        return 0.0
    ramp = v_max * v_max / accel  # Strecke für Beschleunigen plus Bremsen
    if d >= ramp:
        return d / v_max + v_max / accel
    return 2.0 * math.sqrt(d / accel)


def _t(axis: Axis, distance: float) -> float:
    return move_time(distance, axis.v_max, axis.accel) + SETTLE_S


def cycle_report(empty_slot: int = 0, fresh_slot: int = 1) -> dict[str, Any]:
    """Dauer eines Wechsels je Phase (0-basierte Fächer: leeres Fach für die alte Platte, Fach der frischen Platte)."""
    ze = pc.SLOT_Z[empty_slot]
    zf = pc.SLOT_Z[fresh_slot]
    arm_in = pc.PARK_Y - pc.Y_GRIP  # Greiferbacke von der Parkposition bis zur Plattenmitte im Drucker
    pull = pc.TRANSFER_Y  # Plattenmitte von Y = 0 bis zum Übergabekorridor
    door = DOOR_SERVO_SWING_DEG / DOOR_SERVO_DEG_PER_S
    bed = (BED_REST_Z - pc.Z_SWAP) / BED_Z_SPEED
    rows = [
        ("door_open", "Tür öffnet", door, "Servo"),
        ("bed_down", "Bett fährt auf Wechselhöhe", bed, "Drucker"),
        ("to_printer", "Shuttle vor den Drucker", max(_t(X_AXIS, pc.MAG_X), _t(Y_AXIS, arm_in)), "X und Y"),
        ("pull_old", "Alte Platte herausziehen", _t(Y_AXIS, pull) + MAGNET_S, "Y, Magnet"),
        ("to_rack", "Zum Plattenregal", max(_t(X_AXIS, pc.MAG_X), _t(Z_AXIS, ze - pc.Z_SWAP)), "X und Z"),
        ("store_old", "Alte Platte ablegen", _t(Y_AXIS, pull) + MAGNET_S, "Y, Magnet"),
        ("lift_fresh", "Zur frischen Platte", _t(Z_AXIS, zf - ze), "Z"),
        ("pull_fresh", "Frische Platte holen", _t(Y_AXIS, pull) + MAGNET_S, "Y, Magnet"),
        ("to_printer_fresh", "Zurück zum Drucker", max(_t(X_AXIS, pc.MAG_X), _t(Z_AXIS, pc.Z_SWAP - zf)), "X und Z"),
        ("place_fresh", "Platte auf das Bett legen", _t(Y_AXIS, pull) + MAGNET_S, "Y, Magnet"),
        (
            "park_close",
            "Parken, Tür schließt",
            max(_t(Y_AXIS, arm_in), _t(X_AXIS, pc.MAG_X)) + door + bed,
            "Y, X, Servo, Drucker",
        ),
    ]
    phases = [{"id": i, "label": lbl, "seconds": round(s, 1), "by": by} for i, lbl, s, by in rows]
    ids = [p.id for p in pc.PHASES]
    if [r[0] for r in rows] != ids:
        raise RuntimeError("cycle_report und plate_changer.PHASES laufen auseinander")
    return {
        "phases": phases,
        "total_s": round(sum(r[2] for r in rows), 1),
        "empty_slot": empty_slot,
        "fresh_slot": fresh_slot,
    }


def cycle_range() -> tuple[float, float]:
    """Kürzester und längster Wechsel über alle Fachkombinationen."""
    totals = [cycle_report(e, f)["total_s"] for e in range(pc.SLOT_COUNT) for f in range(pc.SLOT_COUNT) if e != f]
    return min(totals), max(totals)


# --- Stromversorgung (12 V, Netzteil LRS-100-12) ---------------------------------------------------------------------------
PSU_AMPS = 8.5
POWER_HEADROOM = 0.25  # verlangte Reserve
# (Name, Ampere bei 12 V, Gruppe) – ASSUMPTION: typische Datenblattwerte, am Gerät messen
LOADS: tuple[tuple[str, float, str], ...] = (
    ("4× NEMA17 fahrend (je 0,8 A)", 3.2, "move"),
    ("4× NEMA17 haltend (je 0,35 A)", 1.4, "hold"),
    ("Elektromagnet 12 V / 80 N", 0.6, "move"),
    ("Tür-Servo MG90S über 5-V-Wandler (Anlauf)", 0.45, "door"),
    ("Walzenmotor N20 (Anlauf)", 0.8, "wash"),
    ("Peristaltikpumpe", 0.3, "wash"),
    ("Radiallüfter 5015", 0.25, "wash"),
    ("Bewegungs-Controller und Relais", 0.3, "base"),
)


def power_budget() -> list[dict[str, Any]]:
    """Strombedarf je Betriebsfall und Reserve zum Netzteil."""

    def total(groups: set[str]) -> float:
        return sum(a for _, a, g in LOADS if g in groups)

    cases = [
        ("Wechsel (alle Achsen und Magnet)", total({"move", "base"})),
        ("Waschen (Achsen stehen unter Strom)", total({"hold", "wash", "base"})),
        ("Tür öffnen (Achsen stehen unter Strom)", total({"hold", "door", "base"})),
        ("Alles gleichzeitig (nicht vorgesehen)", total({"move", "wash", "door", "base"})),
    ]
    return [
        {
            "case": name,
            "amps": round(amps, 2),
            "load_pct": round(100 * amps / PSU_AMPS, 0),
            "ok": amps <= PSU_AMPS * (1 - POWER_HEADROOM),
        }
        for name, amps in cases
    ]


# --- Raspberry-Pi-Pins (BCM) -------------------------------------------------------------------------------------------------
# Name -> (BCM, Pin, Richtung, Funktion). Schritte, Richtung und Endschalter der drei Achsen liegen NICHT am Pi, sondern am
# Bewegungs-Controller (USB), siehe Plan Abschnitt 7.
PI_PINS: dict[str, tuple[int, int, str, str]] = {
    "door_servo": (18, 12, "PWM", "Tür-Servo MG90S (Hardware-PWM)"),
    "door_endstop_open": (23, 16, "in", "Endschalter Tür offen"),
    "door_endstop_closed": (24, 18, "in", "Endschalter Tür zu"),
    "plate_sensor": (25, 22, "in", "Platte liegt plan auf dem Heizbett"),
    "estop": (26, 37, "in", "Not-Halt-Taster (Öffner), Software-Pfad"),
    "button_ack": (16, 36, "in", "Quittiertaste"),
    "button_pause": (20, 38, "in", "Pause-Taste"),
    "status_led": (21, 40, "out", "Status-LED"),
    "washer_roller": (19, 35, "out", "Relais Walzenmotor N20"),
    "washer_fan": (13, 33, "out", "Relais Trocknungsgebläse"),
    "washer_pump": (6, 31, "out", "Relais Peristaltikpumpe (früher BCM 26, doppelt mit dem Not-Halt)"),
    "slot1_sensor": (4, 7, "in", "Gabellichtschranke Fach 1"),
    "slot2_sensor": (5, 29, "in", "Gabellichtschranke Fach 2"),
    "slot3_sensor": (12, 32, "in", "Gabellichtschranke Fach 3"),
    "slot4_sensor": (7, 26, "in", "Gabellichtschranke Fach 4"),
}


def pin_conflicts() -> list[str]:
    """Doppelt belegte BCM- oder Board-Pins."""
    out: list[str] = []
    for idx in (0, 1):
        seen: dict[int, str] = {}
        for name, spec in PI_PINS.items():
            if spec[idx] in seen:
                out.append(f"{'BCM' if idx == 0 else 'Pin'} {spec[idx]}: {seen[spec[idx]]} und {name}")
            seen[spec[idx]] = name
    return out


# --- Referenzfahrt -------------------------------------------------------------------------------------------------------------
# (Schritt, Achse, Beschreibung, Endschalter, Position nach der Referenz)
HOMING: tuple[tuple[int, str, str, str, float], ...] = (
    (
        1,
        "Z",
        "Nach oben auf den Endschalter (Öffner), 3 mm zurück, langsam erneut",
        "Mikroschalter oben",
        Z_TOP_ENDSTOP,
    ),
    (2, "Y", "Arm ganz zurück bis Parkposition, 3 mm vor, langsam erneut", "Mikroschalter hinten", pc.PARK_Y),
    (3, "X", "Zum Turm bis zum Endschalter, 3 mm zurück, langsam erneut", "Mikroschalter am Turm", pc.MAG_X),
)
HOMING_FAST = {"X": 30.0, "Y": 30.0, "Z": 5.0}  # mm/s zum Schalter
HOMING_SLOW = {"X": 5.0, "Y": 5.0, "Z": 1.0}  # mm/s zweiter Anlauf
HOMING_BACKOFF_MM = 3.0


def axis_checks() -> list[dict[str, Any]]:
    """Antriebsprüfung je Achse: Moment, Schrittfrequenz, Selbsthemmung."""
    out = []
    for ax in AXES:
        out.append(
            {
                "axis": ax.id,
                "steps_per_mm": round(ax.steps_per_mm, 1),
                "resolution_um": round(ax.resolution_um, 1),
                "rpm": round(ax.rpm, 0),
                "step_rate_khz": round(ax.step_rate_hz / 1000, 1),
                "torque_need_nm": round(ax.required_torque_nm(), 3),
                "torque_have_nm": ax.motor_torque_nm,
                "torque_ratio": round(ax.torque_ratio, 1),
                "ok": ax.torque_ratio >= REQUIRED_TORQUE_MARGIN and (ax.drive != "spindle" or ax.self_locking()),
                "self_locking": ax.self_locking() if ax.drive == "spindle" else None,
            }
        )
    return out
