"""Tests für CLAHE-Beleuchtungsfilter in der optischen Betterkennung."""

import pytest

from backend.app.services import plate_detection


class TestPlateDetectionCLAHE:
    def test_clahe_enhancement_runs_on_frame(self):
        if not plate_detection.OPENCV_AVAILABLE:
            pytest.skip("OpenCV nicht verfügbar")

        import numpy as np

        detector = plate_detection.PlateDetector()
        # Erstelle ein synthetisches Graustufen-/Farb-Testbild
        frame = np.full((100, 100, 3), 120, dtype=np.uint8)
        enhanced = detector._apply_clahe_enhancement(frame)
        assert enhanced is not None
        assert enhanced.shape == (100, 100, 3)

    def test_preprocess_for_comparison_includes_clahe(self):
        if not plate_detection.OPENCV_AVAILABLE:
            pytest.skip("OpenCV nicht verfügbar")

        import numpy as np

        detector = plate_detection.PlateDetector()
        frame = np.full((120, 120, 3), 80, dtype=np.uint8)
        preprocessed = detector._preprocess_for_comparison(frame)
        assert preprocessed is not None
        assert preprocessed.shape == (120, 120)
