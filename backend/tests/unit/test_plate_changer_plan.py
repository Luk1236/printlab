"""Bauteil- und Bewegungsplan des Plattenwechslers: Rechnung, Pinbelegung, Abgleich mit Maßen und Phasen."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from backend.app.services import plate_changer as pc, plate_changer_plan as plan
from backend.app.services.gpio_hardware import DEFAULT_GPIO_CONFIG


def test_axis_travel_comes_from_the_dimensions():
    assert plan.X_AXIS.travel_mm == pc.MAG_X
    assert plan.Y_AXIS.travel_mm == pytest.approx(405.5)
    assert plan.Z_AXIS.travel_mm == max(pc.SLOT_Z) - pc.WASH_Z


def test_travel_fits_the_rails_with_reserve():
    """Schiene minus Wagen muss den Weg samt Anschlägen tragen (gleiche Rechnung wie die Konstruktionsprüfung)."""
    for axis, (kind, length) in ((plan.X_AXIS, pc.RAIL_X), (plan.Y_AXIS, pc.RAIL_Y_ARM), (plan.Z_AXIS, pc.RAIL_Z)):
        assert length - pc.CARRIAGE_LEN[kind] - axis.travel_mm >= pc.MIN_MARGIN, axis.id


def test_every_axis_has_torque_reserve():
    for row in plan.axis_checks():
        assert row["ok"], row
        assert row["torque_ratio"] >= plan.REQUIRED_TORQUE_MARGIN


def test_z_spindle_holds_its_load_without_power():
    """Ohne Strom darf der Querträger nicht herunterfallen: Tr8x2 hemmt selbst, die erste Auslegung (Tr8x8) tat es nicht."""
    assert plan.Z_AXIS.self_locking()
    old = plan.Axis("z", "alt", "spindle", 246, plan.LEGACY_Z_LEAD_MM, 15, 60, 3.5, 2, 0.15, 7.0, 0.15, 0.25)
    assert not old.self_locking()


def test_z_self_locking_depends_on_the_lubrication():
    """Tr8x2 hemmt trocken (0,15), geschmiert (0,08) nicht mehr: Selbsthemmung allein reicht nicht als Sicherung."""
    assert plan.Z_AXIS.self_locking(0.15)
    assert not plan.Z_AXIS.self_locking(0.08)
    assert plan.Z_AXIS.backdrive_torque_nm(0.15) == 0.0
    assert plan.Z_AXIS.backdrive_torque_nm(plan.Z_FRICTION_RANGE[0]) > 0.0


def test_z_drag_brake_holds_the_beam_at_any_lubrication():
    """Not-Halt schaltet die Treiber stromlos; die Reibbremse hält den Querträger mit doppelter Reserve."""
    worst = plan.Z_AXIS.backdrive_torque_nm(plan.Z_FRICTION_RANGE[0])
    assert plan.Z_AXIS.drag_nm >= plan.REQUIRED_TORQUE_MARGIN * worst
    assert plan.Z_AXIS.holds_without_power()
    without_brake = plan.Axis("z", "ohne Bremse", "spindle", 246, 2.0, 15, 60, 3.5, 2, 0.15, 7.0, 0.15, 0.25)
    assert not without_brake.holds_without_power()
    # Der Motor überwindet die Bremse mit Reserve (steckt in required_torque_nm).
    assert plan.Z_AXIS.torque_ratio >= plan.REQUIRED_TORQUE_MARGIN


def test_step_rates_stay_within_the_driver():
    for ax in plan.AXES:
        assert ax.step_rate_hz < 50_000, ax.id  # TMC2209 mit Step/Dir weit darunter


def test_move_time_profiles():
    assert plan.move_time(0, 100, 100) == 0
    assert plan.move_time(1000, 100, 100) == pytest.approx(11.0)  # Trapez: 10 s Fahrt + 1 s Rampen
    assert plan.move_time(1, 100, 100) == pytest.approx(0.2)  # Dreieck


def test_cycle_follows_the_phase_list():
    report = plan.cycle_report()
    assert [p["id"] for p in report["phases"]] == [p.id for p in pc.PHASES]
    assert report["total_s"] == pytest.approx(sum(p["seconds"] for p in report["phases"]), abs=0.6)
    shortest, longest = plan.cycle_range()
    assert 20 < shortest <= longest < 120


def test_power_budget_keeps_headroom():
    for row in plan.power_budget()[:3]:
        assert row["ok"], row
    # auch "alles gleichzeitig" bleibt unter dem Netzteil
    assert plan.power_budget()[3]["amps"] < plan.PSU_AMPS


def test_no_pin_is_used_twice():
    assert plan.pin_conflicts() == []


def test_pi_pins_agree_with_gpio_hardware():
    pins = {name: spec[0] for name, spec in plan.PI_PINS.items()}
    assert pins["estop"] == DEFAULT_GPIO_CONFIG["estop_pin"]
    assert pins["button_ack"] == DEFAULT_GPIO_CONFIG["button_ack_pin"]
    assert pins["button_pause"] == DEFAULT_GPIO_CONFIG["button_pause_pin"]
    assert pins["status_led"] == DEFAULT_GPIO_CONFIG["status_led_pin"]


def _load_mechanik():
    path = Path(__file__).resolve().parents[3] / "werkzeuge" / "gpio_mechanik.py"
    if not path.exists():
        pytest.skip("werkzeuge/ fehlt in dieser Umgebung")
    spec = importlib.util.spec_from_file_location("gpio_mechanik_for_plan", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pi_pins_agree_with_gpio_mechanik():
    mech = _load_mechanik().DEFAULT_PINS
    for name in ("door_servo", "washer_roller", "washer_pump", "washer_fan"):
        assert mech[name] == plan.PI_PINS[name][0], name
    assert mech["endstop_open"] == plan.PI_PINS["door_endstop_open"][0]
    assert mech["endstop_closed"] == plan.PI_PINS["door_endstop_closed"][0]
    assert mech["plate_sensor"] == plan.PI_PINS["plate_sensor"][0]


def test_mechanik_does_not_use_the_estop_pin():
    mech = _load_mechanik().DEFAULT_PINS
    assert DEFAULT_GPIO_CONFIG["estop_pin"] not in mech.values()
    assert DEFAULT_GPIO_CONFIG["status_led_pin"] not in mech.values()


def test_homing_ends_on_the_documented_positions():
    by_axis = {axis: pos for _, axis, _, _, pos in plan.HOMING}
    assert by_axis == {"Z": plan.Z_TOP_ENDSTOP, "Y": pc.PARK_Y, "X": pc.MAG_X}
    assert [axis for _, axis, *_ in plan.HOMING] == ["Z", "Y", "X"]  # erst hoch, dann Arm zurück, dann zum Turm
    assert plan.Z_SOFT_MIN < pc.WASH_Z and max(pc.SLOT_Z) <= plan.Z_SOFT_MAX


def test_design_document_carries_the_computed_tables():
    """Die Tabellen im Konstruktionsplan stammen aus ``sync_viewer.py --plan``; wer Werte ändert, erzeugt sie neu."""
    doc = Path(__file__).resolve().parents[3] / "werkzeuge" / "automation_hardware" / "TUER_MAGAZIN_WASCHSTATION.md"
    if not doc.exists():
        pytest.skip("werkzeuge/ fehlt in dieser Umgebung")
    text = doc.read_text(encoding="utf-8")
    for name, (bcm, pin, direction, note) in plan.PI_PINS.items():
        assert f"| `{name}` | {bcm} | {pin} | {direction} | {note} |" in text, name
    for row in plan.power_budget():
        assert f"| {row['case']} | {row['amps']} A |" in text, row
    report = plan.cycle_report()
    assert f"**{report['total_s']} s**" in text
    assert "Tr8×2" in text
