"""Tests for Thingiverse model provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.app.services.model_providers.base import ProviderResourceRef
from backend.app.services.model_providers.thingiverse.errors import (
    ThingiverseNotFoundError,
    ThingiverseUnavailableError,
    ThingiverseUrlError,
)
from backend.app.services.model_providers.thingiverse.provider import ThingiverseProvider
from backend.app.services.model_providers.thingiverse.service import ThingiverseService
from backend.app.services.model_providers.thingiverse.url import parse_url


class TestThingiverseUrl:
    def test_parse_url_standard(self):
        ref = parse_url("https://www.thingiverse.com/thing:763622")
        assert ref.external_id == "763622"
        assert ref.sub_id is None
        assert ref.source_type == "thingiverse"

    def test_parse_url_slash(self):
        ref = parse_url("https://thingiverse.com/thing/123456")
        assert ref.external_id == "123456"
        assert ref.sub_id is None

    def test_parse_url_with_fragment(self):
        ref = parse_url("https://www.thingiverse.com/thing:763622#file-42")
        assert ref.external_id == "763622"
        assert ref.sub_id == "42"

    def test_parse_url_no_scheme(self):
        ref = parse_url("thingiverse.com/thing:999")
        assert ref.external_id == "999"
        assert ref.sub_id is None

    def test_parse_url_invalid(self):
        with pytest.raises(ThingiverseUrlError):
            parse_url("https://printables.com/model/123")


class TestThingiverseService:
    @pytest.mark.asyncio
    async def test_resolve_success(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 763622,
            "name": "#3DBenchy",
            "description": "Benchy model",
            "thumbnail": "https://cdn.thingiverse.com/renders/benchy.jpg",
            "creator": {"name": "CreativeTools"},
            "download_count": 50000,
            "license": "Creative Commons - Public Domain",
            "zip_data": {
                "files": [
                    {
                        "name": "3DBenchy.stl",
                        "url": "https://cdn.thingiverse.com/assets/3DBenchy.stl",
                        "size": 11280000,
                    }
                ]
            },
        }
        mock_client.get.return_value = mock_resp

        svc = ThingiverseService(client=mock_client)
        ref = ProviderResourceRef(source_type="thingiverse", external_id="763622")
        resolved = await svc.resolve(ref)

        assert resolved.design["id"] == 763622
        assert resolved.design["title"] == "#3DBenchy"
        assert len(resolved.instances) == 1
        assert resolved.instances[0]["name"] == "3DBenchy.stl"
        assert resolved.instances[0]["directUrl"] == "https://cdn.thingiverse.com/assets/3DBenchy.stl"

    @pytest.mark.asyncio
    async def test_resolve_not_found(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client.get.return_value = mock_resp

        svc = ThingiverseService(client=mock_client)
        ref = ProviderResourceRef(source_type="thingiverse", external_id="99999999")
        with pytest.raises(ThingiverseNotFoundError):
            await svc.resolve(ref)

    @pytest.mark.asyncio
    async def test_download(self):
        mock_client = MagicMock(spec=httpx.AsyncClient)
        # Mock resolve get
        resolve_resp = MagicMock()
        resolve_resp.status_code = 200
        resolve_resp.json.return_value = {
            "id": 763622,
            "name": "#3DBenchy",
            "zip_data": {
                "files": [
                    {
                        "name": "3DBenchy.stl",
                        "url": "https://cdn.thingiverse.com/assets/3DBenchy.stl",
                    }
                ]
            },
        }

        async def fake_get(*args, **kwargs):
            return resolve_resp

        mock_client.get = fake_get

        # Mock download stream
        mock_stream_resp = MagicMock()
        mock_stream_resp.status_code = 200
        mock_stream_resp.headers = {"content-type": "application/octet-stream"}

        async def fake_aiter():
            yield b"solid fake_stl_content"

        mock_stream_resp.aiter_bytes = fake_aiter

        class FakeStreamContext:
            async def __aenter__(self):
                return mock_stream_resp

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_client.stream.return_value = FakeStreamContext()

        svc = ThingiverseService(client=mock_client)
        ref = ProviderResourceRef(source_type="thingiverse", external_id="763622", sub_id="1")
        download_info = await svc.get_download(ref)
        assert download_info.url == "https://cdn.thingiverse.com/assets/3DBenchy.stl"
        assert download_info.suggested_filename == "3DBenchy.stl"

        dl = await svc.download(download_info)
        assert dl.file_bytes == b"solid fake_stl_content"
        assert dl.filename == "3DBenchy.stl"
