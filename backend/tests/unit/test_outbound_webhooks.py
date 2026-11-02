"""Tests für die Outbound Webhooks Engine."""

from backend.app.services import outbound_webhooks


class TestOutboundWebhooks:
    def test_register_list_delete_webhook(self, tmp_path, monkeypatch):
        test_file = tmp_path / "webhooks_test.json"
        monkeypatch.setattr(outbound_webhooks, "WEBHOOKS_FILE", test_file)

        hook = outbound_webhooks.register_webhook(
            url="https://discord.com/api/webhooks/test",
            secret="supersecret123",
            events=["print.completed", "safety.emergency_stop"],
            format_type="discord",
            description="Discord Notfallkanal",
        )
        assert hook["id"].startswith("wh_")
        assert hook["format"] == "discord"

        hooks = outbound_webhooks.list_webhooks()
        assert len(hooks) == 1
        assert hooks[0]["id"] == hook["id"]

        del_ok = outbound_webhooks.delete_webhook(hook["id"])
        assert del_ok is True
        assert len(outbound_webhooks.list_webhooks()) == 0

    def test_build_signature(self):
        sig = outbound_webhooks.build_signature("secretkey", b'{"test": 123}')
        assert sig.startswith("sha256=")
        assert len(sig) == 7 + 64

    def test_format_payload_discord(self):
        payload = outbound_webhooks.format_payload(
            "discord",
            "print.completed",
            {"job": "Gehaeuse_v2.3mf", "time": "2h 15m", "filament_g": 65.4},
        )
        assert "embeds" in payload
        assert len(payload["embeds"]) == 1
        assert payload["embeds"][0]["title"] == "PrintLab: print.completed"
        assert payload["embeds"][0]["color"] == 0x00AE42

    def test_format_payload_slack(self):
        payload = outbound_webhooks.format_payload(
            "slack",
            "safety.emergency_stop",
            {"reason": "Not-Aus Schalter betätigt"},
        )
        assert "text" in payload
        assert "emergency_stop" in payload["text"]

    def test_format_payload_generic(self):
        payload = outbound_webhooks.format_payload(
            "generic",
            "plate.swap_required",
            {"plate_slot": 2, "printer_id": "P2S_01"},
        )
        assert payload["event"] == "plate.swap_required"
        assert payload["data"]["printer_id"] == "P2S_01"
