"""Unit tests for the spaghetti/abandonment check (warn-only, spread metric)."""

import json

import cv2
import numpy as np
import pytest

from backend.app.services import spaghetti_check


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    path = tmp_path / "spaghetti_check.json"
    monkeypatch.setattr(spaghetti_check, "CONFIG_PATH", path)
    return path


@pytest.fixture()
def singleton():
    return spaghetti_check.SpaghettiCheck()


def _jpg(arr: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", arr)
    assert ok
    return encoded.tobytes()


def _blank(w=200, h=200, value=255) -> np.ndarray:
    return np.full((h, w, 3), value, dtype=np.uint8)


class TestConfig:
    def test_defaults(self):
        cfg = spaghetti_check.read_config()
        assert cfg["enabled"] is False
        assert cfg["max_components"] == 25
        assert cfg["min_changed_percent"] == 0.5

    def test_roundtrip_and_corrupt_file(self, isolated_config):
        isolated_config.write_text("{ broken", encoding="utf-8")
        assert spaghetti_check.read_config()["enabled"] is False
        spaghetti_check.write_config({"enabled": True, "max_components": 40})
        cfg = spaghetti_check.read_config()
        assert cfg["enabled"] is True
        assert cfg["max_components"] == 40


class TestSpreadScore:
    def test_blank_vs_identical(self):
        blank = _jpg(_blank())
        components, percent = spaghetti_check.spread_score(blank, blank)
        assert components == 0
        assert percent == 0.0

    def test_one_spot(self):
        frame = _blank()
        frame[60:120, 60:120] = 0
        blank = _jpg(_blank())
        components, percent = spaghetti_check.spread_score(_jpg(frame), blank)
        assert components == 1
        assert percent > 0

    def test_spaghetti_pattern(self):
        frame = _blank()
        rng = np.random.default_rng(7)
        for _ in range(60):
            x, y = int(rng.integers(10, 190)), int(rng.integers(10, 190))
            frame[y : y + 3, x : x + 3] = 0
        blank = _jpg(_blank())
        components, _ = spaghetti_check.spread_score(_jpg(frame), blank)
        assert components > 25  # scattered -> many components


class TestCheck:
    def _enable_warp_passthrough(self, monkeypatch):
        from backend.app.services import plate_calibration

        monkeypatch.setattr(plate_calibration, "warp_bytes", lambda pid, img: img)

    def test_check_warns_on_spread(self, isolated_config, monkeypatch):
        spaghetti_check.write_config({"enabled": True})
        self._enable_warp_passthrough(monkeypatch)
        blank = _jpg(_blank())
        frame = _blank()
        rng = np.random.default_rng(3)
        for _ in range(80):
            x, y = int(rng.integers(5, 195)), int(rng.integers(5, 195))
            frame[y : y + 3, x : x + 3] = 0
        result = spaghetti_check.check(1, _jpg(frame), blank)
        assert result is not None
        assert result["warning"]
        assert result["components"] > 25

    def test_check_quiet_when_concentrated(self, isolated_config, monkeypatch):
        spaghetti_check.write_config({"enabled": True})
        self._enable_warp_passthrough(monkeypatch)
        blank = _jpg(_blank())
        frame = _blank()
        frame[70:130, 70:130] = 0  # one solid block = a normal print
        result = spaghetti_check.check(1, _jpg(frame), blank)
        assert result is not None
        assert result["warning"] is None

    def test_disabled_returns_none(self, isolated_config, monkeypatch):
        self._enable_warp_passthrough(monkeypatch)
        assert spaghetti_check.check(1, _jpg(_blank()), _jpg(_blank())) is None


class TestCycle:
    def test_needs_frame_once_per_print_and_at_end(self, singleton):
        spaghetti_check.write_config({"enabled": True})
        assert singleton.needs_frame(1, 5, 100, "job-a") is False  # 5 < 75
        assert singleton.needs_frame(1, 80, 100, "job-a") is True  # at 75+
        singleton.observe(1, "P2S", 80, b"img", "job-a")  # checked flag set
        assert singleton.needs_frame(1, 85, 100, "job-a") is False

    def test_new_print_resets_check_flag(self, singleton):
        spaghetti_check.write_config({"enabled": True})
        singleton.observe(1, "P2S", 80, b"img", "job-a")
        assert singleton.needs_frame(1, 80, 100, "job-b") is True
