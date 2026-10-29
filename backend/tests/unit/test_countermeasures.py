"""Gegenmaßnahmen der Fehlerhilfe: Regelentscheidung, Grenzen und Befehlsbau."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.app.services import countermeasures

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def state(
    material: str = "PLA",
    chamber: float | None = 40.0,
    *,
    status: str = "RUNNING",
    layer: int = 20,
    door_open: bool = False,
    chamber_fan: int | None = 0,
    aux_fan: int | None = 0,
    bed_target: float | None = 60.0,
    nozzle_target: float | None = 210.0,
    gcode: str = "job.3mf",
):
    trays = [] if material is None else [{"tray_type": material}]
    return SimpleNamespace(
        state=status,
        layer_num=layer,
        door_open=door_open,
        big_fan2_speed=chamber_fan,
        big_fan1_speed=aux_fan,
        gcode_file=gcode,
        subtask_name=None,
        temperatures={"chamber": chamber, "bed_target": bed_target, "nozzle_target": nozzle_target},
        raw_data={"ams": [{"tray": trays}]} if trays else {},
    )


def config(rule: str = "chamber_hot", *, dry_run: bool = False, **over):
    base = {
        "enabled": True,
        "dry_run": dry_run,
        "printers": {"7": {"enabled": True, "rules": {rule: True}}},
        "thresholds": {"hot_c": 38.0, "cold_c": 45.0},
        "cooldown_seconds": 600,
        "max_per_print": 3,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _clear_memory():
    countermeasures.reset_memory()
    yield
    countermeasures.reset_memory()


class TestEvaluate:
    def test_warm_chamber_on_pla_turns_the_fans_up_and_lowers_the_bed(self):
        actions = countermeasures.evaluate(7, state(chamber=41), "X1C", config())
        assert len(actions) == 1
        assert actions[0]["rule"] == "chamber_hot"
        assert actions[0]["commands"] == ["M106 P3 S255", "M106 P2 S178", "M140 S55"]

    def test_a_cool_chamber_stays_quiet(self):
        assert countermeasures.evaluate(7, state(chamber=32), "X1C", config()) == []

    def test_fans_already_running_leave_only_the_bed_step(self):
        actions = countermeasures.evaluate(7, state(chamber=41, chamber_fan=100, aux_fan=70), "X1C", config())
        assert [a["commands"] for a in actions] == [["M140 S55"]]

    def test_open_door_is_treated_as_ventilation(self):
        assert countermeasures.evaluate(7, state(chamber=45, door_open=True), "X1C", config()) == []

    def test_early_layers_are_left_alone(self):
        assert countermeasures.evaluate(7, state(chamber=45, layer=2), "X1C", config()) == []

    def test_a_printer_without_chamber_sensor_is_skipped(self):
        assert countermeasures.evaluate(7, state(chamber=45), "P1S", config()) == []

    def test_mixed_material_is_not_guessed(self):
        mixed = state(chamber=45)
        mixed.raw_data = {"ams": [{"tray": [{"tray_type": "PLA"}, {"tray_type": "ABS"}]}]}
        assert countermeasures.evaluate(7, mixed, "X1C", config()) == []

    def test_the_rule_must_be_enabled_for_that_printer(self):
        disabled = config()
        disabled["printers"]["7"]["rules"]["chamber_hot"] = False
        assert countermeasures.evaluate(7, state(chamber=45), "X1C", disabled) == []
        assert countermeasures.evaluate(7, state(chamber=45), "X1C", config(enabled=False)) == []

    def test_cold_chamber_on_abs_switches_ventilation_off(self):
        actions = countermeasures.evaluate(
            7, state(material="ABS", chamber=39, chamber_fan=60, aux_fan=50), "X1C", config("chamber_cold")
        )
        assert len(actions) == 1
        assert actions[0]["commands"] == ["M106 P3 S0", "M106 P2 S0"]

    def test_cooldown_blocks_a_second_action(self):
        assert len(countermeasures.evaluate(7, state(chamber=41), "X1C", config(), NOW)) == 1
        assert countermeasures.evaluate(7, state(chamber=41), "X1C", config(), NOW + timedelta(minutes=5)) == []
        assert len(countermeasures.evaluate(7, state(chamber=41), "X1C", config(), NOW + timedelta(minutes=11))) == 1

    def test_the_action_budget_per_print_is_limited(self):
        cfg = config(max_per_print=2, cooldown_seconds=60)
        times = [NOW + timedelta(minutes=offset) for offset in (0, 2, 4)]
        assert [len(countermeasures.evaluate(7, state(chamber=41), "X1C", cfg, t)) for t in times] == [1, 1, 0]

    def test_a_new_print_resets_the_budget(self):
        cfg = config(max_per_print=1, cooldown_seconds=60)
        assert len(countermeasures.evaluate(7, state(chamber=41), "X1C", cfg, NOW)) == 1
        assert (
            countermeasures.evaluate(7, state(chamber=41, gcode="next.3mf"), "X1C", cfg, NOW + timedelta(hours=1)) != []
        )

    def test_leaving_running_resets_the_memory(self):
        assert len(countermeasures.evaluate(7, state(chamber=41), "X1C", config(), NOW)) == 1
        assert countermeasures.evaluate(7, state(chamber=41, status="IDLE"), "X1C", config(), NOW) == []
        assert len(countermeasures.evaluate(7, state(chamber=41), "X1C", config(), NOW)) == 1


class TestManualCommand:
    def test_bed_delta_uses_the_current_target(self):
        command, error = countermeasures.build_manual_command({"bed_delta": -5}, state(bed_target=42), "X1C")
        assert error is None and command == "M140 S37"

    def test_nozzle_delta_is_capped(self):
        command, _ = countermeasures.build_manual_command({"nozzle_delta": 10}, state(nozzle_target=300), "X1C")
        assert command == "M104 S310"

    def test_idle_printer_is_refused(self):
        _, error = countermeasures.build_manual_command(
            {"fan": {"index": 1, "speed": 100}}, state(status="IDLE"), "X1C"
        )
        assert error

    def test_aux_fan_requires_a_reported_fan(self):
        _, error = countermeasures.build_manual_command({"fan": {"index": 2, "speed": 70}}, state(aux_fan=None), "X1C")
        assert error
