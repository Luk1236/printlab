"""Outbound Webhooks API für PrintLab.

Verwaltung ausgehender Webhook-Registrierungen für Discord, Slack, Home Assistant
und externe ERP-/Automatisierungssysteme mit SSRF-Schutz und HMAC-SHA256 Signatur.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.outbound_webhooks import (
    ALL_EVENTS,
    delete_webhook,
    dispatch_event,
    list_webhooks,
    mask_webhook,
    register_webhook,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/outbound", tags=["webhooks"])


class WebhookCreateRequest(BaseModel):
    url: str = Field(..., description="Ziel-URL des Webhook-Empfängers")
    secret: str = Field("", description="Geheimschlüssel für die HMAC-SHA256 Signatur")
    events: list[str] = Field(default_factory=lambda: ["*"], description="Abonnierte Ereignisse")
    format_type: str = Field("generic", description="Format: generic, discord oder slack")
    description: str = Field("", description="Optionale Beschreibung des Endpunkts")


class WebhookTestRequest(BaseModel):
    event: str = Field("print.started", description="Zu testendes Ereignis")
    data: dict[str, Any] = Field(default_factory=dict, description="Test-Payload")


@router.get("")
async def get_all_webhooks(
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
) -> list[dict[str, Any]]:
    """Liefert alle registrierten ausgehenden Webhooks."""
    return list_webhooks()


@router.post("")
async def create_outbound_webhook(
    req: WebhookCreateRequest,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
) -> dict[str, Any]:
    """Registriert einen neuen ausgehenden Webhook mit SSRF-Validierung."""
    try:
        hook = register_webhook(
            url=req.url,
            secret=req.secret,
            events=req.events,
            format_type=req.format_type,
            description=req.description,
        )
        # Das HMAC-Geheimnis kommt nie im Klartext in einer Antwort zurück.
        return {"success": True, "webhook": mask_webhook(hook)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        # Persistenz fehlgeschlagen (Dateisystem) — kein Client-Fehler.
        logger.error("Webhook-Persistenz fehlgeschlagen: %s", exc)
        raise HTTPException(503, "Webhook konnte nicht gespeichert werden. Bitte System-Meldungen prüfen.")


@router.delete("/{webhook_id}")
async def remove_outbound_webhook(
    webhook_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
) -> dict[str, Any]:
    """Löscht einen registrierten Webhook anhand seiner ID."""
    ok = delete_webhook(webhook_id)
    if not ok:
        raise HTTPException(404, f"Webhook '{webhook_id}' nicht gefunden.")
    return {"success": True, "message": f"Webhook '{webhook_id}' gelöscht."}


@router.get("/events")
async def get_supported_events(
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
) -> dict[str, Any]:
    """Liefert die Liste aller verfügbaren Webhook-Ereignisse."""
    return {"events": ALL_EVENTS}


@router.post("/test")
async def trigger_test_webhook(
    req: WebhookTestRequest,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
) -> dict[str, Any]:
    """Sendet ein Test-Ereignis an alle passenden aktiven Webhooks."""
    if req.event not in ALL_EVENTS:
        raise HTTPException(400, f"Unbekanntes Ereignis '{req.event}'. Gültig sind: {', '.join(ALL_EVENTS)}")
    test_data = req.data or {"message": "PrintLab Test Webhook Payload", "test": True}
    dispatched = dispatch_event(req.event, test_data)
    return {"success": True, "event": req.event, "dispatched_count": dispatched}
