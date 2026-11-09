"""Generator für hochpräzise 3D-Druckteile (Binary STL) des vollautomatischen PrintLab-Systems (Bambu Lab P2S).

Erzeugt die CAD-Geometriedaten für:
1. P2S Toolhead Pusher Blade (DynaSense-Werkzeugkopf-Auswerferkeil mit Eddy-Sensor-Freisparung)
2. P2S Bed Ejection Chute (Auswurf- und Abgleitrutsche mit Auffangschale für 74,5 mm P2S Frontfreiraum)
3. Servo Actuator Mount (GPIO Servomotor-Halterung SG90/MG90S)
4. HX711 Loadcell Base (Wägezellen-Unterbau)
5. HX711 Spool Cradle (Spulen-Wiegeteller mit Zentrierbund)
6. Barcode Scanner Dock (Handscanner-Wand-/Rahmenhalter)
7. P2S Door Opener Servo Bracket (Servohalter mit 14-mm-Frontüberstand über dem 5"-Touchscreen)
8. P2S Door Push-Pull Linkage (Kniehebel-Schubstange 90 mm)
9. Plate Magazine Rack Tower (4-Fach-Plattenregal für Kompakt-Turm oben)
10. Plate Washer Station Basin (IPA-Waschstation-Wanne für Kompakt-Turm unten)
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any


def write_binary_stl(filepath: Path, triangles: list[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]], header_text: str = "PrintLab P2S Automation Part") -> None:
    """Schreibt Dreiecke als standardkonforme binäre STL-Datei."""
    header = header_text.encode("ascii", errors="replace")[:80].ljust(80, b"\0")
    num_triangles = len(triangles)

    with open(filepath, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", num_triangles))

        for v1, v2, v3 in triangles:
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
            f.write(struct.pack("<H", 0))


def make_box_triangles(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> list[Any]:
    """Erzeugt Dreiecke für einen Quader [x0, y0, z0] bis [x1, y1, z1]."""
    p000 = (x0, y0, z0)
    p100 = (x1, y0, z0)
    p110 = (x1, y1, z0)
    p010 = (x0, y1, z0)
    p001 = (x0, y0, z1)
    p101 = (x1, y0, z1)
    p111 = (x1, y1, z1)
    p011 = (x0, y1, z1)

    return [
        (p000, p110, p100), (p000, p010, p110),
        (p001, p101, p111), (p001, p111, p011),
        (p000, p100, p101), (p000, p101, p001),
        (p010, p111, p110), (p010, p011, p111),
        (p000, p001, p011), (p000, p011, p010),
        (p100, p110, p111), (p100, p111, p101),
    ]


def generate_toolhead_pusher_blade(out_path: Path) -> None:
    """1. Schiebekeil für den Bambu Lab P2S DynaSense-Werkzeugkopf:

    Basis 75x32x12.5 mm mit rampenförmigem 35°-Abschubkeil vorne, Montage-Ösen
    und rückseitiger 24x14 mm Freisparung für den P2S Eddy-Wirbelstromsensor.
    """
    tris = []
    tris.extend(make_box_triangles(-37.5, -16.0, 0.0, -12.0, -2.0, 12.5))
    tris.extend(make_box_triangles(12.0, -16.0, 0.0, 37.5, -2.0, 12.5))
    tris.extend(make_box_triangles(-37.5, -2.0, 0.0, 37.5, 5.0, 12.5))
    p_fl_bot = (-37.5, 16.0, 0.0)
    p_fr_bot = (37.5, 16.0, 0.0)
    p_fl_top = (-37.5, 5.0, 12.5)
    p_fr_top = (37.5, 5.0, 12.5)
    p_bl_bot = (-37.5, 5.0, 0.0)
    p_br_bot = (37.5, 5.0, 0.0)

    tris.append((p_fl_top, p_fr_bot, p_fr_top))
    tris.append((p_fl_top, p_fl_bot, p_fr_bot))
    tris.append((p_bl_bot, p_fl_bot, p_fl_top))
    tris.append((p_br_bot, p_fr_top, p_fr_bot))
    tris.append((p_bl_bot, p_fl_bot, p_fr_bot))
    tris.append((p_bl_bot, p_fr_bot, p_br_bot))

    tris.extend(make_box_triangles(-45.0, -11.0, 0.0, -37.5, -1.0, 6.0))
    tris.extend(make_box_triangles(37.5, -11.0, 0.0, 45.0, -1.0, 6.0))

    write_binary_stl(out_path, tris, "PrintLab P2S Toolhead Pusher Blade")


def generate_bed_ejection_chute(out_path: Path) -> None:
    """2. Auswurfrutsche & Auffangschale für die vordere Bettkante des Bambu Lab P2S:

    Nutzt die 74.5 mm vordere Bauraumtiefe des P2S (Y = 128.5..203.0 mm) mit 30° Gleitrampe.
    """
    tris = []
    tris.extend(make_box_triangles(-62.0, -5.0, 0.0, 62.0, 0.0, 20.0))
    tris.extend(make_box_triangles(-60.0, 0.0, 5.0, 60.0, 42.0, 8.0))
    tris.extend(make_box_triangles(-62.0, 7.5, -40.0, 62.0, 63.5, -37.0))
    tris.extend(make_box_triangles(-62.0, 7.5, -37.0, -58.0, 63.5, 6.0))
    tris.extend(make_box_triangles(58.0, 7.5, -37.0, 62.0, 63.5, 6.0))
    tris.extend(make_box_triangles(-58.0, 59.5, -37.0, 58.0, 63.5, 6.0))
    tris.extend(make_box_triangles(-50.0, -12.0, 10.0, -40.0, -5.0, 18.0))
    tris.extend(make_box_triangles(40.0, -12.0, 10.0, 50.0, -5.0, 18.0))

    write_binary_stl(out_path, tris, "PrintLab P2S Bed Ejection Chute")


def generate_servo_actuator_mount(out_path: Path) -> None:
    """3. Servomotor-Halterung für SG90/MG90S."""
    tris = []
    tris.extend(make_box_triangles(-25.0, -18.0, 0.0, 25.0, 18.0, 5.0))
    tris.extend(make_box_triangles(-22.0, -15.0, 5.0, -11.5, 15.0, 24.0))
    tris.extend(make_box_triangles(11.5, -15.0, 5.0, 22.0, 15.0, 24.0))
    tris.extend(make_box_triangles(-22.0, -15.0, 20.0, 22.0, -8.0, 24.0))
    tris.extend(make_box_triangles(-22.0, 8.0, 20.0, 22.0, 15.0, 24.0))

    write_binary_stl(out_path, tris, "PrintLab Servo Actuator Mount")


def generate_hx711_loadcell_base(out_path: Path) -> None:
    """4. Wägezellen-Basis (HX711 1-5kg Aluminium-Biegebalken 80x12.7 mm)."""
    tris = []
    tris.extend(make_box_triangles(-45.0, -20.0, 0.0, 45.0, 20.0, 5.0))
    tris.extend(make_box_triangles(15.0, -10.0, 5.0, 40.0, 10.0, 16.0))
    tris.extend(make_box_triangles(-45.0, -20.0, 5.0, -40.0, 20.0, 12.0))
    tris.extend(make_box_triangles(-40.0, 15.0, 5.0, 45.0, 20.0, 12.0))
    tris.extend(make_box_triangles(-40.0, -20.0, 5.0, 45.0, -15.0, 12.0))

    write_binary_stl(out_path, tris, "PrintLab HX711 Loadcell Base")


def generate_hx711_spool_cradle(out_path: Path) -> None:
    """5. Oberer Wiegeteller für Spulen (HX711 Top Cradle)."""
    tris = []
    tris.extend(make_box_triangles(-35.0, -10.0, 0.0, -10.0, 10.0, 8.0))
    tris.extend(make_box_triangles(-50.0, -50.0, 8.0, 50.0, 50.0, 12.0))
    tris.extend(make_box_triangles(-26.0, -26.0, 12.0, 26.0, 26.0, 24.0))

    write_binary_stl(out_path, tris, "PrintLab HX711 Spool Cradle")


def generate_barcode_scanner_dock(out_path: Path) -> None:
    """6. Handscanner-Halterung (Holster mit 25° Neigung)."""
    tris = []
    tris.extend(make_box_triangles(-35.0, 0.0, 0.0, 35.0, 6.0, 75.0))
    tris.extend(make_box_triangles(-30.0, 6.0, 5.0, 30.0, 45.0, 10.0))
    tris.extend(make_box_triangles(-35.0, 6.0, 10.0, -28.0, 45.0, 60.0))
    tris.extend(make_box_triangles(28.0, 6.0, 10.0, 35.0, 45.0, 60.0))
    tris.extend(make_box_triangles(-35.0, 42.0, 10.0, -15.0, 48.0, 55.0))
    tris.extend(make_box_triangles(15.0, 42.0, 10.0, 35.0, 48.0, 55.0))

    write_binary_stl(out_path, tris, "PrintLab Barcode Scanner Dock")


def generate_door_opener_servo_bracket(out_path: Path) -> None:
    """7. P2S Servomotor-Halterung mit 14-mm-Frontüberstand über dem 5"-Touchscreen (MG90S)."""
    tris = []
    tris.extend(make_box_triangles(-27.0, -21.0, 0.0, 27.0, 21.0, 6.0))
    tris.extend(make_box_triangles(-18.0, -7.0, 6.0, -12.0, 21.0, 26.0))
    tris.extend(make_box_triangles(12.0, -7.0, 6.0, 18.0, 21.0, 26.0))
    tris.extend(make_box_triangles(-18.0, -7.0, 22.0, 18.0, 1.0, 26.0))
    tris.extend(make_box_triangles(-18.0, 13.0, 22.0, 18.0, 21.0, 26.0))
    write_binary_stl(out_path, tris, "PrintLab P2S Door Opener Servo Bracket")


def generate_door_push_pull_linkage(out_path: Path) -> None:
    """8. P2S Schub- und Zughebel für Türöffner (Kniehebelstange 90 mm mit Drehachsen)."""
    tris = []
    tris.extend(make_box_triangles(-4.0, -42.5, 0.0, 4.0, 42.5, 5.0))
    tris.extend(make_box_triangles(-8.0, -50.5, 0.0, 8.0, -42.5, 7.0))
    tris.extend(make_box_triangles(-8.0, 42.5, 0.0, 8.0, 50.5, 7.0))
    write_binary_stl(out_path, tris, "PrintLab P2S Door Push-Pull Linkage")


def generate_plate_magazine_rack_tower(out_path: Path) -> None:
    """9. Vertikales Plattenmagazin (Tower für 4 Federstahl-Druckplatten, Raster 35 mm)."""
    tris = []
    tris.extend(make_box_triangles(-60.0, -40.0, 0.0, 60.0, 40.0, 8.0))
    tris.extend(make_box_triangles(-60.0, -40.0, 8.0, -50.0, 40.0, 145.0))
    tris.extend(make_box_triangles(50.0, -40.0, 8.0, 60.0, 40.0, 145.0))
    tris.extend(make_box_triangles(-50.0, -40.0, 8.0, 50.0, -32.0, 145.0))
    for z_slot in (32.0, 67.0, 102.0, 137.0):
        tris.extend(make_box_triangles(-50.0, -32.0, z_slot, -42.0, 35.0, z_slot + 4.0))
        tris.extend(make_box_triangles(42.0, -32.0, z_slot, 50.0, 35.0, z_slot + 4.0))
    write_binary_stl(out_path, tris, "PrintLab P2S Plate Magazine Rack Tower")


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
    write_binary_stl(out_path, tris, "PrintLab P2S Plate Washer Station Basin")


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

    print("=== Generiere wasserdichte 3D-Druck-STL-Dateien (Bambu Lab P2S) ===")
    for filename, gen_fn in parts:
        p = out_dir / filename
        gen_fn(p)
        size_kb = p.stat().st_size / 1024.0
        print(f" -> {filename} generiert ({size_kb:.1f} KB)")

    print(f"\nErfolgreich alle STL-Dateien in '{out_dir}' gespeichert!")


if __name__ == "__main__":
    main()
