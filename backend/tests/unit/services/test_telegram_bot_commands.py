"""Tests for Telegram bot commands and ntfy action buttons."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.app.models.notification import NotificationProvider
from backend.app.services.notification_service import NotificationService
from backend.app.services.telegram_bot_commands import (
    handle_telegram_callback_query,
    handle_telegram_message,
)

BOT_TOKEN = "123456:AAbbCC"
CHAT_ID = "-1002520100736"


class _CaptureClient:
    """Mock httpx.AsyncClient capturing outgoing calls."""

    def __init__(self):
        self.is_closed = False
        self.calls: list[dict] = []

    async def post(self, url, json=None, data=None, files=None):
        self.calls.append({"method": "POST", "url": url, "json": json, "data": data, "files": files})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 999}})

    async def put(self, url, content=None, headers=None):
        self.calls.append({"method": "PUT", "url": url, "content": content, "headers": headers})
        return httpx.Response(200, json={"ok": True})


@pytest.mark.asyncio
async def test_unauthorized_chat_rejected():
    client = _CaptureClient()
    message = {
        "chat": {"id": 99999},
        "text": "/status",
    }
    await handle_telegram_message(
        bot_token=BOT_TOKEN,
        message=message,
        allowed_chat_ids={CHAT_ID},
        http_client=client,
    )
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"].endswith("/sendMessage")
    assert call["json"]["chat_id"] == "99999"
    assert "nicht für PrintLab autorisiert" in call["json"]["text"]


@pytest.mark.asyncio
async def test_help_command():
    client = _CaptureClient()
    message = {
        "chat": {"id": int(CHAT_ID)},
        "text": "/help",
    }
    await handle_telegram_message(
        bot_token=BOT_TOKEN,
        message=message,
        allowed_chat_ids={CHAT_ID},
        http_client=client,
    )
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"].endswith("/sendMessage")
    assert "/status" in call["json"]["text"]
    assert "/live" in call["json"]["text"]


@pytest.mark.asyncio
async def test_status_command():
    client = _CaptureClient()
    message = {
        "chat": {"id": int(CHAT_ID)},
        "text": "/status",
    }
    with patch(
        "backend.app.services.telegram_bot_commands.format_printers_status",
        return_value=("🖨️ *Status Test*", [[{"text": "📷 Live-Foto", "callback_data": "cmd:live"}]]),
    ):
        await handle_telegram_message(
            bot_token=BOT_TOKEN,
            message=message,
            allowed_chat_ids={CHAT_ID},
            http_client=client,
        )
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"].endswith("/sendMessage")
    assert call["json"]["text"] == "🖨️ *Status Test*"
    assert call["json"]["reply_markup"]["inline_keyboard"][0][0]["text"] == "📷 Live-Foto"


@pytest.mark.asyncio
async def test_live_photo_command():
    client = _CaptureClient()
    message = {
        "chat": {"id": int(CHAT_ID)},
        "text": "/live",
    }
    fake_frame = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    with patch(
        "backend.app.services.telegram_bot_commands.capture_live_snapshot",
        return_value=(fake_frame, "X1C", "📷 *X1C*"),
    ):
        await handle_telegram_message(
            bot_token=BOT_TOKEN,
            message=message,
            allowed_chat_ids={CHAT_ID},
            http_client=client,
        )
    urls = [c["url"].rsplit("/", 1)[-1] for c in client.calls]
    assert "sendChatAction" in urls
    assert "sendPhoto" in urls

    photo_call = next(c for c in client.calls if c["url"].endswith("/sendPhoto"))
    assert photo_call["data"]["chat_id"] == CHAT_ID
    assert photo_call["data"]["caption"] == "📷 *X1C*"
    assert photo_call["files"]["photo"][1] == fake_frame


@pytest.mark.asyncio
async def test_callback_query_live():
    client = _CaptureClient()
    callback = {
        "id": "query123",
        "data": "cmd:live",
        "message": {
            "chat": {"id": int(CHAT_ID)},
            "message_id": 888,
        },
    }
    fake_frame = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    with patch(
        "backend.app.services.telegram_bot_commands.capture_live_snapshot",
        return_value=(fake_frame, "X1C", "📷 *X1C*"),
    ):
        await handle_telegram_callback_query(
            bot_token=BOT_TOKEN,
            callback_query=callback,
            allowed_chat_ids={CHAT_ID},
            http_client=client,
        )
    urls = [c["url"].rsplit("/", 1)[-1] for c in client.calls]
    assert "answerCallbackQuery" in urls
    assert "sendPhoto" in urls


@pytest.mark.asyncio
async def test_send_ntfy_with_click_and_actions():
    service = NotificationService()
    captured_headers: dict = {}

    class FakeNtfyClient:
        def __init__(self):
            self.is_closed = False

        async def post(self, url, content=None, headers=None):
            captured_headers.update(headers or {})
            return httpx.Response(200, json={"ok": True})

    service._http_client = FakeNtfyClient()
    ok, _ = await service._send_ntfy(
        config={"server": "https://ntfy.sh", "topic": "testtopic"},
        title="Druck fertig",
        message="Alles super",
        actions="view, 📷 Live-Kamera, https://printlab.local/cameras",
        click_url="https://printlab.local/printers/1",
    )
    assert ok is True
    assert captured_headers["Click"] == "https://printlab.local/printers/1"
    assert "view, 📷 Live-Kamera" in captured_headers["Actions"]


@pytest.mark.asyncio
async def test_send_to_provider_ntfy_sets_camera_action_and_click():
    service = NotificationService()
    captured: dict = {}

    async def _capture_ntfy(config, title, message, image_data=None, event_type=None, actions=None, click_url=None):
        captured["actions"] = actions
        captured["click_url"] = click_url
        return True, "ok"

    service._send_ntfy = _capture_ntfy
    provider = NotificationProvider(
        name="ntfy-test",
        provider_type="ntfy",
        config='{"server": "https://ntfy.sh", "topic": "mytopic"}',
        printer_id=42,
    )

    with patch(
        "backend.app.api.routes.settings.get_external_base_url",
        return_value="https://farm.example.com",
    ):
        ok, _ = await service._send_to_provider(
            provider,
            "Druck bereit",
            "Job abgeschlossen",
            db=object(),
            event_type="print_success",
        )
    assert ok is True
    assert captured["click_url"] == "https://farm.example.com/printers/42"
    assert "view, 📷 Live-Kamera, https://farm.example.com/cameras" in captured["actions"]
    assert "view, 🖨️ Drucker öffnen, https://farm.example.com/printers/42" in captured["actions"]


@pytest.mark.asyncio
async def test_pause_and_resume_commands():
    client = _CaptureClient()
    fake_printer = type("Printer", (), {"id": 1, "name": "Bambu P1S"})()
    mock_bambu_client = MagicMock()

    with (
        patch("backend.app.services.telegram_bot_commands.resolve_target_printer", return_value=fake_printer),
        patch("backend.app.services.printer_manager.printer_manager.get_client", return_value=mock_bambu_client),
    ):
        # /pause
        await handle_telegram_message(
            bot_token=BOT_TOKEN,
            message={"chat": {"id": int(CHAT_ID)}, "text": "/pause"},
            allowed_chat_ids={CHAT_ID},
            http_client=client,
        )
        assert mock_bambu_client.pause_print.called

        # /resume
        await handle_telegram_message(
            bot_token=BOT_TOKEN,
            message={"chat": {"id": int(CHAT_ID)}, "text": "/resume"},
            allowed_chat_ids={CHAT_ID},
            http_client=client,
        )
        assert mock_bambu_client.resume_print.called


@pytest.mark.asyncio
async def test_light_toggle_command():
    client = _CaptureClient()
    fake_printer = type("Printer", (), {"id": 1, "name": "Bambu P1S"})()
    mock_bambu_client = MagicMock()
    mock_bambu_client.state = type("State", (), {"chamber_light": False})()

    with (
        patch("backend.app.services.telegram_bot_commands.resolve_target_printer", return_value=fake_printer),
        patch("backend.app.services.printer_manager.printer_manager.get_client", return_value=mock_bambu_client),
    ):
        await handle_telegram_message(
            bot_token=BOT_TOKEN,
            message={"chat": {"id": int(CHAT_ID)}, "text": "/licht"},
            allowed_chat_ids={CHAT_ID},
            http_client=client,
        )
        mock_bambu_client.set_chamber_light.assert_called_with(True)


@pytest.mark.asyncio
async def test_stop_command_prompts_confirmation():
    client = _CaptureClient()
    fake_printer = type("Printer", (), {"id": 1, "name": "Bambu P1S"})()

    with patch("backend.app.services.telegram_bot_commands.resolve_target_printer", return_value=fake_printer):
        await handle_telegram_message(
            bot_token=BOT_TOKEN,
            message={"chat": {"id": int(CHAT_ID)}, "text": "/stop"},
            allowed_chat_ids={CHAT_ID},
            http_client=client,
        )
    send_msg = next(c for c in client.calls if c["url"].endswith("/sendMessage"))
    assert "wirklich abbrechen" in send_msg["json"]["text"]
    assert "cmd:stop_confirm:1" in send_msg["json"]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]


@pytest.mark.asyncio
async def test_callback_query_actions():
    client = _CaptureClient()
    mock_bambu_client = MagicMock()
    mock_bambu_client.state = type("State", (), {"chamber_light": False})()

    with patch("backend.app.services.printer_manager.printer_manager.get_client", return_value=mock_bambu_client):
        # Test cmd:light:1
        await handle_telegram_callback_query(
            bot_token=BOT_TOKEN,
            callback_query={
                "id": "q1",
                "data": "cmd:light:1",
                "message": {"chat": {"id": int(CHAT_ID)}, "message_id": 10},
            },
            allowed_chat_ids={CHAT_ID},
            http_client=client,
        )
        mock_bambu_client.set_chamber_light.assert_called_with(True)

        # Test cmd:stop_confirm:1
        await handle_telegram_callback_query(
            bot_token=BOT_TOKEN,
            callback_query={
                "id": "q2",
                "data": "cmd:stop_confirm:1",
                "message": {"chat": {"id": int(CHAT_ID)}, "message_id": 11},
            },
            allowed_chat_ids={CHAT_ID},
            http_client=client,
        )
        mock_bambu_client.stop_print.assert_called()
