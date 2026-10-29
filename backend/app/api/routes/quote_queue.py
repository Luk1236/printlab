"""Angebot → Warteschlange: die verknüpften Druckjobs eines Angebots neu einreihen.

Der Weg für wiederkommende Aufträge: Verhalten → Nachkalkulation verknüpft
Archiv-Druckjobs mit einem Angebot, und diese Route stellt genau diese Archive
wieder in die Warteschlange (Drucker oder „irgendein Drucker dieses Modells",
Priorität optional). Sie geht bewusst durch ``add_to_queue`` — dieselbe
Validierung und Kostenkalkulation wie jede andere Einreihung, keine Abkürzung.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.print_queue import PrintQueueItemCreate, add_to_queue
from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.user import User
from backend.app.services import quote_history

router = APIRouter(prefix="/quote", tags=["quote"])

MAX_COPIES = 20


class QuoteQueueRequest(BaseModel):
    printer_id: int | None = Field(default=None, description="Zieldrucker; andernfalls target_model")
    target_model: str | None = Field(default=None, description="„irgendein Drucker dieses Modells“")
    priority: int = Field(default=1, ge=0, le=2)
    quantity: int = Field(default=1, ge=1, le=MAX_COPIES)


@router.post("/history/{quote_id}/queue")
async def queue_quote_prints(
    quote_id: str,
    payload: QuoteQueueRequest,
    user: User | None = RequirePermissionIfAuthEnabled(Permission.QUEUE_CREATE),
    db: AsyncSession = Depends(get_db),
):
    """Reiht jeden verknüpften Druckjob des Angebots wieder in die Warteschlange ein."""
    if payload.printer_id is not None and payload.target_model:
        raise HTTPException(422, "Entweder Drucker oder Modell — nicht beides.")
    entry = quote_history.get(quote_id)
    if entry is None:
        raise HTTPException(404, "Angebot nicht gefunden.")
    ids = [i for i in entry.get("archive_ids", []) if isinstance(i, int)]
    if not ids:
        raise HTTPException(
            400,
            "Das Angebot hat keine verknüpften Druckjobs — erst unter Verhalten → Nachkalkulation verknüpfen.",
        )

    queued: list[dict] = []
    errors: list[dict] = []
    for archive_id in ids:
        item_create = PrintQueueItemCreate(
            archive_id=archive_id,
            printer_id=payload.printer_id,
            target_model=payload.target_model,
            priority=payload.priority,
            quantity=payload.quantity,
        )
        try:
            item = await add_to_queue(item_create, db, user)
            queued.append({"archive_id": archive_id, "queue_item_id": getattr(item, "id", None)})
        except HTTPException as exc:
            errors.append({"archive_id": archive_id, "detail": exc.detail})

    label = entry.get("description") or entry.get("customer") or quote_id
    message = f"{len(queued)} Auftrag/Aufträge aus dem Angebot „{label}“ eingereiht."
    if errors:
        message += f" {len(errors)} abgelehnt (einzeln in „errors“)."
    return {"quote_id": quote_id, "queued": queued, "errors": errors, "message": message}
