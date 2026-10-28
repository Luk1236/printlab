"""GPIO-Treiber (werkzeuge/gpio_mechanik.py) mit einem Ersatz für RPi.GPIO."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "werkzeuge" / "gpio_mechanik.py"
spec = importlib.util.spec_from_file_location("gpio_mechanik", SCRIPT)
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)


class FakePwm:
    def __init__(self, pin, hz):
        self.duties = []
        self.stopped = False

    def start(self, duty):
        self.duties.append(duty)

    def ChangeDutyCycle(self, duty):  # noqa: N802 - Name wie in RPi.GPIO
        self.duties.append(duty)

    def stop(self):
        self.stopped = True


class FakeGpio:
    BCM, IN, OUT, PUD_UP, HIGH, LOW = "BCM", "IN", "OUT", "PUD_UP", 1, 0

    def __init__(self, switches=None):
        self.levels = {}  # Pin -> Pegel eines Eingangs; LOW = Schalter aktiv
        for pin, active in (switches or {}).items():
            self.levels[pin] = self.LOW if active else self.HIGH
        self.outputs = {}
        self.cleaned = False
        self.pwm = None

    def setmode(self, mode):
        pass

    def setwarnings(self, flag):
        pass

    def setup(self, pin, direction, pull_up_down=None):
        self.levels.setdefault(pin, self.HIGH)

    def output(self, pin, level):
        self.outputs[pin] = level

    def input(self, pin):
        return self.levels[pin]

    def PWM(self, pin, hz):  # noqa: N802
        self.pwm = FakePwm(pin, hz)
        return self.pwm

    def cleanup(self):
        self.cleaned = True


PINS = gm.DEFAULT_PINS


def make(tmp_path, switches=None, **cfg):
    config = gm.load_config(tmp_path / "keine-datei.json")
    config.update(cfg)
    gpio = FakeGpio(switches)
    return gm.Mechanik(gpio=gpio, config=config, state_path=tmp_path / "stand.json", sleep=lambda s: None), gpio


def test_motors_start_de_energised(tmp_path):
    _, gpio = make(tmp_path)
    assert gpio.outputs[PINS["motors_enable"]] == gpio.HIGH


def test_door_open_waits_for_the_endstop_and_reports_open(tmp_path, capsys):
    mech, _ = make(tmp_path, {PINS["endstop_open"]: True})
    assert mech.door_open() is True
    assert "DOOR:OPEN" in capsys.readouterr().out
    assert mech.moves[-1] == 154.0


def test_door_close_reports_closed(tmp_path, capsys):
    mech, _ = make(tmp_path, {PINS["endstop_closed"]: True})
    assert mech.door_close() is True
    assert "DOOR:CLOSED" in capsys.readouterr().out
    assert mech.moves[-1] == 10.0


def test_missing_endstop_is_a_failure_not_a_guess(tmp_path, capsys):
    mech, _ = make(tmp_path, {}, timeout_s=0.0)
    assert mech.door_open() is False
    captured = capsys.readouterr()
    assert "DOOR:UNKNOWN" in captured.out and "FEHLER" in captured.err


def test_without_endstops_the_door_state_stays_unknown(tmp_path, capsys):
    mech, _ = make(tmp_path, endschalter=False)
    assert mech.door_open() is True
    assert mech.door_check() == "UNKNOWN"
    assert "DOOR:OPEN" not in capsys.readouterr().out  # nie einen Zustand behaupten, den niemand gemessen hat


@pytest.mark.parametrize(
    ("opened", "closed", "expected"),
    [(True, False, "OPEN"), (False, True, "CLOSED"), (False, False, "UNKNOWN"), (True, True, "UNKNOWN")],
)
def test_door_check_needs_exactly_one_switch(tmp_path, opened, closed, expected):
    mech, _ = make(tmp_path, {PINS["endstop_open"]: opened, PINS["endstop_closed"]: closed})
    assert mech.door_check() == expected


def test_servo_moves_in_small_steps_from_the_last_position(tmp_path):
    mech, _ = make(tmp_path)
    (tmp_path / "stand.json").write_text(json.dumps({"winkel": 10}))
    mech.move_servo(30)
    assert mech.moves[0] == 12.0 and mech.moves[-1] == 30 and len(mech.moves) > 5
    assert all(b - a <= 2.0 + 1e-9 for a, b in zip(mech.moves, mech.moves[1:], strict=False))
    assert json.loads((tmp_path / "stand.json").read_text())["winkel"] == 30


def test_servo_signal_is_switched_off_after_the_move(tmp_path):
    mech, gpio = make(tmp_path)
    mech.move_servo(90)
    assert gpio.pwm.duties[-1] == 0


def test_first_move_without_a_known_position_goes_straight_to_the_target(tmp_path):
    mech, _ = make(tmp_path)
    mech.move_servo(45)
    assert mech.moves == [45]


def test_servo_angle_out_of_range_is_refused(tmp_path):
    mech, _ = make(tmp_path)
    with pytest.raises(gm.GpioError):
        mech.move_servo(181)


def test_stop_cuts_the_motors_and_the_servo(tmp_path, capsys):
    mech, gpio = make(tmp_path)
    gpio.outputs[PINS["motors_enable"]] = gpio.LOW
    mech.stop()
    assert gpio.outputs[PINS["motors_enable"]] == gpio.HIGH and gpio.pwm.duties[-1] == 0
    assert "STOP:OK" in capsys.readouterr().out


def test_swap_is_refused(tmp_path, capsys):
    mech, gpio = make(tmp_path)
    before = dict(gpio.outputs)
    assert mech.swap() is False
    assert gpio.outputs == before  # kein Motor wurde angefasst
    assert "nicht umgesetzt" in capsys.readouterr().err


def test_selftest_reads_the_inputs(tmp_path):
    mech, _ = make(tmp_path, {PINS["plate_sensor"]: True})
    assert mech.selftest() == {"endstop_open": False, "endstop_closed": False, "plate_sensor": True}


class TestConfig:
    def test_defaults_without_a_file(self, tmp_path):
        cfg = gm.load_config(tmp_path / "fehlt.json")
        assert cfg["pins"] == gm.DEFAULT_PINS and cfg["endschalter"] is True

    def test_file_overrides_values_and_pins(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(
            json.dumps({"offen_grad": 120, "endschalter": False, "pins": {"endstop_open": 5}, "unbekannt": 1})
        )
        cfg = gm.load_config(path)
        assert cfg["offen_grad"] == 120 and cfg["endschalter"] is False and cfg["pins"]["endstop_open"] == 5
        assert "unbekannt" not in cfg

    def test_angle_beyond_the_servo_range_is_refused(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"offen_grad": 400}))
        with pytest.raises(gm.GpioError):
            gm.load_config(path)

    def test_two_functions_on_one_pin_are_refused(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"pins": {"endstop_open": 24}}))
        with pytest.raises(gm.GpioError):
            gm.load_config(path)

    def test_broken_file_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text("{kaputt")
        assert gm.load_config(path)["zu_grad"] == 10.0

    def test_example_file_is_valid(self):
        gm.load_config(SCRIPT.with_name("gpio_mechanik.beispiel.json"))


def test_missing_gpio_library_aborts_instead_of_simulating(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(gm, "CONFIG_PATH", tmp_path / "x.json")
    monkeypatch.setitem(sys.modules, "RPi", None)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", None)
    assert gm.main(["door_open"]) == 2
    assert "GPIO nicht verfügbar" in capsys.readouterr().err


def test_pins_command_needs_no_gpio(capsys):
    assert gm.main(["pins"]) == 0
    assert "door_servo: GPIO 18" in capsys.readouterr().out
