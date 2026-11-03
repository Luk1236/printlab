"""Integration- und Regressionstests für PrintLab v2.0.1 Enterprise & Hardening."""

from __future__ import annotations

import pytest

from backend.app.services.customer_portal import calculate_instant_quote
from backend.app.services.fleet_load_balancer import calculate_printer_fitness, dispatch_job_to_fleet
from backend.app.services.ha_discovery import build_discovery_payloads
from backend.app.services.hardware_extension import HardwareExtension
from backend.app.services.outbound_webhooks import (
    is_safe_webhook_url,
    register_webhook,
)
from backend.app.services.wear_tracker import (
    get_wear_overview,
    record_print_usage,
    reset_wear_component,
)


def test_outbound_webhooks_ssrf_protection():
    """Verifiziert die SSRF-Abwehr gegen Cloud-Metadatendienste und unberechtigte Netze."""
    # 1. AWS / GCP / Azure Metadatendienst blockiert
    safe, msg = is_safe_webhook_url("http://169.254.169.254/latest/meta-data/")
    assert not safe
    assert "Cloud-Instanz-Metadaten" in msg

    safe, msg = is_safe_webhook_url("http://metadata.google.internal/computeMetadata/v1/")
    assert not safe
    assert "Cloud-Instanz-Metadaten" in msg

    # 2. Loopback-Adressen im Standardmodus blockiert
    safe, msg = is_safe_webhook_url("http://127.0.0.1:8000/internal-admin", allow_private=False)
    assert not safe
    assert "Loopback" in msg

    # 3. Ungültige Schemas (file://, ftp://, gopher://) blockiert
    safe, msg = is_safe_webhook_url("file:///etc/passwd")
    assert not safe
    assert "Protokoll" in msg

    # 4. Offizieller sicherer Webhook erlaubt
    safe, _ = is_safe_webhook_url("https://discord.com/api/webhooks/12345/abcdef")
    assert safe

    # 5. register_webhook wirft ValueError bei SSRF-URL
    with pytest.raises(ValueError, match="Cloud-Instanz-Metadaten"):
        register_webhook("http://169.254.169.254/leak")


def test_hardware_cooldown_guard_interlock(tmp_path):
    """Verifiziert die thermische Plattenwechselsperre bei heißem Druckbett."""
    cfg = tmp_path / "hardware.json"
    mag = tmp_path / "magazine.json"
    hw = HardwareExtension(config_path=cfg, magazine_path=mag)

    # 1. Druckbett heiß (60 °C) -> Plattenwechsel gesperrt
    ok, msg = hw.change_plate("TestJob", current_bed_temp=60.0)
    assert not ok
    assert "Druckbett ist noch zu heiß" in msg or "Abkühlsperre" in msg

    # 2. Mit explizitem force=True wird der Wechsel trotz Hitze erzwungen
    ok, msg = hw.change_plate("TestJob", current_bed_temp=60.0, force=True)
    assert ok
    assert "eingesetzt (Simulation)" in msg

    # 3. Druckbett abgekühlt (30 °C <= 36 °C) -> Plattenwechsel regulär erlaubt
    ok, msg = hw.change_plate("TestJob2", current_bed_temp=30.0)
    assert ok
    assert "eingesetzt (Simulation)" in msg


def test_wear_tracker_component_reset(tmp_path, monkeypatch):
    """Prüft das Aufbuchen und Zurücksetzen von Verschleißkomponenten."""
    fake_wear_file = tmp_path / "wear.json"
    monkeypatch.setattr("backend.app.services.wear_tracker.WEAR_FILE", fake_wear_file)

    printer_id = "test_printer_42"

    # Druckzeit mit abrasivem Filament buchen
    record_print_usage(printer_id, print_time_hours=10.0, filament_type="PLA-CF")

    overview = get_wear_overview(printer_id)
    nozzle_comp = next(c for c in overview["components"] if c["id"] == "nozzle")
    # PLA-CF hat Abrasiv-Multiplikator 5.0 -> 10 * 5 = 50 Stunden
    assert nozzle_comp["used_hours"] >= 50.0

    # Wartung quittieren / Komponente zurücksetzen
    reset_ok = reset_wear_component(printer_id, "nozzle")
    assert reset_ok

    overview_after = get_wear_overview(printer_id)
    nozzle_after = next(c for c in overview_after["components"] if c["id"] == "nozzle")
    assert nozzle_after["used_hours"] == 0.0


def test_fleet_load_balancer_scoring():
    """Verifiziert die Flotten-Zuweisung und Fitness-Bewertung."""
    job = {
        "name": "Carbon Flange",
        "material": "PLA-CF",
        "filament_grams": 45.0,
        "nozzle_diameter": 0.4,
        "requires_hardened_nozzle": True,
    }

    printers = [
        {
            "id": 1,
            "name": "P2S-Alpha",
            "connected": True,
            "state": "IDLE",
            "plate_clear": True,
            "bed_temp": 24.0,
            "nozzle_diameter": 0.4,
            "is_hardened_nozzle": True,
            "ams_slots": [{"slot_id": 1, "material": "PLA-CF", "color": "black", "remaining_grams": 250.0}],
            "total_operating_hours": 80.0,
        },
        {
            "id": 2,
            "name": "P2S-Beta",
            "connected": False,
            "state": "OFFLINE",
        },
    ]

    result = dispatch_job_to_fleet(job, printers)
    assert result["status"] == "DISPATCHED"
    assert result["selected_printer_id"] == 1
    assert result["candidates"][0]["fitness_score"] >= 70.0


def test_ha_discovery_payloads():
    """Verifiziert die Home Assistant MQTT Discovery Entitätserzeugung."""
    payloads = build_discovery_payloads("p2s_01", "P2S Vorne")
    assert len(payloads) >= 4

    topics = [p["topic"] for p in payloads]
    assert any("sensor/printlab_p2s_01/print_state/config" in t for t in topics)
    assert any("sensor/printlab_p2s_01/nozzle_temperature/config" in t for t in topics)


def test_customer_portal_quote():
    """Verifiziert die Sofort-Kalkulation im Kundenportal."""
    quote = calculate_instant_quote(
        volume_cm3=30.0,
        filament_type="PETG",
        infill_percent=20,
        layer_height=0.20,
        quantity=5,
    )

    assert quote["quantity"] == 5
    assert quote["pricing"]["discount_percent"] == 5.0
    assert quote["pricing"]["gross_total_eur"] > 0.0
