"""Thingiverse API service.

Async client for Thingiverse's public API (``https://api.thingiverse.com/``).
Resolves thing details, lists downloadable files (STL, 3MF, etc.), retrieves
direct download URLs from the Thingiverse CDN, and streams file bytes.
"""

from __future__ import annotations

import logging
import os
import re
import ssl
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

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
from backend.app.services.model_providers.thingiverse.errors import (
    ThingiverseAuthError,
    ThingiverseNotFoundError,
    ThingiverseUnavailableError,
    ThingiverseUrlError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

THINGIVERSE_API_BASE = "https://api.thingiverse.com"
THINGIVERSE_BUNDLE_URL = "https://cdn.thingiverse.com/site/js/app.bundle.js"

DEFAULT_THINGIVERSE_TOKEN = "56edfc79ecf25922b98202dd79a291aa"

ALLOWED_THUMBNAIL_HOSTS = (
    "cdn.thingiverse.com",
    "resize.thingiverse.com",
)
ALLOWED_DOWNLOAD_HOSTS = (
    "cdn.thingiverse.com",
    "thingiverse.com",
    "www.thingiverse.com",
)

_MAX_FILE_BYTES = 250 * 1024 * 1024  # 250 MB
_MAX_THUMBNAIL_BYTES = 10 * 1024 * 1024  # 10 MB

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.thingiverse.com/",
    "Accept": "application/json, text/plain, */*",
}


def _create_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    except Exception:
        pass
    return ctx


class ThingiverseService(ProviderService):
    """Client for Thingiverse model operations."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        auth_token: str | None = None,
        thumbnail_hosts: tuple[str, ...] = ALLOWED_THUMBNAIL_HOSTS,
        download_hosts: tuple[str, ...] = ALLOWED_DOWNLOAD_HOSTS,
    ) -> None:
        self._thumbnail_hosts = tuple(h.lower() for h in thumbnail_hosts)
        self._download_hosts = tuple(h.lower() for h in download_hosts)
        self._auth_token = auth_token or DEFAULT_THINGIVERSE_TOKEN

        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.AsyncClient(
                verify=_create_ssl_context(),
                headers=_HEADERS,
                timeout=30.0,
            )
            self._owns_client = True

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_status(self, db: AsyncSession) -> ProviderStatus:
        """Thingiverse requires no Bambu cloud login for resolving or downloading models."""
        return ProviderStatus(authenticated=True, can_download=True)

    async def _fetch_thing_data(self, thing_id: int) -> dict[str, Any]:
        """Fetch thing metadata from api.thingiverse.com, refreshing token if needed."""
        url = f"{THINGIVERSE_API_BASE}/things/{thing_id}"
        headers = dict(_HEADERS)
        headers["Authorization"] = f"Bearer {self._auth_token}"

        try:
            resp = await self._client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise ThingiverseUnavailableError(f"Thingiverse request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ThingiverseUnavailableError(f"Thingiverse request failed: {exc}") from exc

        # If token was rejected (401/403), attempt to refresh token from app.bundle.js
        if resp.status_code in (401, 403):
            refreshed = await self._refresh_token()
            if refreshed:
                headers["Authorization"] = f"Bearer {self._auth_token}"
                try:
                    resp = await self._client.get(url, headers=headers)
                except Exception as exc:
                    raise ThingiverseUnavailableError(f"Thingiverse retry failed: {exc}") from exc

        if resp.status_code == 404:
            raise ThingiverseNotFoundError(f"Thingiverse model not found: {thing_id}")
        if resp.status_code != 200:
            raise ThingiverseUnavailableError(f"Thingiverse API returned status {resp.status_code}")

        try:
            return resp.json()
        except ValueError as exc:
            raise ThingiverseUnavailableError("Thingiverse returned non-JSON response") from exc

    async def _refresh_token(self) -> bool:
        """Try to discover an updated token from the Thingiverse frontend bundle."""
        try:
            bundle_resp = await self._client.get(THINGIVERSE_BUNDLE_URL)
            if bundle_resp.status_code == 200:
                tokens = set(re.findall(r"([a-f0-9]{32})", bundle_resp.text))
                for candidate in tokens:
                    if candidate != self._auth_token:
                        self._auth_token = candidate
                        return True
        except Exception as exc:
            logger.debug("Failed to dynamically refresh Thingiverse token: %s", exc)
        return False

    async def resolve(self, ref: ProviderResourceRef) -> ProviderResolvedModel:
        """Resolve a Thingiverse model URL to metadata + files list."""
        thing_id = int(ref.external_id)
        data = await self._fetch_thing_data(thing_id)

        title = data.get("name") or f"Thingiverse #{thing_id}"
        summary = data.get("description_html") or data.get("description") or ""

        # Cover image
        cover_url = ""
        thumb_field = data.get("thumbnail")
        if isinstance(thumb_field, str) and thumb_field.strip():
            cover_url = thumb_field.strip()
        elif isinstance(data.get("default_image"), dict):
            cover_url = data["default_image"].get("url") or ""

        creator_name = (data.get("creator") or {}).get("name") or "Maker"
        download_count = data.get("download_count") or 0
        license_str = data.get("license") or "Creative Commons"

        # Files in zip_data
        zip_files = (data.get("zip_data") or {}).get("files") or []
        instances: list[dict[str, Any]] = []

        valid_exts = {".stl", ".3mf", ".step", ".stp", ".obj"}

        for idx, f in enumerate(zip_files):
            if not isinstance(f, dict):
                continue
            fname = f.get("name") or f"file-{idx}.stl"
            furl = f.get("url")
            if not furl:
                continue

            ext = os.path.splitext(fname)[1].lower()
            if ext and ext not in valid_exts and not fname.lower().endswith(".pdf"):
                # Still include other 3D or document files, but prioritize printable models
                pass

            file_id = idx + 1
            instances.append({
                "id": file_id,
                "profileId": file_id,
                "title": fname,
                "name": fname,
                "fileSize": f.get("size") or 0,
                "cover": cover_url,
                "instanceCreator": {"name": creator_name},
                "directUrl": furl,
            })

        design: dict[str, Any] = {
            "id": thing_id,
            "title": title,
            "summary": summary,
            "coverUrl": cover_url,
            "downloadCount": download_count,
            "license": license_str,
            "designCreator": {"name": creator_name},
            "sourceType": "thingiverse",
        }

        return ProviderResolvedModel(ref=ref, design=design, instances=instances)

    async def get_download(self, ref: ProviderResourceRef) -> ProviderDownloadInfo:
        """Resolve a direct download URL for a Thingiverse file."""
        resolved = await self.resolve(ref)
        instances = resolved.instances

        if not instances:
            raise ThingiverseNotFoundError("No downloadable files found for this Thingiverse model")

        target_file_id: int | None = int(ref.sub_id) if ref.sub_id else None
        target_instance: dict[str, Any] | None = None

        if target_file_id is not None:
            for inst in instances:
                if inst.get("id") == target_file_id or inst.get("profileId") == target_file_id:
                    target_instance = inst
                    break

        if target_instance is None:
            # Fall back to first STL or 3MF file if available, otherwise first instance
            stl_candidates = [
                inst for inst in instances
                if inst.get("name", "").lower().endswith((".stl", ".3mf", ".step", ".stp"))
            ]
            target_instance = stl_candidates[0] if stl_candidates else instances[0]

        direct_url = target_instance.get("directUrl")
        if not direct_url:
            raise ThingiverseNotFoundError("Thingiverse did not return a download URL for this file")

        filename = target_instance.get("name") or f"thingiverse-{ref.external_id}.stl"

        return ProviderDownloadInfo(
            ref=ref,
            url=direct_url,
            suggested_filename=filename,
        )

    async def download(self, info: ProviderDownloadInfo) -> ProviderDownload:
        """Stream file bytes from Thingiverse CDN."""
        parsed = urlparse(info.url)
        host = (parsed.hostname or "").lower()

        if not any(host == allowed.lower() or host.endswith(f".{allowed.lower()}") for allowed in self._download_hosts):
            raise ThingiverseUrlError(f"Host {host!r} is not in allowed Thingiverse download hosts")

        headers = dict(_HEADERS)

        try:
            async with self._client.stream("GET", info.url, headers=headers, timeout=60.0, follow_redirects=True) as resp:
                if resp.status_code == 404:
                    raise ThingiverseNotFoundError(f"File not found: {info.url}")
                if resp.status_code != 200:
                    raise ThingiverseUnavailableError(f"Download returned HTTP {resp.status_code}")

                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > _MAX_FILE_BYTES:
                        raise ThingiverseUnavailableError(
                            f"File exceeds maximum allowed size of {_MAX_FILE_BYTES // (1024 * 1024)} MB"
                        )
                    chunks.append(chunk)

                body = b"".join(chunks)
        except httpx.TimeoutException as exc:
            raise ThingiverseUnavailableError(f"Download timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ThingiverseUnavailableError(f"Download failed: {exc}") from exc

        return ProviderDownload(
            file_bytes=body,
            filename=info.suggested_filename,
        )

    async def fetch_thumbnail(self, url: str) -> tuple[bytes, str]:
        """Fetch a Thingiverse CDN image (thumbnail / cover)."""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host not in self._thumbnail_hosts:
            raise ThingiverseUrlError(f"Host {host!r} not in allowed thumbnail hosts: {self._thumbnail_hosts}")

        headers = dict(_HEADERS)

        try:
            resp = await self._client.get(url, headers=headers, timeout=15.0, follow_redirects=True)
        except httpx.TimeoutException as exc:
            raise ThingiverseUnavailableError(f"Thumbnail fetch timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ThingiverseUnavailableError(f"Thumbnail fetch failed: {exc}") from exc

        if resp.status_code == 404:
            raise ThingiverseNotFoundError("Thumbnail not found")
        if resp.status_code != 200:
            raise ThingiverseUnavailableError(f"Thumbnail fetch returned HTTP {resp.status_code}")

        content = resp.content
        if len(content) > _MAX_THUMBNAIL_BYTES:
            raise ThingiverseUnavailableError(
                f"Thumbnail exceeds maximum size of {_MAX_THUMBNAIL_BYTES // (1024 * 1024)} MB"
            )

        content_type = resp.headers.get("content-type") or "image/jpeg"
        return content, content_type
