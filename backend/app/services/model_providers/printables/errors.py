"""Printables provider error types."""

from backend.app.services.model_providers.base import (
    ProviderError,
    ProviderNotFoundError,
    ProviderUnavailableError,
    ProviderUrlError,
)


class PrintablesError(ProviderError):
    """Base error for Printables provider operations."""


class PrintablesUrlError(ProviderUrlError, PrintablesError):
    """Raised when a URL is not a valid Printables model URL."""


class PrintablesNotFoundError(ProviderNotFoundError, PrintablesError):
    """Raised when a Printables model or file cannot be found."""


class PrintablesUnavailableError(ProviderUnavailableError, PrintablesError):
    """Raised when the Printables API fails or is unreachable."""
