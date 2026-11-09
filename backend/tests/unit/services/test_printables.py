"""Tests for Printables model provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.app.services.model_providers.base import ProviderResourceRef
from backend.app.services.model_providers.printables.errors import (
    PrintablesNotFoundError,
    PrintablesUnavailableError,
    PrintablesUrlError,
)
from backend.app.services.model_providers.printables.provider import PrintablesProvider
from backend.app.services.model_providers.printables.service import PrintablesService
from backend.app.services.model_providers.printables.url import parse_url


class TestPrintablesUrl:
    def test_parse_url_standard(self):
        ref = parse_url("https://www.printables.com/model/3161-3d-benchy")
        assert ref.external_id == "3161"
        assert ref.sub_id is None
        assert ref.source_type == "printables"

    def test_parse_url_with_fragment(self):
        ref = parse_url("https://www.printables.com/model/3161-3d-benchy#file-54321")
        assert ref.external_id == "3161"
        assert ref.sub_id == "54321"

    def test_parse_url_no_scheme(self):
        ref = parse_url("printables.com/model/12345")
        assert ref.external_id == "12345"
        assert ref.sub_id is None

    def test_parse_url_invalid(self):
        with pytest.raises(PrintablesUrlError):
            parse_url("https://makerworld.com/models/123")


class TestPrintablesService:
    @pytest.mark.asyncio
    async def test_resolve_success(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "print": {
                    "id": "3161",
                    "name": "3D Benchy",
                    "slug": "3d-benchy",
                    "summary": "The jolly 3D printing torture-test",
                    "description": "Full description",
                    "downloadCount": 42000,
                    "likesCount": 15000,
                    "images": [{"filePath": "prints/3161/images/benchy.jpg"}],
                    "user": {"id": "1", "publicUsername": "CreativeTools"},
                    "stls": [{"id": "101", "name": "3DBenchy.stl", "fileSize": 11280000}],
                    "otherFiles": [],
                    "gcodes": [],
                }
            }
        }
        mock_client.post.return_value = mock_resp

        svc = PrintablesService(client=mock_client)
        ref = ProviderResourceRef(source_type="printables", external_id="3161")
        resolved = await svc.resolve(ref)

        assert resolved.design["id"] == 3161
        assert resolved.design["title"] == "3D Benchy"
        assert len(resolved.instances) == 1
        assert resolved.instances[0]["id"] == 101
        assert resolved.instances[0]["name"] == "3DBenchy.stl"

    @pytest.mark.asyncio
    async def test_resolve_not_found(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client.post.return_value = mock_resp

        svc = PrintablesService(client=mock_client)
        ref = ProviderResourceRef(source_type="printables", external_id="9999999")
        with pytest.raises(PrintablesNotFoundError):
            await svc.resolve(ref)

    @pytest.mark.asyncio
    async def test_get_download_link_mutation(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        # Mock resolve response
        resolve_resp = MagicMock()
        resolve_resp.status_code = 200
        resolve_resp.json.return_value = {
            "data": {
                "print": {
                    "id": "3161",
                    "name": "3D Benchy",
                    "images": [],
                    "user": {"publicUsername": "CreativeTools"},
                    "stls": [{"id": "101", "name": "3DBenchy.stl", "fileSize": 11280000}],
                    "otherFiles": [],
                    "gcodes": [],
                }
            }
        }
        # Mock download mutation response
        mut_resp = MagicMock()
        mut_resp.status_code = 200
        mut_resp.json.return_value = {
            "data": {
                "getDownloadLink": {
                    "ok": True,
                    "output": {"link": "https://files.printables.com/signed/3DBenchy.stl"},
                }
            }
        }
        mock_client.post.side_effect = [resolve_resp, mut_resp]

        svc = PrintablesService(client=mock_client)
        ref = ProviderResourceRef(source_type="printables", external_id="3161", sub_id="101")
        download_info = await svc.get_download(ref)

        assert download_info.url == "https://files.printables.com/signed/3DBenchy.stl"
        assert download_info.suggested_filename == "3DBenchy.stl"
