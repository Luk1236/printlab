"""Direct file URL ModelProvider implementation."""

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
from backend.app.services.model_providers.direct.service import DirectUrlService
from backend.app.services.model_providers.direct.url import (
    canonical_url,
    parse_url,
    supports_url,
)

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.app.models.user import User


class DirectUrlProvider(ModelProvider):
    """Provider descriptor and service factory for direct 3D file URLs."""

    source_type = "direct"
    display_name = "Direkt-URL"
    default_folder_name = "Downloads"
    auth = ProviderAuthConfig(
        auth_type=ProviderAuthType.NONE,
        display_label="Direkt-URL",
        description="Direkter Download von .3mf-, .stl- oder .step-Dateien.",
    )
    view_permission = Permission.MAKERWORLD_VIEW
    import_permission = Permission.MAKERWORLD_IMPORT

    def thumbnail_hosts(self) -> tuple[str, ...]:
        return ()

    def download_hosts(self) -> tuple[str, ...]:
        return ()

    def supports_url(self, url: str) -> bool:
        return supports_url(url)

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
        return DirectUrlService(client=client)


direct_url_provider = DirectUrlProvider()
