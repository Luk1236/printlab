"""Tests für die Live-Fehldruck- und Spaghetti-Erkennung."""

import pytest

from backend.app.services import spaghetti_detector


class TestSpaghettiDetector:
    def test_compute_chaos_score_on_smooth_image(self):
        if not spaghetti_detector.OPENCV_AVAILABLE:
            pytest.skip("OpenCV nicht verfügbar")

        import numpy as np

        det = spaghetti_detector.SpaghettiDetector()
        # Glatte Fläche (geringe Kantendichte)
        smooth_frame = np.full((120, 120, 3), 100, dtype=np.uint8)
        score = det.compute_chaos_score(smooth_frame)
        assert score < 0.20

    def test_compute_chaos_score_on_noisy_image(self):
        if not spaghetti_detector.OPENCV_AVAILABLE:
            pytest.skip("OpenCV nicht verfügbar")

        import numpy as np

        det = spaghetti_detector.SpaghettiDetector()
        # Künstliches Rauschen / chaotische Linien (Spaghetti-Simulation)
        noisy_frame = np.random.randint(0, 256, (120, 120, 3), dtype=np.uint8)
        score = det.compute_chaos_score(noisy_frame)
        assert score > 0.40

    def test_analyze_frame_rolling_trigger(self):
        if not spaghetti_detector.OPENCV_AVAILABLE:
            pytest.skip("OpenCV nicht verfügbar")

        import cv2
        import numpy as np

        det = spaghetti_detector.SpaghettiDetector()
        det.reset_printer("p2s_test")

        # Erstelle ein stark verrauschtes Bild
        noisy = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", noisy)
        img_bytes = buf.tobytes()

        # 1. Frame: Verdacht
        res1 = det.analyze_frame(img_bytes, printer_id="p2s_test", layer_num=5)
        assert res1.consecutive_failures == 1
        assert res1.should_pause is False

        # 2. Frame
        res2 = det.analyze_frame(img_bytes, printer_id="p2s_test", layer_num=5)
        assert res2.consecutive_failures == 2
        assert res2.should_pause is False

        # 3. Frame: Schwellwert erreicht -> Not-Pausieren!
        res3 = det.analyze_frame(img_bytes, printer_id="p2s_test", layer_num=5)
        assert res3.consecutive_failures == 3
        assert res3.should_pause is True
        assert "Kritischer Fehldruck" in res3.message
