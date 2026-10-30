"""Fehlerbild-Sammlung: Liste, Bild und Löschen der gesammelten Kamerabilder.

Bei Fehlprüfungen mit Kamerabild speichert ``notification_service`` das Bild
in den Ordner ``failure_images`` (utils/failure_images.py) — Rohmaterial für
eine spätere KI-Fehlererkennung und für das Nachsehen, was die Prüfer
wirklich gesehen haben. Lesen braucht CAMERA_VIEW (wie die Kamerabilder),
das Bild selbst braucht wie alle Bilder ein Media-Token, Löschen ist eine
Einstellungs-Änderung (SETTINGS_UPDATE).
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled, require_media_token_permission
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.user import User
from backend.app.services import error_export
from backend.app.utils import failure_images

router = APIRouter(prefix="/failure-images", tags=["failure-images"])

MAX_LIST = 500


@router.get("/", response_model=list[dict])
async def list_images(
    db: AsyncSession = Depends(get_db),  # noqa: ARG001 - einheitliches Session-Muster
    _: User | None = RequirePermissionIfAuthEnabled(Permission.CAMERA_VIEW),
):
    """Liste der gesammelten Fehlerbilder, neueste zuerst."""
    return failure_images.list_failure_images()[:MAX_LIST]


@router.get("/export")
async def export_images(
    db: AsyncSession = Depends(get_db),  # noqa: ARG001 - einheitliches Session-Muster
    _: User | None = RequirePermissionIfAuthEnabled(Permission.CAMERA_VIEW),
):
    """Sammlung als Trainingsset (ZIP mit Bildern und ``labels.jsonl``).

    Muss **vor** ``/{name}`` stehen, sonst schluckt die Bild-Route den Pfad.
    """
    payload = await asyncio.to_thread(error_export.build_zip)
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(
        payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="fehlerbilder-{stamp}.zip"'},
    )


@router.get("/{name}")
async def get_image(
    name: str,
    db: AsyncSession = Depends(get_db),  # noqa: ARG001
    _: User | None = Depends(require_media_token_permission(Permission.CAMERA_VIEW)),
):
    """Ein Fehlerbild ausliefern (Media-Token wie bei den anderen Bildern)."""
    path = failure_images.find_failure_image(name)
    if path is None:
        raise HTTPException(status_code=404, detail="Failure image not found")
    return FileResponse(path, media_type="image/jpeg")


@router.delete("/{name}")
async def delete_image(
    name: str,
    db: AsyncSession = Depends(get_db),  # noqa: ARG001
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Einen Fehlerbild-Eintrag löschen (z. B. nach dem Export fürs Training)."""
    deleted = await asyncio.to_thread(failure_images.delete_failure_image, name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Failure image not found")
    return {"message": "Failure image deleted"}
