"""Einmessen der Kamera-Prüfung: Schwellwert-Vorschlag und gespeicherter Wert."""

import pytest

from backend.app.services import camera_calibration as cc


class TestSuggest:
    def test_clearly_separated_sets_get_a_threshold_near_the_empty_ones(self):
        result = cc.suggest([0.2, 0.3, 0.25], [3.0, 5.0, 4.0])
        assert result["separable"] and result["quality"] == "good"
        assert 0.3 < result["threshold"] < 1.5  # näher an leer als an belegt
        assert result["missed_objects"] == 0 and result["false_alarms"] == 0

    def test_min_confidence_stays_below_what_empty_frames_reach(self):
        result = cc.suggest([0.1, 0.2], [4.0, 5.0])
        worst_empty_confidence = 1 - 0.2 / result["threshold"]
        assert result["min_confidence"] <= worst_empty_confidence

    def test_small_gap_is_flagged_as_weak(self):
        result = cc.suggest([1.0, 1.1], [1.2, 1.5])
        assert result["separable"] and result["quality"] == "weak"

    def test_overlap_prefers_false_alarms_over_missed_objects(self):
        result = cc.suggest([0.5, 1.5], [1.0, 3.0, 4.0])
        assert not result["separable"] and result["quality"] == "overlap"
        assert result["missed_objects"] == 0  # lieber ein falscher Alarm als ein übersehenes Teil
        assert result["false_alarms"] >= 1

    def test_identical_empty_scores_work(self):
        result = cc.suggest([0.0, 0.0], [2.0])
        assert result["threshold"] >= 0.05 and result["separable"]

    def test_both_kinds_of_images_are_required(self):
        with pytest.raises(ValueError):
            cc.suggest([], [1.0])
        with pytest.raises(ValueError):
            cc.suggest([1.0], [])

    def test_negative_scores_are_rejected(self):
        with pytest.raises(ValueError):
            cc.suggest([-1.0], [2.0])


class TestTuningFile:
    def test_roundtrip_and_reset(self, tmp_path):
        assert cc.load_difference_threshold(tmp_path) is None
        cc.save_difference_threshold(1.234, tmp_path)
        assert cc.load_difference_threshold(tmp_path) == 1.234
        assert cc.clear_difference_threshold(tmp_path) is True
        assert cc.clear_difference_threshold(tmp_path) is False
        assert cc.load_difference_threshold(tmp_path) is None

    @pytest.mark.parametrize("value", [0.0, 0.01, 99])
    def test_absurd_values_are_refused(self, tmp_path, value):
        with pytest.raises(ValueError):
            cc.save_difference_threshold(value, tmp_path)

    def test_broken_or_out_of_range_file_is_ignored(self, tmp_path):
        (tmp_path / cc.TUNING_NAME).write_text("{kaputt")
        assert cc.load_difference_threshold(tmp_path) is None
        (tmp_path / cc.TUNING_NAME).write_text('{"difference_threshold": 500}')
        assert cc.load_difference_threshold(tmp_path) is None

    def test_detector_uses_the_saved_value_unless_told_otherwise(self, tmp_path, monkeypatch):
        from backend.app.services import plate_detection
        from backend.app.services.plate_detection import PlateDetector

        # Andere Tests laden das Modul mit einer Attrappe für OpenCV neu; der Konstruktor braucht nur das Kennzeichen.
        monkeypatch.setattr(plate_detection, "OPENCV_AVAILABLE", True)
        monkeypatch.setattr(cc, "tuning_path", lambda data_dir=None: tmp_path / cc.TUNING_NAME)
        assert PlateDetector().difference_threshold == PlateDetector.DEFAULT_DIFFERENCE_THRESHOLD
        cc.save_difference_threshold(2.5, tmp_path)
        assert PlateDetector().difference_threshold == 2.5
        assert PlateDetector(difference_threshold=0.7).difference_threshold == 0.7
