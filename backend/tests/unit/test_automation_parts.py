"""Druckteile des Plattenwechslers: STL-Dateien, Teileliste (bauteile.json) und Konstruktionsplan passen zusammen.

Die STL-Dateien erzeugt ``werkzeuge/automation_hardware/bauteile.py`` (braucht ``manifold3d``, keine Projektabhängigkeit).
Dieser Test liest nur die erzeugten Dateien und kommt ohne CAD-Bibliothek aus.
"""

from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path

import pytest

from backend.app.services import plate_changer as pc

ROOT = Path(__file__).resolve().parents[3]
PARTS = ROOT / "werkzeuge" / "automation_hardware" / "models_stl" / "bauteile"
DOC = ROOT / "werkzeuge" / "automation_hardware" / "TUER_MAGAZIN_WASCHSTATION.md"
BED = 256.0


def _manifest() -> dict:
    path = PARTS / "bauteile.json"
    if not path.exists():
        pytest.skip("werkzeuge/ fehlt in dieser Umgebung")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_stl(path: Path) -> list[tuple[tuple[float, float, float], ...]]:
    data = path.read_bytes()
    (count,) = struct.unpack_from("<I", data, 80)
    assert len(data) == 84 + 50 * count, f"{path.name}: keine binäre STL"
    tris = []
    for i in range(count):
        v = struct.unpack_from("<9f", data, 84 + 50 * i + 12)
        tris.append(((v[0], v[1], v[2]), (v[3], v[4], v[5]), (v[6], v[7], v[8])))
    return tris


def _parts() -> list[dict]:
    return _manifest()["teile"]


@pytest.mark.parametrize("part", _parts() if (PARTS / "bauteile.json").exists() else [], ids=lambda p: p["datei"])
def test_each_part_fits_the_bed_and_is_closed(part):
    tris = _read_stl(PARTS / part["datei"])
    assert tris, part["datei"]
    pts = [p for t in tris for p in t]
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    size = [hi[k] - lo[k] for k in range(3)]
    assert min(lo) >= -0.01, "Teil liegt nicht auf dem Druckbett (Drucklage)"
    assert max(size) <= BED - 6.0, f"{part['datei']}: {size} mm passt nicht auf das P2S-Bett"
    assert size == pytest.approx(part["groesse_mm"], abs=0.11)
    # Geschlossen: jede Kante gehört zu genau zwei Dreiecken. Gemeinsame Ecken stehen bitgenau gleich in der Datei,
    # deshalb exakter Vergleich (Runden würde nahe, aber verschiedene Ecken zusammenlegen).
    edges: Counter = Counter()
    for t in tris:
        for a, b in ((0, 1), (1, 2), (2, 0)):
            edges[tuple(sorted((t[a], t[b])))] += 1
    open_edges = [e for e, n in edges.items() if n != 2]
    assert not open_edges, f"{part['datei']}: {len(open_edges)} offene Kanten"


def test_every_part_has_a_known_material_and_settings():
    manifest = _manifest()
    for part in manifest["teile"]:
        assert part["material"] in manifest["material"], part["datei"]
        assert 2 <= part["waende"] <= 6 and 10 <= part["infill"] <= 100, part["datei"]
        assert part["menge"] >= 1 and part["gewicht_g"] > 0, part["datei"]
    # Nichts aus PLA: kriecht unter Last und wird im Turm zu warm; im Waschbereich nur PETG (IPA-fest)
    assert all(p["material"] != "PLA" for p in manifest["teile"])
    assert all(p["material"] == "PETG" for p in manifest["teile"] if p["baugruppe"] == 4)


def test_no_stale_files_in_the_parts_folder():
    listed = {p["datei"] for p in _parts()}
    on_disk = {p.name for p in PARTS.glob("*.stl")}
    assert on_disk == listed


def test_the_plan_lists_every_part():
    if not DOC.exists():
        pytest.skip("werkzeuge/ fehlt in dieser Umgebung")
    text = DOC.read_text(encoding="utf-8")
    for part in _parts():
        assert f"`{part['datei']}`" in text, part["datei"]
    assert "plate_magazine_rack_tower.stl" not in text  # alte Platzhalter (Quader) sind ersetzt
    assert "plate_washer_station_basin.stl" not in text


def test_generator_never_uses_manifold_rotate():
    """``Manifold.rotate`` liefert in manifold3d 3.5.4 verzerrte Körper (doppeltes Volumen); bauteile.rotate nutzt transform."""
    src = ROOT / "werkzeuge" / "automation_hardware" / "bauteile.py"
    if not src.exists():
        pytest.skip("werkzeuge/ fehlt in dieser Umgebung")
    assert ".rotate(" not in src.read_text(encoding="utf-8")


def test_rack_combs_keep_the_guide_inside_the_tower_posts():
    """Fachkamm-Führung liegt zwischen Plattenkante und Steher (lichte Weite 266 mm, Platte 257 mm)."""
    names = {p["datei"] for p in _parts()}
    assert {
        "fachkamm_vorne_rechts.stl",
        "fachkamm_vorne_links.stl",
        "fachkamm_hinten_rechts.stl",
        "fachkamm_hinten_links.stl",
    } <= names
    comb = next(p for p in _parts() if p["datei"] == "fachkamm_vorne_rechts.stl")
    wall = (pc.TOWER_CLEAR_X - 259.0) / 2  # Wand zwischen Führungsfläche (259 mm) und Steher
    assert wall >= 3.0
    assert comb["groesse_mm"][2] <= wall + 10.0  # Wand plus Leiste (7 mm) nach innen
