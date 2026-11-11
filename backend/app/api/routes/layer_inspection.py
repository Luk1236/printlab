"""API-Endpunkte für kontinuierliche Schichtanalyse und Edge-Spaghetti-Erkennung."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.services.layer_inspection import layer_inspection_service
from backend.app.services.printer_telemetry_flow import calibrate_snapshot
from backend.app.utils.upload_limits import MAX_IMAGE_UPLOAD_BYTES, read_upload_limited

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/printers", tags=["layer-inspection"])


class LayerInspectionConfigUpdate(BaseModel):
    enabled: bool | None = None
    layer_interval: int | None = Field(default=None, ge=1, le=50)
    sensitivity_threshold: float | None = Field(default=None, ge=0.30, le=0.95)
    consecutive_alerts: int | None = Field(default=None, ge=1, le=10)
    auto_pause: bool | None = None
    save_debug_snapshots: bool | None = None
    min_layer: int | None = Field(default=None, ge=1, le=50)


async def _get_printer_or_404(printer_id: int, db: AsyncSession) -> Printer:
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if not printer:
        raise HTTPException(status_code=404, detail="Drucker nicht gefunden.")
    return printer


@router.get("/{printer_id}/layer-inspection")
async def get_layer_inspection(
    printer_id: int,
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liefert Status, Konfiguration und die letzten Prüfungen für einen Drucker."""
    await _get_printer_or_404(printer_id, db)
    return layer_inspection_service.get_status(printer_id)


@router.put("/{printer_id}/layer-inspection")
async def update_layer_inspection(
    printer_id: int,
    payload: LayerInspectionConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Aktualisiert die Konfiguration der Schichtanalyse für einen Drucker."""
    await _get_printer_or_404(printer_id, db)
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated_cfg = layer_inspection_service.configure(printer_id, update_data)
    return {
        "status": "ok",
        "printer_id": printer_id,
        "config": updated_cfg,
    }


@router.post("/{printer_id}/layer-inspection/reset")
async def reset_layer_inspection(
    printer_id: int,
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Setzt den laufenden Fehlerzähler für Schichtprüfungen zurück."""
    await _get_printer_or_404(printer_id, db)
    layer_inspection_service.reset(printer_id)
    return {"status": "ok", "printer_id": printer_id, "consecutive_alerts": 0}


@router.post("/{printer_id}/layer-inspection/test")
async def test_layer_inspection(
    printer_id: int,
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Führt eine Sofort-Prüfung durch (nutzt hochgeladenes Bild oder Live-Kamerabild)."""
    printer = await _get_printer_or_404(printer_id, db)

    image_data: bytes | None = None
    is_warped = False

    if file and file.filename:
        image_data = await read_upload_limited(file, MAX_IMAGE_UPLOAD_BYTES)
    else:
        # Live-Snapshot vom Drucker holen
        from backend.app.main import _capture_snapshot_for_notification

        raw_snapshot = await _capture_snapshot_for_notification(printer_id, printer, logger)
        if not raw_snapshot:
            raise HTTPException(status_code=503, detail="Kein Kamerabild vom Drucker empfangen.")
        # Kalibrierung anwenden, falls eingemessen
        calibrated = await calibrate_snapshot(printer_id, raw_snapshot)
        if calibrated is not None and calibrated != raw_snapshot:
            image_data = calibrated
            is_warped = True
        else:
            image_data = raw_snapshot

    if not image_data:
        raise HTTPException(status_code=400, detail="Keine Bilddaten vorhanden.")

    return await layer_inspection_service.test_frame(
        printer_id=printer_id,
        image_data=image_data,
        is_warped=is_warped,
    )
