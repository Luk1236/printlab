"""Tests für das Multi-Drucker Fleet Management & Load Balancing."""

from backend.app.services import fleet_load_balancer


class TestFleetLoadBalancer:
    def test_calculate_printer_fitness_ideal_match(self):
        printer = {
            "id": "p2s_1",
            "name": "Bambu P2S #1",
            "connected": True,
            "state": "IDLE",
            "plate_clear": True,
            "bed_temp": 24.0,
            "nozzle_diameter": 0.4,
            "is_hardened_nozzle": True,
            "total_operating_hours": 120.0,
            "ams_slots": [
                {"slot_id": 1, "material": "PLA", "color": "green", "remaining_grams": 450.0},
            ],
        }
        job = {
            "name": "Testgehaeuse",
            "material": "PLA",
            "color": "green",
            "filament_grams": 60.0,
            "nozzle_diameter": 0.4,
            "requires_hardened_nozzle": False,
        }

        score, reasons = fleet_load_balancer.calculate_printer_fitness(printer, job)
        assert score >= 85.0
        assert any("bereit" in r.lower() for r in reasons)
        assert any("ams slot 1" in r.lower() for r in reasons)

    def test_calculate_printer_fitness_incompatible_nozzle(self):
        printer = {
            "id": "p2s_2",
            "connected": True,
            "state": "IDLE",
            "plate_clear": True,
            "nozzle_diameter": 0.2,  # 0.2mm Düse montiert
            "is_hardened_nozzle": False,
        }
        job = {
            "name": "Robuster Halter",
            "nozzle_diameter": 0.4,  # Verlangt 0.4mm
        }

        score, reasons = fleet_load_balancer.calculate_printer_fitness(printer, job)
        assert score == 0.0
        assert any("inkompatibel" in r.lower() for r in reasons)

    def test_dispatch_job_to_fleet_selects_best_candidate(self):
        printers = [
            {
                "id": "busy_printer",
                "name": "P2S Beschaeftigt",
                "connected": True,
                "state": "PRINTING",
                "plate_clear": False,
            },
            {
                "id": "ready_printer",
                "name": "P2S Frei",
                "connected": True,
                "state": "READY",
                "plate_clear": True,
                "bed_temp": 22.0,
                "nozzle_diameter": 0.4,
                "is_hardened_nozzle": True,
                "ams_slots": [{"slot_id": 2, "material": "PETG", "remaining_grams": 300.0}],
            },
        ]
        job = {
            "name": "PETG Halter",
            "material": "PETG",
            "filament_grams": 50.0,
            "nozzle_diameter": 0.4,
        }

        result = fleet_load_balancer.dispatch_job_to_fleet(job, printers)
        assert result["status"] == "DISPATCHED"
        assert result["selected_printer_id"] == "ready_printer"
        assert len(result["candidates"]) == 2
