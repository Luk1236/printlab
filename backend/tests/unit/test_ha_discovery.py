"""Tests für die Home Assistant MQTT Discovery Engine und MQTT Relay Integration."""

import json
from unittest.mock import MagicMock

from backend.app.core.config import PRINTLAB_VERSION
from backend.app.services import ha_discovery
from backend.app.services.mqtt_relay import MQTTRelayService


class TestHADiscovery:
    def test_build_device_info(self):
        info = ha_discovery.build_device_info("printer_1", "Bambu Lab P2S")
        assert info["identifiers"] == ["printlab_printer_1"]
        assert "PrintLab" in info["name"]
        assert info["sw_version"] == PRINTLAB_VERSION

    def test_build_discovery_payloads_generates_all_components(self):
        payloads = ha_discovery.build_discovery_payloads("p2s_lab", "P2S Werkstatt")
        assert len(payloads) >= 13

        topics = [p["topic"] for p in payloads]
        # Prüfe, dass Sensor-, Switch- und Button-Topics im Standard-HA-Format sind
        assert any("homeassistant/sensor/printlab_p2s_lab/print_state/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/nozzle_temperature/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/bed_temperature/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/print_progress/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/remaining_time/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/chamber_temperature/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/current_print/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_p2s_lab/cooling_fan_speed/config" in t for t in topics)
        assert any("homeassistant/switch/printlab_p2s_lab/emergency_stop/config" in t for t in topics)
        assert any("homeassistant/switch/printlab_p2s_lab/chamber_light/config" in t for t in topics)
        assert any("homeassistant/button/printlab_p2s_lab/pause_print/config" in t for t in topics)
        assert any("homeassistant/button/printlab_p2s_lab/resume_print/config" in t for t in topics)

        # Prüfe Payload-Struktur des Not-Halt Schalters
        stop_switch = next(p for p in payloads if p["object_id"] == "emergency_stop")
        assert stop_switch["component"] == "switch"
        assert stop_switch["payload"]["payload_on"] == "STOP"
        assert stop_switch["payload"]["payload_off"] == "RESET"

        # Prüfe Payload-Struktur des Pause Buttons
        pause_btn = next(p for p in payloads if p["object_id"] == "pause_print")
        assert pause_btn["component"] == "button"
        assert pause_btn["payload"]["payload_press"] == "PAUSE"

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
            chamber_temp=38.5,
            current_file="dragon.3mf",
            fan_speed=80,
        )
        data = json.loads(telemetry_json)
        assert data["state"] == "PRINTING"
        assert data["nozzle_temp"] == 220.4
        assert data["bed_temp"] == 55.0
        assert data["chamber_temp"] == 38.5
        assert data["progress"] == 42
        assert data["chamber_light"] is True
        assert data["emergency_stop"] is False
        assert data["current_file"] == "dragon.3mf"
        assert data["fan_speed"] == 80

    def test_mqtt_relay_publishes_ha_discovery(self):
        relay = MQTTRelayService()
        relay.enabled = True
        relay.connected = True
        relay._publish = MagicMock()

        relay.publish_ha_discovery(1, "Bambu P1S")
        assert relay._publish.called
        calls = relay._publish.call_args_list
        topics = [c[0][0] for c in calls]
        assert any("homeassistant/sensor/printlab_1/print_state/config" in t for t in topics)
        assert any("homeassistant/sensor/printlab_1/chamber_temperature/config" in t for t in topics)
        assert any("homeassistant/button/printlab_1/pause_print/config" in t for t in topics)
