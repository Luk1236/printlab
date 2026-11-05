"""Tests for Direct file URL model provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from backend.app.services.model_providers.base import ProviderResourceRef
from backend.app.services.model_providers.direct.errors import (
    DirectUrlNotFoundError,
    DirectUrlUnavailableError,
    DirectUrlError,
)
from backend.app.services.model_providers.direct.provider import DirectUrlProvider
from backend.app.services.model_providers.direct.service import DirectUrlService
from backend.app.services.model_providers.direct.url import parse_url


class TestDirectUrl:
    def test_parse_url_3mf(self):
        ref = parse_url("https://example.com/files/dragon.3mf")
        assert ref.source_type == "direct"
        assert ref.original_url == "https://example.com/files/dragon.3mf"

    def test_parse_url_stl(self):
        ref = parse_url("http://cdn.example.org/models/test.stl")
        assert ref.source_type == "direct"
        assert ref.original_url == "http://cdn.example.org/models/test.stl"

    def test_parse_url_invalid(self):
        with pytest.raises(DirectUrlError):
            parse_url("https://example.com/not-a-model.html")


class TestDirectUrlService:
    @pytest.mark.asyncio
    async def test_resolve(self):
        svc = DirectUrlService()
        ref = ProviderResourceRef(
            source_type="direct",
            external_id="12345",
            original_url="https://example.com/files/fancy_dragon.3mf",
        )
        resolved = await svc.resolve(ref)
        assert resolved.design["title"] == "fancy_dragon.3mf"
        assert len(resolved.instances) == 1
        assert resolved.instances[0]["name"] == "fancy_dragon.3mf"

    @pytest.mark.asyncio
    async def test_download(self):
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        async def fake_aiter():
            yield b"fake 3mf content"

        mock_resp.aiter_bytes = fake_aiter

        class FakeStreamContext:
            async def __aenter__(self):
                return mock_resp

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_client.stream.return_value = FakeStreamContext()

        svc = DirectUrlService(client=mock_client)
        ref = ProviderResourceRef(
            source_type="direct",
            external_id="12345",
            original_url="https://example.com/files/fancy_dragon.3mf",
        )
        download_info = await svc.get_download(ref)
        dl = await svc.download(download_info)
        assert dl.file_bytes == b"fake 3mf content"
        assert dl.filename == "fancy_dragon.3mf"
