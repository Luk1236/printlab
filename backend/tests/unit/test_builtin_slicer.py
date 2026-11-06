"""Unit-Tests fuer den integrierten PrintLab-Slicer (builtin_slicer & pc_slicer)."""

from __future__ import annotations

import io
import json
import struct
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.pc_slicer import app as pc_slicer_app
from backend.app.services.builtin_slicer import (
    list_bundled_profiles,
    resolve_profile_values,
    slice_model_builtin,
)
from backend.app.services.slicer_cli import SlicerCliError


def _make_binary_stl_cube(path: Path) -> None:
    """Schreibt einen einfachen binaeren STL-Wuerfel (10x10x10 mm)."""
    triangles = [
        ((0, 0, -1), (0, 0, 0), (10, 10, 0), (10, 0, 0)),
        ((0, 0, -1), (0, 0, 0), (0, 10, 0), (10, 10, 0)),
        ((0, 0, 1), (0, 0, 10), (10, 0, 10), (10, 10, 10)),
        ((0, 0, 1), (0, 0, 10), (10, 10, 10), (0, 10, 10)),
        ((0, -1, 0), (0, 0, 0), (10, 0, 0), (10, 0, 10)),
        ((0, -1, 0), (0, 0, 0), (10, 0, 10), (0, 0, 10)),
        ((0, 1, 0), (0, 10, 0), (10, 10, 10), (10, 10, 0)),
        ((0, 1, 0), (0, 10, 0), (0, 10, 10), (10, 10, 10)),
        ((-1, 0, 0), (0, 0, 0), (0, 0, 10), (0, 10, 10)),
        ((-1, 0, 0), (0, 0, 0), (0, 10, 10), (0, 10, 0)),
        ((1, 0, 0), (10, 0, 0), (10, 10, 0), (10, 10, 10)),
        ((1, 0, 0), (10, 0, 0), (10, 10, 10), (10, 0, 10)),
    ]
    buf = io.BytesIO()
    buf.write(b"PrintLab STL Cube".ljust(80, b"\x00"))
    buf.write(struct.pack("<I", len(triangles)))
    for normal, v0, v1, v2 in triangles:
        buf.write(struct.pack("<12fH", *normal, *v0, *v1, *v2, 0))
    path.write_bytes(buf.getvalue())


def test_list_bundled_profiles_includes_p2s_and_all_slots():
    bundled = list_bundled_profiles()
    assert set(bundled.keys()) == {"printer", "process", "filament"}
    printer_names = [p["name"] for p in bundled["printer"]]
    assert "Bambu Lab P2S 0.4 nozzle" in printer_names
    assert len(bundled["process"]) >= 5
    assert len(bundled["filament"]) >= 5
    for proc in bundled["process"]:
        assert "Bambu Lab P2S 0.4 nozzle" in proc["compatible_printers"]


def test_resolve_profile_values_flattens_inherits_and_overrides():
    resolved = resolve_profile_values(
        "process",
        {"inherits": "0.16mm Optimal @BBL P2S", "sparse_infill_density": "25%"},
    )
    assert resolved["layer_height"] == "0.16"
    assert resolved["sparse_infill_density"] == "25%"


def test_slice_model_builtin_produces_valid_gcode_3mf(tmp_path: Path):
    stl_path = tmp_path / "cube.stl"
    _make_binary_stl_cube(stl_path)

    result = slice_model_builtin(
        stl_path,
        "cube.gcode.3mf",
        printer_json=json.dumps({"inherits": "Bambu Lab P2S 0.4 nozzle"}),
        process_json=json.dumps({"inherits": "0.20mm Standard @BBL P2S"}),
        filament_jsons=[json.dumps({"inherits": "Bambu PLA Basic @BBL P2S"})],
    )
    assert result.print_time_seconds > 0
    assert result.filament_grams > 0
    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        names = set(zf.namelist())
        assert "Metadata/plate_1.gcode" in names
        assert "Metadata/plate_1.gcode.md5" in names
        assert "Metadata/slice_info.config" in names
        gcode = zf.read("Metadata/plate_1.gcode").decode("utf-8")
        assert "; CHANGE_LAYER" in gcode
        assert "PrintLab Builtin Slicer" in gcode


def test_pc_slicer_sidecar_contract_endpoints(tmp_path: Path):
    client = TestClient(pc_slicer_app)

    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["checks"]["slicer"]["version"]

    bundled = client.get("/profiles/bundled")
    assert bundled.status_code == 200
    assert len(bundled.json()["printer"]) >= 5

    resolved = client.post(
        "/profiles/resolve",
        json={"category": "process", "profile": {"inherits": "0.20mm Standard @BBL P2S"}},
    )
    assert resolved.status_code == 200
    assert resolved.json()["profile"]["layer_height"] == "0.2"
    assert resolved.json()["values"]["layer_height"] == "0.2"

    stl_path = tmp_path / "part.stl"
    _make_binary_stl_cube(stl_path)
    with patch("backend.app.pc_slicer.slice_file", side_effect=SlicerCliError("Bambu Studio nicht gefunden")):
        slice_resp = client.post(
            "/slice",
            headers={"X-Slice-Request-Id": "test-req-1"},
            data={"exportType": "3mf"},
            files=[
                ("file", ("part.stl", stl_path.read_bytes(), "application/octet-stream")),
                (
                    "printerProfile",
                    ("printer.json", json.dumps({"inherits": "Bambu Lab P2S 0.4 nozzle"}).encode(), "application/json"),
                ),
                (
                    "presetProfile",
                    ("process.json", json.dumps({"inherits": "0.20mm Standard @BBL P2S"}).encode(), "application/json"),
                ),
                (
                    "filamentProfile",
                    (
                        "filament_1.json",
                        json.dumps({"inherits": "Bambu PLA Basic @BBL P2S"}).encode(),
                        "application/json",
                    ),
                ),
            ],
        )
    assert slice_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(slice_resp.content), "r") as zf:
        assert "Metadata/plate_1.gcode" in zf.namelist()

    prog = client.get("/slice/progress/test-req-1")
    assert prog.status_code == 200
    assert prog.json()["percent"] == 100


def test_slice_model_builtin_slices_true_geometry_not_bounding_box(tmp_path: Path):
    """Prueft, dass ein Zylinder mit runder Kontur geslict wird und NICHT als 4-Ecken-Klotz (Kastenleiste)."""
    import re
    import trimesh
    cyl = trimesh.creation.cylinder(radius=12.0, height=8.0)
    stl_path = tmp_path / "cylinder.stl"
    cyl.export(str(stl_path))

    result = slice_model_builtin(
        stl_path,
        "cylinder.gcode.3mf",
        printer_json=json.dumps({"inherits": "Bambu Lab P2S 0.4 nozzle"}),
        process_json=json.dumps({"inherits": "0.20mm Standard @BBL P2S"}),
        filament_jsons=[json.dumps({"inherits": "Bambu PLA Basic @BBL P2S"})],
    )
    assert result.print_time_seconds > 0
    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        gcode = zf.read("Metadata/plate_1.gcode").decode("utf-8")
        
        # Pruefe Schichten: es muessen viele runde Koordinatenpunkte vorkommen
        lines = [l for l in gcode.splitlines() if l.startswith("G1 X") and "E" in l]
        assert len(lines) > 50, "Zu wenige G1-Pfade fuer ein 3D-Modell"
        
        # Ein runder Zylinder hat Dutzende unterschiedliche X-Werte,
        # waehrend ein Quader / Kastenleiste nur exakt 2 oder 4 X-Werte hat.
        x_values = set()
        for l in lines:
            m = re.search(r"X([\d.]+)", l)
            if m:
                x_values.add(round(float(m.group(1)), 1))
        assert len(x_values) >= 10, f"Modell wurde als Klotz statt als echter Zylinder geslict! X-Werte: {x_values}"


def test_slice_model_builtin_generates_solid_shells_and_multi_walls(tmp_path: Path):
    """Prueft, dass der Builtin-Slicer dichte Boeden/Decken, Innenwaende und Feature-Tags erzeugt."""
    import trimesh
    box = trimesh.creation.box([30.0, 30.0, 10.0])
    stl_path = tmp_path / "box.stl"
    box.export(str(stl_path))

    result = slice_model_builtin(
        stl_path,
        "box.gcode.3mf",
        printer_json=json.dumps({"inherits": "Bambu Lab P2S 0.4 nozzle"}),
        process_json=json.dumps({"inherits": "0.20mm Standard @BBL P2S", "wall_loops": "3"}),
        filament_jsons=[json.dumps({"inherits": "Bambu PLA Basic @BBL P2S"})],
    )
    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        gcode = zf.read("Metadata/plate_1.gcode").decode("utf-8")
        assert "; FEATURE: Outer wall" in gcode
        assert "; FEATURE: Inner wall" in gcode
        assert "; FEATURE: Top surface" in gcode
        assert "G1 E-0.8000 F3600" in gcode  # Retraktion bei Travel
