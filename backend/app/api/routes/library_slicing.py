"""Slicing-Operationen und Slicer-Workflow fuer die Bibliothek.

Ausgelagert aus library.py zur Modularisierung und Einhaltung des Zeilenbudgets.
"""

from __future__ import annotations

import asyncio
import base64
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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from sqlalchemy import distinct, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.api.routes.cloud import resolve_api_key_cloud_owner

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
from backend.app.models.library import LibraryFile, LibraryFolder
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.project import Project
from backend.app.models.user import User
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
from backend.app.api.routes.library_helpers import (
    _clean_3mf_metadata,
    _ensure_library_file_visible,
    _read_3mf_entry,
    _resolve_slice_destination,
    _stored_file_path,
    _without_print_name,
    get_library_thumbnails_dir,
    to_relative_path,
)

logger = logging.getLogger('backend.app.api.routes.library')

router = APIRouter(tags=["library"])

def _patch_process_bed_type(process_json: str, bed_type: str) -> str:
    """Overwrite ``curr_bed_type`` in a process-profile JSON before forwarding
    to the slicer sidecar.

    The slicer CLI reads the build-plate type from the process profile's
    ``curr_bed_type`` field. When the user picks a non-default plate in the
    SliceModal (#1337), we patch the resolved JSON in place rather than
    asking them to clone the preset just to switch a plate. Returns the
    original string unchanged when the JSON can't be parsed or isn't a
    dict — the slicer will then run with whatever the preset originally
    specified, which is the safe fall-back path.
    """
    try:
        profile = json.loads(process_json)
    except json.JSONDecodeError:
        logger.warning("Bed-type override skipped: process profile is not valid JSON")
        return process_json
    if not isinstance(profile, dict):
        return process_json
    profile["curr_bed_type"] = bed_type
    return json.dumps(profile)


def _source_plate_colours(model_bytes: bytes) -> list[str]:
    """Per-slot colours the source 3MF was designed with, or ``[]``.

    Read from ``project_settings.config`` rather than ``slice_info.config``:
    the latter records the colour the file was *last sliced* with, which for a
    source that never carried one is the slicer's own #00AE42 default — the
    exact value #2977 is about, so using it as a fallback would be circular.
    STL and mesh-only 3MF sources have no project settings and yield ``[]``.
    """
    from io import BytesIO

    try:
        with zipfile.ZipFile(BytesIO(model_bytes), "r") as zf:
            return [str(f.get("color") or "") for f in extract_project_filaments_from_3mf(zf)]
    except (zipfile.BadZipFile, OSError, ValueError):
        return []


def _preset_default_colour(profile: dict) -> str:
    """A filament preset's own ``default_filament_colour``, or ``""``.

    OrcaSlicer's third-party vendor profiles carry this; Bambu Studio's
    bundled BBL filament profiles carry it nowhere (checked across the whole
    shipped `resources/profiles/BBL/filament/` tree — zero occurrences), which
    is why it can only ever be one link in the chain and never the whole fix.

    It is read here and rewritten as ``filament_colour`` because the CLI does
    not read it itself. Measured against a 02.08.02.61 sidecar: a profile
    carrying only ``default_filament_colour: ["#FF00FF"]`` still slices to
    ``filament_colour: ["#00AE42"]``. Bambu Studio consumes the default in the
    GUI when a project is created, not in ``--load-filaments``.
    """
    raw = profile.get("default_filament_colour")
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    return raw.strip() if isinstance(raw, str) else ""


def _patch_filament_colours(
    filament_jsons: list[str],
    requested: list[str],
    model_bytes: bytes,
) -> list[str]:
    """Write ``filament_colour`` onto each resolved filament profile (#2977).

    Neither slicer stores a colour on a filament *preset* — it is a per-project
    property their GUIs set from the plate — so a CLI slice with no colour
    supplied records Bambu Studio's compiled-in default for every slot. That
    default is `#00AE42`, which is why every internal-slicer output was green
    regardless of the filament picked, and why the print dialog's AMS mapping
    reported a colour mismatch against whatever was actually loaded.

    Per slot, first non-empty of:

    1. the caller's explicit colour (the SliceModal's per-slot swatch),
    2. the preset's own ``default_filament_colour``,
    3. the colour the source 3MF's plate was designed with.

    All three empty means the slot is left untouched rather than being given a
    guess: the slicer's default is then still wrong, but it is at least the
    same wrong value the file would have had before this function existed.

    Returns a new list; a profile that isn't parseable JSON is passed through
    unchanged, on the same reasoning as ``_patch_process_bed_type`` — a colour
    is not worth failing a slice that would otherwise succeed.
    """
    source_colours = _source_plate_colours(model_bytes) if filament_jsons else []
    patched: list[str] = []
    for i, raw in enumerate(filament_jsons):
        try:
            profile = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Filament colour skipped for slot %d: profile is not valid JSON", i + 1)
            patched.append(raw)
            continue
        if not isinstance(profile, dict):
            patched.append(raw)
            continue
        colour = (
            (requested[i].strip() if i < len(requested) and requested[i] else "")
            or _preset_default_colour(profile)
            or (source_colours[i].strip() if i < len(source_colours) and source_colours[i] else "")
        )
        if not colour:
            patched.append(raw)
            continue
        # One-element array: the same shape the CLI uses for every other
        # per-filament field (`filament_type`, `filament_vendor`), and the
        # shape a `--load-filaments` profile is parsed as. A bare string is
        # accepted by the JSON parser but not by the config deserialiser.
        profile["filament_colour"] = [colour]
        patched.append(json.dumps(profile))
    return patched


# Support-related keys we lift from the source 3MF's project_settings.config
# into the picked process preset before `--load-settings` sees it (#1881).
# BambuStudio's shipped process presets ("0.20mm Standard @BBL H2D" etc.)
# define `enable_support: 0` as their default — supports are a per-print
# decision, not a per-quality one. `--load-settings` is authoritative, so
# without preserving these fields the source's per-project support intent
# (supports on, PVA in the interface slot, tree vs normal) gets discarded
# and the slicer produces a single-material output with no supports at all.
_SOURCE_PROCESS_SUPPORT_KEYS_TO_PRESERVE = (
    "enable_support",
    "support_filament",
    "support_interface_filament",
    "support_type",
)


def _declined_source_keys(offered: list[DesignOverride], requested: list[str] | None) -> set[str]:
    """Settings the file offered and the caller left unticked (#2942).

    The slice dialog lists what the designer changed and applies only the keys
    that are switched on, so the answer to "which of these does this slice
    want" is already in the request. This reads the other half of it — the
    ones that were on offer and turned down — which the support carry-over
    below must not put back.

    ``requested`` of ``None`` is a caller that predates the per-key choice and
    so cannot have declined anything; an empty list is one that was shown the
    file's settings and took none. Collapsing those two into "nothing
    selected" is what made an empty panel indistinguishable from an old
    client, and only one of them means the user said no.
    """
    if requested is None:
        return set()
    return {override.key for override in offered} - set(requested)


def _patch_process_support_settings(
    process_json: str,
    source_3mf_bytes: bytes,
    declined: set[str] | frozenset[str] = frozenset(),
) -> str:
    """Overlay the source 3MF's support configuration onto the process JSON.

    The carry is deliberately one-way: a source can switch supports *on*,
    never off (#2820). The original #1881 rule was "source wins in both
    directions", which quietly stripped supports from every custom process
    preset that enabled them — a MakerWorld download nearly always ships
    `enable_support: 0`, so the reporter's own preset (supports on, normal
    (auto)) came back out of the slicer disabled and set to tree(auto).
    Nothing is lost by not carrying the off direction: a process preset
    with supports *on* is by definition a deliberate user preset, since
    Bambu's shipped ones all ship them off.

    ``declined`` names keys the caller offered the user as the file's own
    (#2622) and that the user left unticked, which this carry must then not
    reinstate behind their back (#2942). It is empty for a source that offers
    nothing — an OrcaSlicer export carries no ``different_settings_to_system``,
    so there is nothing to tick and #1881's blanket carry still applies — and
    for a client that predates the per-key ticks.

    Only fires on 3MF sources — STL / STEP don't carry `project_settings.
    config`. Silently no-ops when the source doesn't have the config, has
    a malformed one, or when the process JSON isn't parseable — the slice
    then runs with the process preset's own defaults, which is the safe
    fall-back for both this bug and the pre-fix behaviour.
    """
    from io import BytesIO

    try:
        with zipfile.ZipFile(BytesIO(source_3mf_bytes), "r") as zf:
            if "Metadata/project_settings.config" not in zf.namelist():
                return process_json
            src_cfg = json.loads(zf.read("Metadata/project_settings.config").decode("utf-8"))
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, OSError, KeyError):
        return process_json
    if not isinstance(src_cfg, dict):
        return process_json
    if not supports_enabled_in_config(src_cfg):
        return process_json

    try:
        process_cfg = json.loads(process_json)
    except json.JSONDecodeError:
        return process_json
    if not isinstance(process_cfg, dict):
        return process_json

    carried = {
        key: src_cfg[key] for key in _SOURCE_PROCESS_SUPPORT_KEYS_TO_PRESERVE if key in src_cfg and key not in declined
    }
    if not carried:
        return process_json
    process_cfg.update(carried)
    # Logged because this is the one layer of the process JSON the user
    # can't see coming: the slice modal shows the picked preset's values,
    # so a carried key silently disagrees with what was on screen.
    logger.info(
        "Carried support settings from the source 3MF onto the process preset: %s",
        dict(sorted(carried.items())),
    )

    return json.dumps(process_cfg)


# The sidecar prefixes the slicer CLI's own error_string with this when the
# slicer ran and rejected the job (model off the bed, incompatible filament
# temps, range validation) — as opposed to the CLI crashing before it could
# evaluate the job at all.
_SLICER_REJECTION_MARKER = "Slicing failed with error from slicer:"

# The CLI writes its real diagnostic to stdout/stderr on the `[error]` level.
# Format is `[<timestamp>] [error] run <NNNN>: <message>` (or sometimes without
# the `run NNNN:` prefix). The bracketed timestamp is optional; the `[error]`
# tag is what we anchor on. Used to recover the actual rejection reason for
# the `error_string: "The input preset file is invalid and can not be parsed."`
# case (#1851) — the CLI emits that generic placeholder for every -5 exit
# including real preset-compat rejections, and the per-incident specifics
# only live in the stdout dump.
_CLI_ERROR_LINE_RE = re.compile(r"\[error\]\s*(?:run\s+\d+:\s*)?(.+?)\s*$", re.MULTILINE)

# The placeholder error_string Bambu Studio writes to result.json for any
# `--load-settings` parse / compat rejection (-5 exit). When the sidecar
# surfaces this, the real reason lives in the stdout `[error]` line that we
# mine via _CLI_ERROR_LINE_RE.
_INPUT_PRESET_INVALID_PLACEHOLDER = "The input preset file is invalid and can not be parsed."


def _slicer_rejection_message(error_text: str) -> str | None:
    """Extract the slicer's own rejection reason from a sidecar error string,
    or ``None`` when the failure is not a slicer content rejection.

    A content rejection means ``--load-settings`` *was* applied — the slicer
    got far enough to evaluate the model against the chosen printer and say
    no. Retrying with the 3MF's embedded settings would then only "succeed"
    by silently reverting to the source file's original printer, masking the
    real problem; such failures must reach the user instead.

    When the sidecar's `error_string` is Bambu Studio's generic
    "The input preset file is invalid and can not be parsed." placeholder
    (#1851) — emitted for every -5 exit, including the actual preset-compat
    rejections whose real reason is logged to stdout as
    `[error] run NNNN: <diagnostic>` — prefer the stdout `[error]` line so
    the user sees which preset clashed with which printer.
    """
    if _SLICER_REJECTION_MARKER not in error_text:
        return None
    reason = error_text.split(_SLICER_REJECTION_MARKER, 1)[1]
    # Mine the stdout/stderr dump for a more specific CLI diagnostic before
    # we trim it off below. Done first so the lookup window covers the full
    # response, not just the headline.
    cli_diagnostic_match = _CLI_ERROR_LINE_RE.search(reason)
    cli_diagnostic = cli_diagnostic_match.group(1).strip() if cli_diagnostic_match else None
    # Trim the sidecar's trailing exit-code note and any stderr/stdout dump.
    for cut in (": Slicer process failed", "\nstderr:", "\nstdout:"):
        idx = reason.find(cut)
        if idx != -1:
            reason = reason[:idx]
    reason = reason.strip() or None
    # When the headline is Bambu Studio's catch-all placeholder, the real
    # reason is in the stdout `[error]` line. Substitute it. The placeholder
    # by itself tells the user nothing about why their slice was rejected.
    if cli_diagnostic and (reason is None or reason == _INPUT_PRESET_INVALID_PLACEHOLDER):
        return cli_diagnostic
    return reason


async def _run_slicer_with_fallback(
    db: AsyncSession,
    *,
    model_bytes: bytes,
    model_filename: str,
    request: SliceRequest,
    current_user_id: int | None = None,
    job_id: int | None = None,
):
    """Validate presets, dispatch to the right sidecar, run the slicer with
    the auto-fallback for 3MF inputs whose `--load-settings` path crashes the
    CLI. Returns ``(SliceResult, used_embedded_settings: bool)``. Raises
    ``HTTPException`` for any caller-facing error.

    `current_user_id` is needed to resolve **cloud** presets — the cloud token
    is per-user when auth is enabled. For the legacy / local-only path it can
    be left ``None``.

    `job_id`: when set, a request_id is generated and a parallel poller
    pushes the sidecar's --pipe-fed progress events onto
    ``slice_dispatch.set_progress(job_id, ...)`` so the UI's persistent
    toast can show "Generating G-code (75%)" instead of just elapsed
    time. Pass None for synchronous routes that aren't tracked by the
    dispatcher.
    """
    from backend.app.api.routes.settings import get_setting
    from backend.app.services.preset_resolver import resolve_preset_ref
    from backend.app.services.slicer_api import (
        SlicerApiServerError,
        SlicerApiService,
        SlicerApiUnavailableError,
        SlicerInputError,
        SlicerTimeoutError,
        get_stall_timeout_seconds,
    )

    user: User | None = None
    presets: dict[str, str] = {}
    filament_jsons: list[str] = []
    # Resolve each slot via the source-aware resolver. The schema
    # validator has already normalised legacy `*_preset_id: int`
    # fields into `PresetRef(source='local', id=str(int))`, so all
    # three are guaranteed non-None here.
    if current_user_id is not None:
        user = await db.get(User, current_user_id)

    refs = {
        "printer": request.printer_preset,
        "process": request.process_preset,
    }
    for slot, ref in refs.items():
        assert ref is not None, "schema validator guarantees PresetRef is set"
        presets[slot] = await resolve_preset_ref(db, user, ref, slot)
    # Multi-color: resolve each filament slot in plate order. The schema
    # validator backfilled `filament_presets` from the legacy `filament_preset`
    # field for single-color callers, so this list is always non-empty.
    for ref in request.filament_presets:
        assert ref is not None, "schema validator guarantees filament list is non-None"
        filament_jsons.append(await resolve_preset_ref(db, user, ref, "filament"))

    # Give every slot a colour before anything else touches the list, so the
    # unused-slot substitution below propagates a complete profile rather than
    # one that still has to be patched afterwards (#2977).
    filament_jsons = _patch_filament_colours(filament_jsons, request.filament_colours, model_bytes)

    # Bed-type override (#1337): patch curr_bed_type onto the resolved
    # process JSON so the slicer's StaticPrintConfig pass picks up the
    # user's pick instead of whatever the process preset defaults to.
    # Without this, slicing an STL of ABS onto a process preset whose
    # default is "Cool Plate" fails with "Plate 1: Cool Plate does not
    # support filament 1" — the reporter's exact scenario.
    if request.bed_type:
        presets["process"] = _patch_process_bed_type(presets["process"], request.bed_type)

    # Slicer routing — pick the sidecar URL by preferred_slicer.
    # The per-install URL setting (Settings UI → Slicer card) wins; an
    # empty value falls back to the SLICER_API_URL / BAMBU_STUDIO_API_URL
    # env defaults defined in core/config.py.
    preferred = (await get_setting(db, "preferred_slicer")) or "bambu_studio"
    if preferred == "orcaslicer":
        configured = await get_setting(db, "orcaslicer_api_url")
        api_url = (configured or app_settings.slicer_api_url).strip()
    elif preferred == "bambu_studio":
        configured = await get_setting(db, "bambu_studio_api_url")
        api_url = (configured or app_settings.bambu_studio_api_url).strip()
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preferred_slicer setting: '{preferred}'. Expected 'orcaslicer' or 'bambu_studio'.",
        )

    # Note: an earlier version of this code stripped Metadata/project_settings.
    # config + model_settings.config + slice_info.config + cut_information.xml
    # before forwarding the 3MF, the theory being that --load-settings would
    # then take precedence cleanly. That theory was wrong: model_settings.
    # config carries the plate definitions the CLI needs to map `--slice N`
    # to a real plate, and slice_info / project_settings supply baseline
    # config the CLI's StaticPrintConfig pass needs at all. Stripping ANY
    # of them caused the CLI to silently exit immediately after
    # "Initializing StaticPrintConfigs" — exit code 0, no result.json, no
    # stderr — which Node's child_process treated as failure and PrintLab
    # then masked by falling back to slice_without_profiles using the
    # un-stripped bytes (and the source's embedded printer). Net effect:
    # every 3MF slice with profiles silently produced wrong-printer output.
    # Forwarding the original bytes lets --load-settings override the
    # specific fields the user changed (printer/process/filament) while
    # the embedded plate / model definitions remain intact.
    is_3mf = model_filename.lower().endswith(".3mf")
    primary_bytes = model_bytes
    if is_3mf:
        # Strip inherit/unset sentinels from Metadata/project_settings.config
        # so the CLI's StaticPrintConfig range validator accepts the file
        # (#1201, #3030). Surgical — keeps the config present, just removes
        # the offending keys; the supplied --load-settings (and the fallback's
        # embedded values for keys we didn't touch) still drive the slice.
        # The preview-slice path applies the same sanitiser in
        # ``slice_preview.get_preview_filaments``.
        primary_bytes = sanitize_project_settings_sentinels(primary_bytes)

        # #2622: the process settings the file's designer moved off the stock
        # preset. Read once — the support patch below needs to know which of
        # them the user was shown, and the carry after it needs their values.
        design_offered = extract_design_process_overrides(primary_bytes)

        declined_from_file = _declined_source_keys(design_offered, request.design_overrides)

        # #1881: preserve the source 3MF's support configuration on top of
        # the picked process preset. Bambu's shipped process presets set
        # `enable_support: 0` by default (supports are a per-print, not
        # per-quality, decision); `--load-settings` is authoritative so
        # without patching, the source's `enable_support: 1` + support-slot
        # assignments get discarded and the slice comes out single-material
        # with a PVA slot loaded but never used. Bounded by the ticks: this
        # runs for a source that offers no per-key choice at all, and for the
        # keys of one that does but whose ticks the user left on.
        presets["process"] = _patch_process_support_settings(
            presets["process"], primary_bytes, declined=declined_from_file
        )

        # Carry the designer's tweaks onto the picked preset. BambuStudio
        # records exactly which keys deviate from the system preset in
        # `different_settings_to_system`, so a MakerWorld author's 5 walls /
        # 100% infill / 0.1mm first layer survive a re-slice for another printer
        # instead of being flattened by --load-settings. Opt-in per key: only the
        # keys the caller names are applied, and only if the source really lists
        # them as changed. Runs after the #1881 support patch so an explicit
        # design pick wins over the blanket support carry-over.
        if request.design_overrides:
            presets["process"] = apply_design_overrides(
                presets["process"],
                design_offered,
                request.design_overrides,
            )

    # The user's own edits from the slice modal's settings panel. Applied last
    # and for every model type (not just 3MF): unlike the two patches above this
    # doesn't read anything out of the source file, it is what the user typed.
    # Last write wins, so an explicit choice beats both the carried support
    # config (#1881) and the designer's tweaks (#2622).
    if request.process_overrides:
        presets["process"] = apply_process_overrides(presets["process"], request.process_overrides)

    if presets.get("process"):
        try:
            from backend.app.services.slicer_cli import sanitize_process_json_str

            presets["process"] = sanitize_process_json_str(presets["process"]) or presets["process"]
        except Exception:
            pass

    used_embedded_settings = False
    # "Slice as designed" (#2611): honour the file's embedded
    # project_settings.config instead of the picked profile triplet. Only
    # meaningful for a 3MF that actually carries embedded settings; the UI
    # gates the toggle on the picked printer matching the design's target,
    # so this path never re-targets across printer models.
    embedded_mode = bool(request.use_embedded_settings and is_3mf)
    # Bounds silence rather than total slicing time (#2730), so a heavy model
    # that keeps reporting progress runs to completion however long it takes.
    service = SlicerApiService(api_url, timeout_seconds=await get_stall_timeout_seconds(db))

    # #1493: cross-nozzle-class re-slice (single <-> dual). Without
    # intervention the slicer rejects with either "G-code in unprintable
    # area of multi-extruder printers" (the source's X1C-coordinate layout
    # lands in the H2D's per-nozzle dead zone) or — worse — segfaults
    # inside ZFiller's polygon clipping when the geometry pipeline trips
    # on the cross-class transition. Forwarding the sidecar's --arrange
    # flag for these cases lets BambuStudio reposition objects for the
    # target bed and reconcile the embedded project_settings.config
    # against the new printer, the same way the GUI's "Switch Printer"
    # operation does. --arrange WILL reposition objects, so we only
    # enable it on a true class crossing — same-printer slices keep the
    # user's deliberate layout. The bed-type and arrange flags are
    # orthogonal so this decision doesn't interact with the #1337 build-
    # plate override.
    cross_class_arrange = False
    if is_3mf:
        from backend.app.services.slicer_3mf_convert import (
            extract_source_printer_model,
        )
        from backend.app.utils.printer_models import is_dual_nozzle_model

        source_model = extract_source_printer_model(primary_bytes)
        target_model = await _resolve_target_printer_model(db, user, request)
        if source_model and target_model and is_dual_nozzle_model(source_model) != is_dual_nozzle_model(target_model):
            logger.info(
                "Cross-nozzle-class re-slice (%s -> %s): enabling --arrange so BS reconciles "
                "the embedded project layout against the target printer",
                source_model,
                target_model,
            )
            cross_class_arrange = True

    # #2548: the user can also ask for either layout pass per-slice. Arrange
    # is a union with the cross-class decision above — a user opt-out must
    # not be able to switch off the flag that keeps a class-crossing slice
    # from crashing — while orient is user-driven only.
    arrange_flag = cross_class_arrange or request.auto_arrange
    orient_flag = request.auto_orient
    # When this slice is dispatcher-tracked, generate a request_id so
    # the sidecar publishes progress under it, and wire a callback that
    # forwards each frame onto SliceDispatchService.set_progress for the
    # status-poll endpoint to surface to the UI.
    progress_request_id: str | None = None
    progress_callback = None
    if job_id is not None:
        from uuid import uuid4

        from backend.app.services.slice_dispatch import slice_dispatch as _dispatch

        progress_request_id = str(uuid4())

        def _on_progress(snapshot: dict) -> None:
            _dispatch.set_progress(job_id, snapshot)

        progress_callback = _on_progress
    # SliceModal lets the user pick a filament profile per slot, but each
    # plate uses only a subset of the slots. The unused-slot dropdowns get
    # whatever default the modal serves up — and a heterogeneous default
    # (e.g. ABS in slot 2 next to a PLA in the used slot 1) makes
    # BambuStudio reject the slice with "the temperature difference of
    # the filaments used is too large" (exit 194) even though the G-code
    # never touches the unused slot; a default scoped to another printer
    # gets it rejected with "filament preset (slot N) is not compatible
    # with printer …" (#2628). Replace unused-slot entries with the
    # plate's lowest used slot before the real slice so the loaded set is
    # materially homogeneous and printer-correct.
    #
    # ``plate`` is absent for single-plate and STL sources — the SliceModal
    # skips the picker and omits the field — and absent means plate 1, the
    # same reading as ``plate_num`` further down and as the schema's own
    # description. Treating it as "unknown plate" instead is what left every
    # single-plate 3MF unsubstituted (#2711): a MakerWorld project defining
    # four filaments but painting only one reached the CLI with the other
    # three still holding presets baked into the source for a different
    # printer, and the slice died on the first of them.
    #
    # ``plate=0`` is the slice-all sentinel, not a plate: every slot is used
    # by some plate, so there is nothing to substitute. It has to be excluded
    # explicitly because the support-filament slots unioned in below are
    # read from the project config and are not plate-scoped — they would
    # survive the (empty) geometry lookup for plate 0 and become the anchor,
    # collapsing every colour of a slice-all onto the support filament.
    if is_3mf and request.plate != 0:
        from backend.app.services.slicer_3mf_convert import substitute_unused_plate_filaments

        filament_jsons = substitute_unused_plate_filaments(primary_bytes, request.plate or 1, filament_jsons)

    # Arrange slice-all loop (#1493): when the user asks for ``plate=0``
    # (all plates) AND arrange is on, ``--slice 0 --arrange 1``
    # consolidates every plate's objects onto a single target bed (BS's
    # ``--arrange`` is project-wide) — either packing them all together or
    # rejecting with "Some objects are located over the boundary of the
    # heated bed" when nothing fits. Slice each plate independently with
    # ``--arrange 1`` and merge the per-plate outputs into one multi-plate
    # 3MF instead. Slice-all without arrange goes through the regular path
    # below — the sidecar's native ``--slice 0`` produces the right shape
    # directly.
    #
    # Keyed on ``arrange_flag``, not just the cross-class decision: the
    # project-wide collapse is a property of ``--arrange`` itself, so a
    # user-requested arrange over all plates (#2548) hits it identically.
    # Orient doesn't — it rotates objects where they stand and never moves
    # one between plates — so it isn't part of this condition.
    use_arrange_slice_all = arrange_flag and request.plate == 0 and request.export_3mf

    try:
        try:
            if use_arrange_slice_all:
                from backend.app.services.slicer_3mf_convert import (
                    count_plates_in_3mf,
                    merge_plate_3mfs,
                )

                plate_count = count_plates_in_3mf(primary_bytes)
                if plate_count == 0:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Couldn't read plate count from the source 3MF for cross-class "
                            "slice-all. The source may be malformed or missing "
                            "Metadata/model_settings.config."
                        ),
                    )
                logger.info(
                    "Arrange slice-all: looping over %d plates with --arrange per plate, then merging "
                    "(embedded_settings=%s)",
                    plate_count,
                    embedded_mode,
                )
                from backend.app.services.slicer_api import SliceResult

                per_plate_results: list[tuple[int, SliceResult]] = []

                # Forward the same progress request_id + callback to each
                # per-plate sub-call so the toast keeps showing the
                # sidecar's stage messages ("Generating G-code 45%…").
                # The sub-calls run sequentially, so the poller for plate
                # N is cancelled before plate N+1's poller starts — no
                # cross-talk between plate streams. Wrap the callback to
                # surface "(plate N/M)" alongside the slicer's stage
                # message so the user sees progress through the whole
                # multi-plate loop, not just one plate at a time.
                def _wrap_progress_for_plate(plate_num: int, total: int):
                    if progress_callback is None:
                        return None

                    def _cb(snapshot: dict) -> None:
                        snapshot = dict(snapshot)
                        snapshot["multi_plate_index"] = plate_num
                        snapshot["multi_plate_count"] = total
                        progress_callback(snapshot)

                    return _cb

                for plate_num in range(1, plate_count + 1):
                    plate_cb = _wrap_progress_for_plate(plate_num, plate_count)
                    # "Slice as designed" has to take the loop too, not skip
                    # it: the project-wide collapse is caused by --arrange,
                    # and which config drives the slice has no bearing on
                    # that. Same call, minus --load-settings.
                    if embedded_mode:
                        per_plate = await service.slice_without_profiles(
                            model_bytes=primary_bytes,
                            model_filename=model_filename,
                            plate=plate_num,
                            export_3mf=True,
                            arrange=True,
                            orient=orient_flag,
                            request_id=progress_request_id,
                            on_progress=plate_cb,
                        )
                    else:
                        per_plate = await service.slice_with_profiles(
                            model_bytes=primary_bytes,
                            model_filename=model_filename,
                            printer_profile_json=presets["printer"],
                            process_profile_json=presets["process"],
                            filament_profile_jsons=filament_jsons,
                            plate=plate_num,
                            export_3mf=True,
                            arrange=True,
                            orient=orient_flag,
                            request_id=progress_request_id,
                            on_progress=plate_cb,
                        )
                    per_plate_results.append((plate_num, per_plate))

                # Merge the N single-plate 3MFs into one multi-plate 3MF.
                # ``primary_bytes`` is the source 3MF: it carries the
                # original per-plate previews the slicer's --arrange
                # pass doesn't regenerate, so the merger can fall back
                # to those for each plate's cover image.
                merged_bytes = merge_plate_3mfs(
                    [(n, r.content) for n, r in per_plate_results],
                    source_3mf_bytes=primary_bytes,
                )
                # Synthetic SliceResult: totals are the sum of each
                # plate's so the archive card shows the project's print
                # time and filament use, not just plate 1's.
                result = SliceResult(
                    content=merged_bytes,
                    print_time_seconds=sum(r.print_time_seconds for _, r in per_plate_results),
                    filament_used_g=sum(r.filament_used_g for _, r in per_plate_results),
                    filament_used_mm=sum(r.filament_used_mm for _, r in per_plate_results),
                )
                # Report the path honestly: the loop can run either way, and
                # the UI reads this flag to tell the user whose settings won.
                used_embedded_settings = embedded_mode
            elif embedded_mode:
                # No --load-settings: feed the CLI the file's own
                # project_settings.config untouched so the designer's tweaks
                # (walls, infill, etc.) drive the slice. primary_bytes is
                # already sentinel-sanitised above, the same bytes the
                # crash-fallback uses. The resolved presets go unused here.
                # Arrange / orient still apply: they are CLI actions on the
                # geometry, not settings the embedded config could carry.
                result = await service.slice_without_profiles(
                    model_bytes=primary_bytes,
                    model_filename=model_filename,
                    plate=request.plate,
                    export_3mf=request.export_3mf,
                    arrange=arrange_flag,
                    orient=orient_flag,
                    request_id=progress_request_id,
                    on_progress=progress_callback,
                )
                used_embedded_settings = True
            else:
                result = await service.slice_with_profiles(
                    model_bytes=primary_bytes,
                    model_filename=model_filename,
                    printer_profile_json=presets["printer"],
                    process_profile_json=presets["process"],
                    filament_profile_jsons=filament_jsons,
                    plate=request.plate,
                    export_3mf=request.export_3mf,
                    arrange=arrange_flag,
                    orient=orient_flag,
                    request_id=progress_request_id,
                    on_progress=progress_callback,
                )
        except SlicerApiServerError as exc:
            rejection = _slicer_rejection_message(str(exc))
            if rejection:
                # The slicer ran and rejected the job for a content reason —
                # the chosen printer/process/filament *were* applied. Falling
                # back to embedded settings would silently re-slice for the
                # source 3MF's original printer and hide the real problem
                # (e.g. re-slicing an H2D model for an X1C: the object is off
                # the smaller bed). Surface the slicer's reason instead.
                raise HTTPException(status_code=400, detail=rejection) from exc
            if not is_3mf or embedded_mode:
                # embedded_mode already sliced with the file's own settings —
                # there is nothing to fall back TO, so surface the server
                # error (the outer handler turns it into a 502) instead of
                # re-running the same embedded slice.
                raise
            if use_arrange_slice_all:
                # The fallback is a single ``--slice 0`` call, and with
                # arrange on that collapses every plate onto one bed — the
                # exact outcome the per-plate loop above exists to avoid.
                # Retrying would hand back a one-plate result for a job the
                # user asked to slice as N, which reads as a PrintLab bug
                # rather than a slicer failure. Surface the error instead.
                raise
            logger.warning(
                "Slicer CLI failed on the --load-settings path for %s (%s); retrying with embedded settings",
                model_filename,
                exc,
            )
            # Forward the same request_id + callback so the toast's live
            # progress keeps updating across the fallback retry instead
            # of going blank for the rest of the slice. Use the sanitised
            # bytes — the embedded-settings path also reads the same
            # project_settings.config and the same range validator runs
            # there too, so without sanitisation the fallback would die
            # on the same sentinel error (#1201). The SliceModal flags
            # the difference to the user via used_embedded_settings.
            # Carry the layout flags across too — the retry is meant to
            # differ from the failed attempt only in where the print
            # config came from, so dropping them here would silently
            # produce an un-arranged result the user did ask for.
            result = await service.slice_without_profiles(
                model_bytes=primary_bytes,
                model_filename=model_filename,
                plate=request.plate,
                export_3mf=request.export_3mf,
                arrange=arrange_flag,
                orient=orient_flag,
                request_id=progress_request_id,
                on_progress=progress_callback,
            )
            used_embedded_settings = True
    except SlicerInputError as exc:
        raise SliceJobHttpError(400, str(exc), "invalid_input") from exc
    except SlicerTimeoutError as exc:
        # 504, not 502: the sidecar answered for the whole run, we stopped
        # waiting. Reported separately so the user is told the slice ran out of
        # time and where to change that, rather than that the sidecar is
        # unreachable — which is what a read timeout used to look like (#2730).
        raise SliceJobHttpError(504, str(exc), "timeout") from exc
    except SlicerApiServerError as exc:
        raise SliceJobHttpError(502, str(exc), "slicer_error") from exc
    except SlicerApiUnavailableError as exc:
        raise SliceJobHttpError(502, str(exc), "sidecar_unreachable") from exc
    finally:
        await service.close()

    # Backstop for #2838. Only the standard tier, and only when the presets we
    # sent were actually used: there the sidecar resolved a bundled preset by
    # name and the bundle guarantees the start G-code, so its absence is a
    # sidecar defect we can name. A cloud, local or Orca-cloud preset carries
    # its own start G-code, and the embedded-settings fallback prints the
    # source file's — both are the user's to author, and refusing them here
    # would be us second-guessing a profile we did not resolve.
    if (
        not used_embedded_settings
        and request.printer_preset is not None
        and request.printer_preset.source == "standard"
        and start_gcode_is_missing(result.content, export_3mf=bool(request.export_3mf))
    ):
        logger.error(
            "Slice for printer preset %r came back without start G-code (%s); refusing it",
            request.printer_preset.id,
            "3mf" if request.export_3mf else "gcode",
        )
        raise HTTPException(status_code=502, detail=missing_start_gcode_message(request.printer_preset.id))

    # Found while investigating #2977: a filament preset the sidecar's bundle
    # cannot resolve is not an error there — the CLI inherits nothing and
    # slices with its own defaults, so a PETG pick comes back as PLA at 200 C.
    # Warned rather than refused: the file prints, and the user may well have
    # meant to slice with a profile their sidecar image predates. Skipped on
    # the embedded-settings path, which sends no filament profiles for the
    # bundle to resolve in the first place.
    if not used_embedded_settings:
        unresolved = unresolved_filament_slots(result.content, export_3mf=bool(request.export_3mf))
        if unresolved:
            logger.warning(
                "%s",
                unresolved_filament_message(unresolved, [ref.id for ref in request.filament_presets]),
            )

    return result, used_embedded_settings


def _canonical_printer_model(raw: str | None) -> str | None:
    """Normalise a printer-preset name / ``printer_model`` field to a canonical
    model code. Strips the BambuStudio ``"# "`` user-clone prefix and the
    ``" 0.4 nozzle"`` variant suffix that preset names carry but bare model
    names don't — without this, ``"Bambu Lab H2D 0.4 nozzle"`` wouldn't
    normalise to ``H2D``."""
    import re

    from backend.app.utils.printer_models import normalize_printer_model

    if not raw:
        return None
    cleaned = str(raw).strip()
    if cleaned.startswith("# "):
        cleaned = cleaned[2:].strip()
    cleaned = re.sub(r"\s+0\.\d+\s+nozzle$", "", cleaned, flags=re.IGNORECASE)
    return normalize_printer_model(cleaned) if cleaned else None


async def _resolve_target_printer_model(db: AsyncSession, user: User | None, request: SliceRequest) -> str | None:
    """Best-effort: the printer model a slice request targets.

    Returns ``None`` when it can't be determined (the nozzle-class guard
    then simply doesn't fire — fail-open, never blocks a slice spuriously).
    """
    from backend.app.services.preset_resolver import resolve_preset_ref

    if request.printer_preset is None:
        return None
    try:
        printer_json = await resolve_preset_ref(db, user, request.printer_preset, "printer")
        data = json.loads(printer_json)
        if not isinstance(data, dict):
            return None
        return _canonical_printer_model(
            data.get("printer_model") or data.get("printer_settings_id") or data.get("name")
        )
    except Exception:
        return None


async def guard_nozzle_class_reslice(
    db: AsyncSession, user: User | None, request: SliceRequest, source_model: str | None
) -> None:
    """No-op guard, retained for call-site compatibility.

    Cross-nozzle-class re-slicing is handled by ``_run_slicer_with_fallback``'s
    two-pass conversion (#1493): a 1mm cube is sliced with the target triplet
    via ``slice_with_profiles`` to produce a fresh target-shaped
    ``Metadata/project_settings.config``, which is then spliced into the
    source 3MF before the real slice. So this guard never needs to block
    anymore.

    The function and its call sites in ``archives.py`` / the library re-slice
    route are kept so external pinned-version forks and downstream patches
    don't break, but it does nothing on a successful slice path. If the
    two-pass conversion fails inside the slicer, the existing
    ``SlicerApiServerError`` / ``_slicer_rejection_message`` plumbing
    surfaces the CLI's actual error to the user — which is more informative
    than the old "isn't supported yet" 400 the guard used to raise.
    """
    return None


async def slice_and_persist(
    db: AsyncSession,
    *,
    model_bytes: bytes,
    model_filename: str,
    folder_id: int | None,
    extra_metadata: dict | None,
    request: SliceRequest,
    current_user_id: int | None,
    job_id: int | None = None,
) -> SliceResponse:
    """Slice a model and save the result as a new ``LibraryFile`` in
    ``folder_id`` (same folder as the source by convention).

    Always exports as ``.gcode.3mf`` so the existing library thumbnail
    pipeline works on the new file. Plain ``.gcode`` would have no
    embedded thumbnail to extract.
    """
    from backend.app.services.archive import ThreeMFParser

    library_request = request.model_copy(update={"export_3mf": True})

    result, used_embedded_settings = await _run_slicer_with_fallback(
        db,
        model_bytes=model_bytes,
        model_filename=model_filename,
        request=library_request,
        current_user_id=current_user_id,
        job_id=job_id,
    )

    # Same reduction as the archive sink: ``model_filename`` may be built from
    # the source's embedded ``print_name``, which is free text (#2832). Managed
    # storage names the file after a UUID and never sees this, but an external
    # folder writes it verbatim, where a "/" would mean a directory nobody
    # created -- and the library row shows it either way.
    base_name = model_filename.rsplit(".", 1)[0]
    safe_base = safe_path_component(base_name, fallback="sliced", max_bytes=MAX_FILENAME_BYTES - len(b".gcode.3mf"))
    out_filename = f"{safe_base}.gcode.3mf"
    # Write next to the source when the source lives on an external mount
    # (#2810). The folder is loaded here rather than passed in because every
    # caller already has only the id.
    target_folder: LibraryFolder | None = None
    if folder_id is not None:
        folder_result = await db.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id))
        target_folder = folder_result.scalar_one_or_none()
    out_path, out_is_external, external_fallback = _resolve_slice_destination(target_folder, out_filename)
    if out_is_external:
        # _unique_external_name may have suffixed it; the library row has to
        # show the name the file actually has on the share, or the two drift.
        out_filename = out_path.name
    if external_fallback:
        logger.warning(
            "Slice output for %s stored in managed library instead of external folder %s: %s",
            model_filename,
            target_folder.external_path if target_folder else None,
            external_fallback,
        )
    # BS/Orca CLIs skip plate_N.png in headless --export-3mf — render +
    # inject server-side so the library card has a thumbnail. Best-effort:
    # no-op when the slicer did embed thumbs (desktop Studio path), and
    # falls through to the unmodified bytes on any render error. In a thread:
    # a large plate renders for seconds, and on the event loop that stalled
    # every request and printer connection for as long (#3135).
    result = result._replace(content=await asyncio.to_thread(inject_plate_thumbnails_if_missing, result.content))
    out_path.write_bytes(result.content)

    # Extract thumbnail from the produced 3MF so the library card shows a
    # preview. Failures here aren't fatal — the file is still useful
    # without a thumbnail.
    thumbnail_relative: str | None = None
    parsed_metadata: dict = {}
    try:
        parser = ThreeMFParser(str(out_path))
        parsed = parser.parse()
        thumb_data = parsed.get("_thumbnail_data")
        thumb_ext = parsed.get("_thumbnail_ext", ".png")
        if thumb_data:
            thumb_filename = f"{uuid.uuid4().hex}{thumb_ext}"
            thumb_path = get_library_thumbnails_dir() / thumb_filename
            thumb_path.write_bytes(thumb_data)
            thumbnail_relative = to_relative_path(thumb_path)
        cleaned = _clean_3mf_metadata(parsed)
        if isinstance(cleaned, dict):
            parsed_metadata = cleaned
    except Exception as exc:
        logger.warning("Failed to parse sliced 3MF metadata for %s: %s", out_filename, exc)

    # Drop the embedded `print_name` (see _without_print_name) so the sliced
    # row's display falls back to its ".gcode.3mf" filename instead of the
    # source file's project title, which would make the two indistinguishable.
    metadata: dict = dict(_without_print_name(parsed_metadata) or {})
    # Some slicer-sidecar builds leave the X-Filament-Used-* response headers
    # unset, so result.filament_used_g/_mm arrive as 0 even for a real
    # multi-hour print. Fall back to the totals ThreeMFParser read from the
    # produced 3MF's own G-code header.
    filament_g = result.filament_used_g or parsed_metadata.get("filament_used_grams") or 0.0
    filament_mm = result.filament_used_mm or parsed_metadata.get("filament_used_mm") or 0.0
    metadata.update(
        {
            "print_time_seconds": result.print_time_seconds,
            "filament_used_g": filament_g,
            "filament_used_mm": filament_mm,
        }
    )
    if used_embedded_settings:
        metadata["used_embedded_settings"] = True
    if external_fallback:
        metadata["external_write_fallback"] = external_fallback
    if extra_metadata:
        metadata.update(extra_metadata)

    new_file = LibraryFile(
        folder_id=folder_id,
        is_external=out_is_external,
        filename=out_filename,
        file_path=_stored_file_path(out_path, out_is_external),
        # The on-disk payload is a ZIP container — the file_type must
        # record that so the preview endpoint opens it as a 3MF instead
        # of returning the ZIP bytes as text/plain (#1709 / yanglei1980).
        # Earlier code mis-typed sliced rows as "gcode" to share the
        # plain-G-code badge; that broke the embedded viewer. UI badges
        # and gates for "gcode.3mf" are explicit at the call sites.
        file_type="gcode.3mf",
        file_size=len(result.content),
        file_hash=hashlib.sha256(result.content).hexdigest(),
        thumbnail_path=thumbnail_relative,
        file_metadata=metadata,
        source_type="sliced",
        created_by_id=current_user_id,
    )
    db.add(new_file)
    await db.commit()
    # No refresh: expire_on_commit=False keeps id/filename accessible, and
    # refreshing here flakes under pytest-xdist when teardown of a sibling
    # test races the SELECT.

    return SliceResponse(
        library_file_id=new_file.id,
        name=new_file.filename,
        print_time_seconds=result.print_time_seconds,
        filament_used_g=filament_g,
        filament_used_mm=filament_mm,
        used_embedded_settings=used_embedded_settings,
        external_write_fallback=external_fallback,
    )


async def slice_and_persist_as_archive(
    db: AsyncSession,
    *,
    model_bytes: bytes,
    model_filename: str,
    request: SliceRequest,
    source_archive,  # PrintArchive — hint kept loose to avoid cyclic import
    current_user_id: int | None,
    job_id: int | None = None,
):
    """Slice a model and save the result as a new ``PrintArchive`` row,
    inheriting printer / project / makerworld metadata from the source
    archive. Always exports as a `.gcode.3mf` so the existing thumbnail
    and plates infrastructure (which expects a zip-shaped 3MF) works on
    the new archive. Returns ``SliceArchiveResponse``.
    """
    from backend.app.models.archive import PrintArchive
    from backend.app.schemas.slicer import SliceArchiveResponse
    from backend.app.services.archive import ThreeMFParser

    # Archive sinks always want a 3MF. The library route still respects the
    # caller's `export_3mf` flag; here we override.
    archive_request = request.model_copy(update={"export_3mf": True})

    result, used_embedded_settings = await _run_slicer_with_fallback(
        db,
        model_bytes=model_bytes,
        model_filename=model_filename,
        request=archive_request,
        job_id=job_id,
        current_user_id=current_user_id,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    printer_folder = str(source_archive.printer_id) if source_archive.printer_id is not None else "unassigned"

    # ``model_filename`` is built from the archive's display name, which comes
    # from the 3MF's own metadata and is whatever the model's author typed. A
    # "/" in it is a path separator, not a character: the joins below silently
    # gain a level and the write lands on a parent that was never created
    # (#2832). Reduce it to a single component first, leaving room for the
    # prefix and the extension wrapped around it.
    base_name = model_filename.rsplit(".", 1)[0]
    reserve = max(len(f"{timestamp}__sliced".encode()), len(b".gcode.3mf"))
    safe_base = safe_path_component(
        base_name, fallback=f"archive_{source_archive.id}", max_bytes=MAX_FILENAME_BYTES - reserve
    )
    out_filename = f"{safe_base}.gcode.3mf"
    archive_subdir = f"{timestamp}_{safe_base}_sliced"

    archive_dir = (
        app_settings.archive_dir / printer_folder / archive_subdir
    )  # SEC-PATH-OK: printer_folder = str(int|None); archive_subdir wraps safe_path_component output, asserted below
    out_path = archive_dir / out_filename  # SEC-PATH-OK: out_filename wraps safe_path_component output, asserted below
    # The sanitiser is what makes the two joins single-component; this is the
    # backstop that says so out loud, and would catch a future edit that reaches
    # around it. Checked before mkdir so a rejected path creates nothing.
    assert_under(app_settings.archive_dir, archive_dir, http=False)
    assert_under(app_settings.archive_dir, out_path, http=False)
    archive_dir.mkdir(parents=True, exist_ok=True)
    # See library-slice path: BS/Orca sidecar CLIs don't embed plate_N.png
    # in headless --export-3mf, so the produced 3MF often has no thumbnail
    # at all. Server-side render fills the gap; no-op when the slicer did
    # embed (desktop Studio path) and best-effort on any render error. Off the
    # event loop, like the library-slice path (#3135).
    result = result._replace(content=await asyncio.to_thread(inject_plate_thumbnails_if_missing, result.content))
    out_path.write_bytes(result.content)

    # Extract a thumbnail for the new archive card. Priority order:
    #   1. Source archive's ``Metadata/plate_{N}.png`` — the GUI-rendered
    #      preview of the same plate the user is re-slicing. Closer to
    #      "what's actually printing" than any other available image
    #      (with --arrange the layout may differ slightly, but objects
    #      and colours match).
    #   2. ``ThreeMFParser`` fallback chain on the sliced output: the
    #      slicer's own per-plate render if it wrote one, then the
    #      project-wide thumbnail under ``Auxiliaries/.thumbnails/``.
    # BambuStudio CLI frequently doesn't emit a fresh per-plate render
    # (slice writes the new gcode but leaves the preview slot empty),
    # so without (1) the card falls all the way through to the
    # MakerWorld-style cover art — visually unrelated to what the user
    # picked, see #1493 follow-up. Failures don't fail the slice — the
    # archive row is still useful without a thumbnail.
    plate_num = request.plate or 1
    thumbnail_path: str | None = None
    parsed_metadata: dict = {}

    src_3mf_path = app_settings.base_dir / source_archive.file_path
    source_plate_bytes = _read_3mf_entry(src_3mf_path, f"Metadata/plate_{plate_num}.png")
    if source_plate_bytes:
        thumb_dest = archive_dir / "thumbnail.png"
        thumb_dest.write_bytes(source_plate_bytes)
        thumbnail_path = thumb_dest.relative_to(app_settings.base_dir).as_posix()

    try:
        parser = ThreeMFParser(str(out_path), plate_number=plate_num)
        parsed = parser.parse()
        if thumbnail_path is None:
            thumb_data = parsed.get("_thumbnail_data")
            thumb_ext = parsed.get("_thumbnail_ext", ".png")
            if thumb_data:
                thumb_dest = archive_dir / f"thumbnail{thumb_ext}"
                thumb_dest.write_bytes(thumb_data)
                thumbnail_path = thumb_dest.relative_to(app_settings.base_dir).as_posix()
        parsed_metadata = {k: v for k, v in parsed.items() if not k.startswith("_")}
    except Exception as exc:
        logger.warning("Failed to parse sliced 3MF metadata for %s: %s", out_filename, exc)

    metadata = dict(source_archive.extra_data) if source_archive.extra_data else {}
    metadata.update(parsed_metadata)
    # Fall back to the produced 3MF's G-code-header totals when the sidecar
    # leaves the X-Filament-Used-* headers unset (result.filament_used_g == 0
    # even for a real multi-hour print).
    filament_g = result.filament_used_g or parsed_metadata.get("filament_used_grams") or 0.0
    filament_mm = result.filament_used_mm or parsed_metadata.get("filament_used_mm") or 0.0
    metadata.update(
        {
            "sliced_from_archive_id": source_archive.id,
            "print_time_seconds": result.print_time_seconds,
            "filament_used_g": filament_g,
            "filament_used_mm": filament_mm,
        }
    )
    if used_embedded_settings:
        metadata["used_embedded_settings"] = True

    # Prefer the actually-used filament list from the sliced output's
    # slice_info.config (parsed_metadata.filament_* — only entries with
    # used_g > 0). Falling back to the source_archive's list would
    # surface every project-wide AMS slot, including ones the picked
    # plate doesn't use (16+ swatches on the card for a 2-color print).
    new_filament_type = parsed_metadata.get("filament_type") or source_archive.filament_type
    new_filament_color = parsed_metadata.get("filament_color") or source_archive.filament_color

    # When the user re-slices for a different printer model than the source,
    # the source's printer_id (e.g. an H2D's "Workshop H2C") no longer
    # represents where the new archive can be reprinted. The archive card
    # and reprint modal both read printer_id first and only fall back to
    # sliced_for_model when it's None, so leaving the inherited id makes
    # the X1C-sliced card display the source H2D's printer name.
    # Same pitfall as the sliced_for_model copy a few lines below.
    new_target_model = parsed_metadata.get("sliced_for_model") or source_archive.sliced_for_model
    is_cross_model_reslice = (
        new_target_model is not None
        and source_archive.sliced_for_model is not None
        and new_target_model != source_archive.sliced_for_model
    )
    new_printer_id = None if is_cross_model_reslice else source_archive.printer_id

    new_archive = PrintArchive(
        printer_id=new_printer_id,
        project_id=source_archive.project_id,
        filename=out_filename,
        file_path=out_path.relative_to(app_settings.base_dir).as_posix(),
        file_size=len(result.content),
        content_hash=hashlib.sha256(result.content).hexdigest(),
        thumbnail_path=thumbnail_path,
        # Inherit identity from the source archive so the new entry shows
        # up alongside its sibling in the archives list.
        print_name=(source_archive.print_name or base_name) + " (re-sliced)",
        print_time_seconds=result.print_time_seconds,
        filament_used_grams=filament_g or None,
        filament_type=new_filament_type,
        filament_color=new_filament_color,
        layer_height=source_archive.layer_height,
        nozzle_diameter=source_archive.nozzle_diameter,
        # The re-sliced output is for whatever printer the user just picked,
        # not the source archive's printer — read the model the slicer baked
        # into the new 3MF, falling back to the source only if it's absent.
        # (Copying source_archive.sliced_for_model kept a cross-printer
        # re-slice, e.g. X1C→H2D, showing the old "X1C sliced" model.)
        sliced_for_model=parsed_metadata.get("sliced_for_model") or source_archive.sliced_for_model,
        # Build plate type that the sliced output was produced for (#1493
        # follow-up): the frontend's ArchiveCard reads ``archive.bed_type``
        # off the top-level column, not extra_data, so without this lift the
        # re-sliced card had no plate badge. ThreeMFParser pulls it from the
        # sliced 3MF's ``slice_info.config`` ``curr_bed_type``; if that's
        # absent (older sidecar / older slice profile) the source archive's
        # bed_type is the right default.
        bed_type=parsed_metadata.get("bed_type") or source_archive.bed_type,
        makerworld_url=source_archive.makerworld_url,
        designer=source_archive.designer,
        # Sliced-but-not-printed: keep status default ("completed") so it
        # surfaces in the normal archives list, but do not stamp
        # started/completed_at — the user hasn't actually printed it yet.
        extra_data=metadata,
        created_by_id=current_user_id,
    )
    db.add(new_archive)
    await db.commit()
    await db.refresh(new_archive)

    return SliceArchiveResponse(
        archive_id=new_archive.id,
        name=new_archive.print_name or out_filename,
        print_time_seconds=result.print_time_seconds,
        filament_used_g=filament_g,
        filament_used_mm=filament_mm,
        used_embedded_settings=used_embedded_settings,
    )


@router.post("/files/{file_id}/slice", status_code=202)
async def slice_library_file(
    file_id: int,
    request: SliceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_permission_if_auth_enabled(Permission.LIBRARY_UPLOAD)),
    api_key_cloud_owner: User | None = Depends(resolve_api_key_cloud_owner),
):
    """Enqueue a slice job for a library file. Returns 202 + job_id; the
    slice runs in the background, the caller polls `GET /slice-jobs/{id}`.
    """
    from backend.app.core.database import async_session
    from backend.app.services.slice_dispatch import (
        http_exception_to_job_error,
        slice_dispatch,
    )

    src_result = await db.execute(LibraryFile.active().where(LibraryFile.id == file_id))
    lib_file = src_result.scalar_one_or_none()
    # Per-row ownership gate. LIBRARY_UPLOAD alone let a READ_OWN caller (e.g. the
    # built-in Operators group) slice another user's model by raw id even though
    # GET on that id returned 404 — the sliced output was then attributed to and
    # downloadable by the requester. Enforce the same visibility the read routes
    # use before reading the source off disk. API-key / auth-disabled callers
    # (current_user is None) keep can_read_all=True — no per-row identity.
    can_read_all = current_user is None or current_user.has_permission(Permission.LIBRARY_READ_ALL.value)
    lib_file = _ensure_library_file_visible(lib_file, current_user, can_read_all)

    src_lower = (lib_file.filename or "").lower()
    if src_lower.endswith(".step") or src_lower.endswith(".stp"):
        # Neither slicer's CLI can load STEP: OrcaSlicer 2.4.2 and BambuStudio
        # 02.07.01.62 both answer "Unknown file format. Input file must have
        # .stl, .obj, .amf(.xml) extension." Accepting the job here meant
        # reading the file, converting it and uploading it before the sidecar
        # rejected it as unparseable -- which reads as a corrupt model rather
        # than an unsupported format. Say so before any of that happens.
        raise HTTPException(
            status_code=400,
            detail=(
                "STEP files cannot be sliced. The OrcaSlicer and Bambu Studio command-line "
                "slicers load only STL and 3MF -- open the STEP in your slicer and export it "
                "as one of those first."
            ),
        )
    if not (src_lower.endswith(".stl") or src_lower.endswith(".3mf")):
        raise HTTPException(status_code=400, detail="Source file must be STL or 3MF")

    src_path = Path(app_settings.base_dir) / lib_file.file_path
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="Source file missing on disk")

    # Capture inputs the bg task needs — the request DB session is closed
    # before the background task runs.
    model_bytes = src_path.read_bytes()
    folder_id = lib_file.folder_id
    source_lib_file_id = lib_file.id
    # API-keyed callers get None from the auth gate (auth.py keeps that
    # behaviour to avoid a wider scope expansion). Fall back to the API
    # key's owner so cloud-preset resolution can read the stored
    # cloud_token (#1182 follow-up).
    cloud_token_user = current_user or api_key_cloud_owner
    user_id = cloud_token_user.id if cloud_token_user else None

    # If the source has a `print_name` in its metadata (BambuStudio always
    # sets this; OrcaSlicer often leaves it blank), derive the sliced
    # output's filename from it instead of the raw filename. The source
    # row's display already prefers print_name, so the sliced row's
    # filename ("Piggo the piggy bank.gcode.3mf") will match the source's
    # display name ("Piggo the piggy bank") with the gcode extension added.
    src_print_name = None
    if lib_file.file_metadata:
        candidate = lib_file.file_metadata.get("print_name")
        if isinstance(candidate, str) and candidate.strip():
            src_print_name = candidate.strip()
    src_ext = Path(lib_file.filename).suffix.lower() or ".3mf"
    model_filename = f"{src_print_name}{src_ext}" if src_print_name else lib_file.filename

    # Block a cross-nozzle-class re-slice (single-nozzle <-> H2D) up front.
    # Fires only when the source is itself a sliced file (carries
    # sliced_for_model); a plain un-sliced model has no source nozzle class.
    await guard_nozzle_class_reslice(
        db,
        cloud_token_user,
        request,
        (lib_file.file_metadata or {}).get("sliced_for_model"),
    )

    async def _run(job_id: int):
        async with async_session() as task_db:
            try:
                response = await slice_and_persist(
                    task_db,
                    model_bytes=model_bytes,
                    model_filename=model_filename,
                    folder_id=folder_id,
                    extra_metadata={"sliced_from_library_file_id": source_lib_file_id},
                    request=request,
                    current_user_id=user_id,
                    job_id=job_id,
                )
            except HTTPException as exc:
                raise http_exception_to_job_error(exc) from exc
        return response.model_dump()

    job = await slice_dispatch.enqueue(
        kind="library_file",
        source_id=lib_file.id,
        source_name=lib_file.filename,
        owner_id=user_id,
        run=_run,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "status_url": f"/api/v1/slice-jobs/{job.id}",
    }


@router.post("/files/{file_id}/print")
async def print_library_file(
    file_id: int,
    printer_id: int,
    # SECURITY.md SEC-AUTH-1: every route either has an explicit auth dep or
    # is in the route-auth-coverage allowlist. Gating the deprecation stub on
    # QUEUE_CREATE matches the replacement route (POST /queue/) and means
    # anonymous callers bounce at auth instead of seeing the deprecation
    # message.
    _: User | None = Depends(require_permission_if_auth_enabled(Permission.QUEUE_CREATE)),
):
    """Legacy direct library print endpoint. Use POST /queue/ instead."""
    logger.warning(
        "Gone API used: POST /library/files/%s/print?printer_id=%s; use POST /queue/ instead",
        file_id,
        printer_id,
    )
    raise HTTPException(
        status_code=410,
        detail="Direct library-file print has been removed. Create a print queue item with POST /queue/.",
    )


