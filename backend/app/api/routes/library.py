"""API routes for File Manager (Library) functionality."""

import asyncio
import base64
import binascii
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse as FastAPIFileResponse
from sqlalchemy import distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.api.routes.cloud import resolve_api_key_cloud_owner
from backend.app.api.routes.library_variants import normalize_model_name, resolve_variant_model
from backend.app.api.routes.print_queue import _extract_filament_types_from_3mf
from backend.app.core.auth import (
    require_media_token_ownership,
    require_ownership_permission,
    require_permission_if_auth_enabled,
)
from backend.app.core.config import settings as app_settings
from backend.app.core.database import async_session, get_db
from backend.app.core.permissions import Permission
from backend.app.core.tasks import spawn_background_task
from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile, LibraryFileTag, LibraryFolder
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.schemas.library import (
    AddToQueueError,
    AddToQueueRequest,
    AddToQueueResponse,
    AddToQueueResult,
    BatchThumbnailRequest,
    BatchThumbnailResponse,
    BatchThumbnailResult,
    BulkDeleteRequest,
    BulkDeleteResponse,
    ClientThumbnailResponse,
    CombineFilesRequest,
    ExternalFolderCreate,
    FileDuplicate,
    FileListResponse,
    FileMoveRequest,
    FileResponse as FileResponseSchema,
    FileUpdate,
    FileUploadResponse,
    FolderCreate,
    FolderReadmeResponse,
    FolderResponse,
    FolderTreeItem,
    FolderUpdate,
    TagSummary,
    ZipExtractError,
    ZipExtractResponse,
    ZipExtractResult,
)
from backend.app.schemas.slicer import SliceRequest, SliceResponse
from backend.app.services.archive import ThreeMFParser
from backend.app.services.design_settings import (
    DesignOverride,
    apply_design_overrides,
    extract_design_process_overrides,
    overrides_from_config,
)
from backend.app.services.filament_requirements import annotate_rack_groups
from backend.app.services.pdf_thumbnail import generate_pdf_thumbnail
from backend.app.services.plate_thumbnail import inject_plate_thumbnails_if_missing
from backend.app.services.print_confirmation import confirm_outcome_for_new_queue_item
from backend.app.services.process_overrides import apply_process_overrides
from backend.app.services.slice_dispatch import SliceJobHttpError
from backend.app.services.slice_output_check import (
    missing_start_gcode_message,
    start_gcode_is_missing,
    unresolved_filament_message,
    unresolved_filament_slots,
)
from backend.app.services.stl_thumbnail import MIN_USABLE_STL_BYTES, generate_stl_thumbnail
from backend.app.utils.filename import (
    MAX_FILENAME_BYTES,
    InvalidFilenameError,
    safe_path_component,
    validate_print_filename,
)
from backend.app.utils.library_paths import library_photos_dir, remove_library_photos_dir
from backend.app.utils.printer_models import is_gcode_compatible
from backend.app.utils.safe_path import PathTraversalError, assert_under, safe_join_under
from backend.app.utils.threemf_tools import (
    carries_gcode,
    default_plate_gcode_name,
    expand_to_project_slots,
    extract_embedded_presets_from_3mf,
    extract_nozzle_mapping_from_3mf,
    extract_project_filaments_from_3mf,
    sanitize_project_settings_sentinels,
    select_plate_gcode_name,
    supports_enabled_in_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/library", tags=["library"])


# Ausgelagerte Module zur Modularisierung und Einhaltung des Zeilenbudgets
from backend.app.api.routes.library_helpers import (
    _PROJECT_SETTINGS_PATH,
    _backfill_external_thumbnails,
    _clean_3mf_metadata,
    _ensure_library_file_visible,
    _folder_tree_file_ids,
    _move_file_bytes,
    _read_3mf_entry,
    _resolve_slice_destination,
    _resolve_source_disk_path,
    _resolve_upload_destination,
    _stored_file_path,
    _unique_external_name,
    _without_print_name,
    calculate_file_hash,
    classify_file_type,
    create_image_thumbnail,
    extract_gcode_thumbnail,
    get_library_dir,
    get_library_files_dir,
    get_library_thumbnails_dir,
    save_3mf_bytes_to_library,
    to_absolute_path,
    to_relative_path,
    validate_print_file_upload,
)
from backend.app.api.routes.library_slicing import (
    _canonical_printer_model,
    _declined_source_keys,
    _patch_filament_colours,
    _patch_process_bed_type,
    _patch_process_support_settings,
    _preset_default_colour,
    _resolve_target_printer_model,
    _run_slicer_with_fallback,
    _slicer_rejection_message,
    _source_plate_colours,
    guard_nozzle_class_reslice,
    print_library_file,
    router as library_slicing_router,
    slice_and_persist,
    slice_and_persist_as_archive,
    slice_library_file,
)

# Slicing-Subrouter einbinden
router.include_router(library_slicing_router)

# ============ Folder Endpoints ============


@router.get("/folders", response_model=list[FolderTreeItem])
@router.get("/folders/", response_model=list[FolderTreeItem])
async def list_folders(
    response: Response,
    db: AsyncSession = Depends(get_db),
    _: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get all folders as a tree structure."""
    # Prevent browser caching of folder list
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

    # Get all folders with project and archive joins
    result = await db.execute(
        select(LibraryFolder, Project.name, PrintArchive.print_name)
        .outerjoin(Project, LibraryFolder.project_id == Project.id)
        .outerjoin(PrintArchive, LibraryFolder.archive_id == PrintArchive.id)
        .order_by(LibraryFolder.name)
    )
    rows = result.all()

    # Get file counts per folder
    file_counts_result = await db.execute(
        select(LibraryFile.folder_id, func.count(LibraryFile.id))
        .where(LibraryFile.folder_id.isnot(None), LibraryFile.deleted_at.is_(None))
        .group_by(LibraryFile.folder_id)
    )
    file_counts = dict(file_counts_result.all())

    # Latest immediate-child file activity per folder (#1770/#2680). Real on-disk
    # mtime when we have it (external scans populate ``fs_modified_at``), else the
    # DB ``updated_at`` — COALESCE so external rows scanned before this field
    # existed, and internal uploads, still contribute a signal. This is the
    # per-folder *leaf* value; subtree descent is aggregated recursively below.
    latest_file_activity_result = await db.execute(
        select(
            LibraryFile.folder_id,
            func.max(func.coalesce(LibraryFile.fs_modified_at, LibraryFile.updated_at)),
        )
        .where(LibraryFile.folder_id.isnot(None), LibraryFile.deleted_at.is_(None))
        .group_by(LibraryFile.folder_id)
    )
    latest_file_activity = dict(latest_file_activity_result.all())

    # Build tree structure. Each folder's initial ``latest_activity_at`` is its own
    # leaf activity: the newer of its real directory mtime (fallback updated_at)
    # and its immediate files' mtime. The recursive bubble below then rolls each
    # subtree's newest descendant up to its ancestors (#2680 — sorting must match
    # ``ls -t`` recursively, so a freshly-added deep file lifts every parent).
    folder_map = {}
    root_folders = []

    for folder, project_name, archive_name in rows:
        own_activity = folder.fs_modified_at or folder.updated_at
        latest_file = latest_file_activity.get(folder.id)
        if latest_file is not None and latest_file > own_activity:
            own_activity = latest_file
        folder_item = FolderTreeItem(
            id=folder.id,
            name=folder.name,
            parent_id=folder.parent_id,
            project_id=folder.project_id,
            archive_id=folder.archive_id,
            project_name=project_name,
            archive_name=archive_name,
            is_external=folder.is_external,
            external_path=folder.external_path,
            external_readonly=folder.external_readonly,
            file_count=file_counts.get(folder.id, 0),
            latest_activity_at=own_activity,
            children=[],
        )
        folder_map[folder.id] = folder_item

    # Link children to parents
    for folder, _, _ in rows:
        folder_item = folder_map[folder.id]
        if folder.parent_id is None:
            root_folders.append(folder_item)
        elif folder.parent_id in folder_map:
            folder_map[folder.parent_id].children.append(folder_item)

    # Recursive newest-descendant bubble (#2680). Post-order: a folder's activity
    # becomes the max of its own leaf activity and every descendant's, so sorting
    # the tree by ``latest_activity_at`` surfaces the branch with the most recent
    # activity anywhere inside it. Iterative stack keeps deep external mounts off
    # Python's recursion limit.
    def _bubble(root: FolderTreeItem) -> None:
        order: list[FolderTreeItem] = []
        stack = [root]
        while stack:
            node = stack.pop()
            order.append(node)
            stack.extend(node.children)
        for node in reversed(order):  # deepest first
            for child in node.children:
                if child.latest_activity_at is not None and (
                    node.latest_activity_at is None or child.latest_activity_at > node.latest_activity_at
                ):
                    node.latest_activity_at = child.latest_activity_at

    for root in root_folders:
        _bubble(root)

    return root_folders


@router.get("/folders/by-project/{project_id}", response_model=list[FolderResponse])
async def get_folders_by_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get all folders linked to a specific project."""
    result = await db.execute(
        select(LibraryFolder, Project.name)
        .outerjoin(Project, LibraryFolder.project_id == Project.id)
        .where(LibraryFolder.project_id == project_id)
        .order_by(LibraryFolder.name)
    )
    rows = result.all()

    folders = []
    for folder, project_name in rows:
        # Get file count + latest file activity (#1770/#2680) in one trip. Prefer
        # the real on-disk mtime (external scans), fall back to the DB updated_at.
        agg_result = await db.execute(
            select(
                func.count(LibraryFile.id),
                func.max(func.coalesce(LibraryFile.fs_modified_at, LibraryFile.updated_at)),
            ).where(
                LibraryFile.folder_id == folder.id,
                LibraryFile.deleted_at.is_(None),
            )
        )
        file_count, latest_file = agg_result.one()
        file_count = file_count or 0
        own_activity = folder.fs_modified_at or folder.updated_at
        latest_activity_at = max(own_activity, latest_file) if latest_file is not None else own_activity

        folders.append(
            FolderResponse(
                id=folder.id,
                name=folder.name,
                parent_id=folder.parent_id,
                project_id=folder.project_id,
                archive_id=folder.archive_id,
                project_name=project_name,
                archive_name=None,
                is_external=folder.is_external,
                external_path=folder.external_path,
                external_readonly=folder.external_readonly,
                external_show_hidden=folder.external_show_hidden,
                file_count=file_count,
                latest_activity_at=latest_activity_at,
                created_at=folder.created_at,
                updated_at=folder.updated_at,
            )
        )

    return folders


@router.get("/folders/by-archive/{archive_id}", response_model=list[FolderResponse])
async def get_folders_by_archive(
    archive_id: int,
    db: AsyncSession = Depends(get_db),
    _: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get all folders linked to a specific archive."""
    result = await db.execute(
        select(LibraryFolder, PrintArchive.print_name)
        .outerjoin(PrintArchive, LibraryFolder.archive_id == PrintArchive.id)
        .where(LibraryFolder.archive_id == archive_id)
        .order_by(LibraryFolder.name)
    )
    rows = result.all()

    folders = []
    for folder, archive_name in rows:
        # Get file count + latest file activity (#1770/#2680) in one trip. Prefer
        # the real on-disk mtime (external scans), fall back to the DB updated_at.
        agg_result = await db.execute(
            select(
                func.count(LibraryFile.id),
                func.max(func.coalesce(LibraryFile.fs_modified_at, LibraryFile.updated_at)),
            ).where(
                LibraryFile.folder_id == folder.id,
                LibraryFile.deleted_at.is_(None),
            )
        )
        file_count, latest_file = agg_result.one()
        file_count = file_count or 0
        own_activity = folder.fs_modified_at or folder.updated_at
        latest_activity_at = max(own_activity, latest_file) if latest_file is not None else own_activity

        folders.append(
            FolderResponse(
                id=folder.id,
                name=folder.name,
                parent_id=folder.parent_id,
                project_id=folder.project_id,
                archive_id=folder.archive_id,
                project_name=None,
                archive_name=archive_name,
                is_external=folder.is_external,
                external_path=folder.external_path,
                external_readonly=folder.external_readonly,
                external_show_hidden=folder.external_show_hidden,
                file_count=file_count,
                latest_activity_at=latest_activity_at,
                created_at=folder.created_at,
                updated_at=folder.updated_at,
            )
        )

    return folders


@router.post("/folders", response_model=FolderResponse)
@router.post("/folders/", response_model=FolderResponse)
async def create_folder(
    data: FolderCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = Depends(require_permission_if_auth_enabled(Permission.LIBRARY_UPLOAD)),
):
    """Create a new folder."""
    # Verify parent exists if specified
    if data.parent_id is not None:
        parent_result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == data.parent_id))
        if not parent_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Parent folder not found")

    # Verify project exists if specified
    project_name = None
    if data.project_id is not None:
        project_result = await db.execute(select(Project).where(Project.id == data.project_id))
        project = project_result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project_name = project.name

    # Verify archive exists if specified
    archive_name = None
    if data.archive_id is not None:
        archive_result = await db.execute(select(PrintArchive).where(PrintArchive.id == data.archive_id))
        archive = archive_result.scalar_one_or_none()
        if not archive:
            raise HTTPException(status_code=404, detail="Archive not found")
        archive_name = archive.print_name

    folder = LibraryFolder(
        name=data.name,
        parent_id=data.parent_id,
        project_id=data.project_id,
        archive_id=data.archive_id,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)

    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        project_id=folder.project_id,
        archive_id=folder.archive_id,
        project_name=project_name,
        archive_name=archive_name,
        is_external=folder.is_external,
        external_path=folder.external_path,
        external_readonly=folder.external_readonly,
        external_show_hidden=folder.external_show_hidden,
        file_count=0,
        # New folder has no files yet — fall back to the folder's own
        # updated_at so this matches the list-route semantics (#1770).
        latest_activity_at=folder.updated_at,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.get("/folders/{folder_id}", response_model=FolderResponse)
async def get_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    _: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get a folder by ID."""
    result = await db.execute(
        select(LibraryFolder, Project.name, PrintArchive.print_name)
        .outerjoin(Project, LibraryFolder.project_id == Project.id)
        .outerjoin(PrintArchive, LibraryFolder.archive_id == PrintArchive.id)
        .where(LibraryFolder.id == folder_id)
    )
    row = result.one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Folder not found")

    folder, project_name, archive_name = row

    # Get file count + latest file activity (#1770) in one trip
    agg_result = await db.execute(
        select(
            func.count(LibraryFile.id),
            func.max(LibraryFile.updated_at),
        ).where(
            LibraryFile.folder_id == folder_id,
            LibraryFile.deleted_at.is_(None),
        )
    )
    file_count, latest_file = agg_result.one()
    file_count = file_count or 0
    latest_activity_at = max(folder.updated_at, latest_file) if latest_file is not None else folder.updated_at

    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        project_id=folder.project_id,
        archive_id=folder.archive_id,
        project_name=project_name,
        archive_name=archive_name,
        is_external=folder.is_external,
        external_path=folder.external_path,
        external_readonly=folder.external_readonly,
        external_show_hidden=folder.external_show_hidden,
        file_count=file_count,
        latest_activity_at=latest_activity_at,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


_README_BYTES_CAP = 512 * 1024  # 512 KiB — model descriptions don't need more
_README_PREFERRED_STEMS = ("readme", "description")


@router.get("/folders/{folder_id}/readme", response_model=FolderReadmeResponse)
async def get_folder_readme(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Return the first markdown description file for a folder (#1268).

    Picks ``README.md`` / ``readme.md`` / ``description.md`` first (any case),
    otherwise the alphabetically-first ``*.md`` in the folder. 404 when no
    markdown file is present so the FE can hide the side panel.
    """
    user, can_read_all = auth_result

    folder_row = await db.execute(select(LibraryFolder.id).where(LibraryFolder.id == folder_id))
    if folder_row.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    query = LibraryFile.active().where(
        LibraryFile.folder_id == folder_id,
        func.lower(LibraryFile.filename).like("%.md"),
    )
    if user is not None and not can_read_all:
        query = query.where(LibraryFile.created_by_id == user.id)
    result = await db.execute(query)
    candidates = result.scalars().all()
    if not candidates:
        raise HTTPException(status_code=404, detail="No markdown description in folder")

    def sort_key(f: LibraryFile) -> tuple[int, str]:
        stem = os.path.splitext(f.filename.lower())[0]
        try:
            return (_README_PREFERRED_STEMS.index(stem), f.filename.lower())
        except ValueError:
            return (len(_README_PREFERRED_STEMS), f.filename.lower())

    pick = sorted(candidates, key=sort_key)[0]

    abs_path = to_absolute_path(pick.file_path)
    if not abs_path or not abs_path.exists():
        raise HTTPException(status_code=404, detail="Markdown file missing on disk")

    try:
        raw = abs_path.read_bytes()
    except OSError as e:
        logger.warning("Folder readme read failed for %s: %s", abs_path, e)
        raise HTTPException(status_code=500, detail="Could not read markdown file") from None

    truncated = len(raw) > _README_BYTES_CAP
    if truncated:
        raw = raw[:_README_BYTES_CAP]
    # `errors="replace"` so a single bad byte never blanks the panel.
    content = raw.decode("utf-8", errors="replace")

    return FolderReadmeResponse(filename=pick.filename, content=content, truncated=truncated)


@router.put("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: int,
    data: FolderUpdate,
    db: AsyncSession = Depends(get_db),
    _: User | None = Depends(require_permission_if_auth_enabled(Permission.LIBRARY_UPDATE_ALL)),
):
    """Update a folder.

    Note: Folders require library:update_all permission since they don't have
    ownership tracking.
    """
    result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id))
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if data.name is not None:
        folder.name = data.name

    if data.parent_id is not None:
        # Prevent circular reference
        if data.parent_id == folder_id:
            raise HTTPException(status_code=400, detail="Folder cannot be its own parent")

        # Check for circular reference in ancestors
        if data.parent_id != 0:  # 0 means move to root
            current_id = data.parent_id
            while current_id is not None:
                if current_id == folder_id:
                    raise HTTPException(status_code=400, detail="Cannot move folder into its own subtree")
                parent_result = await db.execute(select(LibraryFolder.parent_id).where(LibraryFolder.id == current_id))
                current_id = parent_result.scalar()

            folder.parent_id = data.parent_id
        else:
            folder.parent_id = None

    # Update project_id (0 to unlink)
    if data.project_id is not None:
        if data.project_id == 0:
            folder.project_id = None
        else:
            # Verify project exists
            project_result = await db.execute(select(Project).where(Project.id == data.project_id))
            if not project_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Project not found")
            folder.project_id = data.project_id

    # Update archive_id (0 to unlink)
    if data.archive_id is not None:
        if data.archive_id == 0:
            folder.archive_id = None
        else:
            # Verify archive exists
            archive_result = await db.execute(select(PrintArchive).where(PrintArchive.id == data.archive_id))
            if not archive_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Archive not found")
            folder.archive_id = data.archive_id

    await db.commit()
    await db.refresh(folder)

    # Get file count + latest file activity (#1770) and names
    agg_result = await db.execute(
        select(
            func.count(LibraryFile.id),
            func.max(LibraryFile.updated_at),
        ).where(
            LibraryFile.folder_id == folder_id,
            LibraryFile.deleted_at.is_(None),
        )
    )
    file_count, latest_file = agg_result.one()
    file_count = file_count or 0
    latest_activity_at = max(folder.updated_at, latest_file) if latest_file is not None else folder.updated_at

    # Get project and archive names
    project_name = None
    archive_name = None
    if folder.project_id:
        project_result = await db.execute(select(Project.name).where(Project.id == folder.project_id))
        project_name = project_result.scalar()
    if folder.archive_id:
        archive_result = await db.execute(select(PrintArchive.print_name).where(PrintArchive.id == folder.archive_id))
        archive_name = archive_result.scalar()

    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        project_id=folder.project_id,
        archive_id=folder.archive_id,
        project_name=project_name,
        archive_name=archive_name,
        is_external=folder.is_external,
        external_path=folder.external_path,
        external_readonly=folder.external_readonly,
        external_show_hidden=folder.external_show_hidden,
        file_count=file_count,
        latest_activity_at=latest_activity_at,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


async def _restricted_folder_delete_blocker(db: AsyncSession, folder: LibraryFolder) -> str | None:
    """Why a library:delete_own user may NOT delete this folder, or None if they may.

    Folders have no ownership tracking, so users without library:delete_all may
    only delete folders that are truly empty — an empty folder contains nobody's
    data (#1781). "Empty" must include trashed files: LibraryFile.folder_id
    cascades on folder delete, so a folder holding another user's trashed file
    would silently break trash restore.
    """
    if folder.is_external:
        return "External folders can only be deleted by users with library:delete_all"
    if folder.project_id is not None or folder.archive_id is not None:
        return "Folders linked to a project or archive can only be deleted by users with library:delete_all"

    child_result = await db.execute(select(func.count(LibraryFolder.id)).where(LibraryFolder.parent_id == folder.id))
    if (child_result.scalar() or 0) > 0:
        return "Only empty folders can be deleted without library:delete_all"

    # Includes trashed files (no deleted_at filter) — see docstring.
    file_result = await db.execute(select(func.count(LibraryFile.id)).where(LibraryFile.folder_id == folder.id))
    if (file_result.scalar() or 0) > 0:
        return "Only empty folders can be deleted without library:delete_all (the folder may contain trashed files)"

    return None


@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_DELETE_ALL,
            Permission.LIBRARY_DELETE_OWN,
        )
    ),
):
    """Delete a folder and all its contents (cascade).

    Folders have no ownership tracking, so cascade deletion requires
    library:delete_all. Users with only library:delete_own may delete empty,
    non-external, non-linked folders (#1781).
    """
    _, can_modify_all = auth_result
    result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id))
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if not can_modify_all:
        blocker = await _restricted_folder_delete_blocker(db, folder)
        if blocker:
            raise HTTPException(status_code=403, detail=blocker)

    # External folders: only remove DB records, never delete files from external path
    is_ext = folder.is_external

    # Get all files in this folder and subfolders to delete from disk
    async def get_all_file_ids(fid: int) -> list[int]:
        """Recursively get all file IDs in a folder tree."""
        file_ids = []

        # Get files in this folder
        files_result = await db.execute(
            select(LibraryFile.id, LibraryFile.file_path, LibraryFile.thumbnail_path, LibraryFile.is_external).where(
                LibraryFile.folder_id == fid
            )
        )
        for fid_val, file_path, thumb_path, file_is_ext in files_result.all():
            file_ids.append(fid_val)
            # Only delete non-external files from disk
            if not is_ext and not file_is_ext:
                try:
                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                    if thumb_path and os.path.exists(thumb_path):
                        os.remove(thumb_path)
                except OSError as e:
                    logger.warning("Failed to delete file: %s", e)

        # Get child folders and recurse
        children_result = await db.execute(select(LibraryFolder.id).where(LibraryFolder.parent_id == fid))
        for (child_id,) in children_result.all():
            file_ids.extend(await get_all_file_ids(child_id))

        return file_ids

    doomed_file_ids = await get_all_file_ids(folder_id)

    # The folder cascade hard-deletes every file row under it, so the queue has
    # to be taken off them first — same as the single-file delete below (#2819).
    # The return value used to be discarded here, which is why this never
    # happened for a folder delete.
    from backend.app.services.library_trash import delete_dependent_variants, release_queue_references

    await delete_dependent_variants(db, doomed_file_ids)
    await release_queue_references(db, doomed_file_ids)
    for doomed_id in doomed_file_ids:
        remove_library_photos_dir(doomed_id)

    # Delete folder (cascade will handle files and subfolders)
    await db.delete(folder)
    await db.commit()

    return {"status": "success", "message": "Folder deleted"}


# ============ External Folder Endpoints ============

# GHSA-r2qv follow-up (audit finding I1): external-folder mount path uses an
# allowlist of operator-opted-in roots rather than the original denylist of
# system directories. The denylist shape was fail-open-on-growth — anything
# not enumerated (``/data`` containing other users' archives, ``/root``,
# arbitrary NFS/SMB mounts, the PrintLab ``LOG_DIR``) could be mounted by any
# user with ``LIBRARY_UPLOAD``. The allowlist defaults to empty and is
# extended via the ``PRINTLAB_EXTERNAL_ROOTS`` env var (colon-separated
# absolute paths). The route is additionally gated on ``SETTINGS_UPDATE``
# (admin scope) rather than ``LIBRARY_UPLOAD`` because mounting host paths
# is an operator-level capability that crosses user boundaries.


# PrintLab-owned data directories. Hardcode-rejected even if the operator
# tries to add them to ``PRINTLAB_EXTERNAL_ROOTS`` — mounting these would
# allow reading other users' archives, log files, or the static assets path.
def _printlab_reserved_roots() -> tuple[Path, ...]:
    """Resolved PrintLab-owned directories that may NEVER be mounted as an
    external folder regardless of the operator's allowlist.

    Resolved at call time because tests patch ``settings.base_dir`` /
    ``settings.log_dir`` to a temp dir; resolving lazily picks up the
    patched values rather than module-import-time values.
    """
    from backend.app.core.config import settings as app_settings

    reserved = [app_settings.base_dir, app_settings.log_dir, app_settings.static_dir, app_settings.archive_dir]
    return tuple(Path(p).resolve() for p in reserved if p is not None)


def _allowed_external_roots() -> tuple[Path, ...]:
    """Parse ``PRINTLAB_EXTERNAL_ROOTS`` into resolved allowed roots.

    Empty env var (the default) means external folders are disabled.
    Operators opt in explicitly: ``PRINTLAB_EXTERNAL_ROOTS=/mnt/library:/srv/3d``
    Returns a tuple of resolved ``Path`` objects; entries that don't
    resolve to absolute paths are silently dropped (operator error, not
    a security boundary). Resolved lazily so tests can monkeypatch.
    """
    raw = os.environ.get("PRINTLAB_EXTERNAL_ROOTS", "")
    roots: list[Path] = []
    for entry in raw.split(":"):
        entry = entry.strip()
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve()
        except (OSError, RuntimeError):  # noqa: BLE001 — operator config error, not a security boundary
            continue
        if resolved.is_absolute():
            roots.append(resolved)
    return tuple(roots)


def _path_within(child: Path, parent: Path) -> bool:
    """Return True if ``child`` is ``parent`` or any descendant.

    Uses ``Path.relative_to`` semantics (raises ``ValueError`` on miss)
    instead of string ``startswith``, which would falsely match
    ``/data-other`` against ``/data``. ``Path.is_relative_to`` is the
    sanctioned form on Python 3.9+; both are available here.
    """
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


# Supported file extensions for external folder scanning
_SCANNABLE_EXTENSIONS = {
    ".3mf",
    ".gcode",
    ".gcode.3mf",
    ".stl",
    ".obj",
    ".step",
    ".stp",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".md",
    # Documents that ship alongside a job folder and now have in-app
    # previews (#2976): drawings/datasheets and part lists.
    ".pdf",
    ".csv",
    ".xlsx",
    ".ods",
}


def _validate_external_path(path_str: str) -> Path:
    """Validate an external path is safe to mount.

    Allowlist semantics:
    1. Path must be absolute and resolve cleanly (symlink-escape rejected
       implicitly by the resolved-startswith check below).
    2. Path must fall under one of the roots enumerated in
       ``PRINTLAB_EXTERNAL_ROOTS``; empty allowlist (the default)
       means external folders are not available on this deployment.
    3. Path must NOT fall under any PrintLab-owned directory (``base_dir``,
       ``log_dir``, ``static_dir``, ``archive_dir``) — the reserved set
       takes precedence over the allowlist, so an operator who accidentally
       sets ``PRINTLAB_EXTERNAL_ROOTS=/`` does not expose ``/data``.
    4. Existence + directory-type + readability gates remain.
    """
    path = Path(path_str).resolve()

    if not path.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")

    allowed_roots = _allowed_external_roots()
    if not allowed_roots:
        raise HTTPException(
            status_code=400,
            detail=(
                "External folders are not enabled on this deployment. Ask the "
                "operator to set PRINTLAB_EXTERNAL_ROOTS=<colon-separated paths>."
            ),
        )

    # Reserved (PrintLab-owned) paths are rejected before the allowlist check
    # so an over-broad allowlist (e.g. operator set "/" for testing) cannot
    # expose PrintLab's own data dir or log dir.
    for reserved in _printlab_reserved_roots():
        if _path_within(path, reserved):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot mount PrintLab-managed directory: {reserved}",
            )

    if not any(_path_within(path, root) for root in allowed_roots):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Path '{path}' is not within an allowed external root. "
                f"Allowed roots: {', '.join(str(r) for r in allowed_roots)}"
            ),
        )

    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {path}")

    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")

    # Check readability
    if not os.access(path, os.R_OK):
        raise HTTPException(status_code=400, detail=f"Path is not readable: {path}")

    return path


@router.post("/folders/external", response_model=FolderResponse)
async def create_external_folder(
    data: ExternalFolderCreate,
    db: AsyncSession = Depends(get_db),
    # GHSA-r2qv follow-up (I1): elevated from LIBRARY_UPLOAD to SETTINGS_UPDATE.
    # Registering a host filesystem path as a PrintLab library folder is an
    # operator-level capability that crosses user boundaries (one user's
    # registered external folder is visible to every other user via
    # /api/v1/library/folders). LIBRARY_UPLOAD was always the wrong scope —
    # SETTINGS_UPDATE is the admin-class gate that already protects every
    # other host-affecting setting (SMTP, LDAP, cloud, smart plugs).
    _: User | None = Depends(require_permission_if_auth_enabled(Permission.SETTINGS_UPDATE)),
):
    """Create an external folder that points to a host directory."""
    resolved = _validate_external_path(data.external_path)

    # Check no other external folder already points to this path
    existing = await db.execute(
        select(LibraryFolder).where(
            LibraryFolder.is_external.is_(True),
            LibraryFolder.external_path == str(resolved),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An external folder already exists for this path")

    # Verify parent exists if specified
    if data.parent_id is not None:
        parent_result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == data.parent_id))
        if not parent_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Parent folder not found")

    folder = LibraryFolder(
        name=data.name,
        parent_id=data.parent_id,
        is_external=True,
        external_path=str(resolved),
        external_readonly=data.readonly,
        external_show_hidden=data.show_hidden,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)

    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        project_id=None,
        archive_id=None,
        is_external=True,
        external_path=folder.external_path,
        external_readonly=folder.external_readonly,
        external_show_hidden=folder.external_show_hidden,
        file_count=0,
        # Newly-created external folder hasn't been scanned yet — fall back
        # to the folder's own updated_at (#1770).
        latest_activity_at=folder.updated_at,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


def _mtime_to_datetime(mtime: float) -> datetime:
    """Convert an ``os.stat().st_mtime`` epoch value to a naive-UTC datetime (#2680).

    Naive UTC to match the other library timestamp columns (``created_at`` /
    ``updated_at`` are naive ``func.now()``), so activity comparisons never mix
    naive and aware values on either dialect.
    """
    return datetime.fromtimestamp(mtime, tz=timezone.utc).replace(tzinfo=None)


@router.post("/folders/{folder_id}/scan")
async def scan_external_folder(
    folder_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = Depends(require_permission_if_auth_enabled(Permission.LIBRARY_UPLOAD)),
):
    """Scan an external folder and sync files to the database.

    Discovers new files, removes DB entries for deleted files.
    Does not copy files — stores the external path directly.
    """
    result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id))
    folder = result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not folder.is_external or not folder.external_path:
        raise HTTPException(status_code=400, detail="Not an external folder")

    ext_path = Path(folder.external_path)
    if not ext_path.exists() or not ext_path.is_dir():
        raise HTTPException(status_code=400, detail=f"External path is not accessible: {folder.external_path}")

    # Collect all existing child external subfolder IDs (single query)
    all_folder_ids = [folder_id]
    child_result = await db.execute(
        select(LibraryFolder).where(
            LibraryFolder.is_external.is_(True),
            LibraryFolder.parent_id.isnot(None),
        )
    )
    all_child_folders = child_result.scalars().all()

    # Walk the parent chain to find all descendants of folder_id
    parent_to_children: dict[int, list] = {}
    for cf in all_child_folders:
        parent_to_children.setdefault(cf.parent_id, []).append(cf)

    queue = [folder_id]
    while queue:
        pid = queue.pop()
        for child in parent_to_children.get(pid, []):
            all_folder_ids.append(child.id)
            queue.append(child.id)

    # Get existing DB files across root and all subfolders
    existing_result = await db.execute(
        LibraryFile.active().where(
            LibraryFile.folder_id.in_(all_folder_ids),
            LibraryFile.is_external.is_(True),
        )
    )
    existing_files = {f.file_path: f for f in existing_result.scalars().all()}

    # Build folder cache: relative path -> folder_id (for resolving subfolders)
    # Pre-populate with existing child folders keyed by their external_path
    folder_cache: dict[str, int] = {"": folder_id}
    for fid in all_folder_ids:
        if fid == folder_id:
            continue
        # Find the child folder object
        for cf in all_child_folders:
            if cf.id == fid and cf.external_path:
                try:
                    rel = Path(cf.external_path).relative_to(ext_path).as_posix()
                    if rel != ".":
                        folder_cache[rel] = cf.id
                except ValueError:
                    pass

    # Scan the directory
    added = 0
    removed = 0
    found_paths: set[str] = set()
    seen_rel_dirs: set[str] = set()
    # Real on-disk mtime per visited folder id (#2680), applied after the walk.
    folder_mtimes: dict[int, datetime] = {}

    for dirpath, dirnames, filenames in os.walk(ext_path):
        # Filter hidden directories unless configured
        if not folder.external_show_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        rel_dir = Path(dirpath).relative_to(ext_path).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        seen_rel_dirs.add(rel_dir)

        # Resolve or create subfolder chain for this directory
        if rel_dir and rel_dir not in folder_cache:
            parts = Path(rel_dir).parts
            current_path = ""
            current_parent = folder_id
            for part in parts:
                current_path = f"{current_path}/{part}".lstrip("/")
                if current_path in folder_cache:
                    current_parent = folder_cache[current_path]
                else:
                    existing_sub = await db.execute(
                        select(LibraryFolder).where(
                            LibraryFolder.name == part,
                            LibraryFolder.parent_id == current_parent,
                            LibraryFolder.is_external.is_(True),
                        )
                    )
                    existing_folder = existing_sub.scalar_one_or_none()
                    if existing_folder:
                        current_parent = existing_folder.id
                    else:
                        new_folder = LibraryFolder(
                            name=part,
                            parent_id=current_parent,
                            is_external=True,
                            external_path=str(
                                ext_path / current_path
                            ),  # SEC-PATH-OK: current_path built from Path(rel_dir).parts of an os.walk descent under ext_path
                            external_readonly=folder.external_readonly,
                            external_show_hidden=folder.external_show_hidden,
                        )
                        db.add(new_folder)
                        await db.flush()
                        current_parent = new_folder.id
                    folder_cache[current_path] = current_parent

        target_folder_id = folder_cache.get(rel_dir, folder_id)

        # Record this directory's own mtime (#2680). os.walk visits every
        # directory once, so this covers the root external folder and every
        # subfolder (existing or just created). Applied to the folder rows
        # after the walk completes.
        try:
            folder_mtimes[target_folder_id] = _mtime_to_datetime(os.stat(dirpath).st_mtime)
        except OSError:
            pass

        for filename in filenames:
            # Skip hidden files unless configured
            if not folder.external_show_hidden and filename.startswith("."):
                continue

            filepath = (
                Path(dirpath) / filename
            )  # SEC-PATH-OK: dirpath + filename from os.walk(ext_path); filesystem-discovered, not user input
            ext = filepath.suffix.lower()

            # Check for compound extensions like .gcode.3mf
            if ext not in _SCANNABLE_EXTENSIONS:
                # Check compound
                compound = "".join(filepath.suffixes[-2:]).lower() if len(filepath.suffixes) >= 2 else ""
                if compound not in _SCANNABLE_EXTENSIONS:
                    continue

            # Resolve symlinks and ensure still under external_path
            try:
                real_path = filepath.resolve()
                real_path.relative_to(ext_path.resolve())
            except (ValueError, OSError):
                continue  # Symlink escapes the external dir

            file_path_str = str(filepath)
            found_paths.add(file_path_str)

            if file_path_str in existing_files:
                # Already tracked — refresh its on-disk mtime (#2680) so a file
                # edited/replaced over the mount (samba, etc.) re-sorts correctly
                # and old rows scanned before this field existed get backfilled.
                tracked = existing_files[file_path_str]
                try:
                    fs_mtime = _mtime_to_datetime(filepath.stat().st_mtime)
                except OSError:
                    fs_mtime = None
                if fs_mtime is not None and tracked.fs_modified_at != fs_mtime:
                    tracked.fs_modified_at = fs_mtime
                continue

            # Get file info
            try:
                stat = filepath.stat()
            except OSError:
                continue

            # The zip is opened for the thumbnail immediately below either way,
            # so judging a `.3mf` on its contents rather than its name (#2993)
            # costs this scan nothing.
            file_type = classify_file_type(filename, filepath)

            # Extract thumbnail for 3mf files (including .gcode.3mf sliced
            # outputs — those are 3MF zips on disk and carry the same
            # thumbnail Metadata/plate_1.png the parser reads). Pre-#1600
            # the gate was `file_type == "3mf"` alone, so .gcode.3mf files
            # in external folders silently got no thumbnail.
            thumbnail_path = None
            file_metadata = None
            if file_type in ("3mf", "gcode.3mf"):
                try:
                    parser = ThreeMFParser(str(filepath))
                    raw_metadata = parser.parse()
                    if raw_metadata:
                        # Extract thumbnail before cleaning metadata
                        thumb_data = raw_metadata.get("_thumbnail_data")
                        thumbnail_ext = raw_metadata.get("_thumbnail_ext", ".png")
                        if thumb_data:
                            thumb_dir = get_library_thumbnails_dir()
                            thumb_filename = f"{uuid.uuid4().hex}{thumbnail_ext}"
                            thumb_full = (
                                thumb_dir / thumb_filename
                            )  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + thumbnail_ext
                            thumb_full.write_bytes(thumb_data)
                            thumbnail_path = to_relative_path(thumb_full)

                        # Clean metadata - remove non-JSON-serializable data (bytes, etc.)
                        def clean_metadata(obj):
                            if isinstance(obj, dict):
                                return {
                                    k: clean_metadata(v)
                                    for k, v in obj.items()
                                    if not isinstance(v, bytes) and k not in ("_thumbnail_data", "_thumbnail_ext")
                                }
                            elif isinstance(obj, list):
                                return [clean_metadata(i) for i in obj if not isinstance(i, bytes)]
                            elif isinstance(obj, bytes):
                                return None
                            return obj

                        file_metadata = clean_metadata(raw_metadata)
                except Exception as e:
                    logger.debug("Failed to extract metadata from external 3mf %s: %s", filepath, e)

            # STL and PDF thumbnails are deferred to a background task spawned
            # after the scan's db.commit() — see _backfill_external_thumbnails.
            # Doing them inline would block the HTTP request for minutes on a
            # large NAS mount (#1299).

            # Extract gcode thumbnail
            if file_type == "gcode" and thumbnail_path is None:
                thumb_data = extract_gcode_thumbnail(filepath)
                if thumb_data:
                    thumb_dir = get_library_thumbnails_dir()
                    thumb_filename = f"{uuid.uuid4().hex}.png"
                    thumb_full = thumb_dir / thumb_filename  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + ".png"
                    thumb_full.write_bytes(thumb_data)
                    thumbnail_path = to_relative_path(thumb_full)

            # Create thumbnail for image files
            if ext.lower() in IMAGE_EXTENSIONS and thumbnail_path is None:
                thumbnail_path_str = create_image_thumbnail(filepath, get_library_thumbnails_dir())
                if thumbnail_path_str:
                    thumbnail_path = to_relative_path(Path(thumbnail_path_str))

            db_file = LibraryFile(
                folder_id=target_folder_id,
                is_external=True,
                filename=filename,
                file_path=file_path_str,
                file_type=file_type,
                file_size=stat.st_size,
                file_hash=None,  # Skip hashing external files for performance
                thumbnail_path=thumbnail_path,
                file_metadata=_without_print_name(file_metadata),
                fs_modified_at=_mtime_to_datetime(stat.st_mtime),  # #2680: real on-disk mtime
            )
            db.add(db_file)
            added += 1

    # Remove DB entries for files that no longer exist on disk.
    #
    # Gate on actual disk presence, NOT merely absence from found_paths:
    # found_paths only collects extensions in _SCANNABLE_EXTENSIONS, so a
    # record for any other file the upload path admitted (e.g. a .md README,
    # #2520) would otherwise be treated as "deleted from disk" and purged on
    # every scan even though the file is still there. os.path.exists keeps
    # such records; genuinely-deleted files (absent from disk) are still
    # cleaned up. External file_path is the absolute on-disk path.
    for path_str, db_file in existing_files.items():
        if path_str not in found_paths and not os.path.exists(path_str):
            # Clean up thumbnail if we generated one
            if db_file.thumbnail_path:
                try:
                    abs_thumb = to_absolute_path(db_file.thumbnail_path)
                    if abs_thumb and abs_thumb.exists():
                        abs_thumb.unlink()
                except OSError:
                    pass
            # The row is gone for good — external files skip the trash — so
            # its photos go with it rather than being orphaned under an id
            # nothing points at any more (#3077).
            remove_library_photos_dir(db_file.id)
            await db.delete(db_file)
            removed += 1

    # Remove empty subfolders whose directories no longer exist on disk
    # Process deepest-first by sorting on path depth (descending)
    subfolder_entries = [(rel, fid) for rel, fid in folder_cache.items() if rel and fid != folder_id]
    subfolder_entries.sort(key=lambda x: x[0].count("/"), reverse=True)
    for rel_path, sub_fid in subfolder_entries:
        if rel_path in seen_rel_dirs:
            continue  # Directory still exists on disk
        # Check if subfolder has any remaining files
        file_count_result = await db.execute(
            select(func.count(LibraryFile.id)).where(
                LibraryFile.folder_id == sub_fid,
                LibraryFile.deleted_at.is_(None),
            )
        )
        if (file_count_result.scalar() or 0) == 0:
            # Check if it has any remaining child folders
            child_count_result = await db.execute(
                select(func.count(LibraryFolder.id)).where(LibraryFolder.parent_id == sub_fid)
            )
            if (child_count_result.scalar() or 0) == 0:
                sub_folder_result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == sub_fid))
                sub_folder_obj = sub_folder_result.scalar_one_or_none()
                if sub_folder_obj:
                    await db.delete(sub_folder_obj)
                    folder_mtimes.pop(sub_fid, None)

    # Persist each visited folder's real directory mtime (#2680). Fetched in one
    # trip; folders deleted by the cleanup above were dropped from folder_mtimes.
    if folder_mtimes:
        folders_result = await db.execute(select(LibraryFolder).where(LibraryFolder.id.in_(list(folder_mtimes.keys()))))
        for folder_obj in folders_result.scalars().all():
            new_mtime = folder_mtimes.get(folder_obj.id)
            if new_mtime is not None and folder_obj.fs_modified_at != new_mtime:
                folder_obj.fs_modified_at = new_mtime

    await db.commit()

    # Spawn STL/PDF thumbnail backfill in the background — the scan endpoint
    # returns immediately so the FE modal closes and subdirectories are
    # visible right away; thumbnails fill in over the following seconds /
    # minutes as the task processes each file. Survives FE refresh —
    # the task lives in the FastAPI event loop, not the request scope.
    # folder_cache.values() covers the root + every pre-existing subfolder
    # + every subfolder created during this scan. all_folder_ids on its own
    # would miss the newly-created ones (it's snapshotted before the walk).
    spawn_background_task(
        _backfill_external_thumbnails(list(set(folder_cache.values()))),
        name=f"thumbnail-backfill-folder-{folder_id}",
    )

    return {"status": "success", "added": added, "removed": removed}


# ============ File Endpoints ============


@router.get("/files", response_model=list[FileListResponse])
@router.get("/files/", response_model=list[FileListResponse])
async def list_files(
    response: Response,
    folder_id: int | None = None,
    project_id: int | None = None,
    include_root: bool = True,
    internal_only: bool = False,
    external_only: bool = False,
    recursive: bool = False,
    tag_ids: list[int] = Query(default_factory=list),
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """List files, optionally filtered by folder or project.

    Args:
        folder_id: Filter by folder ID. If None and include_root=True, returns root files.
        project_id: Return all files across folders linked to this project (bulk fetch, avoids N+1).
        include_root: If True and folder_id is None, returns files at root level.
                     If False and folder_id is None, returns all files.
        internal_only: Restrict the result to files in managed storage (`is_external=False`).
                       Used by the File Manager's "All Files" sidebar entry so a linked NAS
                       with hundreds of files doesn't drown the user's own uploads (#1621).
        external_only: Restrict the result to files under external folders
                       (`is_external=True`) — the symmetric combined view for users with
                       multiple linked external sources (#1621).
        recursive: When combined with ``folder_id``, also include files in every
                   descendant subfolder (#1268). Implemented via a recursive CTE
                   that walks ``library_folders.parent_id``. Default off so
                   existing callers (folder browsing, etc.) keep their narrow
                   single-folder semantics.
        tag_ids: Restrict the listing to files carrying ALL of these tags
                 (AND semantics, #1268). When non-empty the folder filter is
                 intentionally bypassed — tags are cross-cutting and the user
                 wants "every file with this tag" regardless of where it lives.
                 ``recursive`` becomes irrelevant in that case.
    """
    if internal_only and external_only:
        raise HTTPException(
            status_code=400,
            detail="internal_only and external_only are mutually exclusive",
        )

    user, can_read_all = auth_result
    query = LibraryFile.active().options(
        selectinload(LibraryFile.created_by),
        selectinload(LibraryFile.tags),
    )
    if user is not None and not can_read_all:
        query = query.where(LibraryFile.created_by_id == user.id)

    if tag_ids:
        # Cross-cutting filter — every requested tag must be present on the
        # file. JOIN + GROUP BY + HAVING COUNT(DISTINCT) is portable across
        # SQLite and Postgres without dialect tricks. We deliberately skip
        # the folder / project / include_root scoping below so the result
        # is the global "all files carrying these tags".
        unique_tag_ids = list(dict.fromkeys(tag_ids))
        query = (
            query.join(LibraryFileTag, LibraryFileTag.file_id == LibraryFile.id)
            .where(LibraryFileTag.tag_id.in_(unique_tag_ids))
            .group_by(LibraryFile.id)
            .having(func.count(distinct(LibraryFileTag.tag_id)) == len(unique_tag_ids))
        )
    elif folder_id is not None and recursive:
        # Walk the subtree starting at folder_id and collect every descendant
        # id. Recursive CTE works on both SQLite (>=3.8.3, shipped 2014) and
        # Postgres without dialect branching.
        roots = (
            select(LibraryFolder.id).where(LibraryFolder.id == folder_id).cte(name="folder_descendants", recursive=True)
        )
        descendants = roots.union_all(select(LibraryFolder.id).join(roots, LibraryFolder.parent_id == roots.c.id))
        query = query.where(LibraryFile.folder_id.in_(select(descendants.c.id)))
    elif folder_id is not None:
        query = query.where(LibraryFile.folder_id == folder_id)
    elif project_id is not None:
        # Single join instead of one query per folder (avoids N+1 pattern)
        query = query.join(LibraryFolder, LibraryFile.folder_id == LibraryFolder.id)
        query = query.where(LibraryFolder.project_id == project_id)
    elif include_root:
        query = query.where(LibraryFile.folder_id.is_(None))

    if internal_only:
        query = query.where(LibraryFile.is_external.is_(False))
    elif external_only:
        query = query.where(LibraryFile.is_external.is_(True))

    query = query.order_by(LibraryFile.filename)
    result = await db.execute(query)
    files = result.scalars().unique().all() if tag_ids else result.scalars().all()

    # Get duplicate counts
    hash_counts = {}
    if files:
        hashes = [f.file_hash for f in files if f.file_hash]
        if hashes:
            dup_result = await db.execute(
                select(LibraryFile.file_hash, func.count(LibraryFile.id))
                .where(LibraryFile.file_hash.in_(hashes), LibraryFile.deleted_at.is_(None))
                .group_by(LibraryFile.file_hash)
            )
            hash_counts = {h: c - 1 for h, c in dup_result.all()}  # -1 to exclude self

    # Variant group sizes (#671 / #2570). Counted across the whole group rather
    # than the rows on screen — members can sit in different folders, so counting
    # the listing would under-report and the "2 versions" badge would blink in
    # and out as the user navigated.
    variant_counts: dict[int, int] = {}
    group_ids = {f.variant_group_id for f in files if f.variant_group_id}
    if group_ids:
        count_result = await db.execute(
            select(LibraryFile.variant_group_id, func.count(LibraryFile.id))
            .where(LibraryFile.variant_group_id.in_(group_ids), LibraryFile.deleted_at.is_(None))
            .group_by(LibraryFile.variant_group_id)
        )
        variant_counts = dict(count_result.all())

    # Prevent browser caching of file list
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

    file_list = []
    for f in files:
        # Extract key metadata for display
        print_name = None
        print_time = None
        filament_grams = None
        sliced_for_model = None
        if f.file_metadata:
            print_name = f.file_metadata.get("print_name")
            print_time = f.file_metadata.get("print_time_seconds")
            filament_grams = f.file_metadata.get("filament_used_grams")
            sliced_for_model = f.file_metadata.get("sliced_for_model")

        file_list.append(
            FileListResponse(
                id=f.id,
                folder_id=f.folder_id,
                is_external=f.is_external,
                filename=f.filename,
                file_type=f.file_type,
                file_size=f.file_size,
                thumbnail_path=f.thumbnail_path,
                print_count=f.print_count,
                duplicate_count=hash_counts.get(f.file_hash, 0) if f.file_hash else 0,
                created_by_id=f.created_by_id,
                created_by_username=f.created_by.username if f.created_by else None,
                created_at=f.created_at,
                fs_modified_at=f.fs_modified_at,
                print_name=print_name,
                print_time_seconds=print_time,
                filament_used_grams=filament_grams,
                sliced_for_model=sliced_for_model,
                tags=[TagSummary(id=t.id, name=t.name) for t in f.tags],
                variant_group_id=f.variant_group_id,
                variant_count=variant_counts.get(f.variant_group_id, 0) if f.variant_group_id else 0,
                external_url=f.external_url,
                has_notes=bool(f.notes),
                photo_count=len(f.photos or []),
            )
        )

    return file_list


@router.post("/files", response_model=FileUploadResponse)
@router.post("/files/", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    folder_id: int | None = None,
    generate_stl_thumbnails: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_permission_if_auth_enabled(Permission.LIBRARY_UPLOAD)),
):
    """Upload a file to the library."""
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")

        filename = file.filename
        # Reject FAT32/exFAT-incompatible filenames up front (#1540).
        try:
            validate_print_filename(filename)
        except InvalidFilenameError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # `ext` stays the trailing extension because the on-disk filename uses
        # it directly and the 3MF-parse branch below still gates on
        # `ext == ".3mf"`, which is correct for both `.3mf` and `.gcode.3mf`.
        # `file_type` is compound-aware and is decided further down, once the
        # bytes are on disk to be read.
        ext = os.path.splitext(filename)[1].lower()

        # Verify folder exists if specified
        target_folder = None
        if folder_id is not None:
            folder_result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id))
            target_folder = folder_result.scalar_one_or_none()
            if not target_folder:
                raise HTTPException(status_code=404, detail="Folder not found")

        # Writable external folders write through to the mount so the file is
        # visible outside PrintLab (#1112); everything else lands under the
        # internal library dir with a UUID-scoped filename. Resolved BEFORE
        # the content validation below so folder-permission rejections
        # (403 read-only, 400 missing path, 409 collision) still surface
        # before any "bad file format" 400 — preserves existing error
        # ordering / tests.
        file_path, is_external_upload = _resolve_upload_destination(target_folder, filename)

        # Read upload now so the validation can sniff magic bytes; the file
        # is written to disk only after the checks. #1401.
        content = await file.read()
        validate_print_file_upload(filename, content)

        # Save file
        with open(file_path, "wb") as f:
            f.write(content)

        # Now that the bytes are on disk the zip can settle what the name only
        # guessed at: a sliced 3MF uploaded as `Foo.3mf` is a sliced 3MF (#2993).
        file_type = classify_file_type(filename, file_path)

        # Calculate hash
        file_hash = calculate_file_hash(file_path)

        # Check for duplicates
        dup_result = await db.execute(
            select(LibraryFile.id).where(LibraryFile.file_hash == file_hash, LibraryFile.deleted_at.is_(None)).limit(1)
        )
        duplicate_of = dup_result.scalar()

        # Extract metadata and thumbnail
        metadata = {}
        thumbnail_path = None
        thumbnails_dir = get_library_thumbnails_dir()

        if ext == ".3mf":
            try:
                parser = ThreeMFParser(str(file_path))
                raw_metadata = parser.parse()

                # Extract thumbnail before cleaning metadata
                thumbnail_data = raw_metadata.get("_thumbnail_data")
                thumbnail_ext = raw_metadata.get("_thumbnail_ext", ".png")

                # Save thumbnail if extracted
                if thumbnail_data:
                    thumb_filename = f"{uuid.uuid4().hex}{thumbnail_ext}"
                    thumb_path = (
                        thumbnails_dir / thumb_filename
                    )  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + thumbnail_ext
                    with open(thumb_path, "wb") as f:
                        f.write(thumbnail_data)
                    thumbnail_path = str(thumb_path)

                # Clean metadata - remove non-JSON-serializable data (bytes, etc.)
                def clean_metadata(obj):
                    if isinstance(obj, dict):
                        return {
                            k: clean_metadata(v)
                            for k, v in obj.items()
                            if not isinstance(v, bytes) and k not in ("_thumbnail_data", "_thumbnail_ext")
                        }
                    elif isinstance(obj, list):
                        return [clean_metadata(i) for i in obj if not isinstance(i, bytes)]
                    elif isinstance(obj, bytes):
                        return None
                    return obj

                metadata = clean_metadata(raw_metadata)
            except Exception as e:
                logger.warning("Failed to parse 3MF: %s", e)

        elif ext == ".gcode":
            # Extract embedded thumbnail from gcode
            try:
                thumbnail_data = extract_gcode_thumbnail(file_path)
                if thumbnail_data:
                    thumb_filename = f"{uuid.uuid4().hex}.png"
                    thumb_path = (
                        thumbnails_dir / thumb_filename
                    )  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + ".png"
                    with open(thumb_path, "wb") as f:
                        f.write(thumbnail_data)
                    thumbnail_path = str(thumb_path)
            except Exception as e:
                logger.warning("Failed to extract gcode thumbnail: %s", e)

        elif ext.lower() in IMAGE_EXTENSIONS:
            # For image files, create a thumbnail from the image itself
            thumbnail_path = create_image_thumbnail(file_path, thumbnails_dir)

        elif ext.lower() == ".pdf":
            # Page one, rendered server-side; the browser preview's own
            # render (POST /preview-thumbnail) remains the fallback.
            thumbnail_path = await asyncio.to_thread(generate_pdf_thumbnail, file_path, thumbnails_dir)

        elif ext == ".stl":
            # Generate STL thumbnail if enabled. Same MIN_USABLE_STL_BYTES
            # pre-skip as extract_zip_file — stubs / placeholders below this
            # size can't contain a triangle so trimesh would return an empty
            # mesh anyway.
            if generate_stl_thumbnails:
                try:
                    if file_path.stat().st_size >= MIN_USABLE_STL_BYTES:
                        thumbnail_path = generate_stl_thumbnail(file_path, thumbnails_dir)
                except OSError:
                    pass

        # Create database entry (managed files store relative paths for portability;
        # external files store the absolute mount path — same shape as scan produces)
        library_file = LibraryFile(
            folder_id=folder_id,
            is_external=is_external_upload,
            filename=filename,
            file_path=_stored_file_path(file_path, is_external_upload),
            file_type=file_type,
            file_size=len(content),
            file_hash=file_hash,
            thumbnail_path=to_relative_path(thumbnail_path) if thumbnail_path else None,
            file_metadata=_without_print_name(metadata) if metadata else None,
            created_by_id=current_user.id if current_user else None,
        )
        db.add(library_file)
        await db.commit()
        await db.refresh(library_file)

        return FileUploadResponse(
            id=library_file.id,
            filename=library_file.filename,
            file_type=library_file.file_type,
            file_size=library_file.file_size,
            thumbnail_path=library_file.thumbnail_path,
            duplicate_of=duplicate_of,
            metadata=library_file.file_metadata,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Upload failed for %s: %s", file.filename, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/files/extract-zip", response_model=ZipExtractResponse)
async def extract_zip_file(
    file: UploadFile = File(...),
    folder_id: int | None = Query(default=None),
    preserve_structure: bool = Query(default=True),
    create_folder_from_zip: bool = Query(default=False),
    generate_stl_thumbnails: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_permission_if_auth_enabled(Permission.LIBRARY_UPLOAD)),
):
    """Upload and extract a ZIP file to the library.

    Args:
        file: The ZIP file to extract
        folder_id: Target folder ID (None = root)
        preserve_structure: If True, recreate folder structure from ZIP; if False, extract all files flat
        create_folder_from_zip: If True, create a folder named after the ZIP file and extract into it
        generate_stl_thumbnails: If True, generate thumbnails for STL files
    """
    import tempfile

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are supported")

    # Verify target folder exists if specified
    if folder_id is not None:
        folder_result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id))
        target_folder = folder_result.scalar_one_or_none()
        if not target_folder:
            raise HTTPException(status_code=404, detail="Target folder not found")
        if target_folder.is_external and target_folder.external_readonly:
            raise HTTPException(status_code=403, detail="Cannot extract ZIP to a read-only external folder")
        if target_folder.is_external:
            # Writable external folders aren't supported by extract-zip because the
            # nested-subfolder creation path would need to mkdir on the mount and
            # create matching is_external=True LibraryFolder rows — a separate
            # design. Direct the user at Scan, which already handles that shape
            # (#1112).
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot extract ZIP directly into an external folder. "
                    "Extract the ZIP on the external mount and run 'Scan External Folder' instead."
                ),
            )

    # Save ZIP to temp file
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save ZIP file: {str(e)}")

    extracted_files: list[ZipExtractResult] = []
    errors: list[ZipExtractError] = []
    folders_created = 0
    folder_cache: dict[str, int] = {}  # path -> folder_id

    # If create_folder_from_zip is True, create a folder named after the ZIP file
    zip_folder_id = folder_id
    logger.info(
        f"ZIP extraction: create_folder_from_zip={create_folder_from_zip}, folder_id={folder_id}, filename={file.filename}"
    )
    if create_folder_from_zip and file.filename:
        # Remove .zip extension to get folder name
        zip_folder_name = file.filename[:-4] if file.filename.lower().endswith(".zip") else file.filename
        # Check if folder already exists
        existing = await db.execute(
            select(LibraryFolder).where(
                LibraryFolder.name == zip_folder_name,
                LibraryFolder.parent_id == folder_id if folder_id else LibraryFolder.parent_id.is_(None),
            )
        )
        existing_folder = existing.scalar_one_or_none()
        if existing_folder:
            zip_folder_id = existing_folder.id
            logger.info("Reusing existing folder '%s' with id=%s", zip_folder_name, zip_folder_id)
        else:
            # Create folder
            new_folder = LibraryFolder(name=zip_folder_name, parent_id=folder_id)
            db.add(new_folder)
            await db.flush()
            await db.commit()  # Commit folder creation immediately
            zip_folder_id = new_folder.id
            folders_created += 1
            logger.info("Created new folder '%s' with id=%s", zip_folder_name, zip_folder_id)

    try:
        with zipfile.ZipFile(tmp_path, "r") as zf:
            # Filter out directories and hidden/system files
            file_list = [
                name
                for name in zf.namelist()
                if not name.endswith("/")
                and not name.startswith("__MACOSX")
                and not os.path.basename(name).startswith(".")
            ]

            for zip_path in file_list:
                try:
                    # Determine target folder (use zip_folder_id as base if create_folder_from_zip was used)
                    target_folder_id = zip_folder_id

                    if preserve_structure:
                        # Get directory path from ZIP
                        dir_path = os.path.dirname(zip_path)
                        if dir_path:
                            # Create folder structure
                            parts = dir_path.split("/")
                            current_parent = zip_folder_id
                            current_path = ""

                            for part in parts:
                                if not part:
                                    continue
                                current_path = f"{current_path}/{part}" if current_path else part

                                if current_path in folder_cache:
                                    current_parent = folder_cache[current_path]
                                else:
                                    # Check if folder exists
                                    existing = await db.execute(
                                        select(LibraryFolder).where(
                                            LibraryFolder.name == part,
                                            LibraryFolder.parent_id == current_parent
                                            if current_parent
                                            else LibraryFolder.parent_id.is_(None),
                                        )
                                    )
                                    existing_folder = existing.scalar_one_or_none()

                                    if existing_folder:
                                        current_parent = existing_folder.id
                                    else:
                                        # Create folder
                                        new_folder = LibraryFolder(name=part, parent_id=current_parent)
                                        db.add(new_folder)
                                        await db.flush()
                                        current_parent = new_folder.id
                                        folders_created += 1

                                    folder_cache[current_path] = current_parent

                            target_folder_id = current_parent

                    # Extract file
                    filename = os.path.basename(zip_path)
                    ext = os.path.splitext(filename)[1].lower()

                    # Generate unique filename for storage
                    unique_filename = f"{uuid.uuid4().hex}{ext}"
                    file_path = (
                        get_library_files_dir() / unique_filename
                    )  # SEC-PATH-OK: unique_filename = uuid.uuid4().hex + ext

                    # Extract and save file
                    file_content = zf.read(zip_path)
                    with open(file_path, "wb") as f:
                        f.write(file_content)

                    # Classified once the bytes are on disk so a sliced 3MF
                    # named `Foo.3mf` inside the zip is recognised as sliced
                    # (#2993) rather than trusted to say so in its name.
                    file_type = classify_file_type(filename, file_path)

                    # Calculate hash
                    file_hash = calculate_file_hash(file_path)

                    # Extract metadata and thumbnail for 3MF files
                    metadata = {}
                    thumbnail_path = None
                    thumbnails_dir = get_library_thumbnails_dir()

                    if ext == ".3mf":
                        try:
                            parser = ThreeMFParser(str(file_path))
                            raw_metadata = parser.parse()

                            thumbnail_data = raw_metadata.get("_thumbnail_data")
                            thumbnail_ext = raw_metadata.get("_thumbnail_ext", ".png")

                            if thumbnail_data:
                                thumb_filename = f"{uuid.uuid4().hex}{thumbnail_ext}"
                                thumb_path = (
                                    thumbnails_dir / thumb_filename
                                )  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + thumbnail_ext
                                with open(thumb_path, "wb") as f:
                                    f.write(thumbnail_data)
                                thumbnail_path = str(thumb_path)

                            def clean_metadata(obj):
                                if isinstance(obj, dict):
                                    return {
                                        k: clean_metadata(v)
                                        for k, v in obj.items()
                                        if not isinstance(v, bytes) and k not in ("_thumbnail_data", "_thumbnail_ext")
                                    }
                                elif isinstance(obj, list):
                                    return [clean_metadata(i) for i in obj if not isinstance(i, bytes)]
                                elif isinstance(obj, bytes):
                                    return None
                                return obj

                            metadata = clean_metadata(raw_metadata)
                        except Exception as e:
                            logger.warning("Failed to parse 3MF from ZIP: %s", e)

                    elif ext == ".gcode":
                        try:
                            thumbnail_data = extract_gcode_thumbnail(file_path)
                            if thumbnail_data:
                                thumb_filename = f"{uuid.uuid4().hex}.png"
                                thumb_path = (
                                    thumbnails_dir / thumb_filename
                                )  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + ".png"
                                with open(thumb_path, "wb") as f:
                                    f.write(thumbnail_data)
                                thumbnail_path = str(thumb_path)
                        except Exception as e:
                            logger.warning("Failed to extract gcode thumbnail from ZIP: %s", e)

                    elif ext.lower() in IMAGE_EXTENSIONS:
                        thumbnail_path = create_image_thumbnail(file_path, thumbnails_dir)

                    elif ext.lower() == ".pdf":
                        thumbnail_path = await asyncio.to_thread(generate_pdf_thumbnail, file_path, thumbnails_dir)

                    elif ext == ".stl":
                        # Generate STL thumbnail if enabled. Pre-skip files
                        # below MIN_USABLE_STL_BYTES — they can't contain
                        # even a single triangle, and bulk-uploaded ZIPs of
                        # stub STLs would otherwise log one debug line per
                        # file via the empty-mesh branch in trimesh.load.
                        if generate_stl_thumbnails and len(file_content) >= MIN_USABLE_STL_BYTES:
                            thumbnail_path = generate_stl_thumbnail(file_path, thumbnails_dir)

                    # Create database entry (store relative paths for portability)
                    library_file = LibraryFile(
                        folder_id=target_folder_id,
                        filename=filename,
                        file_path=to_relative_path(file_path),
                        file_type=file_type,
                        file_size=len(file_content),
                        file_hash=file_hash,
                        thumbnail_path=to_relative_path(thumbnail_path) if thumbnail_path else None,
                        file_metadata=_without_print_name(metadata) if metadata else None,
                        created_by_id=current_user.id if current_user else None,
                    )
                    db.add(library_file)
                    await db.flush()
                    await db.refresh(library_file)

                    extracted_files.append(
                        ZipExtractResult(
                            filename=filename,
                            file_id=library_file.id,
                            folder_id=target_folder_id,
                        )
                    )

                    # Commit after each file to release database lock
                    # This prevents long-running transactions from blocking other requests
                    await db.commit()

                except Exception as e:
                    logger.error("Failed to extract %s: %s", zip_path, e)
                    errors.append(ZipExtractError(filename=os.path.basename(zip_path), error=str(e)))
                    # Rollback the failed file but continue with others
                    await db.rollback()

        return ZipExtractResponse(
            extracted=len(extracted_files),
            folders_created=folders_created,
            files=extracted_files,
            errors=errors,
        )

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid or corrupted ZIP file")
    except Exception as e:
        logger.error("ZIP extraction failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"ZIP extraction failed: {str(e)}")
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass  # Best-effort temp file cleanup; ignore if already removed


# ============ STL Thumbnail Batch Generation ============


@router.post("/generate-stl-thumbnails", response_model=BatchThumbnailResponse)
async def batch_generate_stl_thumbnails(
    request: BatchThumbnailRequest,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_UPDATE_ALL,
            Permission.LIBRARY_UPDATE_OWN,
        )
    ),
):
    """Generate thumbnails for STL and PDF files in batch.

    With library:update_all this covers every matching file; with only
    library:update_own it is narrowed to the caller's own files, the same
    rule as update_file. The File Manager offers the toolbar button and the
    per-file "Generate Thumbnail" entry to update_own users, and both land
    here.

    PDFs are included so the ones added before server-side PDF thumbnails
    existed can be backfilled without opening each preview. The route keeps
    its name for API compatibility.

    Can generate thumbnails for:
    - Specific file IDs (file_ids)
    - All STL/PDF files in a folder (folder_id)
    - All STL/PDF files missing thumbnails (all_missing=True)
    """
    thumbnails_dir = get_library_thumbnails_dir()
    results: list[BatchThumbnailResult] = []

    # Build query based on request
    query = LibraryFile.active().where(LibraryFile.file_type.in_(("stl", "pdf")))

    user, can_modify_all = auth_result
    if not can_modify_all:
        query = query.where(LibraryFile.created_by_id == user.id)

    if request.file_ids:
        # Specific files
        query = query.where(LibraryFile.id.in_(request.file_ids))
    elif request.folder_id is not None:
        # All STL/PDF files in a specific folder
        query = query.where(LibraryFile.folder_id == request.folder_id)
        if not request.all_missing:
            # If not specifically asking for missing thumbnails, get all
            pass
        else:
            query = query.where(LibraryFile.thumbnail_path.is_(None))
    elif request.all_missing:
        # All STL/PDF files without thumbnails
        query = query.where(LibraryFile.thumbnail_path.is_(None))
    else:
        # No criteria specified - return empty
        return BatchThumbnailResponse(
            processed=0,
            succeeded=0,
            failed=0,
            results=[],
        )

    result = await db.execute(query)
    target_files = result.scalars().all()

    succeeded = 0
    failed = 0

    for target_file in target_files:
        file_path = to_absolute_path(target_file.file_path)

        if not file_path or not file_path.exists():
            results.append(
                BatchThumbnailResult(
                    file_id=target_file.id,
                    filename=target_file.filename,
                    success=False,
                    error="File not found on disk",
                )
            )
            failed += 1
            continue

        try:
            if target_file.file_type == "pdf":
                thumbnail_path = await asyncio.to_thread(generate_pdf_thumbnail, file_path, thumbnails_dir)
            else:
                thumbnail_path = generate_stl_thumbnail(file_path, thumbnails_dir)

            if thumbnail_path:
                # Update database with relative path
                target_file.thumbnail_path = to_relative_path(thumbnail_path)
                await db.flush()
                results.append(
                    BatchThumbnailResult(
                        file_id=target_file.id,
                        filename=target_file.filename,
                        success=True,
                    )
                )
                succeeded += 1
            else:
                results.append(
                    BatchThumbnailResult(
                        file_id=target_file.id,
                        filename=target_file.filename,
                        success=False,
                        error="Thumbnail generation failed",
                    )
                )
                failed += 1
        except Exception as e:
            logger.error("Failed to generate thumbnail for %s: %s", target_file.filename, e)
            results.append(
                BatchThumbnailResult(
                    file_id=target_file.id,
                    filename=target_file.filename,
                    success=False,
                    error=str(e),
                )
            )
            failed += 1

    await db.commit()

    return BatchThumbnailResponse(
        processed=len(target_files),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


# ============ Queue Operations ============
# NOTE: These routes must be defined BEFORE /files/{file_id} to avoid path parameter conflicts


def is_sliced_file(filename: str) -> bool:
    """Check if a file is a sliced (printable) file.

    Sliced files are:
    - .gcode files
    - .3mf files that contain '.gcode.' in the name (e.g., filename.gcode.3mf)
    """
    lower = filename.lower()
    return lower.endswith(".gcode") or ".gcode." in lower


@router.post("/files/combine", response_model=FileUploadResponse)
async def combine_files(
    request: CombineFilesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_permission_if_auth_enabled(Permission.LIBRARY_UPLOAD)),
):
    """Combine STL library files into one multi-object 3MF.

    The slicer sidecar takes one model per slice, so putting several separate
    STLs (or several copies of one, #2999) on one plate means building that
    file first. The result is a new library file that slices like any other
    3MF; with auto-arrange on, the slicer lays the objects out on the bed.
    The sources are left untouched.
    """
    from backend.app.services.mesh_combine import CombinePart, MeshCombineError, combine_parts_to_3mf

    filename = request.filename.strip()
    if not filename.lower().endswith(".3mf"):
        filename = f"{filename}.3mf"
    try:
        validate_print_filename(filename)
    except InvalidFilenameError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if request.folder_id is not None:
        folder = (
            await db.execute(select(LibraryFolder).where(LibraryFolder.id == request.folder_id))
        ).scalar_one_or_none()
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")

    # Same per-row visibility the slice route applies: a READ_OWN caller must
    # not be able to pull another user's model into their own file by raw id.
    can_read_all = current_user is None or current_user.has_permission(Permission.LIBRARY_READ_ALL.value)

    # The same file listed twice is one object with the copies added up, so
    # its mesh is loaded and stored once. Order follows first appearance.
    copies_by_id: dict[int, int] = {}
    for item in request.items:
        copies_by_id[item.file_id] = copies_by_id.get(item.file_id, 0) + item.copies

    rows = (await db.execute(LibraryFile.active().where(LibraryFile.id.in_(copies_by_id)))).scalars().all()
    by_id = {row.id: row for row in rows}

    # Gate every source before touching any of them on disk, so the answer for
    # a file the caller can't see is the same 404 whatever else is in the list.
    sources = [_ensure_library_file_visible(by_id.get(file_id), current_user, can_read_all) for file_id in copies_by_id]

    parts: list[CombinePart] = []
    for lib_file in sources:
        if not lib_file.filename.lower().endswith(".stl"):
            raise HTTPException(status_code=400, detail=f"Only STL files can be combined: {lib_file.filename}")
        src_path = _resolve_source_disk_path(lib_file)
        if src_path is None or not src_path.exists():
            raise HTTPException(status_code=404, detail=f"Source file missing on disk: {lib_file.filename}")
        parts.append(CombinePart(name=lib_file.filename, path=src_path, copies=copies_by_id[lib_file.id]))

    try:
        content = await asyncio.to_thread(combine_parts_to_3mf, parts)
    except MeshCombineError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # The preview is embedded as Metadata/thumbnail.png by combine_parts_to_3mf,
    # so ThreeMFParser picks it up here like any other 3MF's thumbnail. Loading
    # the combined file back to render one would expand every copy.
    library_file, _ = await save_3mf_bytes_to_library(
        db,
        file_bytes=content,
        filename=filename,
        folder_id=request.folder_id,
        source_type="combined",
        owner_id=current_user.id if current_user else None,
    )

    return FileUploadResponse(
        id=library_file.id,
        filename=library_file.filename,
        file_type=library_file.file_type,
        file_size=library_file.file_size,
        thumbnail_path=library_file.thumbnail_path,
        metadata=library_file.file_metadata,
    )


@router.post("/files/add-to-queue", response_model=AddToQueueResponse)
async def add_files_to_queue(
    request: AddToQueueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_permission_if_auth_enabled(Permission.QUEUE_CREATE)),
):
    """Add library files to the print queue.

    Only sliced files (.gcode or .gcode.3mf) can be added to the queue.
    The archive will be created automatically when the print starts.

    A caller may name a printer or a target model for the whole batch; with
    neither, each file is aimed at the model it says it was sliced for. The
    gates are the ones ``POST /queue/`` applies to a single item, because an
    item that reaches the scheduler through this route has to be as printable
    as one that reaches it through that one (#3112).
    """
    added: list[AddToQueueResult] = []
    errors: list[AddToQueueError] = []

    # Batch-level targeting. Rejected outright rather than per file: the whole
    # request names one destination, so a bad one is not a property of any
    # single file and reporting it fourteen times would say nothing extra.
    target_model_norm = normalize_model_name(request.target_model)
    if request.printer_id is not None and target_model_norm:
        raise HTTPException(400, "Cannot specify both printer_id and target_model")

    if request.printer_id is not None:
        printer_row = (await db.execute(select(Printer).where(Printer.id == request.printer_id))).scalar_one_or_none()
        if not printer_row:
            raise HTTPException(400, "Printer not found")

    # Active printers of every model, read once, and only when the batch has no
    # printer of its own -- with one named, neither the check below nor the
    # inference in the loop consults it. The explicit target is validated for
    # the same reason POST /queue/ validates: a model nobody owns is a queue
    # item that waits forever. The inferred target reads the same set and
    # silently declines when it finds nothing, because there, owning no such
    # printer is the user's situation rather than their mistake -- the file
    # still queues, as the unassigned row it has always been.
    active_models: set[str] = set()
    if request.printer_id is None:
        active_models = {
            model
            for (model,) in (
                await db.execute(select(Printer.model).where(Printer.is_active == True).distinct())  # noqa: E712
            ).all()
            if model
        }
        if target_model_norm and target_model_norm not in active_models:
            raise HTTPException(400, f"No active printers for model: {target_model_norm}")

    # Get all requested files
    result = await db.execute(LibraryFile.active().where(LibraryFile.id.in_(request.file_ids)))
    files = {f.id: f for f in result.scalars().all()}

    # Ownership-scoped reads apply here as everywhere else in this module: a
    # file the caller may not read is a file they may not print. Dropped from
    # the map rather than refused by name, so the per-file error below is the
    # same "File not found" an unknown id gets and the response says nothing
    # about which ids exist. Ownerless rows need LIBRARY_READ_ALL, matching
    # _ensure_library_file_visible.
    if current_user is not None and not current_user.has_permission(Permission.LIBRARY_READ_ALL.value):
        files = {fid: f for fid, f in files.items() if f.created_by_id == current_user.id}

    # Project attribution (#1897): a file queued from a project-linked folder
    # inherits that project, so the resulting archive counts toward the
    # project's progress. A file's own project link wins over its folder's.
    folder_ids = {f.folder_id for f in files.values() if f.folder_id is not None}
    folder_projects: dict[int, int | None] = {}
    if folder_ids:
        folder_result = await db.execute(
            select(LibraryFolder.id, LibraryFolder.project_id).where(LibraryFolder.id.in_(folder_ids))
        )
        folder_projects = dict(folder_result.all())

    # Get max position for queue ordering
    pos_result = await db.execute(select(func.coalesce(func.max(PrintQueueItem.position), 0)))
    max_position = pos_result.scalar() or 0

    # There is no per-job ask-for-outcome toggle on a bulk add, so the rows take
    # the same default the print dialog seeds itself from (#1898).
    confirm_outcome = await confirm_outcome_for_new_queue_item(db)

    for file_id in request.file_ids:
        lib_file = files.get(file_id)

        if not lib_file:
            errors.append(AddToQueueError(file_id=file_id, filename="(not found)", error="File not found"))
            continue

        # Validate file is sliced
        if not is_sliced_file(lib_file.filename):
            errors.append(
                AddToQueueError(
                    file_id=file_id,
                    filename=lib_file.filename,
                    error="Not a sliced file. Only .gcode or .gcode.3mf files can be printed.",
                )
            )
            continue

        try:
            # Verify file exists on disk
            file_path = Path(app_settings.base_dir) / lib_file.file_path

            if not file_path.exists():
                errors.append(
                    AddToQueueError(file_id=file_id, filename=lib_file.filename, error="File not found on disk")
                )
                continue

            # The Bambu SD card is FAT32/exFAT, so an illegal character 553s at
            # upload time. POST /queue/ rejects those at queue time (#1540) and
            # this route did not, which turned a nameable mistake into a print
            # that failed hours later.
            try:
                validate_print_filename(lib_file.filename)
            except InvalidFilenameError as e:
                errors.append(AddToQueueError(file_id=file_id, filename=lib_file.filename, error=str(e)))
                continue

            # Where this file is aimed. An explicit printer wins; an explicit
            # model applies to every file and has to be one this file can
            # legally run on; with neither, the file's own declaration is used
            # when some active printer answers to it.
            item_printer_id = request.printer_id
            item_target_model: str | None = None
            if item_printer_id is None:
                if target_model_norm:
                    sliced_for = (lib_file.file_metadata or {}).get("sliced_for_model")
                    if not is_gcode_compatible(sliced_for, target_model_norm):
                        errors.append(
                            AddToQueueError(
                                file_id=file_id,
                                filename=lib_file.filename,
                                error=(
                                    f"File was sliced for {sliced_for} and cannot be dispatched to "
                                    f"{target_model_norm} printers"
                                ),
                            )
                        )
                        continue
                    item_target_model = target_model_norm
                else:
                    inferred = resolve_variant_model(lib_file)
                    item_target_model = inferred if inferred in active_models else None

            # Filament the scheduler must match before handing a model-based
            # item to hardware. Without it the item goes to whichever printer
            # of that model is idle, whatever is loaded in it.
            required_filament_types = None
            if item_target_model:
                # POST /queue/'s own extractor, borrowed rather than
                # reimplemented: a second copy of this rule is a second thing
                # to keep in step.
                #
                # Off the loop, unlike there: that route parses one 3MF per
                # request and this one parses every file in the batch, so on a
                # bulk add of a few hundred -- especially from an external
                # folder on a NAS -- the zip reads add up to a stall the whole
                # event loop takes, status ingest included.
                filament_types = await asyncio.to_thread(_extract_filament_types_from_3mf, file_path)
                if filament_types:
                    required_filament_types = json.dumps(filament_types)

            # Create queue item referencing library file (archive created at print start)
            max_position += 1
            queue_item = PrintQueueItem(
                printer_id=item_printer_id,
                target_model=item_target_model,
                required_filament_types=required_filament_types,
                library_file_id=file_id,
                project_id=lib_file.project_id
                or (folder_projects.get(lib_file.folder_id) if lib_file.folder_id is not None else None),
                position=max_position,
                status="pending",
                confirm_outcome=confirm_outcome,
                # Without this the row is ownerless, and `queue:read_own` filters
                # on `created_by_id` — so the user who queued the file could not
                # see it in their own queue.
                created_by_id=current_user.id if current_user else None,
            )
            db.add(queue_item)

            await db.flush()  # Get queue_item.id

            added.append(
                AddToQueueResult(
                    file_id=file_id,
                    filename=lib_file.filename,
                    queue_item_id=queue_item.id,
                )
            )

        except Exception as e:
            logger.exception("Error adding file %s to queue", file_id)
            errors.append(AddToQueueError(file_id=file_id, filename=lib_file.filename, error=str(e)))

    # Nothing queued and something to say about why. Returning 200 here is what
    # made this look like a working call that quietly did nothing: a client that
    # checks the status code sees success, and the reasons sit in a body it had
    # no cause to read (#3112). Partial success stays 200 -- items really were
    # created, and the per-file errors belong with them.
    if not added and errors:
        raise HTTPException(
            400,
            detail={
                "message": "No files could be added to the queue.",
                "errors": [e.model_dump() for e in errors],
            },
        )

    await db.commit()

    return AddToQueueResponse(added=added, errors=errors)


@router.get("/files/{file_id}/plates")
async def get_library_file_plates(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get available plates from a multi-plate 3MF library file.

    Returns a list of plates with their index, name, thumbnail availability,
    and filament requirements. For single-plate exports, returns a single plate.
    """
    import json

    import defusedxml.ElementTree as ET

    user, can_read_all = auth_result
    # Get the library file
    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    lib_file = _ensure_library_file_visible(result.scalar_one_or_none(), user, can_read_all)

    if not lib_file:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = Path(app_settings.base_dir) / lib_file.file_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    # Only 3MF files have plates
    if not lib_file.filename.lower().endswith(".3mf"):
        return {"file_id": file_id, "filename": lib_file.filename, "plates": [], "is_multi_plate": False}

    plates = []
    # Printer / process preset names the 3MF was prepared with — used by the
    # SliceModal to default its dropdowns (#1325). Initialised here so the
    # final return never raises NameError when the file isn't a valid zip.
    embedded_presets: dict[str, str | None] = {"printer": None, "process": None}
    # Process settings the designer changed away from the stock preset (#2622).
    # Offered in the SliceModal so a cross-printer re-slice can carry them
    # instead of silently losing them to the picked process profile.
    design_overrides: list[dict] = []

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            namelist = zf.namelist()
            embedded_presets = extract_embedded_presets_from_3mf(zf)
            if _PROJECT_SETTINGS_PATH in namelist:
                try:
                    design_overrides = [
                        o._asdict()
                        for o in overrides_from_config(json.loads(zf.read(_PROJECT_SETTINGS_PATH).decode("utf-8")))
                    ]
                except (ValueError, OSError, KeyError):
                    design_overrides = []

            # Find all plate gcode files to determine available plates
            gcode_files = [n for n in namelist if n.startswith("Metadata/plate_") and n.endswith(".gcode")]

            # If no gcode is present (source-only or unsliced), fall back to plate JSON/PNG
            plate_indices: list[int] = []
            if gcode_files:
                # Extract plate indices from gcode filenames
                for gf in gcode_files:
                    try:
                        plate_str = gf[15:-6]  # Remove "Metadata/plate_" and ".gcode"
                        plate_indices.append(int(plate_str))
                    except ValueError:
                        pass  # Skip gcode file with non-numeric plate index
            else:
                plate_json_files = [n for n in namelist if n.startswith("Metadata/plate_") and n.endswith(".json")]
                plate_png_files = [
                    n
                    for n in namelist
                    if n.startswith("Metadata/plate_")
                    and n.endswith(".png")
                    and "_small" not in n
                    and "no_light" not in n
                ]
                plate_name_candidates = plate_json_files + plate_png_files
                plate_re = re.compile(r"^Metadata/plate_(\d+)\.(json|png)$")
                seen_indices: set[int] = set()
                for name in plate_name_candidates:
                    match = plate_re.match(name)
                    if match:
                        try:
                            index = int(match.group(1))
                        except ValueError:
                            continue
                        if index in seen_indices:
                            continue
                        seen_indices.add(index)
                        plate_indices.append(index)

            if not plate_indices:
                # No plate metadata found
                return {"file_id": file_id, "filename": lib_file.filename, "plates": [], "is_multi_plate": False}

            plate_indices.sort()

            # Parse model_settings.config for plate names + object assignments
            plate_names = {}
            plate_object_ids: dict[int, list[str]] = {}
            object_names_by_id: dict[str, str] = {}
            if "Metadata/model_settings.config" in namelist:
                try:
                    model_content = zf.read("Metadata/model_settings.config").decode()
                    model_root = ET.fromstring(model_content)
                    for obj_elem in model_root.findall(".//object"):
                        obj_id = obj_elem.get("id")
                        if not obj_id:
                            continue
                        name_meta = obj_elem.find("metadata[@key='name']")
                        obj_name = name_meta.get("value") if name_meta is not None else None
                        if obj_name:
                            object_names_by_id[obj_id] = obj_name

                    for plate_elem in model_root.findall(".//plate"):
                        plater_id = None
                        plater_name = None
                        for meta in plate_elem.findall("metadata"):
                            key = meta.get("key")
                            value = meta.get("value")
                            if key == "plater_id" and value:
                                try:
                                    plater_id = int(value)
                                except ValueError:
                                    pass  # Ignore plate with non-numeric plater_id
                            elif key == "plater_name" and value:
                                plater_name = value.strip()
                        if plater_id is not None and plater_name:
                            plate_names[plater_id] = plater_name

                        if plater_id is not None:
                            for instance_elem in plate_elem.findall("model_instance"):
                                for inst_meta in instance_elem.findall("metadata"):
                                    if inst_meta.get("key") == "object_id":
                                        obj_id = inst_meta.get("value")
                                        if not obj_id:
                                            continue
                                        plate_object_ids.setdefault(plater_id, [])
                                        if obj_id not in plate_object_ids[plater_id]:
                                            plate_object_ids[plater_id].append(obj_id)
                except Exception:
                    pass  # model_settings.config is optional; skip if missing or malformed

            # Parse slice_info.config for plate metadata
            plate_metadata = {}
            if "Metadata/slice_info.config" in namelist:
                content = zf.read("Metadata/slice_info.config").decode()
                root = ET.fromstring(content)

                for plate_elem in root.findall(".//plate"):
                    plate_info = {"filaments": [], "prediction": None, "weight": None, "name": None, "objects": []}

                    plate_index = None
                    for meta in plate_elem.findall("metadata"):
                        key = meta.get("key")
                        value = meta.get("value")
                        if key == "index" and value:
                            try:
                                plate_index = int(value)
                            except ValueError:
                                pass  # Ignore plate with non-numeric index
                        elif key == "prediction" and value:
                            try:
                                plate_info["prediction"] = int(value)
                            except ValueError:
                                pass  # Leave prediction as None if not a valid integer
                        elif key == "weight" and value:
                            try:
                                plate_info["weight"] = float(value)
                            except ValueError:
                                pass  # Leave weight as None if not a valid number

                    # Get filaments used in this plate
                    for filament_elem in plate_elem.findall("filament"):
                        filament_id = filament_elem.get("id")
                        filament_type = filament_elem.get("type", "")
                        filament_color = filament_elem.get("color", "")
                        used_g = filament_elem.get("used_g", "0")
                        used_m = filament_elem.get("used_m", "0")

                        try:
                            used_grams = float(used_g)
                        except (ValueError, TypeError):
                            used_grams = 0

                        if used_grams > 0 and filament_id:
                            plate_info["filaments"].append(
                                {
                                    "slot_id": int(filament_id),
                                    "type": filament_type,
                                    "color": filament_color,
                                    "used_grams": round(used_grams, 1),
                                    "used_meters": float(used_m) if used_m else 0,
                                }
                            )

                    plate_info["filaments"].sort(key=lambda x: x["slot_id"])

                    # Collect object names
                    for obj_elem in plate_elem.findall("object"):
                        obj_name = obj_elem.get("name")
                        if obj_name and obj_name not in plate_info["objects"]:
                            plate_info["objects"].append(obj_name)

                    # Set plate name
                    if plate_index is not None:
                        custom_name = plate_names.get(plate_index)
                        if custom_name:
                            plate_info["name"] = custom_name
                        elif plate_info["objects"]:
                            plate_info["name"] = plate_info["objects"][0]
                        plate_metadata[plate_index] = plate_info

            # Parse plate_*.json for object lists when slice_info is missing
            plate_json_objects: dict[int, list[str]] = {}
            for name in namelist:
                match = re.match(r"^Metadata/plate_(\d+)\.json$", name)
                if not match:
                    continue
                try:
                    plate_index = int(match.group(1))
                except ValueError:
                    continue
                try:
                    payload = json.loads(zf.read(name).decode())
                    bbox_objects = payload.get("bbox_objects", [])
                    names: list[str] = []
                    for obj in bbox_objects:
                        obj_name = obj.get("name") if isinstance(obj, dict) else None
                        if obj_name and obj_name not in names:
                            names.append(obj_name)
                    if names:
                        plate_json_objects[plate_index] = names
                except Exception:
                    continue

            # Build plate list
            for idx in plate_indices:
                meta = plate_metadata.get(idx, {})
                has_thumbnail = f"Metadata/plate_{idx}.png" in namelist
                objects = meta.get("objects", [])
                if not objects:
                    objects = plate_json_objects.get(idx, [])
                if not objects and plate_object_ids.get(idx):
                    objects = [
                        object_names_by_id.get(obj_id, f"Object {obj_id}") for obj_id in plate_object_ids.get(idx, [])
                    ]

                plate_name = meta.get("name")
                if not plate_name:
                    plate_name = plate_names.get(idx)
                if not plate_name and objects:
                    plate_name = objects[0]

                plates.append(
                    {
                        "index": idx,
                        "name": plate_name,
                        "objects": objects,
                        "object_count": len(objects),
                        "has_thumbnail": has_thumbnail,
                        "thumbnail_url": f"/api/v1/library/files/{file_id}/plate-thumbnail/{idx}"
                        if has_thumbnail
                        else None,
                        "print_time_seconds": meta.get("prediction"),
                        "filament_used_grams": meta.get("weight"),
                        "filaments": meta.get("filaments", []),
                    }
                )

    except Exception as e:
        logger.warning("Failed to parse plates from library file %s: %s", file_id, e)

    return {
        "file_id": file_id,
        "filename": lib_file.filename,
        "plates": plates,
        "is_multi_plate": len(plates) > 1,
        "embedded_printer": embedded_presets["printer"],
        "embedded_process": embedded_presets["process"],
        "design_overrides": design_overrides,
    }


@router.get("/files/{file_id}/plate-thumbnail/{plate_index}")
async def get_library_file_plate_thumbnail(
    file_id: int,
    plate_index: int,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_media_token_ownership(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get the thumbnail image for a specific plate from a library file.

    Ownership-gated on the same terms as the file itself (#3025).
    """
    from starlette.responses import Response

    user, can_read_all = auth_result
    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    lib_file = _ensure_library_file_visible(result.scalar_one_or_none(), user, can_read_all)

    file_path = Path(app_settings.base_dir) / lib_file.file_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            thumb_path = f"Metadata/plate_{plate_index}.png"
            if thumb_path in zf.namelist():
                data = zf.read(thumb_path)
                return Response(content=data, media_type="image/png")
    except Exception:
        pass  # Archive unreadable or thumbnail missing; fall through to 404

    raise HTTPException(status_code=404, detail=f"Thumbnail for plate {plate_index} not found")


async def _try_preview_slice_filaments(
    db: AsyncSession,
    *,
    kind: str,
    source_id: int,
    plate_id: int,
    file_path: Path,
    request_id: str | None = None,
) -> list[dict] | None:
    """Run a preview slice via the user's configured sidecar. Same shape as
    the matching helper in archives.py — see that module for rationale.

    ``request_id``: when supplied, forwarded to the sidecar so the
    SliceModal's inline spinner + toast can poll the matching progress
    endpoint and show "Generating G-code (45%)" for the preview as well.
    """
    from backend.app.api.routes.settings import get_setting
    from backend.app.services.slice_preview import get_preview_filaments
    from backend.app.services.slicer_api import get_stall_timeout_seconds

    preferred = (await get_setting(db, "preferred_slicer")) or "bambu_studio"
    if preferred == "orcaslicer":
        configured = await get_setting(db, "orcaslicer_api_url")
        api_url = (configured or app_settings.slicer_api_url).strip()
    elif preferred == "bambu_studio":
        configured = await get_setting(db, "bambu_studio_api_url")
        api_url = (configured or app_settings.bambu_studio_api_url).strip()
    else:
        return None
    if not api_url:
        return None

    try:
        file_bytes = file_path.read_bytes()
    except OSError:
        return None
    return await get_preview_filaments(
        kind=kind,
        source_id=source_id,
        plate_id=plate_id,
        file_bytes=file_bytes,
        file_name=file_path.name,
        api_url=api_url,
        request_id=request_id,
        timeout_seconds=await get_stall_timeout_seconds(db),
    )


@router.get("/files/{file_id}/filament-requirements")
async def get_library_file_filament_requirements(
    file_id: int,
    plate_id: int | None = None,
    request_id: str | None = None,
    full_slots: bool = False,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get filament requirements from a library file.

    Parses the 3MF file to extract filament slot IDs, types, colors, and usage.
    This enables AMS slot assignment when printing from the file manager.

    Args:
        file_id: The library file ID
        plate_id: Optional plate index to get filaments for a specific plate
        full_slots: Return one entry per *project* slot rather than only the
            slots the plate consumes. See :func:`_expand_to_project_slots`.
            Only the slice modal wants this; print-time AMS matching must keep
            the used-only list.
    """
    import defusedxml.ElementTree as ET

    user, can_read_all = auth_result
    # Get the library file
    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    lib_file = _ensure_library_file_visible(result.scalar_one_or_none(), user, can_read_all)

    # Get the full file path
    file_path = Path(app_settings.base_dir) / lib_file.file_path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    # Only 3MF files have parseable filament info
    if not lib_file.filename.lower().endswith(".3mf"):
        return {"file_id": file_id, "filename": lib_file.filename, "plate_id": plate_id, "filaments": []}

    filaments = []

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # Parse slice_info.config for filament requirements
            if "Metadata/slice_info.config" in zf.namelist():
                content = zf.read("Metadata/slice_info.config").decode()
                root = ET.fromstring(content)

                if plate_id is not None:
                    # Find filaments for specific plate
                    for plate_elem in root.findall(".//plate"):
                        # Check if this is the requested plate
                        plate_index = None
                        for meta in plate_elem.findall("metadata"):
                            if meta.get("key") == "index":
                                try:
                                    plate_index = int(meta.get("value", ""))
                                except ValueError:
                                    pass  # Skip plate with non-numeric index value
                                break

                        if plate_index == plate_id:
                            # Extract filaments from this plate
                            for filament_elem in plate_elem.findall("filament"):
                                filament_id = filament_elem.get("id")
                                filament_type = filament_elem.get("type", "")
                                filament_color = filament_elem.get("color", "")
                                used_g = filament_elem.get("used_g", "0")
                                used_m = filament_elem.get("used_m", "0")

                                tray_info_idx = filament_elem.get("tray_info_idx", "")

                                try:
                                    used_grams = float(used_g)
                                except (ValueError, TypeError):
                                    used_grams = 0

                                if used_grams > 0 and filament_id:
                                    filaments.append(
                                        {
                                            "slot_id": int(filament_id),
                                            "type": filament_type,
                                            "color": filament_color,
                                            "used_grams": round(used_grams, 1),
                                            "used_meters": float(used_m) if used_m else 0,
                                            "tray_info_idx": tray_info_idx,
                                            # Sliced output already pre-filtered by used_g>0,
                                            # so every entry that survives is in fact used by
                                            # this plate. Print-dispatch consumers ignore the
                                            # flag; SliceModal uses it to enable/disable rows.
                                            "used_in_plate": True,
                                        }
                                    )
                            break
                else:
                    # Extract all filaments with used_g > 0 (for single-plate or overview)
                    for filament_elem in root.findall(".//filament"):
                        filament_id = filament_elem.get("id")
                        filament_type = filament_elem.get("type", "")
                        filament_color = filament_elem.get("color", "")
                        used_g = filament_elem.get("used_g", "0")
                        used_m = filament_elem.get("used_m", "0")

                        tray_info_idx = filament_elem.get("tray_info_idx", "")

                        try:
                            used_grams = float(used_g)
                        except (ValueError, TypeError):
                            used_grams = 0

                        if used_grams > 0 and filament_id:
                            filaments.append(
                                {
                                    "slot_id": int(filament_id),
                                    "type": filament_type,
                                    "color": filament_color,
                                    "used_grams": round(used_grams, 1),
                                    "used_meters": float(used_m) if used_m else 0,
                                    "tray_info_idx": tray_info_idx,
                                    "used_in_plate": True,
                                }
                            )

            # Re-slicing a source that already carries slice_info (#2712).
            # The block above answers "what does this plate consume", which is
            # what print-time AMS matching needs. The slice modal needs "what
            # slots exist", because its list is positional and the CLI binds
            # entry N to slot N — so a source using only slot 4 handed the
            # user's single pick to slot 1 and sliced slot 4 with the source's
            # embedded default. Widen here rather than in the modal so the
            # print path keeps the narrow list it depends on.
            if full_slots and filaments:
                filaments = expand_to_project_slots(zf, filaments)

            # Unsliced project files: slice_info had no per-plate data.
            # Return the FULL project_settings.config AMS slot list so
            # the slicer CLI receives a profile for every project slot
            # (otherwise it silently fills the gap from embedded
            # defaults — surfaces as "I picked white but the print has
            # grey" because the source's grey support filament leaks
            # into the output). Use the preview slice to mark which
            # slots the picked plate actually consumes; the SliceModal
            # disables the unused rows so the user only interacts with
            # the dropdowns that matter, while the backend still has
            # the complete list to pass to the CLI.
            if not filaments:
                project_filaments = extract_project_filaments_from_3mf(zf)
                used_slot_ids: set[int] = set()
                if project_filaments and plate_id is not None:
                    preview = await _try_preview_slice_filaments(
                        db,
                        kind="library_file",
                        source_id=file_id,
                        plate_id=plate_id,
                        file_path=file_path,
                        request_id=request_id,
                    )
                    if preview is not None:
                        used_slot_ids = {f["slot_id"] for f in preview}
                # Default to "every slot is used" when preview-slice
                # didn't produce data: better to over-enable dropdowns
                # than under-enable and have the user unable to pick a
                # filament the plate actually uses.
                fallback_all_used = not used_slot_ids
                for f in project_filaments:
                    f["used_in_plate"] = fallback_all_used or f["slot_id"] in used_slot_ids
                filaments = project_filaments

            # Sort by slot ID
            filaments.sort(key=lambda x: x["slot_id"])

            # Enrich with nozzle mapping for dual-nozzle printers
            nozzle_mapping = extract_nozzle_mapping_from_3mf(zf)
            if nozzle_mapping:
                for filament in filaments:
                    filament["nozzle_id"] = nozzle_mapping.get(filament["slot_id"])

            # Nozzle-rack machines (#1784): the print dialog offers a rack
            # position per filament group, which needs the group table as well
            # as the carriage above.
            annotate_rack_groups(filaments, file_path, plate_id)

    except Exception as e:
        logger.warning("Failed to parse filament requirements from library file %s: %s", file_id, e)

    return {
        "file_id": file_id,
        "filename": lib_file.filename,
        "plate_id": plate_id,
        "filaments": filaments,
    }


# ============ File Detail Endpoints ============


@router.get("/files/{file_id}", response_model=FileResponseSchema)
async def get_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get a file by ID with full details."""
    user, can_read_all = auth_result
    result = await db.execute(
        LibraryFile.active().options(selectinload(LibraryFile.created_by)).where(LibraryFile.id == file_id)
    )
    file = _ensure_library_file_visible(result.scalar_one_or_none(), user, can_read_all)

    # Get folder name
    folder_name = None
    if file.folder_id:
        folder_result = await db.execute(select(LibraryFolder.name).where(LibraryFolder.id == file.folder_id))
        folder_name = folder_result.scalar()

    # Get project name
    project_name = None
    if file.project_id:
        project_result = await db.execute(select(Project.name).where(Project.id == file.project_id))
        project_name = project_result.scalar()

    # Get duplicates
    duplicates = []
    duplicate_count = 0
    if file.file_hash:
        dup_result = await db.execute(
            select(LibraryFile, LibraryFolder.name)
            .outerjoin(LibraryFolder, LibraryFile.folder_id == LibraryFolder.id)
            .where(
                LibraryFile.file_hash == file.file_hash,
                LibraryFile.id != file.id,
                LibraryFile.deleted_at.is_(None),
            )
        )
        for dup_file, dup_folder_name in dup_result.all():
            duplicates.append(
                FileDuplicate(
                    id=dup_file.id,
                    filename=dup_file.filename,
                    folder_id=dup_file.folder_id,
                    folder_name=dup_folder_name,
                    created_at=dup_file.created_at,
                )
            )
        duplicate_count = len(duplicates)

    # Extract key metadata fields
    print_name = None
    print_time = None
    filament_grams = None
    sliced_for_model = None
    if file.file_metadata:
        print_name = file.file_metadata.get("print_name")
        print_time = file.file_metadata.get("print_time_seconds")
        filament_grams = file.file_metadata.get("filament_used_grams")
        sliced_for_model = file.file_metadata.get("sliced_for_model")

    return FileResponseSchema(
        id=file.id,
        folder_id=file.folder_id,
        folder_name=folder_name,
        project_id=file.project_id,
        project_name=project_name,
        filename=file.filename,
        file_path=file.file_path,
        file_type=file.file_type,
        file_size=file.file_size,
        file_hash=file.file_hash,
        thumbnail_path=file.thumbnail_path,
        metadata=file.file_metadata,
        print_count=file.print_count,
        last_printed_at=file.last_printed_at,
        notes=file.notes,
        external_url=file.external_url,
        photos=list(file.photos or []),
        source_url=file.source_url,
        duplicates=duplicates if duplicates else None,
        duplicate_count=duplicate_count,
        created_by_id=file.created_by_id,
        created_by_username=file.created_by.username if file.created_by else None,
        created_at=file.created_at,
        updated_at=file.updated_at,
        print_name=print_name,
        print_time_seconds=print_time,
        filament_used_grams=filament_grams,
        sliced_for_model=sliced_for_model,
    )


@router.put("/files/{file_id}", response_model=FileResponseSchema)
async def update_file(
    file_id: int,
    data: FileUpdate,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_UPDATE_ALL,
            Permission.LIBRARY_UPDATE_OWN,
        )
    ),
):
    """Update a file's metadata."""
    user, can_modify_all = auth_result

    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    file = result.scalar_one_or_none()

    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Ownership check
    if not can_modify_all:
        if file.created_by_id != user.id:
            raise HTTPException(status_code=403, detail="You can only update your own files")

    if data.filename is not None:
        # Bambu printer SD cards are FAT32/exFAT; reject the same set Bambu
        # Studio refuses on save so we fail here with a clear message
        # instead of an obscure FTP 553 at print time (#1540).
        try:
            validate_print_filename(data.filename)
        except InvalidFilenameError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        file.filename = data.filename
        # No print_name to keep in sync — library files display by filename,
        # and _without_print_name strips the embedded 3MF Title on import (#1489).

    if data.folder_id is not None:
        if data.folder_id == 0:
            file.folder_id = None
        else:
            # Verify folder exists
            folder_result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == data.folder_id))
            if not folder_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Folder not found")
            file.folder_id = data.folder_id

    if data.project_id is not None:
        if data.project_id == 0:
            file.project_id = None
        else:
            # Verify project exists
            project_result = await db.execute(select(Project).where(Project.id == data.project_id))
            if not project_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Project not found")
            file.project_id = data.project_id

    if data.notes is not None:
        file.notes = data.notes if data.notes else None

    if data.external_url is not None:
        file.external_url = data.external_url.strip() or None

    await db.commit()
    await db.refresh(file)

    # Return full response. Bypass get_file's ownership gate — caller already
    # passed update_file's ownership gate above, so we re-fetch + serialise
    # directly instead of calling the route function (which would try to
    # evaluate its own Depends() at call time and trip a TypeError).
    return await get_file(file_id, db, auth_result=(None, True))


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_DELETE_ALL,
            Permission.LIBRARY_DELETE_OWN,
        )
    ),
):
    """Move a file to the trash (soft-delete).

    The file's bytes and thumbnail stay on disk until the trash sweeper
    hard-deletes the row after the retention window (see #1008). External
    files skip the trash entirely — they can't be restored from disk and the
    underlying file is outside PrintLab's control, so we just drop the DB
    record and thumbnail.
    """
    user, can_modify_all = auth_result

    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    file = result.scalar_one_or_none()

    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Ownership check
    if not can_modify_all:
        if file.created_by_id != user.id:
            raise HTTPException(status_code=403, detail="You can only delete your own files")

    if file.is_external:
        # External files bypass the trash — just drop the DB row + our thumbnail.
        abs_thumb_path = to_absolute_path(file.thumbnail_path)
        if abs_thumb_path and abs_thumb_path.exists():
            try:
                abs_thumb_path.unlink()
            except OSError as e:
                logger.warning("Failed to delete thumbnail from disk: %s", e)
        from backend.app.services.library_trash import delete_dependent_variants, release_queue_references

        await delete_dependent_variants(db, [file.id])
        await release_queue_references(db, [file.id])
        remove_library_photos_dir(file.id)
        await db.delete(file)
        await db.commit()
        return {"status": "success", "message": "File deleted", "trashed": False}

    # Managed file: soft-delete. Sweeper removes bytes + thumbnail after retention.
    file.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "success", "message": "File moved to trash", "trashed": True}


# ============ File Content Endpoints ============


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Download a file."""
    user, can_read_all = auth_result
    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    file = _ensure_library_file_visible(result.scalar_one_or_none(), user, can_read_all)

    abs_path = to_absolute_path(file.file_path)
    if not abs_path or not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FastAPIFileResponse(
        str(abs_path),
        filename=file.filename,
        media_type="application/octet-stream",
    )


@router.post("/files/{file_id}/slicer-token")
async def create_library_slicer_token(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Create a short-lived download token for opening files in slicer applications.

    Slicer protocol handlers (bambustudioopen://, orcaslicer://) cannot send
    auth headers, so they use this token in the URL path instead.
    """
    from backend.app.core.auth import create_slicer_download_token

    user, can_read_all = auth_result
    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    _ensure_library_file_visible(result.scalar_one_or_none(), user, can_read_all)

    token = await create_slicer_download_token("library", file_id)
    return {"token": token}


@router.get("/files/{file_id}/dl/{token}/{filename}")
async def download_library_file_for_slicer(
    file_id: int,
    token: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a library file using a slicer download token.

    Token-authenticated (no auth headers needed). The token is short-lived and
    file-bound, created by POST /files/{file_id}/slicer-token, and redeemable
    for the rest of its TTL rather than exactly once -- the slicer is a separate
    process that may fetch the URL more than once (#3029).
    Filename is at the end of the URL so slicers can detect the file format.
    """
    from backend.app.core.auth import verify_slicer_download_token

    if not await verify_slicer_download_token(token, "library", file_id, single_use=False):
        raise HTTPException(status_code=403, detail="Invalid or expired download token")

    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    abs_path = to_absolute_path(file.file_path)
    if not abs_path or not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FastAPIFileResponse(
        str(abs_path),
        filename=file.filename,
        media_type="application/octet-stream",
    )


@router.get("/files/{file_id}/thumbnail")
async def get_thumbnail(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_media_token_ownership(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get a file's thumbnail.

    Accepts a media token in ``?token=`` because <img> cannot send headers.
    Ownership is enforced here rather than assumed from the credential: until
    #3025 this route took the anonymous camera-stream token, which carried no
    principal, so any holder could read any user's thumbnail by walking IDs.
    """
    user, can_read_all = auth_result
    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    file = _ensure_library_file_visible(result.scalar_one_or_none(), user, can_read_all)

    abs_thumb_path = to_absolute_path(file.thumbnail_path)
    if not abs_thumb_path or not abs_thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    # Detect media type from extension
    thumb_ext = abs_thumb_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(thumb_ext, "image/png")

    return FastAPIFileResponse(str(abs_thumb_path), media_type=media_type)


@router.post("/files/{file_id}/preview-thumbnail", response_model=ClientThumbnailResponse)
async def upload_preview_thumbnail(
    file_id: int,
    thumbnail: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_UPDATE_ALL,
            Permission.LIBRARY_UPDATE_OWN,
        )
    ),
):
    """Store a client-rendered preview thumbnail for a file (#2976).

    STEP, PDF and spreadsheet previews are rendered in the browser; the FE
    posts its first render here so the grid gets a thumbnail without the
    server needing OpenCascade. A PDF normally has its PDFium thumbnail from
    upload already, so for PDFs this only fills the gap for a file PDFium
    could not read. Only file types in ``CLIENT_THUMBNAIL_TYPES`` are
    accepted, and only while the file has no thumbnail yet — a stored
    thumbnail is never replaced by this route.
    """
    user, can_modify_all = auth_result

    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    file = result.scalar_one_or_none()

    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    # Ownership check (same shape as update_file)
    if not can_modify_all:
        if file.created_by_id != user.id:
            raise HTTPException(status_code=403, detail="You can only update your own files")

    if file.file_type not in CLIENT_THUMBNAIL_TYPES:
        raise HTTPException(status_code=400, detail="File type does not accept client-rendered thumbnails")

    if file.thumbnail_path:
        return ClientThumbnailResponse(updated=False)

    content = await thumbnail.read(MAX_CLIENT_THUMBNAIL_BYTES + 1)
    if len(content) > MAX_CLIENT_THUMBNAIL_BYTES:
        raise HTTPException(status_code=413, detail="Thumbnail too large")

    # Decode and re-encode through PIL: validates the bytes are a real PNG
    # and strips anything that isn't pixel data before it lands on disk.
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        # Image.open() reads the header only. Both checks below happen before
        # load(), so a declared-but-never-delivered canvas is refused rather
        # than allocated. DecompressionBombError derives straight from
        # Exception, so it has to be named explicitly — open() itself raises
        # it once the declared size passes PIL's own limit.
        with Image.open(io.BytesIO(content)) as source:
            if source.format != "PNG":
                raise HTTPException(status_code=400, detail="Thumbnail must be a PNG image")
            if max(source.size) > MAX_CLIENT_THUMBNAIL_EDGE:
                raise HTTPException(status_code=400, detail="Thumbnail image dimensions too large")
            source.load()
            img = source.convert("RGBA") if source.mode not in ("RGB", "RGBA") else source.copy()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise HTTPException(status_code=400, detail="Invalid thumbnail image") from e

    if max(img.size) > STORED_CLIENT_THUMBNAIL_EDGE:
        img.thumbnail((STORED_CLIENT_THUMBNAIL_EDGE, STORED_CLIENT_THUMBNAIL_EDGE), Image.Resampling.LANCZOS)

    thumbnails_dir = get_library_thumbnails_dir()
    thumb_filename = f"{uuid.uuid4().hex}.png"
    thumb_path = thumbnails_dir / thumb_filename  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + ".png"
    # Outside the decode guard on purpose: a full disk or an unwritable
    # thumbnail directory is ours, not "Invalid thumbnail image".
    try:
        img.save(thumb_path, "PNG", optimize=True)
    except OSError as e:
        logger.error("Failed to store preview thumbnail for file %s: %s", file_id, e)
        raise HTTPException(status_code=500, detail="Failed to store thumbnail") from e

    # Two previews of the same file can reach this point together; the loser
    # of the UPDATE takes its PNG back off disk instead of orphaning it.
    result = await db.execute(
        update(LibraryFile)
        .where(LibraryFile.id == file_id, LibraryFile.thumbnail_path.is_(None))
        .values(thumbnail_path=to_relative_path(thumb_path))
    )
    await db.commit()
    if result.rowcount == 0:
        thumb_path.unlink(missing_ok=True)
        return ClientThumbnailResponse(updated=False)

    return ClientThumbnailResponse(updated=True)


# ============ Photo Endpoints (#3077) ============


@router.post("/files/{file_id}/photos")
async def upload_file_photo(
    file_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_UPDATE_ALL,
            Permission.LIBRARY_UPDATE_OWN,
        )
    ),
):
    """Attach a photo of the printed result to a library file.

    Photos are PrintLab-side metadata, so external files take them too. Same
    shape as the archive photo upload: extension allowlist, uuid-named on
    disk, and the ``photos`` list re-assigned so SQLAlchemy sees the change.
    """
    user, can_modify_all = auth_result

    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    library_file = result.scalar_one_or_none()

    if not library_file:
        raise HTTPException(status_code=404, detail="File not found")

    # Ownership check (same shape as update_file)
    if not can_modify_all:
        if library_file.created_by_id != user.id:
            raise HTTPException(status_code=403, detail="You can only update your own files")

    if not file.filename or not file.filename.lower().endswith(PHOTO_EXTENSIONS):
        raise HTTPException(status_code=400, detail="File must be an image (.jpg, .jpeg, .png, .webp)")

    content = await file.read(MAX_PHOTO_BYTES + 1)
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo too large (max 10 MB)")

    photos_dir = library_photos_dir(library_file.id)
    photos_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix.lower()
    photo_filename = f"{uuid.uuid4().hex[:8]}{ext}"
    photo_path = photos_dir / photo_filename  # SEC-PATH-OK: photo_filename = uuid.uuid4().hex[:8] + ext
    photo_path.write_bytes(content)

    photos = list(library_file.photos or [])
    photos.append(photo_filename)
    library_file.photos = photos

    await db.commit()
    await db.refresh(library_file)

    return {"status": "uploaded", "filename": photo_filename, "photos": library_file.photos}


@router.get("/files/{file_id}/photos/{filename}")
async def get_file_photo(
    file_id: int,
    filename: str,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_media_token_ownership(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Serve one photo. Media-token auth like the thumbnail route (#3025)."""
    user, can_read_all = auth_result
    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    library_file = _ensure_library_file_visible(result.scalar_one_or_none(), user, can_read_all)

    # Membership check first: names are uuid-generated on upload, so anything
    # not in the stored list is not a photo, whatever is on disk.
    if not library_file.photos or filename not in library_file.photos:
        raise HTTPException(status_code=404, detail="Photo not found")

    try:
        photo_path = safe_join_under(library_photos_dir(library_file.id), filename, http=False)
    except PathTraversalError:
        raise HTTPException(status_code=404, detail="Photo not found") from None
    if not photo_path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")

    media_type = PHOTO_MEDIA_TYPES.get(Path(filename).suffix.lower(), "image/jpeg")
    return FastAPIFileResponse(str(photo_path), media_type=media_type)


@router.delete("/files/{file_id}/photos/{filename}")
async def delete_file_photo(
    file_id: int,
    filename: str,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_UPDATE_ALL,
            Permission.LIBRARY_UPDATE_OWN,
        )
    ),
):
    """Remove a photo from a library file."""
    user, can_modify_all = auth_result

    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    library_file = result.scalar_one_or_none()

    if not library_file:
        raise HTTPException(status_code=404, detail="File not found")

    if not can_modify_all:
        if library_file.created_by_id != user.id:
            raise HTTPException(status_code=403, detail="You can only update your own files")

    if not library_file.photos or filename not in library_file.photos:
        raise HTTPException(status_code=404, detail="Photo not found")

    try:
        photo_path = safe_join_under(library_photos_dir(library_file.id), filename, http=False)
    except PathTraversalError:
        raise HTTPException(status_code=404, detail="Photo not found") from None
    if photo_path.is_file():
        try:
            photo_path.unlink()
        except OSError as e:
            logger.warning("Failed to delete photo from disk: %s", e)

    photos = [p for p in library_file.photos if p != filename]
    library_file.photos = photos if photos else None

    await db.commit()

    return {"status": "deleted", "photos": library_file.photos or []}


@router.get("/files/{file_id}/gcode")
async def get_gcode(
    file_id: int,
    plate: int | None = None,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get gcode for a file (for preview).

    Mirrors the archive route: ``?plate=2`` returns ``Metadata/plate_2.gcode``,
    and omitting it returns the lowest-numbered plate. The viewer has been
    sending ``plate`` since it gained a multi-plate URL, but this route took no
    such parameter and FastAPI drops unknown query parameters silently — so
    every multi-plate library file opened on whichever plate the slicer wrote
    first into the zip, which is not plate 1.
    """
    user, can_read_all = auth_result
    result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    file = _ensure_library_file_visible(result.scalar_one_or_none(), user, can_read_all)

    abs_path = to_absolute_path(file.file_path)
    if not abs_path or not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    # Legacy sliced rows from before #1709 stored a `.gcode.3mf` ZIP body
    # under file_type="gcode" — the on-disk filename is the truth in that
    # case, so detect by suffix before checking the type column.
    is_gcode_3mf = file.file_type in ("3mf", "gcode.3mf") or file.filename.lower().endswith(".gcode.3mf")

    if plate is not None and plate < 1:
        raise HTTPException(status_code=400, detail="Plate index must be >= 1")

    if is_gcode_3mf:
        try:
            with zipfile.ZipFile(str(abs_path), "r") as zf:
                gcode_files = [n for n in zf.namelist() if n.endswith(".gcode")]
                if not gcode_files:
                    raise HTTPException(status_code=404, detail="No gcode found in 3MF file")
                if plate is not None:
                    selected = select_plate_gcode_name(gcode_files, plate)
                    if selected is None:
                        raise HTTPException(status_code=404, detail=f"Plate {plate} not found in this file")
                else:
                    selected = default_plate_gcode_name(gcode_files)
                gcode_content = zf.read(selected)
                from fastapi.responses import Response

                return Response(content=gcode_content, media_type="text/plain")
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid 3MF file")
    elif file.file_type == "gcode":
        return FastAPIFileResponse(str(abs_path), media_type="text/plain")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")


# ============ Bulk Operations ============


@router.post("/files/move")
async def move_files(
    data: FileMoveRequest,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_UPDATE_ALL,
            Permission.LIBRARY_UPDATE_OWN,
        )
    ),
):
    """Move multiple files to a folder.

    Cross-boundary moves (managed ↔ external, or external ↔ external)
    physically relocate the bytes — see ``_move_file_bytes``. Same-boundary
    moves stay DB-only because the file's on-disk location doesn't depend
    on which managed folder owns it.

    Files not owned by the user are skipped (unless user has ``*_all``
    permission). Each skip carries a structured reason so the UI can
    surface "5 of 10 files were skipped: 3 had filename collisions on
    the NAS, 2 are no longer on disk" rather than a blank "skipped: 5".
    """
    user, can_modify_all = auth_result

    # Verify folder exists if specified
    target_folder: LibraryFolder | None = None
    if data.folder_id is not None:
        folder_result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == data.folder_id))
        target_folder = folder_result.scalar_one_or_none()
        if not target_folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        if target_folder.is_external and target_folder.external_readonly:
            raise HTTPException(status_code=403, detail="Cannot move files to a read-only external folder")

    target_is_external = target_folder is not None and target_folder.is_external

    moved = 0
    skipped = 0
    skipped_reasons: list[dict] = []

    for file_id in data.file_ids:
        result = await db.execute(
            LibraryFile.active().options(selectinload(LibraryFile.folder)).where(LibraryFile.id == file_id)
        )
        file = result.scalar_one_or_none()
        if not file:
            continue
        # Ownership check
        if not can_modify_all and file.created_by_id != user.id:
            skipped += 1
            skipped_reasons.append({"file_id": file_id, "code": "not_owner", "reason": "not the file owner"})
            continue

        # No bytes need to move when both ends are managed (same-boundary).
        if not file.is_external and not target_is_external:
            file.folder_id = data.folder_id
            moved += 1
            continue

        # Block moves out of a read-only external mount. The user only has
        # read access to the source, and a move is semantically a delete on
        # the source — which a read-only mount can't fulfil. Without this
        # guard we'd succeed at copying to the target, fail to unlink the
        # source, and the same file would now exist in two places (with
        # the DB pointing at only one).
        if file.is_external and file.folder is not None and file.folder.external_readonly:
            skipped += 1
            skipped_reasons.append(
                {"file_id": file_id, "code": "source_readonly", "reason": "source is on a read-only external folder"}
            )
            continue

        # Otherwise relocate the bytes, then update the DB row to match.
        try:
            new_file_path = _move_file_bytes(file, target_folder)
        except _MoveSkip as e:
            skipped += 1
            skipped_reasons.append({"file_id": file_id, "code": e.code, "reason": e.reason})
            continue

        file.is_external = target_is_external
        file.folder_id = data.folder_id
        file.file_path = new_file_path
        # External rows historically carry `file_hash=None` (scan skips
        # hashing). When pulling an external file into managed storage,
        # compute the hash so dedup detection works for future uploads
        # of the same content.
        if not target_is_external and file.file_hash is None:
            try:
                abs_path = to_absolute_path(new_file_path)
                if abs_path:
                    file.file_hash = calculate_file_hash(abs_path)
            except OSError:
                pass  # leave hash null; dedup just won't match this row
        moved += 1

    await db.commit()

    return {
        "status": "success",
        "moved": moved,
        "skipped": skipped,
        "skipped_reasons": skipped_reasons,
    }


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete(
    data: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_DELETE_ALL,
            Permission.LIBRARY_DELETE_OWN,
        )
    ),
):
    """Delete multiple files and/or folders.

    Files not owned by the user are skipped (unless user has *_all permission).
    """
    from backend.app.services.library_trash import delete_dependent_variants, release_queue_references

    user, can_modify_all = auth_result
    deleted_files = 0
    deleted_folders = 0
    skipped_files = 0
    # External files bypass the trash and are removed for good, so the queue has
    # to come off them. Collected here and dealt with once, below the loop.
    hard_deleted: list[LibraryFile] = []

    # Delete files first. Managed files go to trash (sweeper hard-deletes bytes
    # later); external files bypass trash since their disk state is outside our
    # control and can't be restored from trash anyway.
    now = datetime.now(timezone.utc)
    for file_id in data.file_ids:
        result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
        file = result.scalar_one_or_none()
        if not file:
            continue
        if not can_modify_all and file.created_by_id != user.id:
            skipped_files += 1
            continue

        if file.is_external:
            abs_thumb_path = to_absolute_path(file.thumbnail_path)
            if abs_thumb_path and abs_thumb_path.exists():
                try:
                    abs_thumb_path.unlink()
                except OSError as e:
                    logger.warning("Failed to delete thumbnail from disk: %s", e)
            hard_deleted.append(file)
        else:
            file.deleted_at = now
        deleted_files += 1

    # After the loop and before any delete is issued (#2819). Order matters
    # twice over: a query run while a delete is pending autoflushes it, taking
    # the cascade with it, and releasing once for the whole set is a couple of
    # statements rather than a couple per file.
    if hard_deleted:
        hard_deleted_ids = [f.id for f in hard_deleted]
        await delete_dependent_variants(db, hard_deleted_ids)
        await release_queue_references(db, hard_deleted_ids)
        for file in hard_deleted:
            remove_library_photos_dir(file.id)
            await db.delete(file)

    # Delete folders (cascade will handle contents). Folders have no ownership
    # tracking, so users without *_all permission may only delete empty,
    # non-external, non-linked folders (#1781) — same rule as DELETE /folders/{id}.
    for folder_id in data.folder_ids:
        result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id))
        folder = result.scalar_one_or_none()
        if folder:
            if not can_modify_all and await _restricted_folder_delete_blocker(db, folder):
                continue
            # Count files that will be deleted
            file_count_result = await db.execute(
                select(func.count(LibraryFile.id)).where(
                    LibraryFile.folder_id == folder_id,
                    LibraryFile.deleted_at.is_(None),
                )
            )
            deleted_files += file_count_result.scalar() or 0
            tree_file_ids = await _folder_tree_file_ids(db, folder_id)
            await delete_dependent_variants(db, tree_file_ids)
            await release_queue_references(db, tree_file_ids)
            # The cascade hard-deletes every row in the subtree, so their
            # photos go with them — same as DELETE /folders/{id} (#3077).
            for doomed_id in tree_file_ids:
                remove_library_photos_dir(doomed_id)
            await db.delete(folder)
            deleted_folders += 1

    await db.commit()

    return BulkDeleteResponse(deleted_files=deleted_files, deleted_folders=deleted_folders)


# ============ Stats Endpoint ============


@router.get("/stats")
async def get_library_stats(
    db: AsyncSession = Depends(get_db),
    auth_result: tuple[User | None, bool] = Depends(
        require_ownership_permission(
            Permission.LIBRARY_READ_ALL,
            Permission.LIBRARY_READ_OWN,
        )
    ),
):
    """Get library statistics."""
    user, can_read_all = auth_result
    # Stats exclude trashed files — users see counts/sizes for what's actually in the library.
    # Without LIBRARY_READ_ALL the stats reflect only the caller's own files —
    # match what the file list endpoint shows so the numbers stay consistent.
    file_filters = [LibraryFile.deleted_at.is_(None)]
    if user is not None and not can_read_all:
        file_filters.append(LibraryFile.created_by_id == user.id)

    # Total files
    total_files_result = await db.execute(select(func.count(LibraryFile.id)).where(*file_filters))
    total_files = total_files_result.scalar() or 0

    # Total folders (folders are shared org structure, not per-user — count all)
    total_folders_result = await db.execute(select(func.count(LibraryFolder.id)))
    total_folders = total_folders_result.scalar() or 0

    # Total size
    total_size_result = await db.execute(select(func.sum(LibraryFile.file_size)).where(*file_filters))
    total_size = total_size_result.scalar() or 0

    # Files by type
    type_result = await db.execute(
        select(LibraryFile.file_type, func.count(LibraryFile.id)).where(*file_filters).group_by(LibraryFile.file_type)
    )
    files_by_type = dict(type_result.all())

    # Total prints
    total_prints_result = await db.execute(select(func.sum(LibraryFile.print_count)).where(*file_filters))
    total_prints = total_prints_result.scalar() or 0

    # Disk space info
    library_dir = get_library_dir()
    try:
        disk_stat = shutil.disk_usage(library_dir)
        disk_free_bytes = disk_stat.free
        disk_total_bytes = disk_stat.total
        disk_used_bytes = disk_stat.used
    except OSError:
        disk_free_bytes = 0
        disk_total_bytes = 0
        disk_used_bytes = 0

    return {
        "total_files": total_files,
        "total_folders": total_folders,
        "total_size_bytes": total_size,
        "files_by_type": files_by_type,
        "total_prints": total_prints,
        "disk_free_bytes": disk_free_bytes,
        "disk_total_bytes": disk_total_bytes,
        "disk_used_bytes": disk_used_bytes,
    }
