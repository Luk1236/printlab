"""Tests für den Verschleißteil- und Predictive-Maintenance-Tracker."""

from backend.app.services import wear_tracker


class TestWearTracker:
    def test_record_standard_print_usage(self, tmp_path, monkeypatch):
        test_file = tmp_path / "wear_test.json"
        monkeypatch.setattr(wear_tracker, "WEAR_FILE", test_file)

        overview = wear_tracker.record_print_usage(
            printer_id="p2s_test",
            print_time_hours=10.0,
            filament_type="PLA",
        )
        assert overview["printer_id"] == "p2s_test"
        assert overview["overall_status"] in ("OK", "WARN", "CRITICAL")

        nozzle = next(c for c in overview["components"] if c["id"] == "nozzle")
        assert nozzle["used_hours"] == 10.0
        assert nozzle["remaining_hours"] > 0
        assert nozzle["health_percent"] > 90.0

    def test_record_abrasive_print_usage_accelerates_wear(self, tmp_path, monkeypatch):
        test_file = tmp_path / "wear_test.json"
        monkeypatch.setattr(wear_tracker, "WEAR_FILE", test_file)

        # 5 Stunden PLA-CF mit Abrasiv-Faktor (5x Multiplikator)
        overview = wear_tracker.record_print_usage(
            printer_id="p2s_abrasive",
            print_time_hours=5.0,
            filament_type="PLA-CF",
        )
        nozzle = next(c for c in overview["components"] if c["id"] == "nozzle")
        assert nozzle["used_hours"] == 25.0  # 5h * 5x = 25h

    def test_reset_wear_component(self, tmp_path, monkeypatch):
        test_file = tmp_path / "wear_test.json"
        monkeypatch.setattr(wear_tracker, "WEAR_FILE", test_file)

        wear_tracker.record_print_usage("p2s_reset", 20.0, "PLA")
        ok = wear_tracker.reset_wear_component("p2s_reset", "nozzle")
        assert ok is True

        cur = wear_tracker.get_printer_wear("p2s_reset")
        assert cur["nozzle_hours"] == 0.0
