"""Model-provider interface + registry.

The shared seam for "import a model from a 3D model website". Providers
implement the interface (a ``ModelProvider`` descriptor + a per-request
``ProviderService`` transport) and register an instance here; the registry
routes pasted URLs to the owning provider via ``find_for_url``.
"""

from backend.app.services.model_providers.base import (
    ModelProvider,
    ProviderAuthConfig,
    ProviderAuthError,
    ProviderAuthType,
    ProviderDownload,
    ProviderDownloadInfo,
    ProviderError,
    ProviderForbiddenError,
    ProviderNotFoundError,
    ProviderResolvedModel,
    ProviderResourceRef,
    ProviderService,
    ProviderStatus,
    ProviderUnavailableError,
    ProviderUrlError,
)
from backend.app.services.model_providers.direct import direct_url_provider
from backend.app.services.model_providers.makerworld import makerworld_provider
from backend.app.services.model_providers.printables import printables_provider
from backend.app.services.model_providers.thingiverse import thingiverse_provider
from backend.app.services.model_providers.registry import ModelProviderRegistry, registry

registry.register(makerworld_provider)
registry.register(printables_provider)
registry.register(thingiverse_provider)
registry.register(direct_url_provider)

__all__ = [
    "ModelProvider",
    "ModelProviderRegistry",
    "ProviderAuthConfig",
    "ProviderAuthError",
    "ProviderAuthType",
    "ProviderDownload",
    "ProviderDownloadInfo",
    "ProviderError",
    "ProviderForbiddenError",
    "ProviderNotFoundError",
    "ProviderResolvedModel",
    "ProviderResourceRef",
    "ProviderService",
    "ProviderStatus",
    "ProviderUnavailableError",
    "ProviderUrlError",
    "direct_url_provider",
    "makerworld_provider",
    "printables_provider",
    "thingiverse_provider",
    "registry",
]
