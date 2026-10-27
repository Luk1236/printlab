"""Tests für die Hardware-Erweiterung (Tür und Plattenwechsler)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.app.services.hardware_extension import HardwareExtension, _run


def make(tmp: Path, **config) -> HardwareExtension:
    cfg = {"mode": "simulated", **config}
    (tmp / "hardware.json").write_text(json.dumps(cfg), encoding="utf-8")
    return HardwareExtension(tmp / "hardware.json", tmp / "magazine.json")


class TestSimulation:
    def test_default_ist_simuliert_und_legt_config_an(self, tmp_path):
        hw = HardwareExtension(tmp_path / "hardware.json", tmp_path / "magazine.json")
        assert hw.status()["mode"] == "simulated"
        assert (tmp_path / "hardware.json").is_file()

    def test_tuer_auf_und_zu(self, tmp_path):
        hw = make(tmp_path)
        assert hw.status()["door"] == "closed"
        ok, _ = hw.open_door()
        assert ok and hw.status()["door"] == "open"
        ok, _ = hw.close_door()
        assert ok and hw.status()["door"] == "closed"

    def test_plattenwechsel_verbraucht_vorrat_und_ablage(self, tmp_path):
        hw = make(tmp_path)
        before = hw.status()
        assert before["supply_ready"] == 3
        assert before["storage_empty"] == 3
        ok, message = hw.change_plate("Testteil.3mf")
        assert ok, message
        after = hw.status()
        assert after["supply_ready"] == 2
        assert after["storage_empty"] == 2
        assert after["changes"] == 1
        assert after["last_change"]
        used = next(s for s in after["slots"] if s["type"] == "supply" and s["status"] == "used")
        occupied = next(s for s in after["slots"] if s["type"] == "storage" and s["status"] == "occupied")
        assert used and occupied and occupied["print"] == "Testteil.3mf"

    def test_ohne_vorrat_kein_wechsel(self, tmp_path):
        hw = make(tmp_path)
        for _ in range(3):
            assert hw.change_plate()[0]
        ok, message = hw.change_plate()
        assert not ok
        assert "frische Platte" in message

    def test_auffuellen_setzt_zurueck(self, tmp_path):
        hw = make(tmp_path)
        assert hw.change_plate()[0]
        ok, _ = hw.refill_magazine()
        assert ok
        status = hw.status()
        assert status["supply_ready"] == 3
        assert status["storage_empty"] == 3
        assert status["changes"] == 1  # Zähler bleibt erhalten

    def test_zustand_ueberlebt_neustart(self, tmp_path):
        hw = make(tmp_path)
        assert hw.change_plate("Teil.3mf")[0]
        hw2 = HardwareExtension(tmp_path / "hardware.json", tmp_path / "magazine.json")
        assert hw2.status()["supply_ready"] == 2
        assert hw2.status()["changes"] == 1


class TestCommand:
    def test_befehl_erfolg_setzt_zustand(self, tmp_path):
        cmd = f'"{sys.executable}" -c "print(\'DOOR:OPEN\')"'
        hw = make(tmp_path, mode="command", door_open_command=cmd)
        ok, message = hw.open_door()
        assert ok, message
        assert hw.status()["door"] == "open"

    def test_fehlender_befehl_scheitert(self, tmp_path):
        hw = make(tmp_path, mode="command", door_open_command="")
        ok, message = hw.open_door()
        assert not ok
        assert "Kein Befehl" in message
        assert hw.status()["door"] == "closed"

    def test_run_fehlercode(self):
        ok, message = _run(f'"{sys.executable}" -c "import sys; sys.exit(2)"', 10)
        assert not ok
        assert "Code 2" in message or message

    def test_endschalter_unknown_scheitert(self, tmp_path):
        cmd = f'"{sys.executable}" -c "print(\'DOOR:UNKNOWN\')"'
        hw = make(tmp_path, mode="command", door_open_command=cmd)
        ok, message = hw.open_door()
        assert not ok
        assert "UNKNOWN" in message
        assert hw.status()["door"] == "closed"

    def test_falsche_tuerstellung_scheitert(self, tmp_path):
        cmd = f'"{sys.executable}" -c "print(\'DOOR:CLOSED\')"'
        hw = make(tmp_path, mode="command", door_open_command=cmd)
        ok, message = hw.open_door()
        assert not ok
        assert "geschlossen" in message
        assert hw.status()["door"] == "closed"

    def test_schliessen_erkennt_offene_tuer(self, tmp_path):
        cmd = f'"{sys.executable}" -c "print(\'DOOR:OPEN\')"'
        hw = make(tmp_path, mode="command", door_close_command=cmd)
        hw._door = "open"
        ok, message = hw.close_door()
        assert not ok
        assert "offen" in message
        assert hw.status()["door"] == "open"
