"""Direct URL parsing and canonicalisation."""

from __future__ import annotations

from urllib.parse import urlparse

from backend.app.services.model_providers.base import ProviderResourceRef
from backend.app.services.model_providers.direct.errors import DirectUrlInvalidError

SUPPORTED_EXTENSIONS = (".3mf", ".stl", ".step", ".stp")


def supports_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    candidate = url.strip()
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        parsed = urlparse(candidate)
    except Exception:
        return False
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in SUPPORTED_EXTENSIONS)


def parse_url(url: str) -> ProviderResourceRef:
    if not url or not isinstance(url, str):
        raise DirectUrlInvalidError("URL is empty or not a string")
    candidate = url.strip()
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        parsed = urlparse(candidate)
    except Exception as exc:
        raise DirectUrlInvalidError(f"Could not parse URL: {exc}") from exc

    path = parsed.path.lower()
    if not any(path.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        raise DirectUrlInvalidError(f"URL must point to a supported 3D file ({', '.join(SUPPORTED_EXTENSIONS)})")

    # Generate stable positive integer ID from the URL for route compatibility
    numeric_id = abs(hash(candidate)) % 1_000_000_000

    return ProviderResourceRef(
        source_type="direct",
        external_id=str(numeric_id),
        sub_id=None,
        original_url=candidate,
    )


def canonical_url(ref: ProviderResourceRef) -> str:
    return ref.original_url or f"direct://{ref.external_id}"
