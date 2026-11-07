"""API-Routen für AMS Auto-Fallback und redundante Rollenpaare."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.services.printer_manager import printer_manager

router = APIRouter(prefix="/printers", tags=["spool-auto-fallback"])

@router.get("/{printer_id}/ams-backup-pairs")
async def get_ams_backup_pairs_route(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Liefert kompatible AMS-Rollenpaare für automatischen Rollentausch (Auto-Fallback)."""
    from backend.app.services.spool_auto_fallback import find_ams_backup_pairs

    status = printer_manager.get_status(printer_id)
    pairs = find_ams_backup_pairs(status)
    client = printer_manager.get_client(printer_id)
    enabled = getattr(client.state, "ams_filament_backup", None) if client else None

    return {
        "printer_id": printer_id,
        "ams_filament_backup": enabled,
        "pairs_count": len(pairs),
        "pairs": pairs,
    }


@router.post("/{printer_id}/ams-auto-fallback/apply")
async def apply_ams_auto_fallback(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Aktiviert AMS Filament Backup automatisch, falls redundante Rollenpaare vorhanden sind."""
    from backend.app.services.spool_auto_fallback import auto_enable_ams_filament_backup_if_eligible

    success = auto_enable_ams_filament_backup_if_eligible(printer_id)
    return {"success": success, "printer_id": printer_id}


