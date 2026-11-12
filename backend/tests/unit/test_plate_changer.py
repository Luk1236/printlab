"""Plattenwechsler: Maße, Zyklus, Konstruktionsprüfung, Sperren und die Kopie in der 3D-Ansicht."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from backend.app.services import plate_changer as pc

VIEWER = (
    Path(__file__).resolve().parents[3]
    / "werkzeuge"
    / "automation_hardware"
    / "printlab_3d_assembly_explosion_viewer.html"
)


class TestCycle:
    def test_phases_cover_the_whole_cycle_without_gaps(self):
        assert pc.PHASES[0].t0 == 0.0 and pc.PHASES[-1].t1 == 1.0
        for earlier, later in zip(pc.PHASES, pc.PHASES[1:], strict=False):
            assert earlier.t1 == later.t0

    def test_ids_are_unique_and_the_door_opens_before_anything_moves(self):
        ids = [p.id for p in pc.PHASES]
        assert len(ids) == len(set(ids))
        assert ids[0] == "door_open" and ids[-1] == "park_close"
        assert ids.index("door_open") < ids.index("pull_old")

    def test_parts_stay_on_the_plate_nothing_is_swept_off(self):
        """Die Teile wandern mit der Platte ins Regal: es gibt keinen Abschub in eine Schale."""
        ids = [p.id for p in pc.PHASES]
        assert "sweep_part" not in ids
        assert ids.index("bed_down") < ids.index("pull_old")
        assert "Teile" in next(p for p in pc.PHASES if p.id == "pull_old").detail

    def test_magnet_is_on_while_a_plate_is_pulled_and_off_after_placing_it(self):
        magnet = {p.id: p.magnet for p in pc.PHASES}
        assert magnet["pull_old"] is True and magnet["pull_fresh"] is True
        assert magnet["store_old"] is False and magnet["place_fresh"] is False

    def test_phase_at_picks_the_phase_of_a_time_fraction(self):
        assert pc.phase_at(0.0).id == "door_open"
        assert pc.phase_at(0.5).id == "store_old"
        assert pc.phase_at(1.0).id == "park_close"
        assert pc.phase_at(7.0).id == "park_close"


class TestGeometry:
    def test_fach_2_is_on_the_bed_transfer_height(self):
        assert pc.SLOT_Z[1] == pc.Z_SWAP

    def test_the_door_reaches_558_at_90_degrees(self):
        assert pc.door_tip_y_max() == 558.0
        x, y = pc.door_tip(90.0)
        assert math.isclose(x, pc.DOOR_HINGE[0], abs_tol=1e-6) and math.isclose(y, 558.0, abs_tol=1e-6)

    def test_a_half_open_door_cuts_through_the_transfer_corridor(self):
        """Darum muss die Tür ganz offen sein, bevor die Platte den Drucker verlässt."""
        corridor = pc.plate_box(0.0, pc.TRANSFER_Y)
        assert pc.door_gap(60.0, corridor) == 0.0
        assert pc.door_gap(pc.DOOR_OPEN_DEG, corridor) > pc.MIN_CLEARANCE

    def test_segment_box_distance(self):
        box = (0.0, 0.0, 10.0, 10.0)
        assert pc._segment_box_distance((20.0, 5.0), (30.0, 5.0), box) == 10.0
        assert pc._segment_box_distance((-5.0, 5.0), (15.0, 5.0), box) == 0.0


class TestPartsOnThePlate:
    def test_the_plate_above_limits_the_height_of_the_parts(self):
        pitch = pc.SLOT_Z[1] - pc.SLOT_Z[0]
        assert pc.SLOT_CAPACITY[0] == pitch - pc.PLATE_THICKNESS - pc.PART_GAP == 29.5
        assert pc.SLOT_CAPACITY[:3] == (29.5, 29.5, 29.5)

    def test_the_top_slot_is_limited_by_the_lid_of_the_tower(self):
        assert pc.SLOT_CAPACITY[-1] == pc.RACK_LID_Z - pc.SLOT_Z[-1] - pc.PART_GAP == 17.0

    def test_the_check_reports_the_lowest_slot_against_the_wanted_height(self):
        check = next(c for c in pc.design_checks() if c["id"] == "part_height")
        assert check["value"] == min(pc.SLOT_CAPACITY) and check["limit"] == pc.WANTED_PART_HEIGHT
        assert check["status"] == "warn"


class TestDesignChecks:
    def test_nothing_fails(self):
        assert pc.design_summary()["fail"] == []

    def test_known_findings_stay_visible(self):
        """Wer die Schiene verschiebt oder das Regal anpasst, muss diese Erwartung bewusst ändern."""
        summary = pc.design_summary()
        assert set(summary["warn"]) == {"door_portal", "jaw_ceiling", "part_height", "tower_gap"}
        gap = next(c for c in summary["checks"] if c["id"] == "door_portal")
        assert 5.0 < gap["value"] < 10.0  # 7 mm zur Profilvorderkante, nicht die 17 mm der Doku (Schienenmitte)

    def test_the_plate_fits_between_the_tower_posts(self):
        """Der erste Turm (X 220 bis 500) ließ zwischen den 2020-Stehern nur 240 mm: kein Platz für die 257-mm-Platte."""
        assert pc.TOWER_CLEAR_X - pc.PLATE_EDGE >= 2 * 3.0
        assert pc.PLATE_EDGE < pc.PLATE_GUIDE < pc.TOWER_CLEAR_X
        assert (pc.TOWER_X[0] + pc.TOWER_X[1]) / 2 == pc.MAG_X
        assert 500.0 - 220.0 - 2 * pc.PROFILE < pc.PLATE_EDGE  # so war es vorher
        passage = next(c for c in pc.design_checks() if c["id"] == "tower_passage")
        assert passage["status"] == "ok"

    def test_the_arm_rail_had_to_grow_from_440_mm(self):
        stroke = pc.PARK_Y - pc.Y_GRIP
        assert 440.0 - pc.CARRIAGE_LEN["MGN9H"] < stroke  # mit 440 mm fehlten 5,4 mm
        assert pc.RAIL_Y_ARM[1] - pc.CARRIAGE_LEN["MGN9H"] >= stroke

    def test_every_check_has_the_fields_the_viewer_reads(self):
        for check in pc.design_checks():
            assert {"id", "label", "value", "limit", "unit", "margin", "status", "note"} <= set(check)
            assert check["status"] in {"ok", "warn", "fail"}


class TestInterlocks:
    def test_free_when_idle_and_cool(self):
        assert pc.interlock_problems(printer_state="FINISH", bed_temp=30.0, estop_active=False) == []

    @pytest.mark.parametrize("state", ["RUNNING", "PAUSE", "PREPARE", "SLICING", "running"])
    def test_blocked_while_printing(self, state):
        problems = pc.interlock_problems(printer_state=state, bed_temp=None, estop_active=False)
        assert any("Drucks" in p for p in problems)

    def test_blocked_when_the_bed_is_hot(self):
        problems = pc.interlock_problems(printer_state="FINISH", bed_temp=60.0, estop_active=False)
        assert any("heiß" in p for p in problems)

    def test_an_unknown_bed_temperature_does_not_block_but_an_unknown_state_does(self):
        assert pc.interlock_problems(printer_state="IDLE", bed_temp=None, estop_active=False) == []
        assert pc.interlock_problems(printer_state=None, bed_temp=20.0, estop_active=False)
        assert pc.interlock_problems(printer_state="unknown", bed_temp=20.0, estop_active=False)

    def test_estop_always_blocks_even_without_the_printer_check(self):
        assert pc.interlock_problems(printer_state=None, bed_temp=None, estop_active=True, check_printer=False) == [
            "Not-Halt ist aktiv."
        ]
        assert (
            pc.interlock_problems(printer_state="RUNNING", bed_temp=None, estop_active=False, check_printer=False) == []
        )


class TestViewerCopy:
    @pytest.fixture(autouse=True)
    def _viewer_present(self):
        if not VIEWER.is_file():
            pytest.skip("3D-Ansicht liegt nicht im Test-Image")

    def test_the_viewer_carries_the_current_data(self):
        assert pc.sync_viewer_html(VIEWER, write=False), (
            "Die Daten in der 3D-Ansicht sind veraltet: "
            "python werkzeuge/automation_hardware/sync_viewer.py ausführen und die Datei mitcommitten."
        )

    def test_a_viewer_without_the_data_block_is_reported(self, tmp_path):
        page = tmp_path / "x.html"
        page.write_text("<html></html>", encoding="utf-8")
        with pytest.raises(ValueError):
            pc.sync_viewer_html(page, write=False)

    def test_writing_makes_a_stale_copy_current(self, tmp_path):
        page = tmp_path / "x.html"
        page.write_text(
            '<script id="plate-changer-data" type="application/json">{"phases": []}</script>', encoding="utf-8"
        )
        assert pc.sync_viewer_html(page, write=False) is False
        assert pc.sync_viewer_html(page, write=True) is False
        assert pc.sync_viewer_html(page, write=False) is True
