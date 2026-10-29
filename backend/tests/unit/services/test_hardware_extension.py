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


class TestEmergencyStop:
    def test_simulation_setzt_zustand_auf_unbekannt(self, tmp_path):
        hw = make(tmp_path)
        ok, message = hw.emergency_stop()
        assert ok
        assert "Simulation" in message
        assert hw.status()["door"] == "unknown"

    def test_befehl_wird_ausgefuehrt(self, tmp_path):
        cmd = f'"{sys.executable}" -c "print(\'STOP:OK\')"'
        hw = make(tmp_path, mode="command", emergency_stop_command=cmd)
        ok, message = hw.emergency_stop()
        assert ok, message
        assert hw.status()["door"] == "unknown"

    def test_ohne_befehl_scheitert(self, tmp_path):
        hw = make(tmp_path, mode="command")
        ok, message = hw.emergency_stop()
        assert not ok
        assert "Kein Befehl" in message


PY = f'"{sys.executable}"'


class TestEmergencyStopLatch:
    def test_after_estop_everything_is_locked_until_reload(self, tmp_path):
        hw = make(tmp_path)
        ok, _ = hw.emergency_stop()
        assert ok
        assert hw.status()["estop"] is True
        for action in (hw.open_door, hw.close_door, hw.change_plate):
            ok, message = action()
            assert not ok and "Not-Halt" in message
        hw.reload_config()
        assert hw.status()["estop"] is False
        assert hw.open_door()[0]

    def test_refill_also_lifts_the_latch(self, tmp_path):
        hw = make(tmp_path)
        hw.emergency_stop()
        hw.refill_magazine()
        assert hw.status()["estop"] is False

    def test_estop_kills_the_running_command(self, tmp_path):
        import threading
        import time

        hw = make(
            tmp_path,
            mode="command",
            timeout_seconds=30,
            door_open_command=[sys.executable, "-c", "import time; time.sleep(20)"],
            emergency_stop_command=f'{PY} -c "print(1)"',
        )
        result = {}
        thread = threading.Thread(target=lambda: result.update(r=hw.open_door()))
        thread.start()
        for _ in range(100):
            if hw._proc is not None:
                break
            time.sleep(0.05)
        started = time.time()
        assert hw.emergency_stop()[0]
        thread.join(10)
        assert not thread.is_alive()
        assert time.time() - started < 10  # nicht erst nach 20 s Befehlsdauer
        assert result["r"][0] is False


class TestIncompleteChange:
    def _cmd(self, code: int) -> str:
        return f'{PY} -c "import sys; sys.exit({code})"'

    def test_door_close_failure_tracks_magazine_and_blocks(self, tmp_path):
        hw = make(
            tmp_path,
            mode="command",
            door_open_command=self._cmd(0),
            plate_change_command=self._cmd(0),
            door_close_command=self._cmd(3),
        )
        ok, message = hw.change_plate("Teil")
        assert not ok and "unvollständig" in message
        status = hw.status()
        assert status["incomplete"]["step"] == "Tür schließen"
        assert status["supply_ready"] == 2  # Platte ist mechanisch getauscht, Magazin nachgeführt
        assert status["door"] == "unknown"
        ok, message = hw.change_plate("Nochmal")
        assert not ok and "unvollständig" in message

    def test_plate_change_failure_does_not_touch_magazine(self, tmp_path):
        hw = make(
            tmp_path,
            mode="command",
            door_open_command=self._cmd(0),
            plate_change_command=self._cmd(2),
            door_close_command=self._cmd(0),
        )
        assert not hw.change_plate("Teil")[0]
        assert hw.status()["supply_ready"] == 3
        assert hw.status()["incomplete"]["step"] == "Plattenwechsel"

    def test_door_open_failure_is_a_plain_error(self, tmp_path):
        hw = make(tmp_path, mode="command", door_open_command=self._cmd(1))
        assert not hw.change_plate("Teil")[0]
        assert hw.status()["incomplete"] is None

    def test_resolve_clears_the_block(self, tmp_path):
        hw = make(
            tmp_path,
            mode="command",
            door_open_command=self._cmd(0),
            plate_change_command=self._cmd(2),
            door_close_command=self._cmd(0),
        )
        hw.change_plate("Teil")
        assert hw.resolve_incomplete()[0]
        assert hw.status()["incomplete"] is None
        assert not hw.resolve_incomplete()[0]

    def test_closing_the_door_resolves_a_door_close_failure(self, tmp_path):
        hw = make(
            tmp_path,
            mode="command",
            door_open_command=self._cmd(0),
            plate_change_command=self._cmd(0),
            door_close_command=self._cmd(3),
        )
        hw.change_plate("Teil")
        hw._config["door_close_command"] = self._cmd(0)
        assert hw.close_door()[0]
        assert hw.status()["incomplete"] is None


class TestCommandLists:
    def test_list_command_runs_without_shell(self):
        ok, output = _run([sys.executable, "-c", "print('a b')"], 10)
        assert ok and output == "a b"

    def test_list_arguments_are_not_shell_interpreted(self):
        ok, output = _run([sys.executable, "-c", "import sys; print(sys.argv[1])", "x && echo hacked"], 10)
        assert ok and output == "x && echo hacked"

    def test_config_accepts_lists_and_rejects_other_types(self, tmp_path):
        hw = make(tmp_path)
        assert hw.update_config({"door_open_command": ["tool", "--open"]})[0]
        assert hw.config()["door_open_command"] == ["tool", "--open"]
        assert not hw.update_config({"door_open_command": 5})[0]
        assert not hw.update_config({"door_open_command": ["ok", 3]})[0]


class TestStringCommandsRunWithoutShell:
    """Auch String-Befehle laufen ohne Shell (#sprint-2910): Zitatbewusste Auflösung, Shell-Zeichen abgelehnt."""

    def test_string_is_split_without_shell(self):
        ok, output = _run(f'"{sys.executable}" -c "import sys; print(sys.argv[1])" "x && echo hacked"', 10)
        assert ok, output
        assert output == "x && echo hacked"

    def test_shell_operators_are_rejected_with_list_hint(self, tmp_path):
        hw = make(tmp_path, mode="command", door_open_command="prog --open > log.txt")
        ok, message = hw.open_door()
        assert not ok
        assert "Liste" in message
        assert hw.status()["door"] == "closed"

    def test_pipeline_operator_is_rejected(self):
        ok, message = _run(f'"{sys.executable}" -c "print(1)" | more', 10)
        assert not ok
        assert "Liste" in message

    def test_split_on_windows_keeps_backslashes_and_unquotes(self, monkeypatch):
        from backend.app.services import hardware_extension as he

        monkeypatch.setattr(he.os, "name", "nt")
        assert he._split_command('"C:\\Programme\\Mein Tool\\tool.exe" door_open --wait') == [
            "C:\\Programme\\Mein Tool\\tool.exe",
            "door_open",
            "--wait",
        ]

    def test_split_on_windows_unchanged_for_plain_paths(self, monkeypatch):
        from backend.app.services import hardware_extension as he

        monkeypatch.setattr(he.os, "name", "nt")
        assert he._split_command("C:\\tool.exe --open") == ["C:\\tool.exe", "--open"]

    def test_posix_split_unchanged(self, monkeypatch):
        from backend.app.services import hardware_extension as he

        monkeypatch.setattr(he.os, "name", "posix")
        assert he._split_command("tool --flag 'text mit Leerzeichen'") == ["tool", "--flag", "text mit Leerzeichen"]


class TestPerPrinterHardware:
    @staticmethod
    def _isolate(tmp_path, monkeypatch):
        from backend.app.services import hardware_extension as he

        monkeypatch.setattr(he, "CONFIG_PATH", tmp_path / "hardware.json")
        monkeypatch.setattr(he, "MAGAZINE_PATH", tmp_path / "magazine.json")
        monkeypatch.setattr(he, "_per_printer", {})
        return he

    def test_each_printer_has_its_own_magazine(self, tmp_path, monkeypatch):
        he = self._isolate(tmp_path, monkeypatch)
        first, second = he.get_hardware(1), he.get_hardware(2)
        assert first is not second and first is he.get_hardware(1)
        assert first.change_plate("A")[0]
        assert first.status()["supply_ready"] == 2
        assert second.status()["supply_ready"] == 3

    def test_emergency_stop_only_locks_that_printer(self, tmp_path, monkeypatch):
        he = self._isolate(tmp_path, monkeypatch)
        he.get_hardware(1).emergency_stop()
        assert he.get_hardware(1).status()["estop"] is True
        assert he.get_hardware(2).status()["estop"] is False
        assert he.get_hardware(2).open_door()[0]

    def test_first_printer_adopts_the_legacy_magazine_and_config(self, tmp_path, monkeypatch):
        he = self._isolate(tmp_path, monkeypatch)
        legacy = HardwareExtension(tmp_path / "hardware.json", tmp_path / "magazine.json")
        legacy.change_plate("alt")
        legacy.update_config({"timeout_seconds": 33})
        assert (tmp_path / "magazine.json").exists()
        first = he.get_hardware(7)
        assert first.status()["supply_ready"] == 2  # bisheriger Stand übernommen
        assert first.config()["timeout_seconds"] == 33.0  # Vorlage kopiert
        assert not (tmp_path / "magazine.json").exists()
        assert he.get_hardware(8).status()["supply_ready"] == 3  # weitere Drucker beginnen neu

    def test_per_printer_state_survives_a_restart(self, tmp_path, monkeypatch):
        he = self._isolate(tmp_path, monkeypatch)
        he.get_hardware(3).change_plate("x")
        monkeypatch.setattr(he, "_per_printer", {})
        assert he.get_hardware(3).status()["supply_ready"] == 2

    def test_without_printer_id_the_shared_instance_is_used(self, tmp_path, monkeypatch):
        he = self._isolate(tmp_path, monkeypatch)
        monkeypatch.setattr(he, "_hardware", None)
        assert he.get_hardware() is he.get_hardware()
