"""API: Zeitraffer aus den aufbewahrten Schichtbildern.

Die Schichtbilder selbst entstehen im Druck (``services/layer_timelapse.py``);
hier gibt es die Aufbewahrungs-Einstellungen, die Liste der Sitzungen je Archiv
und das Rendern bzw. Herunterladen eines MP4.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services import timelapse_export

router = APIRouter(prefix="/archives", tags=["timelapse-export"])


class ExportRequest(BaseModel):
    session_id: str | None = Field(None, max_length=80, description="Sitzung; Standard: neueste")
    fps: int | None = Field(None, ge=1, le=60, description="Bildrate; Standard aus den Einstellungen")


class ExportConfigUpdate(BaseModel):
    keep_frames: bool | None = None
    retention_days: int | None = Field(None, ge=1, le=365)
    max_kept_per_archive: int | None = Field(None, ge=1, le=20)
    max_exports_per_archive: int | None = Field(None, ge=1, le=20)
    fps: int | None = Field(None, ge=1, le=60)


# Vor den dynamischen Pfaden deklariert, damit „timelapse-export“ nicht als Archiv-ID gelesen wird.
@router.get("/timelapse-export/config")
async def get_export_config(
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    return timelapse_export.read_config()


@router.put("/timelapse-export/config")
async def set_export_config(
    payload: ExportConfigUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    return timelapse_export.write_config(payload.model_dump(exclude_none=True))


@router.get("/{archive_id}/timelapse/frames")
async def list_frame_sources(
    archive_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    """Aufbewahrte Schichtbild-Sitzungen und bereits gerenderte Videos eines Archivs."""
    return {
        "archive_id": archive_id,
        "sources": timelapse_export.list_sources(archive_id),
        "exports": timelapse_export.list_exports(archive_id),
        "config": timelapse_export.read_config(),
    }


@router.post("/{archive_id}/timelapse/frames/export")
async def render_timelapse_mp4(
    archive_id: int,
    payload: ExportRequest,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    """MP4 aus den aufbewahrten Schichtbildern rendern (dauert je nach Länge einige Sekunden)."""
    try:
        result = await timelapse_export.render(archive_id, payload.session_id, payload.fps)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {k: v for k, v in result.items() if k != "path"}


@router.get("/{archive_id}/timelapse/frames/exports/{name}")
async def download_timelapse_mp4(
    archive_id: int,
    name: str,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    path = timelapse_export.resolve_export(archive_id, name)
    if path is None:
        raise HTTPException(404, "Video nicht gefunden.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)
