"""Direct file URL provider errors."""

from backend.app.services.model_providers.base import (
    ProviderError,
    ProviderNotFoundError,
    ProviderUnavailableError,
    ProviderUrlError,
)


class DirectUrlError(ProviderError):
    """Base error for direct URL operations."""


class DirectUrlInvalidError(ProviderUrlError, DirectUrlError):
    """Raised when a direct URL is invalid."""


class DirectUrlNotFoundError(ProviderNotFoundError, DirectUrlError):
    """Raised when the target file returns 404."""


class DirectUrlUnavailableError(ProviderUnavailableError, DirectUrlError):
    """Raised when downloading from direct URL fails."""
