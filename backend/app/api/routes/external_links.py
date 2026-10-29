"""API routes for external sidebar links."""

import logging
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled, require_media_token_permission
from backend.app.core.config import settings as app_settings
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.external_link import ExternalLink
from backend.app.models.user import User
from backend.app.schemas.external_link import (
    ExternalLinkCreate,
    ExternalLinkReorder,
    ExternalLinkResponse,
    ExternalLinkUpdate,
)

# Directory for storing custom icons
ICONS_DIR = app_settings.base_dir / "icons"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}
# Content-based limits (like the company logo): size cap plus magic-byte sniffing
# for raster formats, so the extension alone does not decide what gets served.
MAX_ICON_BYTES = 2 * 1024 * 1024

_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
    ".ico": (b"\x00\x00\x01\x00",),
}
# SVG must stay inert: scripts, event handlers and URL-based script loads are
# rejected at upload time, and the icon is served with a no-everything CSP
# (see get_icon) so a directly opened file cannot run anything.
_SVG_FORBIDDEN = re.compile(
    r"<script|javascript:|data:\s*text/html|\son\w+\s*=|xlink:href\s*=\s*[\"']\s*(javascript|data|&)",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/external-links", tags=["external-links"])


@router.get("/", response_model=list[ExternalLinkResponse])
async def list_external_links(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.EXTERNAL_LINKS_READ),
):
    """List all external links ordered by sort_order."""
    result = await db.execute(select(ExternalLink).order_by(ExternalLink.sort_order, ExternalLink.id))
    links = result.scalars().all()
    return links


@router.post("/", response_model=ExternalLinkResponse)
async def create_external_link(
    link_data: ExternalLinkCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.EXTERNAL_LINKS_CREATE),
):
    """Create a new external link."""
    # Get the highest sort_order to place new link at end
    result = await db.execute(select(ExternalLink).order_by(ExternalLink.sort_order.desc()).limit(1))
    last_link = result.scalar_one_or_none()
    next_order = (last_link.sort_order + 1) if last_link else 0

    link = ExternalLink(
        name=link_data.name,
        url=link_data.url,
        icon=link_data.icon,
        sort_order=next_order,
    )

    db.add(link)
    await db.commit()
    await db.refresh(link)

    logger.info("Created external link: %s -> %s", link.name, link.url)

    return link


@router.get("/{link_id}", response_model=ExternalLinkResponse)
async def get_external_link(
    link_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.EXTERNAL_LINKS_READ),
):
    """Get a specific external link."""
    result = await db.execute(select(ExternalLink).where(ExternalLink.id == link_id))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="External link not found")

    return link


@router.patch("/{link_id}", response_model=ExternalLinkResponse)
async def update_external_link(
    link_id: int,
    update_data: ExternalLinkUpdate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.EXTERNAL_LINKS_UPDATE),
):
    """Update an external link."""
    result = await db.execute(select(ExternalLink).where(ExternalLink.id == link_id))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="External link not found")

    # Update only provided fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(link, key, value)

    await db.commit()
    await db.refresh(link)

    logger.info("Updated external link: %s", link.name)

    return link


@router.delete("/{link_id}")
async def delete_external_link(
    link_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.EXTERNAL_LINKS_DELETE),
):
    """Delete an external link."""
    result = await db.execute(select(ExternalLink).where(ExternalLink.id == link_id))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="External link not found")

    name = link.name
    await db.delete(link)
    await db.commit()

    logger.info("Deleted external link: %s", name)

    return {"message": f"External link '{name}' deleted"}


@router.put("/reorder", response_model=list[ExternalLinkResponse])
async def reorder_external_links(
    reorder_data: ExternalLinkReorder,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.EXTERNAL_LINKS_UPDATE),
):
    """Update the sort order of external links."""
    # Update sort_order for each link based on position in the list
    for index, link_id in enumerate(reorder_data.ids):
        result = await db.execute(select(ExternalLink).where(ExternalLink.id == link_id))
        link = result.scalar_one_or_none()
        if link:
            link.sort_order = index

    await db.commit()

    # Return updated list
    result = await db.execute(select(ExternalLink).order_by(ExternalLink.sort_order, ExternalLink.id))
    links = result.scalars().all()

    logger.info("Reordered %s external links", len(reorder_data.ids))

    return links


@router.post("/{link_id}/icon", response_model=ExternalLinkResponse)
async def upload_icon(
    link_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.EXTERNAL_LINKS_UPDATE),
):
    """Upload a custom icon for an external link."""
    result = await db.execute(select(ExternalLink).where(ExternalLink.id == link_id))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="External link not found")

    # Validate file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    # Read only up to the size cap, so an oversized file cannot fill memory.
    content = await file.read(MAX_ICON_BYTES + 1)
    if len(content) > MAX_ICON_BYTES:
        raise HTTPException(status_code=400, detail=f"Icon too large (maximum {MAX_ICON_BYTES // (1024 * 1024)} MB)")
    if not content:
        raise HTTPException(status_code=400, detail="Icon file is empty")
    # Content check: raster formats are sniffed by magic bytes, SVG must be a
    # clean XML document without scripts or inline handlers.
    if ext == ".svg":
        _validate_svg(content)
    else:
        if not any(content.startswith(magic) for magic in _MAGIC[ext]):
            raise HTTPException(status_code=400, detail="File content does not match the file extension")

    # Create icons directory if it doesn't exist
    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    # Delete old custom icon if exists
    if link.custom_icon:
        old_path = ICONS_DIR / link.custom_icon
        if old_path.exists():
            old_path.unlink()

    # Generate unique filename
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = ICONS_DIR / filename

    # Save file (atomic, like the other config JSON writers)
    tmp_path = filepath.with_name(filename + ".tmp")
    with open(tmp_path, "wb") as f:
        f.write(content)
    tmp_path.replace(filepath)

    # Update link
    link.custom_icon = filename
    await db.commit()
    await db.refresh(link)

    logger.info("Uploaded custom icon for link %s: %s", link.name, filename)

    return link


@router.delete("/{link_id}/icon", response_model=ExternalLinkResponse)
async def delete_icon(
    link_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.EXTERNAL_LINKS_UPDATE),
):
    """Delete the custom icon for an external link."""
    result = await db.execute(select(ExternalLink).where(ExternalLink.id == link_id))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="External link not found")

    if link.custom_icon:
        filepath = ICONS_DIR / link.custom_icon
        if filepath.exists():
            filepath.unlink()
        link.custom_icon = None
        await db.commit()
        await db.refresh(link)
        logger.info("Deleted custom icon for link %s", link.name)

    return link


@router.get("/{link_id}/icon")
async def get_icon(
    link_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = Depends(require_media_token_permission(Permission.EXTERNAL_LINKS_READ)),
):
    """Get the custom icon for an external link.

    Requires a media token query param (?token=xxx) when auth is enabled, and
    the same ``external_links:read`` every other read on this router takes.
    Previously it took the camera-stream token, so a sidebar icon was visible
    only to users who could also watch the printer camera (#3025).

    The file is served with ``nosniff`` and a strict CSP (belt and suspenders: the
    global security-header middleware writes its CSP over the response, either way
    a directly opened custom SVG — validated at upload, but still user content —
    gets no script room).
    """
    result = await db.execute(select(ExternalLink).where(ExternalLink.id == link_id))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="External link not found")

    if not link.custom_icon:
        raise HTTPException(status_code=404, detail="No custom icon set")

    # custom_icon is always a UUID filename generated in upload_icon; reject
    # anything else before it reaches the filesystem.
    if (
        Path(link.custom_icon).suffix.lower() not in ALLOWED_EXTENSIONS
        or "/" in link.custom_icon
        or "\\" in link.custom_icon
    ):
        raise HTTPException(status_code=404, detail="Invalid icon reference")

    filepath = ICONS_DIR / link.custom_icon
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Icon file not found")

    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'",
    }
    return FileResponse(filepath, headers=headers)


def _validate_svg(content: bytes) -> None:
    """Verwirft SVG-Inhalte, die Code ausführen könnten, und hält sonst nur gültiges XML durch."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="The SVG file is not a valid SVG document") from exc
    if not text.lstrip().startswith(("<?xml", "<svg")):
        raise HTTPException(status_code=400, detail="The SVG file is not a valid SVG document")
    if _SVG_FORBIDDEN.search(text):
        raise HTTPException(status_code=400, detail="The SVG file must not contain scripts or event handlers")
    try:
        ET.fromstring(text)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail="The SVG file is not a valid SVG document") from exc
