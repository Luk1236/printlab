"""Printables ModelProvider implementation."""

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
from backend.app.services.model_providers.printables.service import (
    ALLOWED_DOWNLOAD_HOSTS,
    PrintablesService,
)
from backend.app.services.model_providers.printables.url import (
    canonical_url,
    parse_url,
)

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession
    from backend.app.models.user import User


class PrintablesProvider(ModelProvider):
    """Provider descriptor and service factory for printables.com."""

    source_type = "printables"
    display_name = "Printables"
    host_patterns = ("printables.com", "www.printables.com")
    default_folder_name = "Printables"
    auth = ProviderAuthConfig(
        auth_type=ProviderAuthType.NONE,
        display_label="Printables",
        description="Öffentlicher Zugriff auf STL- und 3MF-Modelle ohne Login.",
    )
    view_permission = Permission.MAKERWORLD_VIEW
    import_permission = Permission.MAKERWORLD_IMPORT

    def thumbnail_hosts(self) -> tuple[str, ...]:
        return ("media.printables.com",)

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
        return PrintablesService(
            client=client,
            thumbnail_hosts=self.thumbnail_hosts(),
            download_hosts=self.download_hosts(),
        )


printables_provider = PrintablesProvider()
