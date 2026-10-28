"""Fernzugriff über Tailscale (siehe services/remote_access.py). Änderungen nur mit eingeschalteter Anmeldung."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled, is_auth_enabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.services import audit_log, remote_access

router = APIRouter(prefix="/remote-access", tags=["remote-access"])
logger = logging.getLogger(__name__)

AUTH_REQUIRED = "Fernzugriff nur mit eingeschalteter Anmeldung."


async def _require_auth(db: AsyncSession) -> None:
    if not await is_auth_enabled(db):
        raise HTTPException(403, AUTH_REQUIRED)


def _guard_supported() -> None:
    if not remote_access.supported():
        raise HTTPException(400, "Fernzugriff gibt es nur unter Linux.")


@router.get("")
async def get_status(
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
    db: AsyncSession = Depends(get_db),
):
    return {**await remote_access.status(), "auth_enabled": await is_auth_enabled(db)}


@router.post("/setup")
async def setup(
    request: Request,
    port: int | None = Query(None, ge=1, le=65535),
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Installieren (falls nötig), starten, anmelden lassen und freigeben, sobald angemeldet."""
    await _require_auth(db)
    _guard_supported()
    try:
        result = await remote_access.setup(port or request.url.port or 8000)
    except remote_access.RemoteAccessError as exc:
        audit_log.record("remote_access_setup", False, str(exc))
        raise HTTPException(400, str(exc)) from exc
    audit_log.record("remote_access_setup", True, result["state"])
    return {**result, "auth_enabled": True}


@router.post("/share")
async def share(
    request: Request,
    port: int | None = Query(None, ge=1, le=65535),
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Nach der Anmeldung im Tailnet den PrintLab-Port freigeben (auch zum Auffrischen des Status)."""
    await _require_auth(db)
    _guard_supported()
    try:
        current = await remote_access.status()
        if current["state"] != "connected":
            raise remote_access.RemoteAccessError("Noch nicht bei Tailscale angemeldet.")
        await remote_access.share(port or request.url.port or 8000)
    except remote_access.RemoteAccessError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit_log.record("remote_access_share", True, "")
    return {**await remote_access.status(), "auth_enabled": True}


@router.post("/disable")
async def disable(
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    result = await remote_access.disable()
    audit_log.record("remote_access_disable", True, "")
    return result
