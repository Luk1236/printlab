"""Outbound Webhooks Engine für PrintLab.

Ermöglicht das automatische Senden von Echtzeit-Ereignissen an externe Systeme
(Discord, Slack, Make, Zapier, Home Assistant, ERP-Systeme):
- print.started
- print.completed
- print.failed
- plate.swap_required
- plate.swap_done
- safety.emergency_stop
- maintenance.wear_alert

Mit kryptografischer HMAC-SHA256-Signaturprüfung (Header 'X-PrintLab-Signature').
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from typing import Any

import httpx

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

WEBHOOKS_FILE = settings.base_dir / "outbound_webhooks.json"
_lock = threading.Lock()

ALL_EVENTS = (
    "print.started",
    "print.completed",
    "print.failed",
    "plate.swap_required",
    "plate.swap_done",
    "safety.emergency_stop",
    "maintenance.wear_alert",
)


def _load_webhooks() -> list[dict[str, Any]]:
    if not WEBHOOKS_FILE.is_file():
        return []
    try:
        data = json.loads(WEBHOOKS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.debug("Konnte outbound_webhooks.json nicht lesen: %s", exc)
        return []


def _save_webhooks(webhooks: list[dict[str, Any]]) -> None:
    try:
        WEBHOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = WEBHOOKS_FILE.with_name(WEBHOOKS_FILE.name + ".tmp")
        tmp.write_text(json.dumps(webhooks, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(WEBHOOKS_FILE)
    except Exception as exc:
        logger.error("Fehler beim Speichern von outbound_webhooks.json: %s", exc)


def register_webhook(
    url: str,
    secret: str = "",
    events: list[str] | None = None,
    format_type: str = "generic",
    description: str = "",
) -> dict[str, Any]:
    """Registriert einen neuen ausgehenden Webhook."""
    with _lock:
        webhooks = _load_webhooks()
        hook = {
            "id": f"wh_{uuid.uuid4().hex[:12]}",
            "url": url.strip(),
            "secret": secret.strip(),
            "events": events if events is not None else ["*"],
            "format": format_type if format_type in ("generic", "discord", "slack") else "generic",
            "description": description.strip(),
            "enabled": True,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        webhooks.append(hook)
        _save_webhooks(webhooks)
        return hook


def list_webhooks() -> list[dict[str, Any]]:
    """Gibt alle registrierten Webhooks zurück."""
    with _lock:
        return _load_webhooks()


def delete_webhook(webhook_id: str) -> bool:
    """Entfernt einen registrierten Webhook anhand seiner ID."""
    with _lock:
        webhooks = _load_webhooks()
        orig_len = len(webhooks)
        webhooks = [w for w in webhooks if w.get("id") != webhook_id]
        if len(webhooks) < orig_len:
            _save_webhooks(webhooks)
            return True
        return False


def build_signature(secret: str, body_bytes: bytes) -> str:
    """Berechnet die HMAC-SHA256 Signatur für den Webhook-Payload."""
    if not secret:
        return ""
    mac = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def format_payload(format_type: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
    """Formatiert den Ereignis-Payload für das jeweilige Zielsystem (Generic, Discord oder Slack)."""
    title = f"PrintLab: {event}"
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    if format_type == "discord":
        color = (
            0x00AE42
            if "completed" in event or "done" in event
            else (0xEF4444 if "emergency" in event or "failed" in event else 0x3B82F6)
        )
        fields = [{"name": str(k), "value": str(v), "inline": True} for k, v in list(data.items())[:6]]
        return {
            "content": f"🚨 **PrintLab Ereignis: `{event}`**",
            "embeds": [
                {
                    "title": title,
                    "description": f"Zeitpunkt: {ts}",
                    "color": color,
                    "fields": fields,
                    "footer": {"text": "PrintLab v1.28 Outbound Engine"},
                }
            ],
        }

    elif format_type == "slack":
        return {
            "text": f"*{title}* ({ts})\n```\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```",
        }

    else:  # Generic JSON
        return {
            "event": event,
            "timestamp": ts,
            "data": data,
            "source": "PrintLab v1.28",
        }


def deliver_webhook_sync(hook: dict[str, Any], event: str, data: dict[str, Any]) -> bool:
    """Sendet den Webhook synchron mit Timeout ab."""
    url = hook.get("url")
    if not url or not hook.get("enabled", True):
        return False

    events = hook.get("events", ["*"])
    if "*" not in events and event not in events:
        return False

    formatted = format_payload(hook.get("format", "generic"), event, data)
    body = json.dumps(formatted, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "PrintLab-Webhooks/1.28.0",
        "X-PrintLab-Event": event,
        "X-PrintLab-Delivery": uuid.uuid4().hex,
    }

    secret = hook.get("secret", "")
    if secret:
        headers["X-PrintLab-Signature"] = build_signature(secret, body)

    try:
        with httpx.Client(timeout=4.0) as client:
            resp = client.post(url, content=body, headers=headers)
            logger.info("Webhook %s an %s gesendet (Status %s)", event, url, resp.status_code)
            return resp.status_code < 400
    except Exception as exc:
        logger.warning("Webhook-Zustellung fehlgeschlagen für %s: %s", url, exc)
        return False


def dispatch_event(event: str, data: dict[str, Any]) -> int:
    """Verteilt ein Ereignis an alle passenden registrierten Webhooks (im Hintergrund)."""
    hooks = list_webhooks()
    dispatched = 0
    for h in hooks:
        if h.get("enabled", True):
            # Sofortige synchrone oder threaded Zustellung
            t = threading.Thread(target=deliver_webhook_sync, args=(h, event, data), daemon=True)
            t.start()
            dispatched += 1
    return dispatched
