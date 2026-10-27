"""API für den Wartungsdruck (Bewegungs-3MF ohne Filament)."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.archive import PrintArchive
from backend.app.models.printer import Printer
from backend.app.services.maintenance_print import MaintenancePrintError, build

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/printers", tags=["maintenance-print"])

OUT_DIR = settings.base_dir / "maintenance"
NAME_RE = re.compile(r"^Wartung_(Oel|Stangen)_\d{8}-\d{6}\.gcode\.3mf$")


async def _printer(printer_id: int, db: AsyncSession) -> Printer:
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        raise HTTPException(404, "Printer not found")
    if (printer.model or "").upper() != "P2S":
        raise HTTPException(400, "Wartungsdruck ist nur für den P2S eingerichtet.")
    return printer


def _template_path(archive: PrintArchive) -> Path | None:
    raw = (archive.file_path or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = settings.base_dir / path
    return path if path.is_file() else None


@router.post("/{printer_id}/maintenance-print/{program}")
async def create_maintenance_print(
    printer_id: int,
    program: str,
    archive_id: int | None = Query(None, description="Archiv-3MF als Vorlage (sonst das neueste)"),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Erzeugt aus einem geslicten Archiv eine reine Bewegungs-3MF zum Herunterladen."""
    await _printer(printer_id, db)
    key = program.strip().lower()
    if key not in ("oil", "rods", "oel", "schmieren"):
        raise HTTPException(400, f"Unknown maintenance print: {program}")

    if archive_id is not None:
        result = await db.execute(
            select(PrintArchive).where(PrintArchive.id == archive_id, PrintArchive.printer_id == printer_id)
        )
        archive = result.scalar_one_or_none()
        if archive is None:
            raise HTTPException(404, "Archive not found for this printer")
    else:
        result = await db.execute(
            select(PrintArchive)
            .where(PrintArchive.printer_id == printer_id, PrintArchive.file_path != "")
            .order_by(PrintArchive.created_at.desc())
            .limit(1)
        )
        archive = result.scalar_one_or_none()
    if archive is None:
        raise HTTPException(400, "Kein geslictes Archiv als Vorlage. Bitte zuerst einen Druck archivieren.")

    template = _template_path(archive)
    if template is None:
        raise HTTPException(400, "Die Archivdatei ist nicht mehr vorhanden.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    label = "Oel" if key in ("oil", "oel") else "Stangen"
    filename = f"Wartung_{label}_{stamp}.gcode.3mf"
    target = OUT_DIR / filename
    try:
        await asyncio.to_thread(build, template, target, "oil" if label == "Oel" else "rods")
    except MaintenancePrintError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info("[Wartungsdruck] %s aus Archiv %s erzeugt (%s)", filename, archive.id, template)
    return {
        "success": True,
        "message": "Wartungsdruck erzeugt. Datei herunterladen und über den Dateimanager starten.",
        "filename": filename,
        "download_url": f"/api/v1/printers/{printer_id}/maintenance-print/{filename}",
    }


@router.get("/{printer_id}/maintenance-print/{filename}")
async def download_maintenance_print(
    printer_id: int,
    filename: str,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
):
    """Liefert eine erzeugte Wartungs-3MF aus."""
    if not NAME_RE.match(filename):
        raise HTTPException(400, "Invalid maintenance file name")
    path = (OUT_DIR / filename).resolve()
    if OUT_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "Maintenance file not found")
    return FileResponse(path, media_type="application/octet-stream", filename=filename)
