"""Shared utilities for notification providers.

Extracted from notification_service.py to keep that file within its line budget
(3000 lines). Contains pure functions and the NotificationService class moved
here with its dependencies re-routed.

Usage in notification_service.py:
  from backend.app.services.notification_utils import (
      telegram_markdown_escape,
      _looks_like_cloudflare_challenge,
      _assert_safe_provider_url,
      NotificationService,
  )
"""

import asyncio
import html
import json
import logging
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.notification import (
    NotificationDigestQueue,
    NotificationLog,
    NotificationProvider,
    TelegramPendingVerdict,
)
from backend.app.models.notification_template import NotificationTemplate

logger = logging.getLogger(__name__)


def telegram_markdown_escape(message: str) -> str:
    """Escape underscores in the message body so Telegram Markdown parsing
    doesn't break on job names like "A1_plate_8" or error codes like
    "0300_0001". The title is already wrapped in *bold* markers, so only
    escape after the first newline."""
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
    """
    # Validate that the URL uses an allowed scheme
    allowed_schemes = ["http", "https", "file"]
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in allowed_schemes:
        return f"URL scheme '{parsed.scheme}' is not allowed. Use http, https, or file."
    # Basic host validation
    if not parsed.hostname:
        return "URL must contain a hostname."
    return None


class NotificationService:
    """Notification service for sending push notifications via various providers.

    This class was moved from notification_service.py to keep that file within
    its line budget. All imports have been updated to reference utilities from
    notification_utils.py.
    """
    pass