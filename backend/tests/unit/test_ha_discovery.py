"""Tests für die Home Assistant MQTT Discovery Engine."""

import json

from backend.app.services import ha_discovery


class TestHADiscovery:
    def test_build_device_info(self):
        info = ha_discovery.build_device_info("printer_1", "Bambu Lab P2S")
        assert info["identifiers"] == ["printlab_printer_1"]
        assert "PrintLab" in info["name"]
        assert info["sw_version"] == "1.27.0"

    def test_build_discovery_payloads_generates_all_components(self):
        payloads = ha_discovery.build_discovery_payloads("p2s_lab", "P2S Werkstatt")
        assert len(payloads) >= 8

        topics = [p["topic"] for p in payloads]
        # Prüfe, dass Sensor- und Switch-Topics im Standard-HA-Format sind
        assert any("homeassistant/sensor/printlab_p2s_lab/print_state/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/nozzle_temperature/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/bed_temperature/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/print_progress/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/remaining_time/config" in t for t in topics)
        assert any("homeassistant/switch/printlab_p2s_lab/emergency_stop/config" in t for t in topics)
        assert any("homeassistant/switch/printlab_p2s_lab/chamber_light/config" in t for t in topics)

        # Prüfe Payload-Struktur des Not-Halt Schalters
        stop_switch = next(p for p in payloads if p["object_id"] == "emergency_stop")
        assert stop_switch["component"] == "switch"
        assert stop_switch["payload"]["payload_on"] == "STOP"
        assert stop_switch["payload"]["payload_off"] == "RESET"

    def test_build_telemetry_payload(self):
        telemetry_json = ha_discovery.build_telemetry_payload(
            state="PRINTING",
            nozzle_temp=220.4,
            bed_temp=55.0,
            progress=42,
            remaining_minutes=18,
            current_layer=15,
            total_layers=50,
            emergency_stop=False,
            chamber_light=True,
        )
        data = json.loads(telemetry_json)
        assert data["state"] == "PRINTING"
        assert data["nozzle_temp"] == 220.4
        assert data["bed_temp"] == 55.0
        assert data["progress"] == 42
        assert data["chamber_light"] is True
        assert data["emergency_stop"] is False
