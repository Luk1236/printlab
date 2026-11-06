"""Unit-Tests fuer den integrierten PrintLab-Slicer (builtin_slicer, slicer_manager & pc_slicer)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app.pc_slicer import app as pc_slicer_app
from backend.app.services.builtin_slicer import (
    BUILTIN_VERSION,
    list_bundled_profiles,
    resolve_profile_values,
    slice_model_builtin,
)
from backend.app.services.slicer_cli import SliceOutput, SlicerCliError
from backend.app.services.slicer_manager import find_existing_slicer, get_slicer_status


def _make_dummy_3mf_with_gcode(path: Path, gcode: str = "; TEST GCODE\nG1 X10 Y10\n") -> None:
    """Erzeugt eine Test-3MF mit eingebetteter plate_1.gcode."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        zf.writestr("Metadata/plate_1.gcode", gcode.encode("utf-8"))
        zf.writestr(
            "Metadata/slice_info.config",
            '<config><plate><metadata key="prediction" value="120"/><metadata key="weight" value="5.5"/></plate></config>',
        )
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


def test_slice_model_builtin_extracts_pre_sliced_3mf(tmp_path: Path):
    """Testet, dass bereits geslicte 3MFs mit vorhandenem G-Code sofort extrahiert werden."""
    dummy_3mf = tmp_path / "presliced.3mf"
    _make_dummy_3mf_with_gcode(dummy_3mf, "; OrcaSlicer generated gcode\nM104 S220\n")

    result = slice_model_builtin(dummy_3mf, "out.gcode.3mf", plate=1)
    assert result.print_time_seconds == 120
    assert result.filament_grams == 5.5
    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        assert "Metadata/plate_1.gcode" in zf.namelist()
        gcode = zf.read("Metadata/plate_1.gcode").decode("utf-8")
        assert "OrcaSlicer generated gcode" in gcode


def test_slice_model_builtin_delegates_to_real_slicer(tmp_path: Path):
    """Testet, dass ungeslicte Modelle an die echte OrcaSlicer-CLI delegiert werden."""
    stl_path = tmp_path / "model.stl"
    stl_path.write_text("solid test\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 1 1 0\nendloop\nendfacet\nendsolid test\n")

    mock_output = SliceOutput(b"FAKE_3MF_DATA", 300, 12.4)
    with patch("backend.app.services.builtin_slicer.find_existing_slicer", return_value="/usr/local/bin/orca-slicer"), \
         patch("backend.app.services.builtin_slicer.slice_file", return_value=mock_output) as mock_slice:
        res = slice_model_builtin(
            stl_path,
            "model.gcode.3mf",
            printer_json=json.dumps({"name": "Bambu Lab P2S 0.4 nozzle"}),
            process_json=json.dumps({"layer_height": "0.2"}),
            plate=1,
            request_id="req-123",
        )
        assert res.print_time_seconds == 300
        assert res.filament_grams == 12.4
        assert mock_slice.called


def test_slicer_manager_status_and_discovery():
    status = get_slicer_status()
    assert "installed" in status
    assert "version" in status
    assert "platform" in status
    assert status["version"] == "2.4.2"


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

    dummy_3mf = tmp_path / "part.3mf"
    _make_dummy_3mf_with_gcode(dummy_3mf, "; GCODE PLATE 1\n")

    slice_resp = client.post(
        "/slice",
        headers={"X-Slice-Request-Id": "test-req-1"},
        data={"exportType": "3mf"},
        files=[
            ("file", ("part.3mf", dummy_3mf.read_bytes(), "application/octet-stream")),
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
