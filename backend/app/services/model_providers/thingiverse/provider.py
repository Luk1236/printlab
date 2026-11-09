"""Thingiverse ModelProvider implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.app.core.permissions import Permission
from backend.app.services.model_providers.base import (
    ModelProvider,
    ProviderAuthConfig,
    ProviderAuthType,
    ProviderResourceRef,
    ProviderService,
)
from backend.app.services.model_providers.thingiverse.service import (
    ALLOWED_DOWNLOAD_HOSTS,
    ALLOWED_THUMBNAIL_HOSTS,
    ThingiverseService,
)
from backend.app.services.model_providers.thingiverse.url import (
    canonical_url,
    parse_url,
)

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.app.models.user import User


class ThingiverseProvider(ModelProvider):
    """Provider descriptor and service factory for thingiverse.com."""

    source_type = "thingiverse"
    display_name = "Thingiverse"
    host_patterns = ("thingiverse.com", "www.thingiverse.com")
    default_folder_name = "Thingiverse"
    auth = ProviderAuthConfig(
        auth_type=ProviderAuthType.NONE,
        display_label="Thingiverse",
        description="Öffentlicher Zugriff auf Thingiverse-Modelle ohne Login.",
    )
    view_permission = Permission.MAKERWORLD_VIEW
    import_permission = Permission.MAKERWORLD_IMPORT

    def thumbnail_hosts(self) -> tuple[str, ...]:
        return ALLOWED_THUMBNAIL_HOSTS

    def download_hosts(self) -> tuple[str, ...]:
        return ALLOWED_DOWNLOAD_HOSTS

    def parse_url(self, url: str) -> ProviderResourceRef:
        return parse_url(url)

    def canonical_url(self, ref: ProviderResourceRef) -> str:
        return canonical_url(ref)

    async def build_service(
        self,
        *,
        db: AsyncSession | None = None,
        user: User | None = None,
        api_key_owner: User | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> ProviderService:
        return ThingiverseService(
            client=client,
            thumbnail_hosts=self.thumbnail_hosts(),
            download_hosts=self.download_hosts(),
        )


thingiverse_provider = ThingiverseProvider()
