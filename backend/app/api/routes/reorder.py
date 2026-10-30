"""API: Nachbestellvorschlag aus der Verbrauchsprognose."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.services import reorder_proposal

router = APIRouter(prefix="/reorder", tags=["reorder"])


class ReorderConfigUpdate(BaseModel):
    coverage_days: int | None = Field(None, ge=1, le=180)
    min_order_grams: int | None = Field(None, ge=0, le=100_000)


@router.get("/config")
async def get_reorder_config(
    _=RequirePermissionIfAuthEnabled(Permission.INVENTORY_FORECAST_READ),
):
    return reorder_proposal.read_config()


@router.put("/config")
async def set_reorder_config(
    payload: ReorderConfigUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.INVENTORY_FORECAST_WRITE),
):
    return reorder_proposal.write_config(payload.model_dump(exclude_none=True))


@router.get("/proposals")
async def get_reorder_proposals(
    _=RequirePermissionIfAuthEnabled(Permission.INVENTORY_FORECAST_READ),
    db: AsyncSession = Depends(get_db),
):
    """Was jetzt bestellt werden sollte: Menge in Rollen, Lieferant, Preis — je Material/Charge."""
    try:
        return await reorder_proposal.generate(db)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
