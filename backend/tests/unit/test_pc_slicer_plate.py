"""Unit tests for the PC slicer's plate selection and plate-scoped gcode."""

import zipfile
from pathlib import Path

from backend.app.pc_slicer import app as slicer_app
from backend.app.services.slicer_cli import build_command


class TestBuildCommand:
    def test_without_plate(self, tmp_path):
        cmd = build_command("studio.exe", tmp_path / "in.3mf", tmp_path, "out.gcode.3mf",
                            None, None, [], False, False)
        assert "--export-plate" not in cmd
        assert cmd[-1] == str(tmp_path / "in.3mf")

    def test_with_plate(self, tmp_path):
        cmd = build_command("studio.exe", tmp_path / "in.3mf", tmp_path, "out.gcode.3mf",
                            None, None, [], False, False, 2)
        idx = cmd.index("--export-plate")
        assert cmd[idx + 1] == "2"


class TestSliceRoutePlate:
    async def test_rejects_bad_plate_value(self):
        import io

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=slicer_app), base_url="http://test") as client:
            resp = await client.post(
                "/slice",
                files={"file": ("m.3mf", io.BytesIO(b"x"), "application/octet-stream")},
                data={"plate": "null"},
            )
        assert resp.status_code == 400
        assert "Platte" in resp.json()["detail"]

    async def test_gcode_extraction_prefers_chosen_plate(self, tmp_path, monkeypatch):
        """With plate=2 the route reads Metadata/plate_2.gcode, not plate_1."""
        import io

        from fastapi import HTTPException
        from httpx import ASGITransport, AsyncClient

        from backend.app.services import slicer_cli

        def fake_slice_file(source, name, printer_json=None, process_json=None,
                            filament_jsons=None, arrange=False, orient=False,
                            timeout=900.0, plate=None):
            assert plate == 2
            out = tmp_path / name
            labels = {"Metadata/plate_1.gcode": "FIRST", "Metadata/plate_2.gcode": "SECOND"}
            with zipfile.ZipFile(out, "w") as zf:
                for member, text in labels.items():
                    zf.writestr(member, text)
            return slicer_cli.SliceOutput(out.read_bytes(), 12, 3.4)

        monkeypatch.setattr(slicer_cli, "slice_file", fake_slice_file)
        from backend.app import pc_slicer

        monkeypatch.setattr(pc_slicer, "slice_file", fake_slice_file)

        async with AsyncClient(transport=ASGITransport(app=slicer_app), base_url="http://test") as client:
            resp = await client.post(
                "/slice",
                files={"file": ("m.3mf", io.BytesIO(b"z"), "application/octet-stream")},
                data={"plate": "2"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.text == "SECOND"
        assert resp.headers["X-Print-Time-Seconds"] == "12"
