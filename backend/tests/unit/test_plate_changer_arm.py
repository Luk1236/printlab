"""Plattenwechsler mit SCARA-Arm auf Seitenschiene: Reichweite, Wege, Abstände, Momente (plate_changer_arm)."""

import math

import pytest

from backend.app.services import plate_changer as pc, plate_changer_arm as arm


def _fk(shoulder_deg: float, elbow_deg: float) -> tuple[float, float]:
    s = math.radians(shoulder_deg)
    e = math.radians(shoulder_deg + elbow_deg)
    return (
        arm.BASE[0] + arm.L1 * math.cos(s) + arm.L2 * math.cos(e),
        arm.BASE[1] + arm.L1 * math.sin(s) + arm.L2 * math.sin(e),
    )


class TestKinematics:
    @pytest.mark.parametrize("pose", arm.poses(), ids=lambda p: p.name)
    def test_every_task_is_reachable_and_ik_lands_on_the_wrist(self, pose):
        sol = arm.ik(pose.wrist)
        assert sol is not None, pose.label
        assert _fk(sol[0], sol[1]) == pytest.approx(pose.wrist, abs=1e-6)

    def test_out_of_reach_is_reported(self):
        assert arm.ik((arm.BASE[0] - arm.L1 - arm.L2 - 1, arm.BASE[1])) is None

    def test_elbow_stays_on_the_side_away_from_the_printer(self):
        for pose in arm.poses():
            elbow = arm.ik(pose.wrist)[2]
            assert elbow[0] > -pc.PRINTER_HALF_W, pose.label


class TestDesign:
    def test_all_checks_pass(self):
        summary = arm.design_summary()
        assert summary["fail"] == [] and summary["warn"] == [], summary
        assert summary["z_travel"] == max(pc.SLOT_Z) - pc.WASH_Z

    def test_column_and_rail_stay_outside_the_door_sweep(self):
        assert pc.DOOR_HINGE[0] + pc.DOOR_WIDTH < arm.ARM_X - arm.COLUMN_R
        assert arm.door_clearance() >= arm.SAFE_GAP

    def test_rail_is_short(self):
        assert arm.RAIL_LEN <= 320.0  # Schiene nur zum Parken

    def test_a_diagonal_path_would_hit_the_printer_corner(self):
        """Erst quer, dann hinein: Schräg vom Drucker zum Turm streift die Platte die Druckerecke."""
        a = (0.0, arm._BED_OUT_TIP_Y)
        b = (pc.MAG_X, arm._TOWER_OUT_TIP_Y)
        worst = min(
            arm._point_box_gap(arm.plate_on_fork((a[0] + (b[0] - a[0]) * k / 40, a[1] + (b[1] - a[1]) * k / 40)),
                               arm.PRINTER_BOX)
            for k in range(41)
        )  # fmt: skip
        assert worst < 0
        assert arm.path_clearances()["plate_printer"] >= 0

    def test_links_in_the_plate_plane_would_sweep_through_the_plate(self, monkeypatch):
        assert arm.arm_over_parts() >= arm.SAFE_GAP
        monkeypatch.setattr(arm, "LINK_DZ", 0.0)
        assert arm.arm_over_parts() < 0

    def test_why_scara_instead_of_an_articulated_arm(self):
        assert arm.gravity_arm_nm() > 4 * arm.SERVO_RATED_NM
        assert arm.SERVO_RATED_NM / arm.shoulder_torque_nm() >= 2.0

    def test_fork_carries_the_whole_plate(self):
        assert arm.FORK_TINE > arm.HOOK_STROKE > pc.PLATE_EDGE
        assert arm.FORK_W < pc.TOWER_CLEAR_X

    def test_plate_is_fully_out_of_the_printer_before_it_moves_sideways(self):
        first = arm.transfer_path()[0]
        assert first[1] > pc.PRINTER_HALF_D + 2.0
