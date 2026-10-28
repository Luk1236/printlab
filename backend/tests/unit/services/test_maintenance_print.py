"""Tests für den Wartungsdruck (Bewegungs-3MF)."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

import pytest

from backend.app.services.maintenance_print import MaintenancePrintError, build, build_gcode


class TestGcode:
    def test_oel_ohne_heizen_und_filament(self):
        gcode = build_gcode("oil")
        assert "G28" in gcode
        assert "G1 Z150" in gcode
        assert "G1 X236" in gcode
        assert "G1 Y236" in gcode
        for verboten in ("M104", "M109", "M140", "M190", "M141"):
            assert verboten not in gcode
        assert not re.search(r"G1[^\n]*\bE-?\d", gcode)

    def test_stangen_mit_zwei_pausen(self):
        gcode = build_gcode("rods")
        assert gcode.count("G4 S30") == 2
        assert gcode.count("G1 Z150") >= 10
        assert "M104" not in gcode

    def test_unbekanntes_programm_wird_zum_stangenprogramm(self):
        # Alles außer oil/oel/verteilen fällt bewusst auf das Stangenprogramm zurück.
        assert build_gcode("unbekannt") == build_gcode("rods")


class TestBuild:
    def _template(self, tmp_path: Path) -> Path:
        template = tmp_path / "vorlage.gcode.3mf"
        with zipfile.ZipFile(template, "w") as zf:
            zf.writestr("Metadata/plate_1.gcode", "ALTER-GCODE")
            zf.writestr("Metadata/plate_1.gcode.md5", "ALT")
            zf.writestr("Metadata/plate_1.json", "{}")
            zf.writestr(
                "Metadata/slice_info.config",
                '<config><plate><metadata key="prediction" value="999"/>'
                '<metadata key="weight" value="42"/>'
                '<metadata key="first_layer_time" value="12"/></plate></config>',
            )
            zf.writestr("3D/3dmodel.model", "<model/>")
        return template

    def test_ersetzt_gcode_und_pruefsumme(self, tmp_path):
        target = tmp_path / "out" / "Wartung_Oel.gcode.3mf"
        build(self._template(tmp_path), target, "oil")
        with zipfile.ZipFile(target) as zf:
            gcode = zf.read("Metadata/plate_1.gcode").decode()
            md5 = zf.read("Metadata/plate_1.gcode.md5").decode()
            info = zf.read("Metadata/slice_info.config").decode()
            assert zf.read("3D/3dmodel.model") == b"<model/>"
        assert gcode == build_gcode("oil")
        assert md5 == hashlib.md5(gcode.encode()).hexdigest().upper()
        assert 'key="prediction" value="420"' in info
        assert 'key="weight" value="0"' in info
        assert 'key="first_layer_time" value="0"' in info

    def test_keine_3mf_wirft(self, tmp_path):
        with pytest.raises(MaintenancePrintError):
            build(tmp_path / "fehlt.3mf", tmp_path / "out.3mf")
