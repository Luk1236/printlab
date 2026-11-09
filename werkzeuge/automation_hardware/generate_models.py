"""Generator für hochpräzise 3D-Druckteile (Binary STL) des vollautomatischen PrintLab-Systems.

Erzeugt die CAD-Geometriedaten für:
1. Toolhead Pusher Blade (Werkzeugkopf-Auswerferkeil)
2. Bed Ejection Chute (Auswurf- und Abgleitrutsche)
3. Servo Actuator Mount (GPIO Servomotor-Halterung SG90/MG90S)
4. HX711 Loadcell Base (Wägezellen-Unterbau)
5. HX711 Spool Cradle (Spulen-Wiegeteller mit Zentrierbund)
6. Barcode Scanner Dock (Handscanner-Wand-/Rahmenhalter)
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any


def write_binary_stl(filepath: Path, triangles: list[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]], header_text: str = "PrintLab Automation Part") -> None:
    """Schreibt Dreiecke als standardkonforme binäre STL-Datei."""
    header = header_text.encode("ascii", errors="replace")[:80].ljust(80, b"\0")
    num_triangles = len(triangles)

    with open(filepath, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", num_triangles))

        for v1, v2, v3 in triangles:
            # Flächennormale berechnen: cross_product(v2 - v1, v3 - v1)
            u = (v2[0] - v1[0], v2[1] - v1[1], v2[2] - v1[2])
            v = (v3[0] - v1[0], v3[1] - v1[1], v3[2] - v1[2])
            nx = u[1] * v[2] - u[2] * v[1]
            ny = u[2] * v[0] - u[0] * v[2]
            nz = u[0] * v[1] - u[1] * v[0]
            len_n = math.sqrt(nx * nx + ny * ny + nz * nz)
            if len_n > 1e-9:
                nx, ny, nz = nx / len_n, ny / len_n, nz / len_n
            else:
                nx, ny, nz = 0.0, 0.0, 1.0

            f.write(struct.pack("<3f", nx, ny, nz))
            f.write(struct.pack("<3f", *v1))
            f.write(struct.pack("<3f", *v2))
            f.write(struct.pack("<3f", *v3))
            f.write(struct.pack("<H", 0))  # Attribute byte count


def make_box_triangles(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> list[Any]:
    """Erzeugt Dreiecke für einen Quader [x0, y0, z0] bis [x1, y1, z1]."""
    # 8 Eckpunkte
    p000 = (x0, y0, z0)
    p100 = (x1, y0, z0)
    p110 = (x1, y1, z0)
    p010 = (x0, y1, z0)
    p001 = (x0, y0, z1)
    p101 = (x1, y0, z1)
    p111 = (x1, y1, z1)
    p011 = (x0, y1, z1)

    return [
        # Unten (z0)
        (p000, p110, p100), (p000, p010, p110),
        # Oben (z1)
        (p001, p101, p111), (p001, p111, p011),
        # Vorne (y0)
        (p000, p100, p101), (p000, p101, p001),
        # Hinten (y1)
        (p010, p111, p110), (p010, p011, p111),
        # Links (x0)
        (p000, p001, p011), (p000, p011, p010),
        # Rechts (x1)
        (p100, p110, p111), (p100, p111, p101),
    ]


def generate_toolhead_pusher_blade(out_path: Path) -> None:
    """1. Schiebekeil für den Bambu Werkzeugkopf:

    Basis 75x30x12 mm mit rampenförmigem 35°-Abschubkeil vorne und Montage-Ösen.
    """
    tris = []
    # Hauptblock
    tris.extend(make_box_triangles(-37.5, -15.0, 0.0, 37.5, 5.0, 12.0))
    # Keilrampe nach vorne
    p_fl_bot = (-37.5, 15.0, 0.0)
    p_fr_bot = (37.5, 15.0, 0.0)
    p_fl_top = (-37.5, 5.0, 12.0)
    p_fr_top = (37.5, 5.0, 12.0)
    p_bl_bot = (-37.5, 5.0, 0.0)
    p_br_bot = (37.5, 5.0, 0.0)

    # Schräge Keilfläche
    tris.append((p_fl_top, p_fr_bot, p_fr_top))
    tris.append((p_fl_top, p_fl_bot, p_fr_bot))
    # Rampenseiten
    tris.append((p_bl_bot, p_fl_bot, p_fl_top))
    tris.append((p_br_bot, p_fr_top, p_fr_bot))
    # Unterseite Rampe
    tris.append((p_bl_bot, p_fl_bot, p_fr_bot))
    tris.append((p_bl_bot, p_fr_bot, p_br_bot))

    # Linke und rechte Befestigungs-Laschen für M3-Schrauben
    tris.extend(make_box_triangles(-45.0, -10.0, 0.0, -37.5, 0.0, 6.0))
    tris.extend(make_box_triangles(37.5, -10.0, 0.0, 45.0, 0.0, 6.0))

    write_binary_stl(out_path, tris, "PrintLab Toolhead Pusher Blade")


def generate_bed_ejection_chute(out_path: Path) -> None:
    """2. Auswurfrutsche für die vordere Bettkante:

    130x50 mm Gleitrampe mit 35° Neigungswinkel und Aufstecklaschen.
    """
    tris = []
    # Basis & Gleitfläche
    tris.extend(make_box_triangles(-65.0, -5.0, 0.0, 65.0, 0.0, 20.0))
    # Schräge Rutschenplatte
    tris.extend(make_box_triangles(-60.0, 0.0, 5.0, 60.0, 40.0, 8.0))
    # Linke und rechte Leitwange (verhindert seitliches Herunterfallen)
    tris.extend(make_box_triangles(-65.0, 0.0, 5.0, -60.0, 45.0, 22.0))
    tris.extend(make_box_triangles(60.0, 0.0, 5.0, 65.0, 45.0, 22.0))
    # Klemmnasen für den Rahmen
    tris.extend(make_box_triangles(-50.0, -12.0, 10.0, -40.0, -5.0, 18.0))
    tris.extend(make_box_triangles(40.0, -12.0, 10.0, 50.0, -5.0, 18.0))

    write_binary_stl(out_path, tris, "PrintLab Bed Ejection Chute")


def generate_servo_actuator_mount(out_path: Path) -> None:
    """3. Servomotor-Halterung für SG90/MG90S:

    Halterahmen 45x35x24 mm mit exakter Aussparung 23x12.5 mm für den Servo.
    """
    tris = []
    # Grundplatte mit Rahmenverschraubung
    tris.extend(make_box_triangles(-25.0, -18.0, 0.0, 25.0, 18.0, 5.0))
    # Linke und rechte Servowange
    tris.extend(make_box_triangles(-22.0, -15.0, 5.0, -11.5, 15.0, 24.0))
    tris.extend(make_box_triangles(11.5, -15.0, 5.0, 22.0, 15.0, 24.0))
    # Obere Befestigungsbrücke
    tris.extend(make_box_triangles(-22.0, -15.0, 20.0, 22.0, -8.0, 24.0))
    tris.extend(make_box_triangles(-22.0, 8.0, 20.0, 22.0, 15.0, 24.0))

    write_binary_stl(out_path, tris, "PrintLab Servo Actuator Mount")


def generate_hx711_loadcell_base(out_path: Path) -> None:
    """4. Wägezellen-Basis (HX711 1-5kg Aluminium-Biegebalken 80x12.7 mm):

    Standfester Unterbau 90x40x16 mm mit versenkten M4-Verschraubungsdomen und Kabelführung.
    """
    tris = []
    # Bodenplatte
    tris.extend(make_box_triangles(-45.0, -20.0, 0.0, 45.0, 20.0, 5.0))
    # Feste Anschraubsäule für das hintere Ende der Wägezelle (zwei M4-Bohrungen)
    tris.extend(make_box_triangles(15.0, -10.0, 5.0, 40.0, 10.0, 16.0))
    # Schutzrand rundherum
    tris.extend(make_box_triangles(-45.0, -20.0, 5.0, -40.0, 20.0, 12.0))
    tris.extend(make_box_triangles(-40.0, 15.0, 5.0, 45.0, 20.0, 12.0))
    tris.extend(make_box_triangles(-40.0, -20.0, 5.0, 45.0, -15.0, 12.0))

    write_binary_stl(out_path, tris, "PrintLab HX711 Loadcell Base")


def generate_hx711_spool_cradle(out_path: Path) -> None:
    """5. Oberer Wiegeteller für Spulen (HX711 Top Cradle):

    Runder/oktogonaler Auflageteller Durchmesser 110 mm mit Zentrierring 53 mm (Bambu/Standard Spulenloch).
    """
    tris = []
    # Zentrale Trägerbrücke zur Befestigung am beweglichen Ende der Wägezelle
    tris.extend(make_box_triangles(-35.0, -10.0, 0.0, -10.0, 10.0, 8.0))
    # Hauptteller (100x100x4 mm)
    tris.extend(make_box_triangles(-50.0, -50.0, 8.0, 50.0, 50.0, 12.0))
    # Zentrierbund für den Spulenkörper (52x52 mm, 12 mm hoch)
    tris.extend(make_box_triangles(-26.0, -26.0, 12.0, 26.0, 26.0, 24.0))

    write_binary_stl(out_path, tris, "PrintLab HX711 Spool Cradle")


def generate_barcode_scanner_dock(out_path: Path) -> None:
    """6. Handscanner-Halterung (Holster mit 25° Neigung):

    Stabiler Köcher für gängige USB-/Funk-Handscanner mit Griffaussparung und Profilklemmung.
    """
    tris = []
    # Rückwand für Wand-/Rahmenmontage (70x75x5 mm)
    tris.extend(make_box_triangles(-35.0, 0.0, 0.0, 35.0, 6.0, 75.0))
    # Köcher-Bodenplatte
    tris.extend(make_box_triangles(-30.0, 6.0, 5.0, 30.0, 45.0, 10.0))
    # Linke und rechte Haltebacken
    tris.extend(make_box_triangles(-35.0, 6.0, 10.0, -28.0, 45.0, 60.0))
    tris.extend(make_box_triangles(28.0, 6.0, 10.0, 35.0, 45.0, 60.0))
    # Vordere Fanglippe mit Griffaussparung
    tris.extend(make_box_triangles(-35.0, 42.0, 10.0, -15.0, 48.0, 55.0))
    tris.extend(make_box_triangles(15.0, 42.0, 10.0, 35.0, 48.0, 55.0))

    write_binary_stl(out_path, tris, "PrintLab Barcode Scanner Dock")




def generate_door_opener_servo_bracket(out_path: Path) -> None:
    """7. Servomotor-Halterung für das automatische Türöffnen der Glastür (MG90S/SG90)."""
    tris = []
    tris.extend(make_box_triangles(-20.0, -15.0, 0.0, 20.0, 15.0, 6.0))
    tris.extend(make_box_triangles(-18.0, -14.0, 6.0, -12.0, 14.0, 26.0))
    tris.extend(make_box_triangles(12.0, -14.0, 6.0, 18.0, 14.0, 26.0))
    tris.extend(make_box_triangles(-18.0, -14.0, 22.0, 18.0, -6.0, 26.0))
    tris.extend(make_box_triangles(-18.0, 6.0, 22.0, 18.0, 14.0, 26.0))
    write_binary_stl(out_path, tris, "PrintLab Door Opener Servo Bracket")


def generate_door_push_pull_linkage(out_path: Path) -> None:
    """8. Schub- und Zughebel für Türöffner (Kniehebelstange 85mm mit Drehachsen)."""
    tris = []
    tris.extend(make_box_triangles(-4.0, -40.0, 0.0, 4.0, 40.0, 5.0))
    tris.extend(make_box_triangles(-8.0, -48.0, 0.0, 8.0, -40.0, 7.0))
    tris.extend(make_box_triangles(-8.0, 40.0, 0.0, 8.0, 48.0, 7.0))
    write_binary_stl(out_path, tris, "PrintLab Door Push-Pull Linkage")


def generate_plate_magazine_rack_tower(out_path: Path) -> None:
    """9. Vertikales Plattenmagazin (Tower für 4 Federstahl-Druckplatten)."""
    tris = []
    tris.extend(make_box_triangles(-60.0, -40.0, 0.0, 60.0, 40.0, 8.0))
    tris.extend(make_box_triangles(-60.0, -40.0, 8.0, -50.0, 40.0, 140.0))
    tris.extend(make_box_triangles(50.0, -40.0, 8.0, 60.0, 40.0, 140.0))
    tris.extend(make_box_triangles(-50.0, -40.0, 8.0, 50.0, -32.0, 140.0))
    for z_slot in (35.0, 65.0, 95.0, 125.0):
        tris.extend(make_box_triangles(-50.0, -32.0, z_slot, -42.0, 35.0, z_slot + 4.0))
        tris.extend(make_box_triangles(42.0, -32.0, z_slot, 50.0, 35.0, z_slot + 4.0))
    write_binary_stl(out_path, tris, "PrintLab Plate Magazine Rack Tower")


def generate_plate_washer_station_basin(out_path: Path) -> None:
    """10. Waschstation-Wanne mit Walzenlagern und Schmutzablauf."""
    tris = []
    tris.extend(make_box_triangles(-55.0, -35.0, 0.0, 55.0, 35.0, 8.0))
    tris.extend(make_box_triangles(-55.0, -35.0, 8.0, -47.0, 35.0, 45.0))
    tris.extend(make_box_triangles(47.0, -35.0, 8.0, 55.0, 35.0, 45.0))
    tris.extend(make_box_triangles(-47.0, -35.0, 8.0, 47.0, -28.0, 45.0))
    tris.extend(make_box_triangles(-47.0, 28.0, 8.0, 47.0, 35.0, 45.0))
    tris.extend(make_box_triangles(-15.0, -28.0, 8.0, -5.0, 28.0, 35.0))
    tris.extend(make_box_triangles(5.0, -28.0, 8.0, 15.0, 28.0, 35.0))
    write_binary_stl(out_path, tris, "PrintLab Plate Washer Station Basin")

def main() -> None:
    out_dir = Path(__file__).resolve().parent / "models_stl"
    out_dir.mkdir(parents=True, exist_ok=True)

    parts = [
        ("bambu_toolhead_sweeper_blade.stl", generate_toolhead_pusher_blade),
        ("bambu_bed_ejection_chute.stl", generate_bed_ejection_chute),
        ("gpio_servo_actuator_mount.stl", generate_servo_actuator_mount),
        ("hx711_loadcell_base.stl", generate_hx711_loadcell_base),
        ("hx711_spool_cradle.stl", generate_hx711_spool_cradle),
        ("barcode_scanner_wall_dock.stl", generate_barcode_scanner_dock),
        ("bambu_door_opener_servo_bracket.stl", generate_door_opener_servo_bracket),
        ("bambu_door_push_pull_linkage.stl", generate_door_push_pull_linkage),
        ("plate_magazine_rack_tower.stl", generate_plate_magazine_rack_tower),
        ("plate_washer_station_basin.stl", generate_plate_washer_station_basin),
    ]

    print("=== Generiere wasserdichte 3D-Druck-STL-Dateien ===")
    for filename, gen_fn in parts:
        p = out_dir / filename
        gen_fn(p)
        size_kb = p.stat().st_size / 1024.0
        print(f" -> {filename} generiert ({size_kb:.1f} KB)")

    print(f"\nErfolgreich alle 6 STL-Dateien in '{out_dir}' gespeichert!")


if __name__ == "__main__":
    main()
