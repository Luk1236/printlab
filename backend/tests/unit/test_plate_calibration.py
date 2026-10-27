"""Unit tests for the plate calibration (homography over the four corners)."""

import sys

import numpy as np
import pytest

from backend.app.services import plate_calibration


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(plate_calibration, "STORE_DIR", tmp_path)
    return tmp_path


class TestPoints:
    def test_status_uncalibrated_and_plate_size(self):
        status = plate_calibration.status(1)
        assert status["calibrated"] is False
        assert status["points"] is None
        assert status["plate_size"] == plate_calibration.PLATE_TARGET_PX

    def test_set_and_read_roundtrip(self):
        points = [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]]
        plate_calibration.set_points(1, points)
        assert plate_calibration.status(1)["points"] == points
        assert plate_calibration.status(1)["calibrated"] is True

    def test_set_rejects_wrong_count_and_bounds(self):
        with pytest.raises(ValueError):
            plate_calibration.set_points(1, [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8]])
        with pytest.raises(ValueError):
            plate_calibration.set_points(1, [[1.5, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]])

    def test_clear(self):
        plate_calibration.set_points(1, [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        assert plate_calibration.clear(1)["calibrated"] is False


class TestWarp:
    def _synthetic_frame(self) -> bytes:
        """A 400x300 white frame with a black rectangle at the plate area
        defined by the calibration points below."""
        import cv2

        frame = np.full((300, 400, 3), 255, dtype=np.uint8)
        frame[60:240, 80:360] = 0
        ok, encoded = cv2.imencode(".jpg", frame)
        assert ok
        return encoded.tobytes()

    def test_warp_requires_calibration(self, isolated_store):
        assert plate_calibration.warp_bytes(1, self._synthetic_frame()) is None

    def test_warp_rectifies_the_plate_area(self, isolated_store):
        # Calibration: the plateau of the rectangle above maps to the full plate.
        pts = [[80 / 400, 60 / 300], [360 / 400, 60 / 300], [360 / 400, 240 / 300], [80 / 400, 240 / 300]]
        plate_calibration.set_points(1, pts)
        warped = plate_calibration.warp_bytes(1, self._synthetic_frame())
        assert warped is not None
        import cv2

        img = cv2.imdecode(np.frombuffer(warped, np.uint8), cv2.IMREAD_GRAYSCALE)
        assert img.shape[:2] == (plate_calibration.PLATE_TARGET_PX,) * 2
        # Corners of the target plate are plate (the frame was white there,
        # inside the rectangle it is black): warped corners now sit inside the
        # former rectangle, so they must be black now.
        assert img.mean() < 40

    def test_warp_with_unreadable_image_returns_none(self, isolated_store):
        plate_calibration.set_points(1, [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        assert plate_calibration.warp_bytes(1, b"notanimage") is None
