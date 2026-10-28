"""Unit tests for per-job part watcher overrides (Roadmap P1)."""

import pytest

from backend.app.services.part_watcher import PartWatcher


@pytest.fixture()
def watcher(tmp_path):
    return PartWatcher(path=tmp_path / "part_watcher.json")


class TestOverrides:
    def test_default_without_rules(self, watcher):
        watcher.configure(1, enabled=True, threshold=1.0)
        entry = watcher._resolve(1, "job-x")
        assert "override" not in entry
        assert entry["threshold"] == 1.0

    def test_first_matching_rule_wins(self, watcher):
        watcher.configure(
            1,
            enabled=True,
            overrides=[
                {"key_contains": "towel", "threshold": 2.0},
                {"key_contains": "job", "threshold": 5.0},
            ],
        )
        entry = watcher._resolve(1, "test_JOB_towel-3mf")
        assert entry["override"] == "towel"
        assert entry["threshold"] == 2.0

    def test_rule_can_disable_job(self, watcher):
        watcher.configure(
            1,
            enabled=True,
            overrides=[
                {"key_contains": "benchy", "enabled": False},
            ],
        )
        assert watcher._resolve(1, "BENCHY.gcode.3mf")["enabled"] is False
        # Unmatched jobs stay enabled.
        assert watcher._resolve(1, "other.gcode.3mf")["enabled"] is True

    def test_thresholds_clamped_and_bad_rules_dropped(self, watcher):
        status = watcher.configure(
            1,
            enabled=True,
            overrides=[
                {"key_contains": "", "threshold": 100},  # dropped (no fragment)
                "not-a-dict",  # dropped
                {"key_contains": "x", "threshold": 999},  # clamped to 20
            ],
        )
        assert status["overrides"] == [{"key_contains": "x", "threshold": 20.0, "enabled": True}]

    def test_obeserve_uses_rule_threshold(self, watcher, monkeypatch):
        watcher.configure(
            1,
            enabled=True,
            overrides=[
                {"key_contains": "big", "threshold": 3.0},
            ],
        )
        import cv2
        import numpy as np

        arr = np.full((100, 100), 200, dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", arr)
        ref = buf.tobytes()
        changed = np.full((100, 100), 0, dtype=np.uint8)
        ok2, buf2 = cv2.imencode(".jpg", changed)
        # First call stores reference (layer 2)
        watcher.observe(1, "P2S", 2, 100, ref, "big-job")
        # Mid print: big change but below the rule threshold 3.0 -> no warning
        warning = watcher.observe(1, "P2S", 50, 100, buf2.tobytes(), "big-job")
        assert warning is None
