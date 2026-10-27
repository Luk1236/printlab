"""Tests für den PC-Slicer (Bambu Studio CLI + Sidecar-API)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import pc_slicer
from backend.app.services.slicer_cli import SliceOutput, _read_slice_info, build_command, slice_file


def make_3mf() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Metadata/plate_1.gcode", "G28\nG1 X20\n")
        zf.writestr("Metadata/slice_info.config",
                    '<plate><metadata key="prediction" value="420"/><metadata key="weight" value="12.5"/></plate>')
    return buf.getvalue()


class TestCli:
    def test_befehl_mit_profilen(self, tmp_path):
        (tmp_path / "m.3mf").write_bytes(b"3mf")
        cmd = build_command("bambu-studio.exe", tmp_path / "m.3mf", tmp_path, "out.gcode.3mf",
                            '{"a":1}', '{"b":2}', ['{"c":3}', '{"d":4}'], arrange=True, orient=True)
        assert "--load-settings" in cmd
        assert "--load-filaments" in cmd
        assert "--arrange" in cmd and cmd[cmd.index("--arrange") + 1] == "1"
        assert "--orient" in cmd and cmd[cmd.index("--orient") + 1] == "1"
        assert (tmp_path / "machine.json").read_text() == '{"a":1}'
        assert (tmp_path / "filament_2.json").read_text() == '{"d":4}'

    def test_befehl_ohne_profile(self, tmp_path):
        (tmp_path / "m.3mf").write_bytes(b"3mf")
        cmd = build_command("bambu-studio.exe", tmp_path / "m.3mf", tmp_path, "out.gcode.3mf",
                            None, None, [], arrange=False, orient=False)
        assert "--load-settings" not in cmd
        assert cmd[cmd.index("--arrange") + 1] == "0"

    def test_slice_info_lesen(self, tmp_path):
        path = tmp_path / "x.3mf"
        path.write_bytes(make_3mf())
        seconds, grams = _read_slice_info(path)
        assert seconds == 420
        assert grams == 12.5

    def test_fehlendes_programm(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BAMBU_STUDIO", str(tmp_path / "fehlt.exe"))
        with pytest.raises(Exception):
            slice_file(tmp_path / "m.3mf", "out.gcode.3mf")


class TestApi:
    def client(self):
        return TestClient(pc_slicer.app)

    def test_health(self):
        data = self.client().get("/health").json()
        assert data["status"] == "ok"
        assert "available" in data

    def test_falsche_endung(self):
        response = self.client().post("/slice", files={"file": ("x.txt", b"abc", "text/plain")})
        assert response.status_code == 400

    def test_slice_liefert_3mf(self, monkeypatch):
        def fake(*args, **kwargs):
            return SliceOutput(make_3mf(), 420, 12.5)
        monkeypatch.setattr(pc_slicer, "slice_file", fake)
        response = self.client().post(
            "/slice",
            files={"file": ("modell.3mf", b"PK\x03\x04", "application/octet-stream")},
            data={"exportType": "3mf", "arrange": "1"},
        )
        assert response.status_code == 200, response.text
        assert response.headers["X-Print-Time-Seconds"] == "420"
        assert response.headers["X-Filament-Used-G"] == "12.50"
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert "Metadata/plate_1.gcode" in zf.namelist()

    def test_progress_nicht_unterstuetzt(self):
        assert self.client().get("/slice/progress/abc").status_code == 404
