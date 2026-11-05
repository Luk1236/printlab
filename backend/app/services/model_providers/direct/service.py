"""Direct file URL service."""

from __future__ import annotations

import logging
import os
import ssl
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

import certifi
import httpx

from backend.app.services.model_providers.base import (
    ProviderDownload,
    ProviderDownloadInfo,
    ProviderResolvedModel,
    ProviderResourceRef,
    ProviderService,
    ProviderStatus,
)
from backend.app.services.model_providers.direct.errors import (
    DirectUrlNotFoundError,
    DirectUrlUnavailableError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 250 * 1024 * 1024


def _create_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    except Exception:
        pass
    return ctx


class DirectUrlService(ProviderService):
    """Client for downloading 3D files directly from URLs."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.AsyncClient(
                verify=_create_ssl_context(),
                headers={"User-Agent": "PrintLab/1.0 (+https://github.com/Luk1236/printlab)"},
                timeout=30.0,
            )
            self._owns_client = True

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_status(self, db: AsyncSession) -> ProviderStatus:
        return ProviderStatus(authenticated=True, can_download=True)

    async def resolve(self, ref: ProviderResourceRef) -> ProviderResolvedModel:
        url = ref.original_url or ""
        parsed = urlparse(url)
        raw_tail = parsed.path.rsplit("/", 1)[-1]
        filename = unquote(raw_tail) if raw_tail else f"model-{ref.external_id}.3mf"

        numeric_id = int(ref.external_id)

        instances = [
            {
                "id": numeric_id,
                "profileId": numeric_id,
                "title": filename,
                "name": filename,
                "cover": "",
                "fileType": os.path.splitext(filename)[1].lstrip("."),
                "fileSize": 0,
            }
        ]

        design: dict[str, Any] = {
            "id": numeric_id,
            "title": filename,
            "summary": f"Direkter Modell-Import von {parsed.netloc}",
            "coverUrl": "",
            "downloadCount": 1,
            "designCreator": {"name": parsed.netloc or "Web"},
            "sourceType": "direct",
        }

        return ProviderResolvedModel(ref=ref, design=design, instances=instances)

    async def get_download(self, ref: ProviderResourceRef) -> ProviderDownloadInfo:
        url = ref.original_url or ""
        parsed = urlparse(url)
        raw_tail = parsed.path.rsplit("/", 1)[-1]
        filename = unquote(raw_tail) if raw_tail else f"model-{ref.external_id}.3mf"

        return ProviderDownloadInfo(
            ref=ref,
            url=url,
            suggested_filename=filename,
        )

    async def download(self, info: ProviderDownloadInfo) -> ProviderDownload:
        try:
            async with self._client.stream("GET", info.url, timeout=60.0, follow_redirects=True) as resp:
                if resp.status_code == 404:
                    raise DirectUrlNotFoundError(f"File not found: {info.url}")
                if resp.status_code != 200:
                    raise DirectUrlUnavailableError(f"Download returned HTTP {resp.status_code}")

                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > _MAX_FILE_BYTES:
                        raise DirectUrlUnavailableError(f"File exceeds {_MAX_FILE_BYTES // (1024 * 1024)} MB cap")
                    chunks.append(chunk)

                return ProviderDownload(file_bytes=b"".join(chunks), filename=info.suggested_filename)
        except httpx.HTTPError as exc:
            raise DirectUrlUnavailableError(f"Download failed: {exc}") from exc

    async def fetch_thumbnail(self, url: str) -> tuple[bytes, str]:
        raise DirectUrlUnavailableError("Thumbnails not supported for direct URLs")
