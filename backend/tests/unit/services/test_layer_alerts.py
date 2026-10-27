"""Tests für Schicht-Hinweise (Pause bei Zielschicht)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services.layer_alerts import LayerAlerts


class FakeClient:
    def __init__(self, state: str = "RUNNING", key: str = "job-a"):
        self.state = SimpleNamespace(state=state, subtask_id=key, gcode_file=key)
        self.pauses = 0

    def pause_print(self) -> bool:
        self.pauses += 1
        self.state.state = "PAUSE"
        return True


class TestLayerAlerts:
    def test_konfiguration_persistiert(self, tmp_path):
        alerts = LayerAlerts(tmp_path / "layer.json")
        data = alerts.configure(1, True, 12)
        assert data["enabled"] is True
        assert data["layer"] == 12
        wieder = LayerAlerts(tmp_path / "layer.json")
        assert wieder.status(1)["layer"] == 12
        assert wieder.status(1)["enabled"] is True

    @pytest.mark.asyncio
    async def test_pausiert_einmal_bei_zielschicht(self, tmp_path):
        alerts = LayerAlerts(tmp_path / "layer.json")
        alerts.configure(1, True, 10)
        client = FakeClient()
        assert await alerts.observe(1, 5, client) is False
        assert await alerts.observe(1, 10, client) is True
        assert client.pauses == 1
        assert await alerts.observe(1, 11, client) is False
        assert client.pauses == 1

    @pytest.mark.asyncio
    async def test_neuer_druck_ist_wieder_scharf(self, tmp_path):
        alerts = LayerAlerts(tmp_path / "layer.json")
        alerts.configure(1, True, 10)
        client = FakeClient()
        assert await alerts.observe(1, 10, client) is True
        client.state.state = "RUNNING"
        client.state.subtask_id = "job-b"
        assert await alerts.observe(1, 11, client) is True
        assert client.pauses == 2

    @pytest.mark.asyncio
    async def test_schicht_rueckwaerts_setzt_zurueck(self, tmp_path):
        alerts = LayerAlerts(tmp_path / "layer.json")
        alerts.configure(1, True, 10)
        client = FakeClient()
        assert await alerts.observe(1, 10, client) is True
        client.state.state = "RUNNING"
        assert await alerts.observe(1, 3, client) is False
        assert alerts.status(1)["triggered"] is False
        assert await alerts.observe(1, 10, client) is True

    @pytest.mark.asyncio
    async def test_aus_oder_nicht_druckend_pausiert_nicht(self, tmp_path):
        alerts = LayerAlerts(tmp_path / "layer.json")
        alerts.configure(1, False, 10)
        client = FakeClient()
        assert await alerts.observe(1, 10, client) is False
        alerts.configure(1, True, 10)
        client.state.state = "PAUSE"
        assert await alerts.observe(1, 10, client) is False
        assert client.pauses == 0

    @pytest.mark.asyncio
    async def test_ohne_client(self, tmp_path):
        alerts = LayerAlerts(tmp_path / "layer.json")
        alerts.configure(1, True, 10)
        assert await alerts.observe(1, 10, None) is False
