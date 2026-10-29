"""Hilfsfunktionen der Meldungs-Kanäle, aus ``notification_service`` ausgelagert.

Reine Funktionen ohne Zustand: Telegram-Escaping, die Erkennung von
Cloudflare-Herausforderungen, die Prüfung von Kanal-Adressen aus der
Benutzerkonfiguration und das Beispielbild für Testmeldungen. Sie bleiben
dadurch unabhängig testbar und halten ``notification_service.py`` unter dem
Zeilenbudget (``test_file_size_budget.py``).
"""

import logging

import httpx

logger = logging.getLogger(__name__)


def telegram_markdown_escape(message: str) -> str:
    """Escape underscores in the message body so Telegram Markdown parsing
    doesn't break on job names like "A1_plate_8" or error codes like
    "0300_0001". The title is already wrapped in *bold* markers, so only
    escape after the first newline. Shared with the reaction poller, which
    re-sends the stored body when it edits the prompt (#3046)."""
    if "\n" in message:
        title_part, body_part = message.split("\n", 1)
        body_part = body_part.replace("_", "\\_")
        return f"{title_part}\n{body_part}"
    return message


def _looks_like_cloudflare_challenge(response: httpx.Response) -> bool:
    """Return True if ``response`` looks like a Cloudflare mitigation
    interstitial (JS challenge / managed challenge / block page) rather
    than a legitimate response passed through Cloudflare.

    Self-hosted servers behind Cloudflare (Tunnel, "Bot Fight Mode", or
    "Under Attack" mode) intercept non-browser clients at the edge and
    return a challenge HTML page instead of forwarding to the origin —
    so we never reach the user's actual ntfy / webhook backend.
    Cloudflare cannot be defeated from a Python client; the user has to
    add a security-skip rule on their side. We detect the shape so the
    UI can tell them that, instead of dumping the raw HTML.

    Detection deliberately does NOT rely on ``Server: cloudflare`` alone
    — Cloudflare adds that header to every response it proxies (success
    AND legitimate origin errors), so a real 401 "wrong token" from a
    CF-fronted ntfy would false-positive into a misleading "your CF is
    blocking" message. Reliable signals: the ``cf-mitigated`` header
    (set only when CF actively mitigates) and the challenge body shape.
    """
    if response.headers.get("cf-mitigated"):
        return True
    content_type = (response.headers.get("content-type") or "").lower()
    if "html" not in content_type:
        return False
    body = (response.text or "")[:1024].lower()
    # "Just a moment..." is Cloudflare's universal challenge-page title
    # (managed challenge, JS challenge, Under Attack mode). Combined with
    # an HTML content-type this is unambiguous — no legitimate ntfy or
    # webhook backend returns HTML with that title. ``cf-chl-*`` and
    # ``challenge-platform`` cover newer / non-default CF templates.
    return "just a moment" in body or "cf-chl-bypass" in body or "cf-chl-opt" in body or "challenge-platform" in body


def _assert_safe_provider_url(url: str, *, label: str) -> str | None:
    """Validate a provider URL taken from user-supplied config.

    Returns an error message on rejection, or None when the URL is
    acceptable — the ``_send_*`` methods return ``tuple[bool, str]`` rather
    than raising, so a message is more useful here than an exception.

    Uses the LAN-service policy: self-hosting ntfy, Bark, Gotify or a webhook
    receiver on the home LAN is normal and must keep working, so loopback and
    RFC-1918 stay permitted. Cloud-metadata endpoints, numeric-encoded IPs and
    non-HTTP schemes are rejected.
    """
    from backend.app.api.routes._url_safety import assert_safe_lan_service_url

    try:
        assert_safe_lan_service_url(url, label=label)
    except ValueError as exc:
        return str(exc)
    return None


def _opaque_http_failure(response: httpx.Response, *, label: str) -> str:
    """Failure message for a provider whose destination host the user supplies.

    The response body is deliberately **not** returned to the caller. Provider
    URLs are configurable by anyone holding ``NOTIFICATIONS_CREATE`` — which
    the default Operators group carries and which does not imply
    ``SETTINGS_UPDATE`` — and ``POST /notifications/test-config`` accepts a URL
    straight from the request body without persisting anything. Echoing the
    response body there turned an intended "does my webhook work?" check into
    an authenticated read primitive against any host the PrintLab process can
    reach, including services that are not exposed to the network at all.

    Providers whose host PrintLab hardcodes (Pushover, Telegram, CallMeBot)
    keep returning the upstream body — there is no trust boundary to cross
    when the destination cannot be influenced.

    The body is logged at debug level, where it stays available to whoever
    already administers the host without being handed back over the API.
    """
    logger.debug(
        "%s delivery failed with HTTP %s; body: %s",
        label,
        response.status_code,
        (response.text or "")[:200],
    )
    return f"HTTP {response.status_code} from the configured {label} (see server logs at debug level for details)"


_sample_notification_image: bytes | None = None
_sample_notification_image_loaded = False


def _load_sample_notification_image() -> bytes | None:
    """Render the bundled app screenshot as a small JPEG.

    Stands in for a real camera snapshot on Test Configuration / test-all,
    since there's no live print to capture one from. Cached after the first
    call so we're not re-reading and resizing the file on every click.
    """
    global _sample_notification_image, _sample_notification_image_loaded
    if _sample_notification_image_loaded:
        return _sample_notification_image
    _sample_notification_image_loaded = True
    try:
        from io import BytesIO

        from PIL import Image

        from backend.app.core.config import settings

        source_path = settings.static_dir / "img" / "screenshot-desktop.png"
        with Image.open(source_path) as img:
            resized = img.convert("RGB")
            resized.thumbnail((640, 640))
            buffer = BytesIO()
            resized.save(buffer, format="JPEG", quality=85)
            _sample_notification_image = buffer.getvalue()
    except Exception as e:
        logger.warning("Failed to build sample notification image: %s", e)
        _sample_notification_image = None
    return _sample_notification_image
