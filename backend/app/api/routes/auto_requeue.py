"""API: automatische Umverteilung gescheiterter Warteschlangen-Aufträge."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services import auto_requeue

router = APIRouter(prefix="/auto-requeue", tags=["auto-requeue"])


class RequeueConfigUpdate(BaseModel):
    enabled: bool | None = None
    max_retries: int | None = Field(None, ge=0, le=5)
    require_sibling: bool | None = None


@router.get("/config")
async def get_requeue_config(
    _=RequirePermissionIfAuthEnabled(Permission.QUEUE_READ),
):
    return auto_requeue.read_config()


@router.put("/config")
async def set_requeue_config(
    payload: RequeueConfigUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.QUEUE_UPDATE_ALL),
):
    return auto_requeue.write_config(payload.model_dump(exclude_none=True))


@router.get("/log")
async def get_requeue_log(
    limit: int = 50,
    _=RequirePermissionIfAuthEnabled(Permission.QUEUE_READ),
):
    """Die letzten Umverteilungen: Ursprungsauftrag, neuer Auftrag, Ziel, Grund."""
    return {"entries": auto_requeue.entries(limit)}
