"""Thingiverse provider exception classes."""

from __future__ import annotations

from backend.app.services.model_providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderForbiddenError,
    ProviderNotFoundError,
    ProviderUnavailableError,
    ProviderUrlError,
)

__all__ = [
    "ThingiverseAuthError",
    "ThingiverseError",
    "ThingiverseForbiddenError",
    "ThingiverseNotFoundError",
    "ThingiverseUnavailableError",
    "ThingiverseUrlError",
]


class ThingiverseError(ProviderError):
    """Base exception for all Thingiverse-specific errors."""


class ThingiverseUrlError(ProviderUrlError, ThingiverseError):
    """Raised when an input URL is not a valid Thingiverse model URL."""


class ThingiverseAuthError(ProviderAuthError, ThingiverseError):
    """Raised when Thingiverse API refuses access."""


class ThingiverseForbiddenError(ProviderForbiddenError, ThingiverseError):
    """Raised when Thingiverse denies access."""


class ThingiverseNotFoundError(ProviderNotFoundError, ThingiverseError):
    """Raised when a Thingiverse design or file cannot be found."""


class ThingiverseUnavailableError(ProviderUnavailableError, ThingiverseError):
    """Raised on upstream connection or HTTP errors from Thingiverse."""
