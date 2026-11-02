"""Auto-Einrichtung (siehe ``services/auto_setup.py``): Vorschau und Ausführen dessen, was das System selbst erledigen kann."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled, is_auth_enabled
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.services import assistant_llm, audit_log, auto_setup, remote_access

router = APIRouter(prefix="/system/auto-setup", tags=["auto-setup"])
_lock = asyncio.Lock()


class AutoSetupRequest(BaseModel):
    only: list[str] | None = None


async def _deps(db: AsyncSession, request: Request) -> auto_setup.Deps:
    return auto_setup.Deps(
        data_dir=settings.base_dir,
        app_dir=settings.app_dir,
        auth_enabled=await is_auth_enabled(db),
        port=request.url.port or 8000,
        assistant_status=assistant_llm.status,
        remote_status=remote_access.status,
        remote_setup=remote_access.setup,
    )


@router.get("")
async def preview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
):
    """Was die Auto-Einrichtung jetzt tun würde (ändert nichts)."""
    return await auto_setup.plan(await _deps(db, request))


@router.post("")
async def run_auto_setup(
    payload: AutoSetupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Alles einrichten, was das System ohne Zugangsdaten des Benutzers kann."""
    unknown = [step for step in payload.only or [] if step not in auto_setup.STEPS]
    if unknown:
        raise HTTPException(400, f"Unbekannter Schritt: {unknown[0]}")
    if _lock.locked():
        raise HTTPException(429, "Die Auto-Einrichtung läuft bereits.")
    async with _lock:
        result = await auto_setup.run(await _deps(db, request), payload.only)
    audit_log.record("auto_setup", True, ",".join(f"{i['id']}={i['state']}" for i in result["items"]))
    return result
