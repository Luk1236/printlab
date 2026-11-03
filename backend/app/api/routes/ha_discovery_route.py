"""Home Assistant MQTT Discovery API für PrintLab.

Stellt normierte MQTT Discovery Schemas und Entitätsdefinitionen für
die automatische Einbindung in Home Assistant bereit.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.ha_discovery import build_device_info, build_discovery_payloads

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discovery/homeassistant", tags=["discovery"])


@router.get("/{printer_id}")
async def get_homeassistant_discovery(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Erzeugt alle Home Assistant Discovery Konfigurationen für diesen Drucker."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    printer_name = printer.name if printer else f"Drucker {printer_id}"

    payloads = build_discovery_payloads(str(printer_id), printer_name)
    device = build_device_info(str(printer_id), printer_name)

    return {
        "printer_id": printer_id,
        "printer_name": printer_name,
        "device": device,
        "entity_count": len(payloads),
        "entities": payloads,
    }
