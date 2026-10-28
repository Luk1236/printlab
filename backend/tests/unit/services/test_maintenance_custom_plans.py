"""Tests für benutzerdefinierte Wartungsprogramme (maintenance_plans.json)."""

import pytest

from backend.app.services import maintenance_programs as mp


def _write(path, plans):
    import json

    path.write_text(json.dumps({"plans": plans}), encoding="utf-8")


class TestValidation:
    def test_valid_plan_passes(self, tmp_path):
        ok, msg, plan = mp._validate_custom_plan(
            {
                "key": "nozzle_clean",
                "label": "Düsen-Reinigungsfahrt",
                "steps": [
                    {"kind": "home"},
                    {"kind": "xy", "axis": "X", "target": 120},
                    {"kind": "pause", "seconds": 30},
                    {"kind": "z", "direction": "up", "steps": 5},
                ],
            }
        )
        assert ok, msg
        assert plan["key"] == "nozzle_clean"

    def test_builtin_key_is_rejected(self, tmp_path):
        ok, msg, _ = mp._validate_custom_plan({"key": "oil", "label": "x", "steps": [{"kind": "home"}]})
        assert not ok

    def test_out_of_bounds_target_is_rejected(self, tmp_path):
        ok, msg, _ = mp._validate_custom_plan(
            {
                "key": "far",
                "label": "x",
                "steps": [{"kind": "xy", "axis": "X", "target": 999}],
            }
        )
        assert not ok
        assert "innerhalb" in msg

    def test_bad_pause_and_direction(self, tmp_path):
        ok, msg, _ = mp._validate_custom_plan(
            {
                "key": "p1",
                "label": "x",
                "steps": [{"kind": "pause", "seconds": 900}],
            }
        )
        assert not ok
        ok, msg, _ = mp._validate_custom_plan(
            {
                "key": "p1",
                "label": "x",
                "steps": [{"kind": "z", "direction": "sideways", "steps": 2}],
            }
        )
        assert not ok

    def test_unknown_kind_is_rejected(self, tmp_path):
        ok, msg, _ = mp._validate_custom_plan({"key": "x", "label": "x", "steps": [{"kind": "extrude"}]})
        assert not ok

    def test_save_rejects_duplicate_keys_and_invalid(self, tmp_path):
        data = {
            "plans": [
                {"key": "a", "label": "A", "steps": [{"kind": "home"}]},
                {"key": "a", "label": "A2", "steps": [{"kind": "home"}]},
            ]
        }
        ok, msg = mp.save_custom_plans(data, tmp_path / "plans.json")
        assert not ok

    def test_save_persists_and_specs_include_custom(self, tmp_path):
        data = {
            "plans": [
                {
                    "key": "nozzle_clean",
                    "label": "Düse",
                    "default_runs": 2,
                    "steps": [{"kind": "xy", "axis": "Y", "target": 60}],
                },
            ]
        }
        path = tmp_path / "plans.json"
        ok, msg = mp.save_custom_plans(data, path)
        assert ok, msg
        specs = mp.custom_specs(path)
        assert "nozzle_clean" in specs
        assert specs["nozzle_clean"].default_runs == 2
        assert "oil" in specs  # built-ins bleiben available


class TestPlanBuilding:
    def test_custom_key_build_plan(self, tmp_path, monkeypatch):
        path = tmp_path / "plans.json"
        monkeypatch.setattr(mp, "CUSTOM_PATH", path)
        _write(
            path,
            [
                {
                    "key": "short_sweep",
                    "label": "Kurz",
                    "steps": [
                        {"kind": "home"},
                        {"kind": "xy", "axis": "X", "target": 200.0},
                        {"kind": "pause", "seconds": 5},
                    ],
                }
            ],
        )
        plan = mp.plan_steps_for("short_sweep", path)
        assert plan == [("home", None), ("xy", ("X", 200.0)), ("pause", 5.0)]

        built = mp.build_plan("short_sweep")
        assert built == plan
        # built-ins unverändert
        assert "oil" in mp.PROGRAMS and mp.plan_steps_for("oil", path) == []

    def test_z_direction_expansion(self, tmp_path):
        path = tmp_path / "plans.json"
        _write(path, [{"key": "updown", "label": "UD", "steps": [{"kind": "z", "direction": "down", "steps": 3}]}])
        assert mp.plan_steps_for("updown", path) == [("z", "-"), ("z", "-"), ("z", "-")]


class TestServiceIntegration:
    def test_start_executes_custom_plan_without_print(self, tmp_path, monkeypatch):
        """Ein eigenes Programm läuft wie ein eingebauter Plan ab (Simulation)."""
        path = tmp_path / "plans.json"
        _write(path, [{"key": "mini", "label": "Mini", "steps": [{"kind": "home"}]}])
        monkeypatch.setattr(mp, "CUSTOM_PATH", path)

        plan = mp.build_plan("mini")
        assert plan == [("home", None)]
        assert plan in ([("home", None)],)
        # estimate und Runner-Status funktionieren mit eigenem Namen
        assert mp.estimate_seconds(plan) >= 1
        specs = mp.custom_specs(path)
        assert specs["mini"].label == "Mini"
