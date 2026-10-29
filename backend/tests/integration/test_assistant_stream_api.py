"""Integration-Tests für /assistant/chat-stream (SSE): Deltas, Abschluss, Fehler, Sperre."""

import json

import pytest
from httpx import AsyncClient

from backend.app.api.routes import assistant as assistant_route
from backend.app.services import assistant_config, assistant_llm


@pytest.fixture(autouse=True)
def enabled_config(tmp_path, monkeypatch):
    config = {
        "enabled": True,
        "base_url": "http://127.0.0.1:11434",
        "model": "test-model",
        "timeout_seconds": 30,
        "max_tokens": 200,
    }
    monkeypatch.setattr(assistant_config, "read", lambda base_dir: config)
    return config


def _fake_stream(pieces):
    async def _gen(config, messages, transport=None):
        for piece in pieces:
            yield piece

    return _gen


def _parse_events(content: bytes) -> list[dict]:
    events = []
    for frame in content.decode("utf-8").split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


class TestAssistantStreamAPI:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_deltas_and_done_event(self, async_client: AsyncClient, monkeypatch):
        pieces = ["Der ", "Drucker", " ist frei.\nACTIONS:"]  # Aktionsteil bleibt im Live-Text weg
        monkeypatch.setattr(assistant_llm, "chat_stream", _fake_stream(pieces))
        monkeypatch.setattr(assistant_route.assistant_llm, "chat_stream", _fake_stream(pieces))
        response = await async_client.post(
            "/api/v1/assistant/chat-stream", json={"messages": [{"role": "user", "content": "Was läuft?"}]}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_events(response.content)
        deltas = [e["text"] for e in events if e["type"] == "delta"]
        joined = "".join(deltas)
        assert joined == "Der Drucker ist frei.\n" and "ACTION" not in joined
        done = [e for e in events if e["type"] == "done"]
        assert done and done[0]["reply"].strip() == "Der Drucker ist frei."
        assert "actions" in done[0] and "rejected" in done[0] and "seconds" in done[0]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_split_marker_is_never_streamed(self, async_client: AsyncClient, monkeypatch):
        pieces = ["Erste ", "ACT", "IONS: set_priority item 1 urgent"]  # Marker über zwei Deltas verteilt
        monkeypatch.setattr(assistant_route.assistant_llm, "chat_stream", _fake_stream(pieces))
        response = await async_client.post(
            "/api/v1/assistant/chat-stream", json={"messages": [{"role": "user", "content": "?"}]}
        )
        events = _parse_events(response.content)
        joined = "".join(e.get("text", "") for e in events if e["type"] == "delta")
        assert "ACTIONS" not in joined and joined == "Erste "
        done = [e for e in events if e["type"] == "done"]
        assert done and "actions" in done[0]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_model_error_arrives_as_event(self, async_client: AsyncClient, monkeypatch):
        async def _boom(config, messages, transport=None):
            raise assistant_llm.AssistantError(
                "Kein Modell-Server unter http://127.0.0.1:11434 erreichbar. Läuft Ollama?"
            )
            yield  # noqa: unreachable - Generator-Typ

        monkeypatch.setattr(assistant_route.assistant_llm, "chat_stream", _boom)
        response = await async_client.post(
            "/api/v1/assistant/chat-stream", json={"messages": [{"role": "user", "content": "?"}]}
        )
        assert response.status_code == 200
        events = _parse_events(response.content)
        assert events and events[-1]["type"] == "error"
        assert "Läuft Ollama" in events[-1]["detail"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_disabled_assistant_is_409(self, async_client: AsyncClient, monkeypatch):
        monkeypatch.setattr(
            assistant_config,
            "read",
            lambda base_dir: {"enabled": False, "base_url": "x", "model": "m", "timeout_seconds": 10, "max_tokens": 50},
        )
        response = await async_client.post(
            "/api/v1/assistant/chat-stream", json={"messages": [{"role": "user", "content": "?"}]}
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_locked_assistant_is_429(self, async_client: AsyncClient):
        await assistant_llm.LOCK.acquire()
        try:
            response = await async_client.post(
                "/api/v1/assistant/chat-stream", json={"messages": [{"role": "user", "content": "?"}]}
            )
            assert response.status_code == 429
        finally:
            assistant_llm.LOCK.release()
