"""Druckteile des Plattenwechslers (Baugruppen 1 bis 4) als druckfertige STL-Dateien, mit Material und Druckeinstellungen.

Erzeugt jedes Teil mit Bohrungen, Taschen und Einsätzen als geschlossenen Volumenkörper (CSG mit ``manifold3d``), legt es
in Drucklage (flache Seite unten) und prüft, dass es auf das Druckbett des Bambu Lab P2S passt (256 × 256 × 256 mm, hier mit
3 mm Rand). Die Fachkämme und die Waschwanne werden in Aufbaukoordinaten konstruiert (Ursprung Bodenmitte des Druckers wie in
``backend/app/services/plate_changer.py``), damit der Generator nachrechnen kann, dass die Platte frei durch Regal und Wanne fährt.

Aufruf (``manifold3d`` ist keine Projektabhängigkeit, einmalig ``pip install manifold3d numpy``)::

    python werkzeuge/automation_hardware/bauteile.py             # STL-Dateien und models_stl/bauteile/bauteile.json
    python werkzeuge/automation_hardware/bauteile.py --tabelle   # Teiletabelle für TUER_MAGAZIN_WASCHSTATION.md

Alle Maße sind Auslegung, nichts ist am Gerät gemessen. Werte, die auf einer Annahme beruhen, stehen in ``ANNAHMEN`` und im
Hinweis des Teils; vor dem Druck am Aufbau gegenprüfen.
"""

from __future__ import annotations

import json
import math
import struct
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from functools import reduce
from pathlib import Path

from manifold3d import Manifold

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.services import plate_changer as pc  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "models_stl" / "bauteile"
BED = 256.0
BED_MARGIN = 3.0  # Rand auf dem Druckbett
SEG = 64  # Kreisauflösung

# Bohrungen (Durchmesser in mm)
M2_TAP = 2.2  # selbstschneidend M2 / M2,5
M3_CLEAR = 3.4
M3_TAP = 2.5
M3_INSERT = 4.0  # Ruthex M3 (Herstellerangabe 4,0 mm, Tiefe 5,7 mm)
M3_HEAD = 6.2
M4_CLEAR = 4.5
M5_CLEAR = 5.5
M5_CSK = 10.4  # Senkkopf M5 (DIN 7991)
NEMA17_WIDTH = 42.3  # Kantenlänge des Motorgehäuses

ANNAHMEN = {
    "glass_thickness": 4.0,  # Glasdicke der P2S-Tür (nicht veröffentlicht, messen)
    "servo_overhang": 18.0,  # Überstand des Servohalters vor der Druckeroberkante (statt 14 mm, Servokörper muss davor hängen)
}

# Material: Dichte g/cm³ und Begründung
MATERIAL = {
    "ASA": (1.07, "UV- und wärmefest bis etwa 95 °C, für Teile am Drucker und am warmen Motor/Magneten"),
    "PETG": (1.27, "zäh, beständig gegen Isopropanol, für Halter, Klemmen und alles im Waschbereich"),
    "PETG-CF": (1.30, "steif, für tragende Teile des Shuttles; gehärtete Düse (beim P2S Serie)"),
}


@dataclass
class Teil:
    id: str
    name: str
    baugruppe: int
    datei: str
    menge: int
    material: str
    waende: int
    infill: int  # Prozent
    muster: str
    stuetzen: str
    drucklage: str
    hinweis: str
    groesse_mm: list[float] = field(default_factory=list)
    volumen_cm3: float = 0.0
    gewicht_g: float = 0.0
    dreiecke: int = 0


# --- Grundkörper ----------------------------------------------------------------------------------------------------------
def box(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> Manifold:
    return Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def _cos_sin(deg: float) -> tuple[float, float]:
    """cos/sin in Grad, für Vielfache von 90° exakt (keine Rundungsreste in den Flächen)."""
    if deg % 90 == 0:
        k = int(deg // 90) % 4
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[k]
    a = math.radians(deg)
    return math.cos(a), math.sin(a)


def rotate(m: Manifold, v: tuple[float, float, float]) -> Manifold:
    """Drehung um die globale X-, dann Y-, dann Z-Achse (Grad), wie ``Manifold.rotate`` dokumentiert.

    ``Manifold.rotate`` selbst liefert in manifold3d 3.5.4 (Windows-Wheel) falsche Geometrie (verzerrt, doppeltes
    Volumen, nicht einmal reproduzierbar); ``transform`` mit einer Matrix ist korrekt. Deshalb nie ``.rotate`` verwenden.
    """
    cx, sx = _cos_sin(v[0])
    cy, sy = _cos_sin(v[1])
    cz, sz = _cos_sin(v[2])
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def mat(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    r = mat(rz, mat(ry, rx))
    return m.transform([[*row, 0.0] for row in r])


def cyl(axis: str, cx: float, cy: float, cz: float, length: float, d: float, *, segments: int = SEG) -> Manifold:
    """Zylinder entlang ``axis`` mit Mittelpunkt (cx, cy, cz) der Grundfläche, Länge in Achsrichtung positiv."""
    body = Manifold.cylinder(length, d / 2, d / 2, segments)
    if axis == "x":
        body = rotate(body, (0, 90, 0))
    elif axis == "y":
        body = rotate(body, (-90, 0, 0))
    return body.translate((cx, cy, cz))


def hex_z(cx: float, cy: float, z0: float, height: float, across_flats: float) -> Manifold:
    """Sechskant-Muttertasche (Schlüsselweite ``across_flats``)."""
    return Manifold.cylinder(height, across_flats / math.sqrt(3), across_flats / math.sqrt(3), 6).translate(
        (cx, cy, z0)
    )


def union(parts: list[Manifold]) -> Manifold:
    return reduce(lambda a, b: a + b, parts)


def drill_z(cx: float, cy: float, d: float, z0: float = -1.0, z1: float = 500.0) -> Manifold:
    return cyl("z", cx, cy, z0, z1 - z0, d)


def counterbore_z(cx: float, cy: float, z_top: float, d_head: float = M3_HEAD, depth: float = 3.2) -> Manifold:
    return cyl("z", cx, cy, z_top - depth, depth + 1.0, d_head)


def slot_z(cx: float, cy: float, d: float, length: float, along: str = "x") -> Manifold:
    """Langloch senkrecht durch das Teil, ``length`` = Weg der Schraube."""
    a = drill_z(cx - (length / 2 if along == "x" else 0), cy - (length / 2 if along == "y" else 0), d)
    b = drill_z(cx + (length / 2 if along == "x" else 0), cy + (length / 2 if along == "y" else 0), d)
    if along == "x":
        mid = box(cx - length / 2, cy - d / 2, -1, cx + length / 2, cy + d / 2, 500)
    else:
        mid = box(cx - d / 2, cy - length / 2, -1, cx + d / 2, cy + length / 2, 500)
    return a + b + mid


def lay_flat(m: Manifold) -> Manifold:
    """Teil auf das Druckbett legen: kleinste Ecke auf (0, 0, 0)."""
    x0, y0, z0, *_ = m.bounding_box()
    return m.translate((-x0, -y0, -z0))


def rot_to_bed(m: Manifold, matrix: list[list[float]]) -> Manifold:
    """Affine Abbildung (3×4) aus Aufbau- in Druckkoordinaten, danach auf das Bett legen."""
    return lay_flat(m.transform(matrix))


# --- Baugruppe 1: Türöffner -----------------------------------------------------------------------------------------------
def tuer_servohalter() -> Manifold:
    """1a: Platte auf der Druckeroberseite (VHB), Servo MG90S hängt im Überstand, Abtrieb nach unten."""
    w, d, t = 54.0, 42.0, 6.0
    over = ANNAHMEN["servo_overhang"]
    body = box(-w / 2, 0, 0, w / 2, d, t)
    ribs = [box(-w / 2, 0, t, -w / 2 + 4, d, 26), box(w / 2 - 4, 0, t, w / 2, d, 26), box(-w / 2, 0, t, w / 2, 4, 18)]
    body = union([body, *ribs])
    # Servotasche 23,2 × 12,6 im Überstand (vordere 18 mm), 3 mm Steg vorne
    y_front = d - 3.0
    pocket = box(-11.6, y_front - 12.6, -1, 11.6, y_front, 50)
    ears = [drill_z(x, y_front - 6.3, M2_TAP) for x in (-13.8, 13.8)]  # Lochabstand MG90S 27,6 mm
    slots = [slot_z(x, 10.0, M4_CLEAR, 6.0, along="y") for x in (-15.0, 15.0)]
    assert d - over < y_front - 12.6, "Servokörper muss ganz im Überstand hängen"
    return body - pocket - union(ears) - union(slots)


def tuer_schubstange() -> Manifold:
    """1b: Kniehebel-Schubstange, 90 mm von Auge zu Auge, für M3-Kugelgelenke."""
    pitch, eye_d, t = 90.0, 12.0, 7.0
    bar = box(-pitch / 2, -4, 0, pitch / 2, 4, 5)
    eyes = [cyl("z", x, 0, 0, t, eye_d) for x in (-pitch / 2, pitch / 2)]
    holes = [drill_z(x, 0, M3_CLEAR) for x in (-pitch / 2, pitch / 2)]
    return union([bar, *eyes]) - union(holes)


def tuer_klemmclip() -> Manifold:
    """1c: U-Clip auf die Oberkante der Glastür (mit VHB), Lasche für das M3-Kugelgelenk der Schubstange."""
    g = ANNAHMEN["glass_thickness"] + 0.2
    wall, depth, length = 3.0, 12.0, 30.0
    outer_w = g + 2 * wall
    body = box(-length / 2, -outer_w / 2, 0, length / 2, outer_w / 2, depth + 4)
    slot = box(-length / 2 - 1, -g / 2, -1, length / 2 + 1, g / 2, depth)
    lug = box(-6, outer_w / 2, depth - 2, 6, outer_w / 2 + 12, depth + 4)
    hole = cyl("z", 0, outer_w / 2 + 7, depth - 3, 10, M3_CLEAR)
    return (body + lug) - slot - hole


def tuer_endschalterhalter() -> Manifold:
    """1d: Halter für den Mikroschalter KW12 „Tür offen“ am Scharnier (VHB-Fuß)."""
    base = box(0, 0, 0, 30, 15, 3)
    upright = box(0, 11, 3, 30, 15, 15)
    holes = [cyl("y", x, 10, 10, 6, M2_TAP) for x in (15 - 4.75, 15 + 4.75)]  # Lochabstand KW12 9,5 mm
    return (base + upright) - union(holes)


# --- Baugruppe 2: Plattenregal (Aufbaukoordinaten, rechte Seite; links gespiegelt) -----------------------------------------
GUIDE_X = pc.MAG_X + 129.5  # Führungsfläche der Fachkämme (lichte Weite 259 mm)
POST_FACE_X = pc.TOWER_X[1] - pc.PROFILE  # Innenfläche der rechten Steher (493)
LEDGE_IN = pc.MAG_X + pc.PLATE_HALF - 6.0  # Leiste reicht 6 mm unter die Plattenkante
COMB_Z = (min(pc.SLOT_Z) - 10.0, max(pc.SLOT_Z) + 10.0)


def _comb_right(front: bool, sensors: bool) -> Manifold:
    y0, y1 = (40.0, pc.TOWER_Y[1]) if front else (pc.TOWER_Y[0], -40.0)
    z0, z1 = COMB_Z
    wall = box(GUIDE_X, y0, z0, POST_FACE_X, y1, z1)
    parts = [wall]
    for z in pc.SLOT_Z:
        top = z - 1.5  # Leistenoberkante 1,5 mm unter der Plattenoberkante (Platte 0,6 mm, Rest Spiel)
        parts.append(box(LEDGE_IN, y0, top - 3.0, GUIDE_X + 0.5, y1, top))
        if not front:
            # Anschlag hinter der Plattenhinterkante
            stop_y = -pc.PLATE_HALF - 0.5
            parts.append(box(LEDGE_IN, y0, top - 3.0, GUIDE_X + 0.5, stop_y, top + 6.0))
            if sensors:
                parts.append(box(LEDGE_IN - 14.0, y0, top - 9.0, GUIDE_X + 0.5, stop_y - 2.0, top + 8.0))
    comb = union(parts)
    cuts = []
    # Senkschrauben M5 in die Nut des Stehers (Steher liegt bei Y ±(125..145))
    post_y = pc.TOWER_Y[1] - pc.PROFILE / 2 if front else pc.TOWER_Y[0] + pc.PROFILE / 2
    for z in (z0 + 15.0, z1 - 15.0):
        cuts.append(cyl("x", GUIDE_X - 1, post_y, z, 10, M5_CLEAR))
        # Senkung von der Führungsseite, bündig
        cuts.append(
            rotate(Manifold.cylinder(2.75, M5_CSK / 2, M5_CLEAR / 2, SEG), (0, 90, 0)).translate((GUIDE_X, post_y, z))
        )
    if front:
        # Einlaufschräge vorne an jeder Leiste: 45°-Fase über die Vorderkante (Würfel um die Kante gedreht)
        for z in pc.SLOT_Z:
            top = z - 1.5
            cuts.append(
                rotate(Manifold.cube((GUIDE_X - LEDGE_IN + 2, 4.3, 4.3)), (45, 0, 0)).translate(
                    (LEDGE_IN - 1, y1, top - 3.0)
                )
            )
    if sensors:
        # Taschen für die Gabellichtschranken TCST2103 (24,5 × 6,3 × 10,8), Gabel waagerecht auf Plattenhöhe
        for z in pc.SLOT_Z:
            top = z - 1.5
            sy = -pc.PLATE_HALF - 2.5
            cuts.append(box(LEDGE_IN - 14.5, sy - 6.5, top - 8.0, LEDGE_IN + 10.0, sy, top + 6.5))
            for dx in (-9.5, 9.5):
                cuts.append(cyl("y", LEDGE_IN - 2.0 + dx, pc.TOWER_Y[0] - 1, top - 1.0, 30, M3_CLEAR))
    return comb - union(cuts) if cuts else comb


def _mirror_left(m: Manifold) -> Manifold:
    return m.mirror((1, 0, 0)).translate((2 * pc.MAG_X, 0, 0))


def _comb_print(m: Manifold, right: bool) -> Manifold:
    """Kamm auf die Außenseite (Anlage am Steher) legen: Druck-Z = Abstand von der Steherfläche."""
    if right:  # x' = y, y' = z, z' = POST_FACE_X - x
        matrix = [[0, 1, 0, 0], [0, 0, 1, 0], [-1, 0, 0, POST_FACE_X]]
    else:  # linke Seite: Steherfläche bei 2·MAG_X − POST_FACE_X
        matrix = [[0, -1, 0, 0], [0, 0, 1, 0], [1, 0, 0, -(2 * pc.MAG_X - POST_FACE_X)]]
    return rot_to_bed(m, matrix)


def fachkaemme_aufbau() -> dict[str, Manifold]:
    right_front = _comb_right(front=True, sensors=False)
    right_rear = _comb_right(front=False, sensors=True)
    left_rear = _mirror_left(_comb_right(front=False, sensors=False))
    return {
        "fachkamm_vorne_rechts": right_front,
        "fachkamm_vorne_links": _mirror_left(right_front),
        "fachkamm_hinten_rechts": right_rear,
        "fachkamm_hinten_links": left_rear,
    }


# --- Baugruppe 3: Shuttle -------------------------------------------------------------------------------------------------
def _mgn_holes(cx: float, cy: float, pitch_x: float, pitch_y: float, top: float) -> list[Manifold]:
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = cx + sx * pitch_x / 2, cy + sy * pitch_y / 2
            out += [drill_z(x, y, M3_CLEAR), counterbore_z(x, y, top)]
    return out


def z_wagenplatte() -> Manifold:
    """3a: MGN12H-Wagen der Z-Schiene ↔ Ende des X-Querträgers (2× M5 in die Nut), Inserts für den Mutterhalter."""
    t = 10.0
    body = box(-31, -25, 0, 31, 25, t)
    cuts = _mgn_holes(-11, 0, 20, 20, t)  # MGN12H: Lochbild 20 × 20, M3
    cuts += [drill_z(17, y, M5_CLEAR) for y in (-8, 8)]
    cuts += [counterbore_z(17, y, t, d_head=9.0, depth=4.0) for y in (-8, 8)]
    cuts += [drill_z(5, y, M3_INSERT, z0=t - 6.0) for y in (-19, 19)]
    return body - union(cuts)


def z_mutterhalter() -> Manifold:
    """3b: Tasche für die Tr8-Flanschmutter (Messing), Langlöcher geben 0,5 mm Spiel quer."""
    t = 12.0
    body = box(-20, -14, 0, 20, 14, t)
    cuts = [drill_z(0, 0, 10.4)]
    for k in range(4):
        a = math.radians(45 + 90 * k)
        cuts.append(drill_z(8 * math.cos(a), 8 * math.sin(a), M3_TAP))  # Flansch Ø22, Lochkreis Ø16
    cuts += [slot_z(x, 0, M3_CLEAR, 1.0, along="y") for x in (-16.0, 16.0)]
    return body - union(cuts)


def x_schlitten() -> Manifold:
    """3c: MGN12H-Wagen der X-Achse, Y-Träger (2020) hängt darunter, Riemenklemmen an beiden Enden."""
    t = 8.0
    body = box(-45, -30, 0, 45, 30, t)
    cuts = _mgn_holes(0, 0, 20, 20, t)
    cuts += [drill_z(0, y, M5_CLEAR) for y in (-22, 22)]
    cuts += [drill_z(x, y, M3_INSERT, z0=t - 6.0) for x in (-38, 38) for y in (-7, 7)]
    return body - union(cuts)


def y_wagen() -> Manifold:
    """3e: MGN9H-Wagen des Greiferarms, Aufnahme des Rechteckrohrs (2× M4), Inserts für die Riemenklemme."""
    t = 10.0
    body = box(-30, -15, 0, 30, 15, t)
    cuts = _mgn_holes(-12, 0, 15, 10, t)  # MGN9H: Lochbild 15 × 10, M3
    cuts += [drill_z(x, 0, M4_CLEAR) for x in (8, 24)]
    cuts += [drill_z(20, y, M3_INSERT, z0=t - 6.0) for y in (-10, 10)]
    return body - union(cuts)


def greiferkopf() -> Manifold:
    """3g: Elektromagnet Ø25 × 20 (Fläche bündig unten), Rohrtasche 20 × 10, Mikroschalter „Platte gegriffen“."""
    L, W, H = 80.0, 34.0, 22.0
    body = box(0, -W / 2, 0, L, W / 2, H)
    cuts = [
        box(-1, -10.2, 5.8, 25, 10.2, 16.2),  # Rohr 20 × 10 × 1,5, 25 mm tief
        *[cyl("z", x, 0, -1, H + 2, M3_CLEAR) for x in (8, 18)],  # Querbohrungen für das Rohr
        cyl("z", 48, 0, -1, 21, 25.3),  # Magnet-Tasche, 20 mm tief
        cyl("y", 48, W / 2 - 6, 10, 8, M3_TAP),  # Madenschrauben M3 von beiden Seiten
        cyl("y", 48, -W / 2 - 1, 10, 8, M3_TAP),
        box(24, -3, 13, 36, 3, 17),  # Kabelkanal 6 × 4 vom Magneten zum Rohr
        box(64, -10.25, -1, 70.6, 10.25, 10.5),  # Mikroschalter (20,5 × 6,6 × 10,5), Hebel nach unten
        *[cyl("x", 63, y, 5.5, 9, M2_TAP) for y in (-4.75, 4.75)],
    ]
    return body - union(cuts)


def riemenklemme() -> Manifold:
    """3h: Klemme für GT2-Riemen 6 mm, Zahnprofil 2 mm, zwei M3 im Abstand 14 mm."""
    body = box(-10, -6, 0, 10, 6, 8)
    cuts = [box(-11, -3.25, -1, 11, 3.25, 1.2)]
    # Zähne ragen über den Kanal hinaus, damit keine deckungsgleichen Flächen entstehen
    teeth = [box(x - 0.5, -4.0, 0.45, x + 0.5, 4.0, 1.5) for x in [i * 2.0 for i in range(-4, 5)]]
    channel = cuts[0] - union(teeth)
    holes = [drill_z(x, 0, M3_CLEAR) for x in (-7, 7)] + [counterbore_z(x, 0, 8.0) for x in (-7, 7)]
    return body - channel - union(holes)


def riemenspanner() -> Manifold:
    """3i: Gabel für die GT2-Umlenkrolle (Bohrung 5 mm), M3-Spannschraube mit Muttertasche, Langlöcher M5 für den Steher."""
    body = box(0, -13, 0, 30, 13, 14)
    cuts = [
        box(8, -4.75, -1, 31, 4.75, 15),  # Gabel 9,5 mm
        cyl("y", 20, -14, 7, 28, 5.2),  # Achse der Umlenkrolle
        cyl("x", -1, 0, 7, 10, M3_CLEAR),  # Spannschraube
        rotate(Manifold.cylinder(3.0, 5.7 / math.sqrt(3), 5.7 / math.sqrt(3), 6), (0, 90, 0)).translate((5.5, 0, 7)),
        *[slot_z(4.0, y, M5_CLEAR, 8.0, along="x") for y in (-9.5, 9.5)],
    ]
    return body - union(cuts)


def motorhalter() -> Manifold:
    """3j: L-Halter NEMA17 (Lochbild 31 mm, Zentrierbund Ø22) mit Fuß für das 2020-Profil.

    Die Rippen stehen außen neben dem Motor: 44 mm lichte Weite für den 42,3 mm breiten NEMA17.
    """
    w = 52.0
    face = box(0, 0, 0, w, 5, 53)
    foot = box(0, 0, 0, w, 30, 5)
    gussets = [
        Manifold.cube((4, 25, 25)).translate((x, 0, 0))
        ^ rotate(Manifold.cube((4, 40, 40)), (45, 0, 0)).translate((x, 5, -28.3 + 5 + 25))
        for x in (0, w - 4)
    ]
    body = union([face, foot, *gussets])
    cx, cz = w / 2, 29.0
    assert w - 8 > NEMA17_WIDTH, "Motor muss zwischen die Rippen passen"
    cuts = [cyl("y", cx, -1, cz, 7, 22.5)]
    cuts += [cyl("y", cx + dx, -1, cz + dz, 7, M3_CLEAR) for dx in (-15.5, 15.5) for dz in (-15.5, 15.5)]
    cuts += [slot_z(x, 19.0, M5_CLEAR, 8.0, along="y") for x in (cx - 12.0, cx + 12.0)]
    return body - union(cuts)


def endschalterhalter() -> Manifold:
    """3k: Halter KW12 für X, Y und Z, Langloch M5 für die Profilnut."""
    base = box(0, 0, 0, 30, 15, 4)
    upright = box(0, 0, 4, 30, 4, 14)
    cuts = [slot_z(8, 9, M5_CLEAR, 6.0, along="x")]
    cuts += [cyl("y", x, -1, 10, 6, M2_TAP) for x in (18.25, 27.75)]
    return (base + upright) - union(cuts)


def schaltfahne() -> Manifold:
    """3k: Fahne, die den Endschalter beim Anfahren auslöst (Langloch zum Einstellen)."""
    return box(0, 0, 0, 25, 10, 3) - slot_z(7, 5, M3_CLEAR, 6.0, along="x")


def kettenaufnahme() -> Manifold:
    """3l: Endstück-Aufnahme der Energiekette 10 × 15 (zwei M3) mit M5 für die Profilnut."""
    body = box(0, 0, 0, 25, 30, 8)
    cuts = [drill_z(12.5, y, M3_TAP) for y in (6, 16)] + [drill_z(12.5, 24.5, M5_CLEAR)]
    return body - union(cuts)


def z_reibbremse() -> Manifold:
    """3m (M18): Reibbremse an der Z-Spindel: Filz-/PTFE-Klotz Ø6 mit Feder, Andruck über M4-Madenschraube."""
    body = box(0, -10, 0, 30, 10, 16)
    cuts = [
        drill_z(10, 0, 8.8),  # Spindel Tr8 läuft durch
        cyl("x", 14.0, 0, 8, 17, 6.5),  # Bohrung für Klotz und Feder
        rotate(Manifold.cylinder(3.5, 7.2 / math.sqrt(3), 7.2 / math.sqrt(3), 6), (0, 90, 0)).translate((25.5, 0, 8)),
        *[drill_z(24, y, M5_CLEAR) for y in (-7, 7)],
    ]
    return body - union(cuts)


# --- Baugruppe 4: Waschstation (Aufbaukoordinaten) -------------------------------------------------------------------------
WASH_X = (227.0, 493.0)
WASH_Y = (-81.0, 81.0)
WASH_TOP = pc.WASH_Z - 2.0  # 2 mm unter der Walzenoberkante: Die Platte läuft über die Wände hinweg
WASH_FLOOR = (4.0, 9.0)
WASH_WALL = 6.0
WASH_END = 10.0
ROLLER_Y = (-45.0, 45.0)
ROLLER_AXIS_Z = pc.WASH_Z - 12.0
JOINT_X = pc.MAG_X
N20_HOLE_DY = 14.0  # Befestigung des N20-Halters neben der Walzenachse
N20_HOLE_DZ = 6.0  # über der Walzenachse (Achse Z 32 → Insert Z 38, Oberkante der Wand 42)
N20_AXIS_Z = 12.0  # Motorachse im Halter


def _wanne_voll() -> Manifold:
    x0, x1 = WASH_X
    y0, y1 = WASH_Y
    outer = box(x0, y0, WASH_FLOOR[0], x1, y1, WASH_TOP)
    inner = box(x0 + WASH_END, y0 + WASH_WALL, WASH_FLOOR[1], x1 - WASH_END, y1 - WASH_WALL, WASH_TOP + 1)
    m = outer - inner
    feet = [box(x, y, 0, x + 14, y + 14, WASH_FLOOR[0] + 0.5) for x in (x0, x1 - 14) for y in (y0, y1 - 14)]
    feet += [box(JOINT_X - 14, y, 0, JOINT_X + 14, y + 14, WASH_FLOOR[0] + 0.5) for y in (y0, y1 - 14)]
    m = m + union(feet)
    cuts = []
    for y in ROLLER_Y:
        for x_face, sign in ((x0 + WASH_END, -1), (x1 - WASH_END, 1)):
            # Lagersitz 608ZZ (Ø22 × 7), oben offen zum Einlegen
            seat_x = x_face - 7.2 if sign < 0 else x_face
            cuts.append(cyl("x", seat_x, y, ROLLER_AXIS_Z, 7.2, 22.2))
            cuts.append(box(seat_x, y - 11.1, ROLLER_AXIS_Z, seat_x + 7.2, y + 11.1, WASH_TOP + 1))
        cuts.append(cyl("x", x0 - 1, y, ROLLER_AXIS_Z, WASH_END + 2, 10.0))  # Welle zum Antrieb (links)
        for dy in (-N20_HOLE_DY, N20_HOLE_DY):  # Inserts für den N20-Halter, 2 mm unter der Wandoberkante
            cuts.append(cyl("x", x0 - 1, y + dy, ROLLER_AXIS_Z + N20_HOLE_DZ, 7.0, M3_INSERT))
    # Ablauf rechts unten, Schlauchtülle außen angesetzt
    cuts.append(cyl("x", x1 - WASH_END - 1, 0, WASH_FLOOR[1] + 3.0, WASH_END + 2, 5.0))
    # Halterung für den IPA-Schlauch 2 × 4 an der Rückwand
    cuts.append(cyl("z", pc.MAG_X + 40, y0 + WASH_WALL / 2, WASH_TOP - 8, 10, 4.2))
    m = m - union(cuts)
    barb = cyl("x", x1, 0, WASH_FLOOR[1] + 3.0, 12, 8.0) - cyl("x", x1 - 1, 0, WASH_FLOOR[1] + 3.0, 14, 5.0)
    return m + barb


def _wanne_haelften() -> tuple[Manifold, Manifold]:
    """Zwei Hälften mit Überlappung (Zunge der linken Hälfte liegt innen auf der rechten), 2× M4 durch den Boden."""
    full = _wanne_voll()
    x0, x1 = WASH_X
    y0, y1 = WASH_Y
    lap = 12.0
    # Zunge: innere 3 mm von Boden und Seitenwänden im Bereich X = Fuge .. Fuge + 12
    skin_outer = box(JOINT_X, y0 + WASH_WALL - 3, WASH_FLOOR[1] - 3, JOINT_X + lap, y1 - WASH_WALL + 3, WASH_TOP)
    skin_inner = box(JOINT_X - 1, y0 + WASH_WALL, WASH_FLOOR[1], JOINT_X + lap + 1, y1 - WASH_WALL, WASH_TOP + 1)
    tongue = skin_outer - skin_inner
    left = (full ^ box(x0 - 20, y0 - 20, -1, JOINT_X, y1 + 20, 100)) + tongue
    right = (full ^ box(JOINT_X, y0 - 20, -1, x1 + 20, y1 + 20, 100)) - (
        box(
            JOINT_X - 1,
            y0 + WASH_WALL - 3.2,
            WASH_FLOOR[1] - 3.2,
            JOINT_X + lap + 0.2,
            y1 - WASH_WALL + 3.2,
            WASH_TOP + 1,
        )
        - skin_inner
    )
    bolts = [cyl("z", JOINT_X + lap / 2, y, -1, 20, M4_CLEAR) for y in (-40.0, 40.0)]
    return left - union(bolts), right - union(bolts)


def n20_halter() -> Manifold:
    """4c: Halter für den Getriebemotor N20 vor der Stirnwand (2 Stück, je Walze ein Motor, gegenläufig verdrahtet).

    Motorplatte (X 0..4) und Wandflansch (X 22..26) sind über zwei Beine verbunden; dazwischen sitzt die Kupplung 4d.
    Der Flansch liegt an der Stirnwand der Wanne und wird mit 2× M3 in deren Inserts geschraubt.
    """
    h = N20_AXIS_Z + N20_HOLE_DZ + 6.0
    plate = box(0, -17, 0, 4, 17, h)
    flange = box(22, -17, 0, 26, 17, h)
    legs = [box(0, y, 0, 26, y + 6, h) for y in (-17, 11)]
    body = union([plate, flange, *legs])
    cuts = [cyl("x", -1, 0, N20_AXIS_Z, 6, 4.5)]  # Getriebebund / Welle
    cuts += [cyl("x", -1, y, N20_AXIS_Z, 6, 1.8) for y in (-4.5, 4.5)]  # M1,6, Abstand 9 mm
    cuts += [cyl("x", 21, 0, N20_AXIS_Z, 6, 16.0)]  # Durchgang für Welle und Kupplung
    cuts += [cyl("x", 21, y, N20_AXIS_Z + N20_HOLE_DZ, 6, M3_CLEAR) for y in (-N20_HOLE_DY, N20_HOLE_DY)]
    return body - union(cuts)


def walzenkupplung() -> Manifold:
    """4d: Kupplung N20-Welle (3 mm, D-Fläche) auf Walzenwelle Ø8, je eine M3-Madenschraube."""
    body = cyl("z", 0, 0, 0, 20, 14)
    d_bore = cyl("z", 0, 0, -1, 9, 3.1) - box(-2, 1.0, -2, 2, 2, 10)  # D-Fläche 2,5 mm
    cuts = [d_bore, cyl("z", 0, 0, 10, 11, 8.1), cyl("x", 0, 0, 4, 8, M3_TAP), cyl("x", 0, 0, 15, 8, M3_TAP)]
    return body - union(cuts)


def luefterduese() -> Manifold:
    """4e: Düse für den Radiallüfter 5015: Auslass 19,5 × 15 auf Breitschlitz 150 × 3 über der Platte."""
    inlet_o = box(-11, -9, 0, 11, 9, 12)
    outlet_o = box(-75, -3.5, 58, 75, 3.5, 60)
    outer = Manifold.batch_hull([inlet_o, outlet_o]) + inlet_o
    inlet_i = box(-9.85, -7.7, -1, 9.85, 7.7, 12.5)
    outlet_i = box(-73, -1.5, 57, 73, 1.5, 61)
    inner = Manifold.batch_hull([box(-9.85, -7.7, 11, 9.85, 7.7, 12.5), outlet_i]) + inlet_i
    tab = box(11, -2, 0, 24, 2, 12) - cyl("y", 18, -3, 6, 6, M4_CLEAR)
    return (outer - inner) + tab


def schlauchclip() -> Manifold:
    """4f: Clip für den Silikonschlauch 2 × 4 (IPA), M3 an der Turmwand."""
    base = box(0, 0, 0, 20, 10, 3)
    ring = cyl("z", 15, 5, 0, 8, 8.0) - cyl("z", 15, 5, -1, 10, 4.2) - box(15, 3.2, -1, 20, 6.8, 10)
    return (base + ring) - drill_z(5, 5, M3_CLEAR)


# --- Katalog --------------------------------------------------------------------------------------------------------------
def _katalog() -> list[tuple[Teil, Callable[[], Manifold]]]:
    kaemme = fachkaemme_aufbau()
    wanne_l, wanne_r = _wanne_haelften()
    flat_wanne = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]

    def comb(name: str, right: bool) -> Callable[[], Manifold]:
        return lambda: _comb_print(kaemme[name], right)

    T = Teil
    return [
        (
            T(
                "1a",
                "Servohalter Türöffner",
                1,
                "tuer_servohalter.stl",
                1,
                "ASA",
                4,
                35,
                "Gyroid",
                "keine",
                "Platte unten",
                "Mit 3M VHB auf der Druckeroberseite, Servo hängt im 18-mm-Überstand (Annahme, am Gerät anpassen).",
            ),
            lambda: lay_flat(tuer_servohalter()),
        ),
        (
            T(
                "1b",
                "Kniehebel-Schubstange",
                1,
                "tuer_schubstange.stl",
                1,
                "PETG",
                5,
                50,
                "Linien",
                "keine",
                "flach",
                "M3-Kugelgelenke mit Mutter; Stichmaß 90 mm.",
            ),
            lambda: lay_flat(tuer_schubstange()),
        ),
        (
            T(
                "1c",
                "Klemmclip Glastür",
                1,
                "tuer_klemmclip.stl",
                1,
                "PETG",
                4,
                40,
                "Gyroid",
                "keine",
                "Schlitz unten",
                "Für 4 mm Glas (Annahme, messen), zusätzlich VHB im Schlitz.",
            ),
            lambda: lay_flat(tuer_klemmclip()),
        ),
        (
            T(
                "1d",
                "Endschalterhalter Tür offen",
                1,
                "tuer_endschalterhalter.stl",
                1,
                "PETG",
                3,
                30,
                "Gyroid",
                "keine",
                "Fuß unten",
                "KW12 mit 2× M2 selbstschneidend; „Tür zu“ meldet der Türsensor des P2S.",
            ),
            lambda: lay_flat(tuer_endschalterhalter()),
        ),
        (
            T(
                "2a",
                "Fachkamm vorne rechts",
                2,
                "fachkamm_vorne_rechts.stl",
                1,
                "PETG",
                4,
                30,
                "Gyroid",
                "keine",
                "Anlagefläche am Steher unten",
                "2× M5×10 Senkkopf mit Nutenstein; Einlaufschräge vorne.",
            ),
            comb("fachkamm_vorne_rechts", True),
        ),
        (
            T(
                "2a",
                "Fachkamm vorne links",
                2,
                "fachkamm_vorne_links.stl",
                1,
                "PETG",
                4,
                30,
                "Gyroid",
                "keine",
                "Anlagefläche am Steher unten",
                "Spiegelbild von vorne rechts.",
            ),
            comb("fachkamm_vorne_links", False),
        ),
        (
            T(
                "2b",
                "Fachkamm hinten rechts mit Lichtschranken",
                2,
                "fachkamm_hinten_rechts.stl",
                1,
                "PETG",
                4,
                30,
                "Gyroid",
                "keine",
                "Anlagefläche am Steher unten",
                "Anschlag hinter der Platte, 4 Taschen für TCST2103 (2× M3 je Sensor); Sensorlage am Aufbau prüfen.",
            ),
            comb("fachkamm_hinten_rechts", True),
        ),
        (
            T(
                "2b",
                "Fachkamm hinten links",
                2,
                "fachkamm_hinten_links.stl",
                1,
                "PETG",
                4,
                30,
                "Gyroid",
                "keine",
                "Anlagefläche am Steher unten",
                "Anschlag hinter der Platte, ohne Sensoren.",
            ),
            comb("fachkamm_hinten_links", False),
        ),
        (
            T(
                "3a",
                "Z-Wagenplatte",
                3,
                "z_wagenplatte.stl",
                2,
                "PETG-CF",
                5,
                60,
                "Gyroid",
                "keine",
                "flach",
                "Trägt den Querträger: 4× M3 zum MGN12H, 2× M5 in die Nut, 2 Inserts für den Mutterhalter.",
            ),
            lambda: lay_flat(z_wagenplatte()),
        ),
        (
            T(
                "3b",
                "Spindelmutter-Halter",
                3,
                "z_mutterhalter.stl",
                2,
                "PETG-CF",
                5,
                60,
                "Gyroid",
                "keine",
                "flach",
                "Messing-Flanschmutter Tr8×2, 4× M3 selbstschneidend; Langlöcher gleichen 0,5 mm aus.",
            ),
            lambda: lay_flat(z_mutterhalter()),
        ),
        (
            T(
                "3c",
                "X-Schlitten",
                3,
                "x_schlitten.stl",
                1,
                "PETG-CF",
                5,
                50,
                "Gyroid",
                "keine",
                "flach",
                "MGN12H, Y-Träger mit 2× M5, Riemenklemmen auf 4 Inserts.",
            ),
            lambda: lay_flat(x_schlitten()),
        ),
        (
            T(
                "3e",
                "Y-Wagen",
                3,
                "y_wagen.stl",
                1,
                "PETG-CF",
                5,
                50,
                "Gyroid",
                "keine",
                "flach",
                "MGN9H, Greiferarm 20 × 10 mit 2× M4, Riemenklemme auf 2 Inserts.",
            ),
            lambda: lay_flat(y_wagen()),
        ),
        (
            T(
                "3g",
                "Greiferkopf",
                3,
                "greiferkopf.stl",
                1,
                "ASA",
                5,
                50,
                "Gyroid",
                "keine",
                "Magnetfläche unten",
                "Magnet Ø25 × 20 mit 2 Madenschrauben M3, Mikroschalter „Platte gegriffen“ mit M2.",
            ),
            lambda: lay_flat(greiferkopf()),
        ),
        (
            T(
                "3h",
                "Riemenklemme GT2",
                3,
                "riemenklemme.stl",
                4,
                "PETG",
                4,
                60,
                "Linien",
                "keine",
                "Zahnseite unten",
                "Zahnprofil 2 mm, Riemen 6 mm, 2× M3.",
            ),
            lambda: lay_flat(riemenklemme()),
        ),
        (
            T(
                "3i",
                "Riemenspanner",
                3,
                "riemenspanner.stl",
                2,
                "PETG",
                4,
                50,
                "Gyroid",
                "keine",
                "flach",
                "Umlenkrolle 20T, Achse M5; Spannschraube M3 mit Mutter.",
            ),
            lambda: lay_flat(riemenspanner()),
        ),
        (
            T(
                "3j",
                "Motorhalter X/Y",
                3,
                "motorhalter.stl",
                2,
                "ASA",
                5,
                40,
                "Gyroid",
                "keine",
                "Fuß unten",
                "NEMA17 wird 60 bis 70 °C warm: ASA, kein PLA oder PETG.",
            ),
            lambda: lay_flat(motorhalter()),
        ),
        (
            T(
                "3k",
                "Endschalterhalter X/Y/Z",
                3,
                "endschalterhalter.stl",
                3,
                "PETG",
                3,
                30,
                "Gyroid",
                "keine",
                "Fuß unten",
                "KW12, 2× M2 selbstschneidend, M5-Langloch für die Profilnut.",
            ),
            lambda: lay_flat(endschalterhalter()),
        ),
        (
            T(
                "3k",
                "Schaltfahne",
                3,
                "schaltfahne.stl",
                3,
                "PETG",
                3,
                30,
                "Gyroid",
                "keine",
                "flach",
                "Mit M3 am bewegten Teil, Langloch zum Einstellen.",
            ),
            lambda: lay_flat(schaltfahne()),
        ),
        (
            T(
                "3l",
                "Kettenaufnahme",
                3,
                "kettenaufnahme.stl",
                6,
                "PETG",
                3,
                30,
                "Gyroid",
                "keine",
                "flach",
                "Lochbild der Kettenendstücke am Kauf prüfen.",
            ),
            lambda: lay_flat(kettenaufnahme()),
        ),
        (
            T(
                "3m",
                "Z-Reibbremse (M18)",
                3,
                "z_reibbremse.stl",
                2,
                "PETG",
                4,
                50,
                "Gyroid",
                "keine",
                "flach",
                "Filzklotz Ø6 + Druckfeder + M4-Madenschraube; auf etwa 0,005 N·m einstellen (Abschnitt 7).",
            ),
            lambda: lay_flat(z_reibbremse()),
        ),
        (
            T(
                "4a",
                "Waschwanne links (mit Zunge)",
                4,
                "waschwanne_links.stl",
                1,
                "PETG",
                5,
                40,
                "Gyroid",
                "keine",
                "Boden unten",
                "Lagersitze 608ZZ, Wellendurchgang, Inserts für die N20-Halter; Fuge mit neutralem Silikon.",
            ),
            lambda: rot_to_bed(wanne_l, flat_wanne),
        ),
        (
            T(
                "4b",
                "Waschwanne rechts (mit Ablauf)",
                4,
                "waschwanne_rechts.stl",
                1,
                "PETG",
                5,
                40,
                "Gyroid",
                "keine",
                "Boden unten",
                "Ablauf Ø5 mit Schlauchtülle Ø8; 2× M4 durch die Überlappung.",
            ),
            lambda: rot_to_bed(wanne_r, flat_wanne),
        ),
        (
            T(
                "4c",
                "N20-Halter",
                4,
                "n20_halter.stl",
                2,
                "PETG",
                4,
                40,
                "Gyroid",
                "keine",
                "flach",
                "Zwei N20 (je Walze einer, gegenläufig verdrahtet) statt Zahnräder.",
            ),
            lambda: lay_flat(n20_halter()),
        ),
        (
            T(
                "4d",
                "Walzenkupplung",
                4,
                "walzenkupplung.stl",
                2,
                "PETG",
                4,
                100,
                "Linien",
                "keine",
                "stehend",
                "3-mm-D-Welle auf Ø8, je M3-Madenschraube.",
            ),
            lambda: lay_flat(walzenkupplung()),
        ),
        (
            T(
                "4e",
                "Lüfterdüse 5015",
                4,
                "luefterduese.stl",
                1,
                "PETG",
                3,
                15,
                "Gyroid",
                "keine",
                "Einlass unten",
                "Breitschlitz 146 × 3 über der Platte.",
            ),
            lambda: lay_flat(luefterduese()),
        ),
        (
            T(
                "4f",
                "Schlauchclip IPA",
                4,
                "schlauchclip.stl",
                2,
                "PETG",
                3,
                40,
                "Gyroid",
                "keine",
                "flach",
                "Silikonschlauch 2 × 4.",
            ),
            lambda: lay_flat(schlauchclip()),
        ),
    ]


# --- Prüfungen ------------------------------------------------------------------------------------------------------------
def pruefe_zusammenbau() -> list[str]:
    """Platte muss frei durch Regal (alle Fächer, bis vor den Turm) und über die Waschwanne laufen."""
    fehler = []
    kaemme = union(list(fachkaemme_aufbau().values()))
    for z in pc.SLOT_Z:
        weg = box(pc.MAG_X - pc.PLATE_HALF, -pc.PLATE_HALF, z - 0.6, pc.MAG_X + pc.PLATE_HALF, pc.TOWER_Y[1] + 300, z)
        if (kaemme ^ weg).volume() > 1e-6:
            fehler.append(f"Platte stößt im Fach Z {z:.0f} an einen Fachkamm")
        auflage = box(
            pc.MAG_X - pc.PLATE_HALF, -pc.PLATE_HALF, z - 2.0, pc.MAG_X + pc.PLATE_HALF, pc.PLATE_HALF, z - 1.4
        )
        if (kaemme ^ auflage).volume() < 1.0:
            fehler.append(f"Fach Z {z:.0f}: keine Auflage unter der Platte")
    links, rechts = _wanne_haelften()
    ueber = box(
        pc.MAG_X - pc.PLATE_HALF,
        -pc.PLATE_HALF - 300,
        pc.WASH_Z,
        pc.MAG_X + pc.PLATE_HALF,
        pc.PLATE_HALF + 300,
        pc.WASH_Z + 0.6,
    )
    if ((links + rechts) ^ ueber).volume() > 1e-6:
        fehler.append("Platte stößt über der Waschwanne an")
    if (links ^ rechts).volume() > 1e-3:
        fehler.append("Wannenhälften überschneiden sich")
    return fehler


def _gewicht(m: Manifold, teil: Teil) -> float:
    """Grobe Filamentmenge: Wände plus Füllung (Schätzung, der Slicer weiß es genauer)."""
    dichte = MATERIAL[teil.material][0]
    vol = m.volume()
    schale = min(vol, m.surface_area() * teil.waende * 0.42)
    return dichte * (schale + teil.infill / 100 * (vol - schale)) / 1000


def write_stl(path: Path, m: Manifold, header: str) -> int:
    mesh = m.to_mesh()
    verts = mesh.vert_properties
    tris = mesh.tri_verts
    with path.open("wb") as f:
        f.write(header.encode("ascii", "replace")[:80].ljust(80, b"\0"))
        f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            p, q, r = verts[a][:3], verts[b][:3], verts[c][:3]
            u = (q[0] - p[0], q[1] - p[1], q[2] - p[2])
            v = (r[0] - p[0], r[1] - p[1], r[2] - p[2])
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            ln = math.sqrt(sum(k * k for k in n)) or 1.0
            f.write(struct.pack("<12fH", n[0] / ln, n[1] / ln, n[2] / ln, *p, *q, *r, 0))
    return len(tris)


def erzeuge() -> list[Teil]:
    fehler = pruefe_zusammenbau()
    if fehler:
        raise SystemExit("Zusammenbau passt nicht:\n  " + "\n  ".join(fehler))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    teile = []
    limit = BED - 2 * BED_MARGIN
    for teil, build in _katalog():
        m = build()
        if m.status().name != "NoError" or m.volume() <= 0:
            raise SystemExit(f"{teil.datei}: kein gültiger Volumenkörper ({m.status()})")
        # Splitter unter 1 mm³ (fast tangentiale Bohrungen) entfernen; danach muss genau ein Körper übrig sein.
        koerper = [p for p in m.decompose() if p.volume() > 1.0]
        if len(koerper) != 1:
            raise SystemExit(f"{teil.datei}: {len(koerper)} Körper statt einem")
        m = koerper[0]
        x0, y0, z0, x1, y1, z1 = m.bounding_box()
        size = [round(x1 - x0, 1), round(y1 - y0, 1), round(z1 - z0, 1)]
        if max(size) > limit:
            raise SystemExit(f"{teil.datei}: {size} mm passt nicht auf das Druckbett ({limit} mm)")
        teil.groesse_mm = size
        teil.volumen_cm3 = round(m.volume() / 1000, 1)
        teil.gewicht_g = round(_gewicht(m, teil), 0)
        teil.dreiecke = write_stl(OUT_DIR / teil.datei, m, f"PrintLab {teil.id} {teil.name}")
        teile.append(teil)
    manifest = {
        "drucker": "Bambu Lab P2S, Druckbett 256 x 256 x 256 mm, Düse 0,4 mm (gehärtet)",
        "schichthoehe_mm": 0.2,
        "material": {k: {"dichte_g_cm3": v[0], "warum": v[1]} for k, v in MATERIAL.items()},
        "annahmen": ANNAHMEN,
        "teile": [asdict(t) for t in teile],
    }
    (OUT_DIR / "bauteile.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return teile


def tabelle(teile: list[dict]) -> str:
    rows = [
        "| Nr. | Teil | Datei | Menge | Material | Wände · Füllung | Drucklage | Größe (mm) | ca. g je Stück | Hinweis |",
        "| :---: | :--- | :--- | :---: | :---: | :---: | :--- | :--- | ---: | :--- |",
    ]
    for t in teile:
        size = " × ".join(f"{v:g}".replace(".", ",") for v in t["groesse_mm"])
        rows.append(
            f"| **{t['id']}** | {t['name']} | `{t['datei']}` | {t['menge']} | {t['material']} | "
            f"{t['waende']} · {t['infill']} % {t['muster']} | {t['drucklage']} | {size} | {t['gewicht_g']:.0f} | {t['hinweis']} |"
        )
    total = sum(t["gewicht_g"] * t["menge"] for t in teile)
    by_mat: dict[str, float] = {}
    for t in teile:
        by_mat[t["material"]] = by_mat.get(t["material"], 0.0) + t["gewicht_g"] * t["menge"]
    mats = ", ".join(f"{k} {v:.0f} g" for k, v in sorted(by_mat.items()))
    rows.append(
        f"| | **Summe** | {len(teile)} Dateien | {sum(t['menge'] for t in teile)} Teile | | | | | **{total:.0f}** | {mats} |"
    )
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    if "--tabelle" in argv:
        data = json.loads((OUT_DIR / "bauteile.json").read_text(encoding="utf-8"))
        sys.stdout.reconfigure(encoding="utf-8")
        print(tabelle(data["teile"]))
        return 0
    teile = erzeuge()
    for t in teile:
        print(f"{t.id:>3} {t.datei:<32} {t.groesse_mm} mm  {t.gewicht_g:>5.0f} g  {t.material}")
    print(f"{len(teile)} Dateien in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
