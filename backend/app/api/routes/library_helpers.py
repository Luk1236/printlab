"""Hilfsfunktionen und Dateisystem-Operationen fuer die Bibliothek (Dateimanager).

Ausgelagert aus library.py zur Modularisierung und Einhaltung des Zeilenbudgets.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import logging
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core import database
from backend.app.core.config import settings as app_settings
from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile, LibraryFolder
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.services.archive import ThreeMFParser
from backend.app.services.pdf_thumbnail import generate_pdf_thumbnail
from backend.app.services.plate_thumbnail import inject_plate_thumbnails_if_missing
from backend.app.services.stl_thumbnail import MIN_USABLE_STL_BYTES, generate_stl_thumbnail
from backend.app.utils.filename import (
    MAX_FILENAME_BYTES,
    InvalidFilenameError,
    safe_path_component,
    validate_print_filename,
)
from backend.app.utils.library_paths import library_photos_dir, remove_library_photos_dir
from backend.app.utils.safe_path import PathTraversalError, assert_under, safe_join_under
from backend.app.utils.threemf_tools import carries_gcode, default_plate_gcode_name

logger = logging.getLogger(__name__)

_PROJECT_SETTINGS_PATH = "Metadata/project_settings.config"

# Path of the embedded slicer config inside a BambuStudio/OrcaSlicer 3MF.
_PROJECT_SETTINGS_PATH = "Metadata/project_settings.config"


def _ensure_library_file_visible(
    library_file: LibraryFile | None,
    user: User | None,
    can_read_all: bool,
) -> LibraryFile:
    """Per-file visibility gate for ownership-scoped LIBRARY reads (#1726-adjacent).

    Mirrors archives.py::_ensure_archive_visible — single enforcement point so a
    less-guarded sibling route can't accidentally leak a row. Same shape:

      - Missing / soft-deleted → 404 (not 403, to avoid id-enumeration leaks).
      - ``can_read_all`` true (LIBRARY_READ_ALL or auth disabled) → file returned.
      - ``can_read_all`` false and ``created_by_id != user.id`` → 404.
      - Ownerless files (``created_by_id is None``) require ALL — fail-closed.
    """
    if library_file is None or getattr(library_file, "deleted_at", None) is not None:
        raise HTTPException(404, "File not found")
    if can_read_all:
        return library_file
    if user is None:
        raise HTTPException(404, "File not found")
    if library_file.created_by_id is None or library_file.created_by_id != user.id:
        raise HTTPException(404, "File not found")
    return library_file


def get_library_dir() -> Path:
    """Get the library storage directory."""
    base_dir = Path(app_settings.archive_dir)
    library_dir = base_dir / "library"
    library_dir.mkdir(parents=True, exist_ok=True)
    return library_dir


def get_library_files_dir() -> Path:
    """Get the directory for library files."""
    files_dir = get_library_dir() / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    return files_dir


def classify_file_type(filename: str, file_path: Path | str | None = None) -> str:
    """Return the canonical ``LibraryFile.file_type`` for *filename*.

    Compound extensions are preserved — a `.gcode.3mf` file (a sliced
    output, still a 3MF zip on disk) is classified ``gcode.3mf`` rather
    than ``3mf``. Pre-#1600 this was only done in the external-scan
    path; the upload / ZIP-extract / in-process paths all stripped to
    the trailing extension and stored ``3mf``, so the FE had to accept
    both. Unified here so every ingest path stores the same value and
    downstream gates (gcode download, file-type filter, thumbnail
    extraction) only need to handle one canonical name per file family.
    Files with no extension classify as ``unknown``.

    Pass ``file_path`` and a ``.3mf`` is judged on what the zip actually holds
    rather than on its name (#2993). The name is not evidence: a plate exported
    from Studio or a print dispatched through the cloud reaches the archive as
    ``Foo.3mf``, G-code and all, and downloading that and re-importing it used
    to land a fully printable file in the library as a source-only project. The
    file is not opened when the name already settles it, so the common case
    still costs nothing.
    """
    lower = filename.lower()
    if lower.endswith(".gcode.3mf"):
        return "gcode.3mf"
    ext = os.path.splitext(lower)[1]
    file_type = ext[1:] if ext else "unknown"
    if file_type == "3mf" and file_path is not None and carries_gcode(file_path):
        return "gcode.3mf"
    return file_type


def get_library_thumbnails_dir() -> Path:
    """Get the directory for library thumbnails."""
    thumbnails_dir = get_library_dir() / "thumbnails"
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    return thumbnails_dir


def to_relative_path(absolute_path: Path | str) -> str:
    """Convert an absolute path to a path relative to base_dir for storage."""
    if not absolute_path:
        return ""
    abs_path = Path(absolute_path)
    base_dir = Path(app_settings.base_dir)
    try:
        return abs_path.relative_to(base_dir).as_posix()
    except ValueError:
        # Path is not under base_dir, return as-is (shouldn't happen normally)
        return str(abs_path)


def to_absolute_path(relative_path: str | None) -> Path | None:
    """Convert a relative path (from database) to an absolute path for file operations."""
    if not relative_path:
        return None
    path = Path(relative_path)
    # Handle already-absolute paths verbatim (backwards compatibility during migration).
    # Legacy DB rows may store absolute paths that predate the base_dir layout; the
    # traversal guard below only applies to relative paths coming from user input.
    if path.is_absolute():
        return path.resolve()
    base = Path(app_settings.base_dir).resolve()
    resolved = (base / relative_path).resolve()
    # Guard against path traversal — resolved path must stay inside base_dir.
    # Use is_relative_to() to avoid the /data/app vs /data/app_evil prefix confusion
    # that a plain startswith(str(base)) check would miss.
    if not resolved.is_relative_to(base):
        raise ValueError(f"Path escapes base directory: {relative_path!r}")
    return resolved


def calculate_file_hash(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def validate_print_file_upload(filename: str, content: bytes) -> None:
    """Reject obviously-unprintable uploads early so the printer doesn't see them (#1401).

    Bambu printers in network mode only parse ``.gcode.3mf`` zip containers
    — raw ``.gcode`` and corrupt/non-zip ``.3mf`` uploads cascade into a
    confusing "Printing stopped because the printer was unable to parse the
    3mf file" rejection 30 seconds after the user clicks Print. The
    the queue dispatch path appends ``.3mf`` to a raw-gcode filename when
    constructing the FTP destination, which is how the printer ends up with a
    file named ``.gcode.3mf`` whose body is raw gcode — exactly the shape that
    triggers the firmware parse failure. Catching both classes here gives an
    actionable error at the
    upload itself.

    Compares the filename suffix rather than ``os.path.splitext`` because
    compound extensions like ``.gcode.3mf`` show up as just ``.3mf`` after
    ``splitext`` — same content validation needs to fire for both
    single-``.3mf`` and ``.gcode.3mf`` uploads.

    Raises ``HTTPException(400, ...)`` with a human-readable message on
    rejection; returns ``None`` for valid (or irrelevant — e.g. STL,
    image) uploads.
    """
    lower_filename = filename.lower()
    is_3mf_upload = lower_filename.endswith(".3mf")
    is_raw_gcode_upload = lower_filename.endswith(".gcode") and not lower_filename.endswith(".gcode.3mf")

    if is_raw_gcode_upload:
        raise HTTPException(
            status_code=400,
            detail=(
                "Raw .gcode files can't be printed on Bambu printers in network mode — "
                "they need a .gcode.3mf zip container (gcode plus metadata). Re-export from "
                "your slicer and make sure the file ends in '.gcode.3mf', not just '.gcode'. "
                "If your OS hides extensions, double-check the file with the extension visible."
            ),
        )

    if is_3mf_upload and not content.startswith(b"PK\x03\x04"):
        raise HTTPException(
            status_code=400,
            detail=(
                "This .3mf file isn't a valid ZIP container. 3MF files are ZIP archives — "
                "either the file is corrupted or it's raw gcode renamed to .3mf. Re-export "
                "from your slicer using its 'Export Plate Sliced File' action."
            ),
        )


def _resolve_upload_destination(target_folder: LibraryFolder | None, filename: str) -> tuple[Path, bool]:
    """Resolve the on-disk destination for an uploaded file.

    Non-external target: returns ``(<library_files_dir>/<uuid><ext>, False)``.
    Writable external target: writes to ``<external_path>/<filename>``
    (preserves the real filename so the file is recognisable on the mount);
    returns ``(dest, True)``. Raises ``HTTPException`` for read-only external
    folders (403), missing/inaccessible/non-writable external paths (400), and
    filename collisions on the external mount (409). See #1112 — previously
    uploads to writable external folders were silently misrouted to the
    internal library dir.
    """
    if target_folder is not None and target_folder.is_external:
        if target_folder.external_readonly:
            raise HTTPException(status_code=403, detail="Cannot upload to a read-only external folder")
        if not target_folder.external_path:
            raise HTTPException(status_code=400, detail="External folder has no configured path")
        ext_dir = Path(target_folder.external_path)
        if not ext_dir.exists() or not ext_dir.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"External path is not accessible: {target_folder.external_path}",
            )
        if not os.access(ext_dir, os.W_OK):
            raise HTTPException(
                status_code=400,
                detail=f"External path is not writable: {target_folder.external_path}",
            )
        # Guard against path-traversal via a pathological filename — join then
        # verify the resolved destination is still inside the external dir.
        dest = (ext_dir / filename).resolve()  # SEC-PATH-OK: resolve + relative_to containment check on next line
        try:
            dest.relative_to(ext_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename")
        if dest.exists():
            raise HTTPException(
                status_code=409,
                detail=f"A file named {filename!r} already exists in the external folder",
            )
        return dest, True
    ext = os.path.splitext(filename)[1].lower()
    return get_library_files_dir() / f"{uuid.uuid4().hex}{ext}", False


def _unique_external_name(ext_dir: Path, filename: str) -> str:
    """Return ``filename``, or the first free ``<stem> (n)<suffix>`` variant.

    Splits on the *compound* extension so re-slicing ``Bidoof.3mf`` yields
    ``Bidoof (2).gcode.3mf`` rather than ``Bidoof.gcode (2).3mf``.

    Uploads answer a name collision with a 409, which is right for a file the
    user just chose to send. A slice is not that: re-slicing the same source
    with different settings is routine, and the second run has already spent
    minutes of CPU by the time the name is known -- refusing to store it would
    throw that away. Overwriting is worse still, since the target is somebody's
    NAS and the file being replaced may not even be ours.
    """
    stem = filename[: -len(".gcode.3mf")] if filename.endswith(".gcode.3mf") else Path(filename).stem
    suffix = ".gcode.3mf" if filename.endswith(".gcode.3mf") else Path(filename).suffix
    candidate = filename
    counter = 2
    # Bounded: a directory holding 999 re-slices of one model is pathological,
    # and an unbounded loop here would hang the request on a mount that lies
    # about exists() (some SMB shares do under contention).
    #
    # safe_join_under rather than `ext_dir / candidate`: `filename` derives
    # from a name read out of a 3MF, so the very first probe must not be able
    # to stat its way outside the mount. It raises PathTraversalError, which
    # the caller turns into a managed-storage fallback.
    while safe_join_under(ext_dir, candidate, http=False).exists() and counter < 1000:
        candidate = f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def _resolve_slice_destination(target_folder: LibraryFolder | None, out_filename: str) -> tuple[Path, bool, str | None]:
    """Resolve where a slice result should be written.

    Returns ``(path, is_external, fallback_reason)``. ``fallback_reason`` is
    ``None`` on the normal paths and otherwise names why an external folder
    could not receive the file, so the caller can tell the user instead of
    quietly filing it elsewhere.

    Slicing a file that lives on an external mount used to store the output in
    the managed library dir unconditionally, while giving the new row the
    external folder's ``folder_id`` (#2810). The file therefore appeared in the
    right folder in the UI and never arrived on the share, which is the one
    place the user was looking -- and made it un-reproducible from the web UI
    alone. Uploads learned this in #1112 (``_resolve_upload_destination``) and
    moves in its follow-up (``_move_file_bytes``); slicing was the last write
    path still assuming managed storage.

    Unlike uploads, a failure here does not raise. The bytes exist and cost
    real time to produce, so an unwritable target falls back to managed storage
    with a reason attached rather than discarding the slice.
    """
    if target_folder is None or not target_folder.is_external:
        return get_library_files_dir() / f"{uuid.uuid4().hex}.gcode.3mf", False, None

    if target_folder.external_readonly:
        return get_library_files_dir() / f"{uuid.uuid4().hex}.gcode.3mf", False, "external_readonly"
    if not target_folder.external_path:
        return get_library_files_dir() / f"{uuid.uuid4().hex}.gcode.3mf", False, "external_no_path"

    ext_dir = Path(target_folder.external_path)
    if not ext_dir.exists() or not ext_dir.is_dir():
        return get_library_files_dir() / f"{uuid.uuid4().hex}.gcode.3mf", False, "external_unreachable"
    if not os.access(ext_dir, os.W_OK):
        return get_library_files_dir() / f"{uuid.uuid4().hex}.gcode.3mf", False, "external_not_writable"

    try:
        dest = safe_join_under(ext_dir, _unique_external_name(ext_dir, out_filename), http=False)
    except PathTraversalError:
        # The source filename reached us from a 3MF on disk, so this is
        # defensive rather than expected -- but a name that escapes the mount
        # must land in managed storage, never outside it.
        return get_library_files_dir() / f"{uuid.uuid4().hex}.gcode.3mf", False, "external_invalid_name"
    return dest, True, None


async def _folder_tree_file_ids(db: AsyncSession, folder_id: int) -> list[int]:
    """Every ``LibraryFile`` id under ``folder_id``, at any depth.

    Deleting a folder cascades to its whole subtree, so anything that has to be
    released before that delete (queue items, cross-model candidates) needs the
    subtree, not just the folder's own files.

    Trashed rows are included deliberately: they are still real rows and the
    cascade takes them too.
    """
    file_ids: list[int] = []
    pending = [folder_id]
    # The API refuses to make a folder its own ancestor, so a loop here would
    # mean the table is already corrupt -- but this walk runs inside a delete
    # request, and hanging one is worse than the cost of a set.
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        file_ids.extend(
            (await db.execute(select(LibraryFile.id).where(LibraryFile.folder_id == current))).scalars().all()
        )
        pending.extend(
            (await db.execute(select(LibraryFolder.id).where(LibraryFolder.parent_id == current))).scalars().all()
        )
    return file_ids


def _stored_file_path(abs_path: Path, is_external: bool) -> str:
    """Produce the value to persist in ``LibraryFile.file_path``.

    External files store the absolute mount path directly (same as scan does),
    so ``to_absolute_path`` round-trips through its ``is_absolute()`` fast
    path. Managed files store a path relative to ``base_dir`` for portability.
    """
    return str(abs_path) if is_external else to_relative_path(abs_path)


class _MoveSkip(Exception):
    """Signalled by ``_move_file_bytes`` to skip a file with a user-visible reason.

    Carries an optional `code` for machine-friendly grouping (the
    front-end can localise it) and a fallback English `reason` for logs.
    """

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _resolve_source_disk_path(file: LibraryFile) -> Path | None:
    """Return the absolute on-disk path for an existing LibraryFile, or None
    if it can't be located (legacy DB row, deleted file, etc.)."""
    if file.is_external:
        return Path(file.file_path) if file.file_path else None
    return to_absolute_path(file.file_path)


def _move_file_bytes(file: LibraryFile, target_folder: LibraryFolder | None) -> str:
    """Physically relocate `file`'s bytes to match `target_folder`.

    Used by the move endpoint when source/target straddle the
    managed↔external boundary (#1112 follow-up — the prior implementation
    updated the DB row's ``folder_id`` but never moved the bytes, so a
    file moved to an external SMB folder showed up in PrintLab's UI but
    not on the NAS).

    Returns the new ``file_path`` value to persist (relative for managed
    targets, absolute for external targets — matches the upload + scan
    paths). Raises ``_MoveSkip`` for any condition that would make the
    move unsafe (target unwritable, filename collision, source missing).

    The copy-then-unlink ordering means a partial copy followed by a
    failed unlink leaves both the source and the dest on disk — better
    than the symmetric "rename or move" which would lose the source if
    the target write didn't complete on a flaky mount. The DB row stays
    pointed at the source until the caller commits the new ``file_path``.
    """
    src = _resolve_source_disk_path(file)
    if not src or not src.exists():
        raise _MoveSkip("source_missing", "source file missing on disk")

    target_is_external = target_folder is not None and target_folder.is_external

    if target_is_external:
        if target_folder.external_readonly:
            # Already blocked at top level, but defence-in-depth.
            raise _MoveSkip("target_readonly", "target external folder is read-only")
        if not target_folder.external_path:
            raise _MoveSkip("target_misconfigured", "target external folder has no path")
        ext_dir = Path(target_folder.external_path)
        if not ext_dir.exists() or not ext_dir.is_dir():
            raise _MoveSkip("target_inaccessible", f"target path not accessible: {ext_dir}")
        if not os.access(ext_dir, os.W_OK):
            raise _MoveSkip("target_unwritable", f"target path not writable: {ext_dir}")
        dest = (ext_dir / file.filename).resolve()  # SEC-PATH-OK: resolve + relative_to containment check on next line
        try:
            dest.relative_to(ext_dir.resolve())
        except ValueError:
            raise _MoveSkip("invalid_filename", f"unsafe filename: {file.filename!r}") from None
        if dest.exists():
            raise _MoveSkip("name_collision", f"a file named {file.filename!r} already exists in target")
        try:
            shutil.copy2(src, dest)
        except OSError as e:
            # Clean up partial dest so a retry can succeed.
            with contextlib.suppress(OSError):
                dest.unlink(missing_ok=True)
            raise _MoveSkip("copy_failed", f"copy failed: {e}") from e
    else:
        # → managed (root or non-external folder): generate a fresh UUID
        # filename in the internal store so we don't collide with another
        # file that happens to share `filename`.
        ext = src.suffix.lower()
        dest = get_library_files_dir() / f"{uuid.uuid4().hex}{ext}"
        try:
            shutil.copy2(src, dest)
        except OSError as e:
            with contextlib.suppress(OSError):
                dest.unlink(missing_ok=True)
            raise _MoveSkip("copy_failed", f"copy failed: {e}") from e

    # Copy succeeded — unlink the original. A failure here leaves an
    # orphan on disk but the DB row is consistent against the new dest.
    try:
        src.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(
            "Move: copied %s → %s but couldn't remove source: %s",
            src,
            dest,
            e,
        )

    return _stored_file_path(dest, is_external=target_is_external)


def _clean_3mf_metadata(obj):
    """Strip bytes and thumbnail-carrier keys so the payload is JSON-storable.

    Shared by ``upload_file`` and :func:`save_3mf_bytes_to_library` — the
    ``ThreeMFParser`` output embeds the thumbnail bytes under
    ``_thumbnail_data``/``_thumbnail_ext`` and may also include raw bytes in
    other fields, none of which can be JSON-encoded.
    """
    if isinstance(obj, dict):
        return {
            k: _clean_3mf_metadata(v)
            for k, v in obj.items()
            if not isinstance(v, bytes) and k not in ("_thumbnail_data", "_thumbnail_ext")
        }
    if isinstance(obj, list):
        return [_clean_3mf_metadata(i) for i in obj if not isinstance(i, bytes)]
    if isinstance(obj, bytes):
        return None
    return obj


def _read_3mf_entry(zip_path: Path, entry: str) -> bytes | None:
    """Return the raw bytes of an entry inside a 3MF (ZIP), or ``None`` when
    the file isn't a parseable zip / doesn't contain that entry / any IO
    error. Used to lift the source archive's per-plate render onto a
    re-sliced archive (#1493 follow-up) — the slicer CLI often doesn't
    emit a fresh ``Metadata/plate_N.png`` and the project-wide cover-art
    fallback in :class:`ThreeMFParser` looks unrelated to the actual slice.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if entry not in zf.namelist():
                return None
            return zf.read(entry)
    except (zipfile.BadZipFile, OSError, KeyError):
        return None


def _without_print_name(metadata: dict | None) -> dict | None:
    """Drop the embedded 3MF Title (``print_name``) from library-file metadata.

    The 3MF ``<metadata name="Title">`` holds the in-app project title — the
    generic ``"Exported 3D Model"`` for a Bambu Studio "Save As", a marketing
    title for a MakerWorld download — never the filename the user saved as.
    The FileManager keys its display name, search and sort off ``print_name``,
    so storing it makes every card show the wrong name (#1489). A library
    file's display name is its filename; only ``PrintArchive`` carries a real
    ``print_name``. Returns the input unchanged when there's nothing to strip;
    otherwise a new dict (never mutates the argument).
    """
    if not metadata or "print_name" not in metadata:
        return metadata
    return {k: v for k, v in metadata.items() if k != "print_name"}


async def save_3mf_bytes_to_library(
    db: AsyncSession,
    *,
    file_bytes: bytes,
    filename: str,
    folder_id: int | None = None,
    source_type: str | None = None,
    source_url: str | None = None,
    owner_id: int | None = None,
) -> tuple[LibraryFile, bool]:
    """Save a 3MF blob into the library and return ``(library_file, was_existing)``.

    Used by routes that receive a 3MF in-process rather than as a multipart
    upload (currently: MakerWorld import; reusable for any future source that
    fetches bytes server-side). Deduplicates by ``source_url`` when provided —
    if a LibraryFile with the same source_url already exists, the existing
    row is returned and the bytes are NOT re-saved (MakerWorld signed URLs
    change each download, so hash-based dedupe alone would miss re-imports).

    Parses 3MF metadata + thumbnail the same way the multipart upload route
    does, via :class:`ThreeMFParser`. Paths are stored as relative so the
    library is portable across installs.
    """
    # Source-URL-based dedupe: return the existing row untouched.
    if source_url:
        existing = await db.execute(LibraryFile.active().where(LibraryFile.source_url == source_url).limit(1))
        existing_row = existing.scalar_one_or_none()
        if existing_row is not None:
            return existing_row, True

    # Resolve target folder so writable-external destinations land on the
    # mount with the real filename, instead of being silently misrouted to
    # the internal library dir with a UUID name (#1645). Mirrors what the
    # multipart-upload path has done since #1112. ``_resolve_upload_destination``
    # also enforces the 403 read-only / 400 unwritable / 409 collision
    # rejections — the makerworld route layer already pre-checks read-only,
    # but the helper's checks remain as defence-in-depth for any future
    # caller that skips that route gate.
    target_folder: LibraryFolder | None = None
    if folder_id is not None:
        folder_q = await db.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id))
        target_folder = folder_q.scalar_one_or_none()

    file_path, is_external = _resolve_upload_destination(target_folder, filename)
    ext = file_path.suffix.lower() or ".3mf"
    with open(file_path, "wb") as fh:
        fh.write(file_bytes)

    file_hash = calculate_file_hash(file_path)

    # Extract metadata + thumbnail from the 3MF.
    metadata: dict | None = None
    thumbnail_path: str | None = None
    if ext == ".3mf":
        try:
            # Off the event loop: the parser still decompresses the whole model
            # entry, which for a combined plate is hundreds of MB (#3162).
            parser = ThreeMFParser(str(file_path))
            raw_metadata = await asyncio.to_thread(parser.parse)
            thumb_data = raw_metadata.get("_thumbnail_data")
            thumb_ext = raw_metadata.get("_thumbnail_ext", ".png")
            if thumb_data:
                thumbs_dir = get_library_thumbnails_dir()
                thumb_filename = f"{uuid.uuid4().hex}{thumb_ext}"
                thumb_path = thumbs_dir / thumb_filename  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + thumb_ext
                with open(thumb_path, "wb") as fh:
                    fh.write(thumb_data)
                thumbnail_path = str(thumb_path)
            metadata = _clean_3mf_metadata(raw_metadata) or None
        except Exception as exc:
            # Matches the multipart upload route's behaviour — a bad 3MF should
            # still land in the library so the user can see / delete it rather
            # than failing the whole request.
            logger.warning("Failed to parse 3MF %s: %s", filename, exc)

    library_file = LibraryFile(
        folder_id=folder_id,
        is_external=is_external,
        filename=filename,
        file_path=_stored_file_path(file_path, is_external),
        file_type=classify_file_type(filename, file_path),
        file_size=len(file_bytes),
        file_hash=file_hash,
        thumbnail_path=to_relative_path(thumbnail_path) if thumbnail_path else None,
        file_metadata=_without_print_name(metadata),
        source_type=source_type,
        source_url=source_url,
        created_by_id=owner_id,
    )
    db.add(library_file)
    await db.commit()
    await db.refresh(library_file)
    return library_file, False


def extract_gcode_thumbnail(file_path: Path) -> bytes | None:
    """Extract embedded thumbnail from gcode file.

    Supports PrusaSlicer/BambuStudio format:
    ; thumbnail begin WxH SIZE
    ; base64data...
    ; thumbnail end
    """
    try:
        thumbnail_data = None
        in_thumbnail = False
        thumbnail_lines = []
        best_size = 0

        with open(file_path, errors="ignore") as f:
            # Only read first 50KB for performance (thumbnails are at the start)
            content = f.read(50000)

        for line in content.split("\n"):
            line = line.strip()

            # Check for thumbnail start
            if line.startswith("; thumbnail begin"):
                in_thumbnail = True
                thumbnail_lines = []
                # Parse dimensions: "; thumbnail begin 300x300 12345"
                match = re.search(r"(\d+)x(\d+)", line)
                if match:
                    width = int(match.group(1))
                    # Prefer larger thumbnails (up to 300px)
                    if width > best_size and width <= 300:
                        best_size = width
                continue

            # Check for thumbnail end
            if line.startswith("; thumbnail end"):
                if in_thumbnail and thumbnail_lines:
                    try:
                        # Decode the base64 data
                        b64_data = "".join(thumbnail_lines)
                        decoded = base64.b64decode(b64_data)
                        # Only keep if this is the best size or first valid thumbnail
                        if thumbnail_data is None or best_size > 0:
                            thumbnail_data = decoded
                    except (binascii.Error, ValueError):
                        pass  # Skip thumbnail with invalid base64 data
                in_thumbnail = False
                thumbnail_lines = []
                continue

            # Collect thumbnail data
            if in_thumbnail and line.startswith(";"):
                # Remove the leading "; " or ";"
                data_line = line[1:].strip()
                if data_line:
                    thumbnail_lines.append(data_line)

        return thumbnail_data
    except Exception as e:
        logger.warning("Failed to extract gcode thumbnail: %s", e)
        return None


def create_image_thumbnail(file_path: Path, thumbnails_dir: Path, max_size: int = 256) -> str | None:
    """Create a thumbnail from an image file.

    For small images, copies directly. For larger images, resizes.
    Returns the thumbnail path or None on failure.
    """
    try:
        from PIL import Image

        thumb_filename = f"{uuid.uuid4().hex}.png"
        thumb_path = thumbnails_dir / thumb_filename  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + ".png"

        with Image.open(file_path) as img:
            # Convert to RGB if necessary (for PNG with transparency, etc.)
            if img.mode in ("RGBA", "LA", "P"):
                # Create white background for transparency
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Resize if larger than max_size
            if img.width > max_size or img.height > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            img.save(thumb_path, "PNG", optimize=True)

        return str(thumb_path)
    except ImportError:
        # PIL not installed, just copy the file if it's small enough
        logger.warning("PIL not installed, copying image as thumbnail")
        try:
            file_size = file_path.stat().st_size
            if file_size < 500000:  # Less than 500KB
                thumb_filename = f"{uuid.uuid4().hex}{file_path.suffix}"
                thumb_path = (
                    thumbnails_dir / thumb_filename
                )  # SEC-PATH-OK: thumb_filename = uuid.uuid4().hex + file_path.suffix
                shutil.copy2(file_path, thumb_path)
                return str(thumb_path)
        except OSError:
            pass  # File inaccessible; fall through to return None
        return None
    except Exception as e:
        logger.warning("Failed to create image thumbnail: %s", e)
        return None


# Supported image extensions for thumbnails
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

# File types whose thumbnails are rendered client-side and uploaded back
# (#2976). The server has no renderer for STEP (that would need OpenCascade)
# or the spreadsheet types, so the browser posts its first preview render to
# POST /files/{id}/preview-thumbnail instead. PDF is rendered server-side with
# PDFium when it lands and stays here for a PDF that renderer cannot read.
# Kept to exactly these types so the endpoint can never overwrite a
# server-generated STL/3MF/G-code/image thumbnail.
CLIENT_THUMBNAIL_TYPES = {"step", "stp", "pdf", "csv", "xlsx", "ods"}

# Photos of the printed result (#3077): same allowlist and naming as the
# archive photo routes. 10 MB is ample for a phone camera JPEG.
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
PHOTO_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_PHOTO_BYTES = 10 * 1024 * 1024

# Upper bound for an uploaded client-rendered thumbnail. The FE sends a
# 256px PNG (a few tens of KB); anything near this limit is not a thumbnail.
MAX_CLIENT_THUMBNAIL_BYTES = 2 * 1024 * 1024

# Upper bound on the *decoded* size, checked against the header before any
# pixels are allocated: a few-KB PNG can declare 12000x7000 and still be under
# PIL's own decompression-bomb limit, which would be ~340 MB of RGBA.
MAX_CLIENT_THUMBNAIL_EDGE = 2048

# What the endpoint stores. The grid renders at ~256px, so anything larger is
# downscaled rather than kept.
STORED_CLIENT_THUMBNAIL_EDGE = 512


async def _backfill_external_thumbnails(folder_ids: list[int], session_factory: Any = None) -> None:
    """Generate STL and PDF thumbnails for an external folder tree in the background.

    Spawned via ``asyncio.create_task`` from ``scan_external_folder`` so the
    HTTP request can return as soon as the filesystem walk + folder/file rows
    are committed. Thumbnails for thousands of STL files would otherwise hold
    the request open for many minutes (each file triggers a ``trimesh.load``
    + matplotlib render, ~1-5s each) and the FE modal times out before the
    final ``db.commit()`` runs — causing the original symptom in #1299 where
    subdirectories never showed up because nothing got committed. PDFs are
    faster (a PDFium page render) but a share holding hundreds of them would
    still hold the request open, so they are rendered here too.

    Opens its own session because the request session is closed by the time
    this task starts running. Commits per-file so a worker restart mid-run
    only loses the in-flight file. Caps STL load to a single file at a time
    to avoid memory pressure on systems with many huge STLs.
    """
    if not folder_ids:
        return
    thumbnails_dir = get_library_thumbnails_dir()
    # Der Aufrufer reicht seine Session-Fabrik durch (Tests tauschen sie dort aus), sonst die aktuelle der Datenbankschicht.
    async with (session_factory or database.async_session)() as db:
        result = await db.execute(
            LibraryFile.active().where(
                LibraryFile.folder_id.in_(folder_ids),
                LibraryFile.file_type.in_(("stl", "pdf")),
                LibraryFile.thumbnail_path.is_(None),
            )
        )
        target_files = result.scalars().all()
        if not target_files:
            return
        logger.info(
            "Backfilling STL/PDF thumbnails: %d file(s) across %d folder(s)",
            len(target_files),
            len(folder_ids),
        )
        for target_file in target_files:
            abs_path = to_absolute_path(target_file.file_path)
            if not abs_path or not abs_path.exists():
                continue
            if target_file.file_type == "pdf":
                # generate_pdf_thumbnail never raises; an unreadable PDF
                # returns None and keeps the browser-preview fallback.
                thumb_path = await asyncio.to_thread(generate_pdf_thumbnail, abs_path, thumbnails_dir)
                if thumb_path:
                    target_file.thumbnail_path = to_relative_path(Path(thumb_path))
                    await db.commit()
                continue
            # Pre-skip files too small to contain even a single triangle.
            # Bulk-uploaded ZIPs of stub STLs would otherwise trigger one
            # trimesh.load() call + one debug log line per stub.
            try:
                if abs_path.stat().st_size < MIN_USABLE_STL_BYTES:
                    continue
            except OSError:
                continue
            try:
                thumb_path = generate_stl_thumbnail(abs_path, thumbnails_dir)
            except Exception as exc:  # noqa: BLE001 — never let one bad STL kill the rest
                logger.debug("STL thumbnail backfill skipped %s: %s", abs_path, exc)
                continue
            if thumb_path:
                target_file.thumbnail_path = to_relative_path(Path(thumb_path))
                await db.commit()
