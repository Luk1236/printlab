"""Printables API service.

Async client for Printables' GraphQL endpoint (``https://api.printables.com/graphql/``).
Resolves model details, lists downloadable files (STL, 3MF, etc.), retrieves
direct download URLs, and streams file bytes.
"""

from __future__ import annotations

import logging
import ssl
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from backend.app.services.model_providers.base import (
    ProviderDownload,
    ProviderDownloadInfo,
    ProviderResolvedModel,
    ProviderResourceRef,
    ProviderService,
    ProviderStatus,
)
from backend.app.services.model_providers.printables.errors import (
    PrintablesNotFoundError,
    PrintablesUnavailableError,
    PrintablesUrlError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

PRINTABLES_GRAPHQL = "https://api.printables.com/graphql/"
PRINTABLES_MEDIA_BASE = "https://media.printables.com/"
ALLOWED_DOWNLOAD_HOSTS = ("files.printables.com", "media.printables.com")

_MAX_FILE_BYTES = 250 * 1024 * 1024  # 250 MB
_MAX_THUMBNAIL_BYTES = 10 * 1024 * 1024

_HEADERS = {
    "User-Agent": "PrintLab/1.0 (+https://github.com/Luk1236/printlab)",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _create_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    except Exception:
        logger.debug("Fehler ignoriert", exc_info=True)
    return ctx


class PrintablesService(ProviderService):
    """Client for Printables model operations."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        thumbnail_hosts: tuple[str, ...] = ("media.printables.com",),
        download_hosts: tuple[str, ...] = ALLOWED_DOWNLOAD_HOSTS,
    ) -> None:
        self._thumbnail_hosts = tuple(h.lower() for h in thumbnail_hosts)
        self._download_hosts = tuple(h.lower() for h in download_hosts)

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
        """Printables requires no login for resolving or downloading models."""
        return ProviderStatus(authenticated=True, can_download=True)

    async def resolve(self, ref: ProviderResourceRef) -> ProviderResolvedModel:
        """Resolve a Printables model URL to metadata + files list."""
        model_id = int(ref.external_id)

        query = """
        query GetPrintDetails($id: ID!) {
          print(id: $id) {
            id
            name
            slug
            summary
            description
            downloadCount
            likesCount
            images {
              filePath
            }
            user {
              id
              publicUsername
            }
            stls {
              id
              name
              fileSize
            }
            otherFiles {
              id
              name
              fileSize
            }
            gcodes {
              id
              name
              fileSize
            }
          }
        }
        """

        try:
            resp = await self._client.post(
                PRINTABLES_GRAPHQL,
                json={"operationName": "GetPrintDetails", "query": query, "variables": {"id": str(model_id)}},
            )
        except httpx.TimeoutException as exc:
            raise PrintablesUnavailableError(f"Printables request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise PrintablesUnavailableError(f"Printables request failed: {exc}") from exc

        if resp.status_code == 404:
            raise PrintablesNotFoundError(f"Printables model not found: {model_id}")
        if resp.status_code != 200:
            raise PrintablesUnavailableError(f"Printables API returned status {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise PrintablesUnavailableError("Printables API returned non-JSON response") from exc

        print_obj = (data.get("data") or {}).get("print")
        if not print_obj or not isinstance(print_obj, dict):
            raise PrintablesNotFoundError(f"Printables model not found: {model_id}")

        images = print_obj.get("images") or []
        cover_url = ""
        if images and isinstance(images, list) and isinstance(images[0], dict):
            fp = images[0].get("filePath")
            if fp:
                cover_url = f"{PRINTABLES_MEDIA_BASE}{fp}"

        user_name = (print_obj.get("user") or {}).get("publicUsername") or "Unknown"

        # Combine all downloadable files into instances
        instances: list[dict[str, Any]] = []

        all_file_groups = [
            ("stls", print_obj.get("stls")),
            ("otherFiles", print_obj.get("otherFiles")),
            ("gcodes", print_obj.get("gcodes")),
        ]

        for group_name, files in all_file_groups:
            if not isinstance(files, list):
                continue
            for f in files:
                if not isinstance(f, dict):
                    continue
                fid = f.get("id")
                fname = f.get("name") or f"model-{fid}.stl"
                if fid is None:
                    continue
                try:
                    num_fid = int(fid)
                except (ValueError, TypeError):
                    continue

                instances.append(
                    {
                        "id": num_fid,
                        "profileId": num_fid,
                        "title": fname,
                        "name": fname,
                        "fileSize": f.get("fileSize") or 0,
                        "cover": cover_url,
                        "instanceCreator": {"name": user_name},
                        "group": group_name,
                    }
                )

        design: dict[str, Any] = {
            "id": model_id,
            "title": print_obj.get("name") or f"Printables #{model_id}",
            "summary": print_obj.get("summary") or print_obj.get("description") or "",
            "coverUrl": cover_url,
            "downloadCount": print_obj.get("downloadCount") or 0,
            "designCreator": {"name": user_name},
            "sourceType": "printables",
        }

        return ProviderResolvedModel(ref=ref, design=design, instances=instances)

    async def get_download(self, ref: ProviderResourceRef) -> ProviderDownloadInfo:
        """Resolve a direct download URL for a Printables file."""
        model_id = int(ref.external_id)
        resolved = await self.resolve(ref)
        instances = resolved.instances

        if not instances:
            raise PrintablesNotFoundError("No downloadable files found for this model")

        target_file_id: int | None = int(ref.sub_id) if ref.sub_id else None
        target_instance: dict[str, Any] | None = None

        if target_file_id is not None:
            for inst in instances:
                if inst.get("id") == target_file_id or inst.get("profileId") == target_file_id:
                    target_instance = inst
                    break

        if target_instance is None:
            target_instance = instances[0]
            target_file_id = target_instance.get("id")

        filename = target_instance.get("name") or f"printables-{model_id}.stl"
        lower_name = filename.lower()
        if lower_name.endswith(".stl"):
            file_type = "stl"
        elif lower_name.endswith(".gcode"):
            file_type = "gcode"
        else:
            file_type = "other"

        mutation = """
        mutation GetDownloadLink($id: ID!, $modelId: ID!, $fileType: DownloadFileTypeEnum!, $source: DownloadSourceEnum!) {
          getDownloadLink(id: $id, printId: $modelId, fileType: $fileType, source: $source) {
            ok
            output {
              link
            }
          }
        }
        """

        try:
            mut_resp = await self._client.post(
                PRINTABLES_GRAPHQL,
                json={
                    "operationName": "GetDownloadLink",
                    "query": mutation,
                    "variables": {
                        "id": str(target_file_id),
                        "modelId": str(model_id),
                        "fileType": file_type,
                        "source": "model_detail",
                    },
                },
            )
        except httpx.HTTPError as exc:
            raise PrintablesUnavailableError(f"Printables download request failed: {exc}") from exc

        if mut_resp.status_code != 200:
            raise PrintablesUnavailableError(f"Printables download returned HTTP {mut_resp.status_code}")

        try:
            mut_data = mut_resp.json()
        except ValueError as exc:
            raise PrintablesUnavailableError("Printables returned invalid JSON for download link") from exc

        link = ((mut_data.get("data") or {}).get("getDownloadLink") or {}).get("output", {}).get("link")

        if not link or not isinstance(link, str):
            raise PrintablesUnavailableError("Printables did not return a valid download link")

        return ProviderDownloadInfo(
            ref=replace(ref, sub_id=str(target_file_id)),
            url=link,
            suggested_filename=filename,
        )

    async def download(self, info: ProviderDownloadInfo) -> ProviderDownload:
        """Download file bytes from Printables CDN URL."""
        try:
            parsed = urlparse(info.url)
        except ValueError as exc:
            raise PrintablesUrlError(f"Invalid download URL: {exc}") from exc

        host = (parsed.hostname or "").lower()
        if host not in self._download_hosts:
            raise PrintablesUrlError(f"Refusing download from non-Printables host: {host!r}")

        path_tail = parsed.path.rsplit("/", 1)[-1] or info.suggested_filename

        try:
            async with self._client.stream("GET", info.url, timeout=60.0, follow_redirects=True) as resp:
                if resp.status_code != 200:
                    raise PrintablesUnavailableError(f"File download returned HTTP {resp.status_code}")

                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > _MAX_FILE_BYTES:
                        raise PrintablesUnavailableError(f"File exceeds {_MAX_FILE_BYTES // (1024 * 1024)} MB cap")
                    chunks.append(chunk)

                return ProviderDownload(file_bytes=b"".join(chunks), filename=path_tail)
        except httpx.TimeoutException as exc:
            raise PrintablesUnavailableError(f"File download timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise PrintablesUnavailableError(f"File download failed: {exc}") from exc

    async def fetch_thumbnail(self, url: str) -> tuple[bytes, str]:
        """Fetch thumbnail from Printables media CDN."""
        try:
            parsed = urlparse(url)
        except ValueError as exc:
            raise PrintablesUrlError(f"Invalid thumbnail URL: {exc}") from exc

        host = (parsed.hostname or "").lower()
        if host not in self._thumbnail_hosts:
            raise PrintablesUrlError(f"Refusing thumbnail from non-Printables host: {host!r}")

        try:
            resp = await self._client.get(url, timeout=20.0, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise PrintablesUnavailableError(f"Thumbnail request failed: {exc}") from exc

        if resp.status_code != 200:
            raise PrintablesUnavailableError(f"Thumbnail fetch returned HTTP {resp.status_code}")

        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        payload = resp.content
        if len(payload) > _MAX_THUMBNAIL_BYTES:
            raise PrintablesUnavailableError(f"Thumbnail exceeds {_MAX_THUMBNAIL_BYTES // (1024 * 1024)} MB cap")

        return payload, content_type
