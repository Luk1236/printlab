"""Tests für die automatische Erkennung und Vorladung des lokalen KI-Assistenten."""

from pathlib import Path

import httpx
import pytest

from backend.app.services import assistant_autoconfig


def test_pick_model_prefers_small_fast_models():
    models = ["llama3:70b", "gemma4:12b", "qwen3.5:4b", "nomic-embed-text"]
    assert assistant_autoconfig.pick_model(models) == "qwen3.5:4b"


def test_pick_model_keeps_current_if_present():
    models = ["qwen3.5:4b", "llama3.2:3b", "gemma4:12b"]
    assert assistant_autoconfig.pick_model(models, current="gemma4:12b") == "gemma4:12b"


def test_pick_model_skips_embedding_models():
    models = ["nomic-embed-text", "bge-m3", "snowflake-arctic-embed"]
    assert assistant_autoconfig.pick_model(models) is None


def test_pick_model_empty_list():
    assert assistant_autoconfig.pick_model([]) is None


def test_pick_model_fallback_to_smallest():
    models = ["unknown-custom:7b", "unknown-custom:1.5b", "unknown-custom:14b"]
    assert assistant_autoconfig.pick_model(models) == "unknown-custom:1.5b"


def test_pick_vision_model():
    models = ["qwen3.5:4b", "qwen2.5vl:3b", "nomic-embed-text"]
    assert assistant_autoconfig.pick_vision_model(models) == "qwen2.5vl:3b"

    models_no_vision = ["qwen3.5:4b", "llama3.2:3b"]
    assert assistant_autoconfig.pick_vision_model(models_no_vision) == ""


@pytest.mark.asyncio
async def test_autoconfigure_ready(tmp_path: Path):
    async def mock_status(_cfg):
        return {
            "reachable": True,
            "models": ["qwen3.5:4b", "qwen2.5vl:3b"],
            "model_present": True,
            "error": "",
        }

    res = await assistant_autoconfig.autoconfigure(tmp_path, status_fn=mock_status)
    assert res["state"] == "ready"
    assert res["model"] == "qwen3.5:4b"
    assert res["config"]["enabled"] is True
    assert res["config"]["vision_model"] == "qwen2.5vl:3b"


@pytest.mark.asyncio
async def test_autoconfigure_no_server(tmp_path: Path):
    async def mock_status_down(_cfg):
        return {"reachable": False, "models": [], "model_present": False, "error": "down"}

    res = await assistant_autoconfig.autoconfigure(tmp_path, status_fn=mock_status_down)
    assert res["state"] == "no_server"
    assert res["changed"] is False


@pytest.mark.asyncio
async def test_autoconfigure_no_model(tmp_path: Path):
    async def mock_status_no_model(_cfg):
        return {"reachable": True, "models": ["nomic-embed-text"], "model_present": False, "error": ""}

    res = await assistant_autoconfig.autoconfigure(tmp_path, status_fn=mock_status_no_model)
    assert res["state"] == "no_model"


@pytest.mark.asyncio
async def test_warmup_success():
    def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        return httpx.Response(200, json={"done": True})

    transport = httpx.MockTransport(handle_request)
    cfg = {"base_url": "http://127.0.0.1:11434", "model": "qwen3.5:4b", "timeout_seconds": 5}
    ok = await assistant_autoconfig.warmup(cfg, transport=transport)
    assert ok is True


@pytest.mark.asyncio
async def test_warmup_handles_failure():
    def handle_request(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "failed"})

    transport = httpx.MockTransport(handle_request)
    cfg = {"base_url": "http://127.0.0.1:11434", "model": "qwen3.5:4b", "timeout_seconds": 5}
    ok = await assistant_autoconfig.warmup(cfg, transport=transport)
    assert ok is False
