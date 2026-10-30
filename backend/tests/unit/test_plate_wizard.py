"""Tests für den Einmess-Assistenten des Plattenwechsels."""

import pytest

from backend.app.services import plate_wizard


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(plate_wizard, "STORE_DIR", tmp_path / "plate_wizard")
    return tmp_path


def _coords(x=10.0, y=20.0, z=5.0, **extra):
    return {"x": x, "y": y, "z": z, **extra}


def _fill_all(printer_id=1, **overrides):
    plate_wizard.save_step(printer_id, "reference", overrides.get("reference", _coords(0, 0, 0)))
    plate_wizard.save_step(printer_id, "pickup", overrides.get("pickup", _coords(120, 130, 10)))
    plate_wizard.save_step(printer_id, "drop", overrides.get("drop", _coords(220, 40, 18)))
    plate_wizard.save_step(printer_id, "door", {"confirmed": True, "sensor": True})
    plate_wizard.save_step(printer_id, "dry_run", {"confirmed": True, "note": "ohne Platte"})


class TestSteps:
    def test_fresh_state(self):
        state = plate_wizard.status(1)
        assert state["complete"] is False
        assert state["started"] is False
        assert state["missing"] == list(plate_wizard.REQUIRED_STEPS)
        assert plate_wizard.blocks_plate_change(1) is None

    def test_coordinates_are_required_and_validated(self):
        with pytest.raises(plate_wizard.WizardError, match="fehlen die Koordinaten"):
            plate_wizard.save_step(1, "pickup", {})
        with pytest.raises(plate_wizard.WizardError, match="Achse „y“ fehlt"):
            plate_wizard.save_step(1, "pickup", {"x": 1, "z": 1})
        with pytest.raises(plate_wizard.WizardError, match="außerhalb"):
            plate_wizard.save_step(1, "pickup", _coords(999, 0, 0))
        with pytest.raises(plate_wizard.WizardError, match="keine Zahl"):
            plate_wizard.save_step(1, "pickup", {"x": "vorne", "y": 0, "z": 0})

    def test_door_and_dry_run_need_confirmation(self):
        with pytest.raises(plate_wizard.WizardError, match="Tür"):
            plate_wizard.save_step(1, "door", {"confirmed": False})
        with pytest.raises(plate_wizard.WizardError, match="Probelauf"):
            plate_wizard.save_step(1, "dry_run", {})
        state = plate_wizard.save_step(1, "door", {"confirmed": True, "sensor": False})
        assert state["steps"]["door"]["sensor"] is False

    def test_unknown_step_is_rejected(self):
        with pytest.raises(plate_wizard.WizardError, match="Unbekannter Schritt"):
            plate_wizard.save_step(1, "fliegen", _coords())

    def test_started_wizard_blocks_plate_change(self):
        plate_wizard.save_step(1, "reference", _coords(0, 0, 0))
        block = plate_wizard.blocks_plate_change(1)
        assert block is not None
        assert "nicht abgeschlossen" in block


class TestCompletion:
    def test_complete_requires_all_steps(self):
        plate_wizard.save_step(1, "reference", _coords(0, 0, 0))
        with pytest.raises(plate_wizard.WizardError, match="fehlen noch Schritte"):
            plate_wizard.complete(1, "Lukas")

    def test_requires_operator_name(self):
        _fill_all()
        with pytest.raises(plate_wizard.WizardError, match="Namen"):
            plate_wizard.complete(1, "")

    def test_completes_and_releases_the_gate(self):
        _fill_all()
        state = plate_wizard.complete(1, "Lukas")
        assert state["complete"] is True
        assert state["operator"] == "Lukas"
        assert plate_wizard.blocks_plate_change(1) is None

    def test_duplicate_positions_are_refused(self):
        _fill_all(pickup=_coords(120, 130, 10), drop=_coords(120, 130, 10))
        with pytest.raises(plate_wizard.WizardError, match="derselben Position"):
            plate_wizard.complete(1, "Lukas")

    def test_optional_magazine_step_is_not_required(self):
        _fill_all()
        assert "magazine" not in plate_wizard.status(1)["missing"]
        assert plate_wizard.complete(1, "Lukas")["complete"] is True

    def test_completed_wizard_is_frozen_until_reset(self):
        _fill_all()
        plate_wizard.complete(1, "Lukas")
        with pytest.raises(plate_wizard.WizardError, match="bereits abgeschlossen"):
            plate_wizard.save_step(1, "magazine", _coords(1, 2, 3))
        with pytest.raises(plate_wizard.WizardError, match="bereits abgeschlossen"):
            plate_wizard.complete(1, "Lukas")
        state = plate_wizard.reset(1)
        assert state["complete"] is False
        assert state["steps"] == {}

    def test_stored_values_survive_reload(self):
        _fill_all()
        plate_wizard.complete(1, "Lukas")
        state = plate_wizard.status(1)
        assert state["steps"]["pickup"]["position"] == {"x": 120.0, "y": 130.0, "z": 10.0}
        assert state["revision"] >= len(plate_wizard.STEPS)
