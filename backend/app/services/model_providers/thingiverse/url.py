"""URL parsing and canonicalisation for Thingiverse models."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from backend.app.services.model_providers.base import ProviderResourceRef
from backend.app.services.model_providers.thingiverse.errors import ThingiverseUrlError

_ALLOWED_HOSTS = ("thingiverse.com", "www.thingiverse.com")

_THING_PATTERN = re.compile(
    r"""^/thing(?::|/)(\d+)""",
    re.IGNORECASE,
)


def parse_url(url: str) -> ProviderResourceRef:
    """Parse any Thingiverse design URL into a ProviderResourceRef.

    Accepts:
      - https://www.thingiverse.com/thing:763622
      - https://thingiverse.com/thing:763622/files
      - https://www.thingiverse.com/thing/763622
      - thingiverse.com/thing:763622
      - https://www.thingiverse.com/thing:763622#file-12345
    """
    raw = (url or "").strip()
    if not raw:
        raise ThingiverseUrlError("URL must not be empty")

    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"

    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise ThingiverseUrlError(f"Invalid URL: {exc}") from exc

    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise ThingiverseUrlError(f"Host {host!r} is not a supported Thingiverse domain")

    path = parsed.path or ""
    match = _THING_PATTERN.search(path)
    if not match:
        raise ThingiverseUrlError(f"URL path {path!r} does not contain a Thingiverse thing id (expected /thing:ID)")

    thing_id = match.group(1)

    sub_id: str | None = None
    if parsed.fragment:
        f_match = re.search(r"(?:file[-:])?(\d+)", parsed.fragment, re.IGNORECASE)
        if f_match:
            sub_id = f_match.group(1)

    return ProviderResourceRef(
        source_type="thingiverse",
        external_id=thing_id,
        sub_id=sub_id,
        original_url=url.strip(),
    )


def canonical_url(ref: ProviderResourceRef) -> str:
    """Return the canonical Thingiverse URL for a ref."""
    base = f"https://www.thingiverse.com/thing:{ref.external_id}"
    if ref.sub_id:
        return f"{base}#file-{ref.sub_id}"
    return base
