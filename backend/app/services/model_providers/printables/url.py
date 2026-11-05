"""Printables URL parsing and canonicalisation."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from backend.app.services.model_providers.base import ProviderResourceRef
from backend.app.services.model_providers.printables.errors import PrintablesUrlError

PRINTABLES_HOST = "printables.com"

_MODEL_ID_RE = re.compile(r"/model/(\d+)")
_FILE_ID_RE = re.compile(r"#(?:file[-=]|id[-=])?(\d+)")


def parse_url(url: str) -> ProviderResourceRef:
    """Extract a :class:`ProviderResourceRef` from a Printables URL."""
    if not url or not isinstance(url, str):
        raise PrintablesUrlError("URL is empty or not a string")
    candidate = url.strip()
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise PrintablesUrlError(f"Could not parse URL: {exc}") from exc

    host = (parsed.hostname or "").lower()
    if host != PRINTABLES_HOST and not host.endswith("." + PRINTABLES_HOST):
        raise PrintablesUrlError(f"Not a Printables URL (host={host!r}); expected printables.com")

    model_match = _MODEL_ID_RE.search(parsed.path)
    if not model_match:
        raise PrintablesUrlError("URL does not contain a /model/{id} segment")
    model_id = int(model_match.group(1))

    file_id: int | None = None
    if parsed.fragment:
        file_match = _FILE_ID_RE.search("#" + parsed.fragment)
        if file_match:
            file_id = int(file_match.group(1))

    return ProviderResourceRef(
        source_type="printables",
        external_id=str(model_id),
        sub_id=str(file_id) if file_id is not None else None,
        original_url=url,
    )


def canonical_url(ref: ProviderResourceRef) -> str:
    """Build a stable dedupe key for a Printables resource."""
    if ref.sub_id:
        return f"https://www.printables.com/model/{ref.external_id}#file-{ref.sub_id}"
    return f"https://www.printables.com/model/{ref.external_id}"
