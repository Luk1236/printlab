"""Unit tests for plate detection service.

Kein ``importlib.reload`` mit gemockten Modulen: Ein Reload unter gemocktem
``cv2``/``numpy`` hinterlässt Mock-Attribute im geteilten Modul und ein
bare ``OPENCV_AVAILABLE = False`` ohne Restore vergiftet jeden nachfolgenden
Test im selben Prozess (im Sharded-Schema der CI lief das als
``test_abnahme``-OpenCV-Crash). Stattdessen: das Modul einmal normal
importieren und die Verfügbarkeits-Flagge über ``monkeypatch`` setzen, die
am Testende automatisch zurücksetzt — in beiden Umgebungen (mit und ohne
echtem OpenCV) korrekt.
"""

from unittest.mock import MagicMock

import pytest

import backend.app.services.plate_detection as pd_module


@pytest.fixture()
def no_opencv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spendiert dem Modul für einen Testzustand „OpenCV fehlt", sauber zurück gesetzt."""
    monkeypatch.setattr(pd_module, "OPENCV_AVAILABLE", False)


@pytest.fixture()
def opencv_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Erzwingt „OpenCV verfügbar" — auch auf Maschinen ohne echte Installation."""
    monkeypatch.setattr(pd_module, "OPENCV_AVAILABLE", True)


class TestPlateDetectionResult:
    """Tests for PlateDetectionResult class."""

    def test_result_to_dict(self):
        """Verify PlateDetectionResult.to_dict() returns correct structure."""
        result = pd_module.PlateDetectionResult(
            is_empty=True,
            confidence=0.95,
            difference_percent=0.5,
            message="Test message",
            debug_image=None,
            needs_calibration=False,
        )

        d = result.to_dict()

        assert d["is_empty"] is True
        assert d["confidence"] == 0.95
        assert d["difference_percent"] == 0.5
        assert d["message"] == "Test message"
        assert d["has_debug_image"] is False
        assert d["needs_calibration"] is False

    def test_result_with_debug_image(self):
        """Verify has_debug_image is True when debug_image is provided."""
        result = pd_module.PlateDetectionResult(
            is_empty=False,
            confidence=0.8,
            difference_percent=5.0,
            message="Objects detected",
            debug_image=b"fake_image_data",
            needs_calibration=False,
        )

        d = result.to_dict()
        assert d["has_debug_image"] is True

    def test_result_needs_calibration(self):
        """Verify needs_calibration flag is preserved."""
        result = pd_module.PlateDetectionResult(
            is_empty=True,
            confidence=0.0,
            difference_percent=0.0,
            message="No calibration",
            needs_calibration=True,
        )

        d = result.to_dict()
        assert d["needs_calibration"] is True


class TestPlateDetector:
    """Tests for PlateDetector class."""

    def test_detector_initialization(self, opencv_fresh):
        """Verify PlateDetector initializes with default values."""
        detector = pd_module.PlateDetector()
        assert detector.roi == (0.15, 0.35, 0.70, 0.55)
        assert detector.difference_threshold == 1.0

    def test_detector_custom_roi(self, opencv_fresh):
        """Verify PlateDetector accepts custom ROI."""
        custom_roi = (0.1, 0.2, 0.8, 0.6)
        detector = pd_module.PlateDetector(roi=custom_roi)
        assert detector.roi == custom_roi

    def test_detector_raises_without_opencv(self, no_opencv):
        """Verify PlateDetector raises when OpenCV not available."""
        with pytest.raises(RuntimeError, match="OpenCV is not installed"):
            pd_module.PlateDetector()


class TestCalibrationStatus:
    """Tests for calibration status functions."""

    def test_get_calibration_status_no_opencv(self, no_opencv):
        """Verify calibration status when OpenCV not available."""
        status = pd_module.get_calibration_status(1)

        assert status["available"] is False
        assert status["calibrated"] is False
        assert status["reference_count"] == 0
        assert "OpenCV not available" in status["message"]


class TestAvailableChecks:
    """Verfügbarkeits-Flagge wird über den monkeypatch-Fixture gesetzt und zurückgesetzt."""

    def test_is_plate_detection_available_true(self, opencv_fresh):
        assert pd_module.is_plate_detection_available() is True

    def test_is_plate_detection_available_false(self, no_opencv):
        assert pd_module.is_plate_detection_available() is False


class TestDeleteCalibration:
    """Tests for delete_calibration function."""

    def test_delete_calibration_no_opencv(self, no_opencv):
        """Verify delete_calibration returns False when OpenCV not available."""
        result = pd_module.delete_calibration(1)
        assert result is False


# Bewusst kein MagicMock-Restbestand: das alte Muster (``patch.dict("sys.modules",
# {"cv2": ...})`` + ``importlib.reload``) ist entfernt, weil es den Modulzustand
# für alles, was danach läuft, verunreinigt. Falls jemand wieder einen
# „ohne-cv2"-Zustand braucht: die Flagge monkeypatchen, nicht das Modul neu laden.
