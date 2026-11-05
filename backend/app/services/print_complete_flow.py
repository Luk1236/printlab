"""
Abschluss-Helfer: Status-Harmonisierung, Meldungs-Bausteine, Ausgangsfragen und Wiedervereinigung

Zustaende und die von den Tests umgebogenen Namen bleiben im Modul main
und werden über :func:`_rt` gelesen. Aufrufer und Tests sehen keinen
Unterschied.
"""

import importlib
import logging
from pathlib import Path, PurePosixPath

from sqlalchemy import select

# der Logger-Name bleibt der der alten Heimat (Backend-Protokolle)
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen."""

    return importlib.import_module("backend.app.main")


def _compute_run_filament_grams(
    status: str,
    archive_filament_used_grams: float | None,
    progress: float | int | None,
    usage_results: list[dict] | None,
) -> float | None:
    """Per-run filament for PrintLogEntry, partial- and tracker-aware (#1378, #1390).

    Priority for every status:
        1. Sum of tracked spool deltas in ``usage_results`` (AMS-measured
           weight delta — same source that drives "Total Consumed" on the
           Inventory page, so Stats and Inventory totals stay aligned).
        2. For ``completed``: the slicer estimate (no tracker available, fall
           back to the canonical "this print used X" value).
        3. For partial statuses: ``estimate * progress%``.
        4. ``None`` if nothing is known.
    """
    tracked_grams = sum(r.get("weight_used") or 0 for r in (usage_results or []))
    if tracked_grams > 0:
        return round(tracked_grams, 1)

    if status == "completed":
        return archive_filament_used_grams

    if archive_filament_used_grams:
        scale = max(0.0, min(((progress or 0) / 100.0), 1.0))
        if scale > 0:
            return round(archive_filament_used_grams * scale, 1)

    return None


def _partial_progress_scale(progress: int | float | None) -> float:
    """Clamp ``progress / 100`` into [0.0, 1.0] for partial-print scaling.

    Used by every site that multiplies a "would-have-used" slicer estimate
    down to "actually-used" for failed / cancelled / stopped prints. Centralised
    so the three sites in ``_background_notifications`` (and the per-plate
    override helper) can't drift apart on the coercion shape.
    """
    return max(0.0, min((progress or 0) / 100.0, 1.0))


def _scope_notification_archive_data_to_plate(
    archive_data: dict,
    archive_file_path: str | None,
    plate_id: int | None,
    print_status: str,
    progress: int | float | None,
    base_dir: Path,
) -> dict:
    """Override summed-across-plates totals in ``archive_data`` with the values
    for ``plate_id`` so the completion notification reports what was actually
    printed, not the whole project (#1785).

    The 3MF parser at services/archive.py:200-264 sums ``prediction`` and
    ``weight`` across every plate of a multi-plate file (#1593) — correct for
    the archive card's "whole project" headline, wrong for the completion
    notification of a single-plate print. The queue UI already re-reads the
    3MF per-plate at print_queue.py:272-285; this helper mirrors that for the
    notification payload (filament grams, time estimate, per-slot breakdown).

    No-ops when ``plate_id`` is None, the file is missing, or the 3MF carries
    no per-plate values — in every fail case the original ``archive_data`` is
    returned unchanged so the notification still sends.
    """
    if plate_id is None or not archive_file_path:
        return archive_data

    from backend.app.utils.threemf_tools import (
        extract_filament_usage_from_3mf,
        extract_print_time_from_3mf,
    )

    archive_path = base_dir / archive_file_path  # SEC-PATH-OK: archive_file_path ist die DB-Spalte archive.file_path (archivintern verwaltet, keine Anfrage-Eingabe)
    if not archive_path.exists():
        return archive_data

    plate_slots = extract_filament_usage_from_3mf(archive_path, plate_id)
    plate_grams = sum(f.get("used_g", 0) for f in plate_slots)
    plate_time = extract_print_time_from_3mf(archive_path, plate_id)

    scale = 1.0 if print_status == "completed" else _partial_progress_scale(progress)

    if plate_time:
        archive_data["print_time_seconds"] = plate_time

    # Gate both the grams headline AND the per-slot breakdown on the same
    # `plate_grams > 0` signal: if the 3MF carries per-plate filament rows but
    # they all sum to zero (slicer bug / re-slice without estimate), drop back
    # to the project-level grams the archive columns already provide rather
    # than ship a project-level headline next to an all-zero per-plate
    # breakdown.
    if plate_grams > 0:
        archive_data["actual_filament_grams"] = round(plate_grams * scale, 1)
        archive_data["filament_slots"] = [
            {
                "slot_id": s.get("slot_id"),
                "used_g": round((s.get("used_g") or 0) * scale, 1),
                "type": s.get("type", ""),
                "color": s.get("color", ""),
            }
            for s in plate_slots
        ]

    return archive_data


async def _finish_photo_for_notification(
    db, archive, archive_id: int, filename: str
) -> tuple[str | None, bytes | None]:
    """The ``{finish_photo_url}`` link and the bytes to attach, for a print's finish photo.

    With authentication off the link is the archive's own photo route, as it
    always was: it opens without a login and doesn't expire. With
    authentication on that route needs a media token, which nothing tapping a
    link in Telegram, CallMeBot or a Home Assistant notification has, so the
    link only ever answered 401. The photo is then saved as a notification
    photo as well (utils/notification_photos.py) and the link points there: an
    unguessable name that opens this one photo and nothing else, for 3 days.

    The link is relative when no External URL is set. Bytes over
    ``_FINISH_PHOTO_ATTACH_MAX_BYTES`` are linked but not attached. Returns
    ``(None, None)`` when the photo can't be found.
    """
    from backend.app.api.routes.settings import get_setting
    from backend.app.core.auth import is_auth_enabled
    from backend.app.utils.archive_paths import find_archive_photo
    from backend.app.utils.notification_photos import save_notification_photo

    log = logging.getLogger(__name__)
    base = ((await get_setting(db, "external_url")) or "").strip().rstrip("/")
    url: str | None = f"{base}/api/v1/archives/{archive_id}/photos/{filename}"

    photo_bytes: bytes | None = None
    try:
        photo_path = find_archive_photo(archive, filename)
        if photo_path is not None:
            photo_bytes = await _rt().asyncio.to_thread(photo_path.read_bytes)
    except Exception as e:
        log.warning("[NOTIFY-BG] Failed to read finish photo bytes: %s", e)

    try:
        auth_on = await is_auth_enabled(db)
    except Exception:
        auth_on = True  # Unknown: the archive link may need a login, so don't rely on it.
    if auth_on:
        url = None
        if photo_bytes:
            try:
                name = await _rt().asyncio.to_thread(save_notification_photo, photo_bytes, "print_complete")
                url = f"{base}/api/v1/notifications/photos/{name}"
            except Exception as e:
                log.warning("[NOTIFY-BG] Failed to save finish photo for its link: %s", e)

    if photo_bytes is not None and len(photo_bytes) > _rt()._FINISH_PHOTO_ATTACH_MAX_BYTES:
        log.warning("[NOTIFY-BG] Finish photo too large for attachment: %s bytes", len(photo_bytes))
        return url, None
    if photo_bytes:
        log.info("[NOTIFY-BG] Loaded finish photo bytes: %s bytes", len(photo_bytes))
    return url, photo_bytes


async def _dispatch_user_print_email(
    status: str,
    created_by_id: int | None,
    printer_name: str,
    filename: str,
    db,
    image_data: bytes | None = None,
    finish_photo_url: str | None = None,
) -> None:
    """Send a user-specific print-completion email based on print status.

    Maps the normalised print status to the correct event type and delegates
    to :meth:`NotificationService.send_user_print_email`.  A single helper
    avoids duplicating the ``if status == "completed" / elif "failed" / elif
    "stopped"`` dispatch block at every call site.

    Does nothing if *created_by_id* is ``None``.
    """
    if created_by_id is None:
        return
    if status == "completed":
        event_type = "user_print_complete"
    elif status == "failed":
        event_type = "user_print_failed"
    elif status in ("stopped", "aborted", "cancelled"):
        event_type = "user_print_stopped"
    else:
        return
    await _rt().notification_service.send_user_print_email(
        event_type=event_type,
        created_by_id=created_by_id,
        printer_name=printer_name,
        filename=filename,
        db=db,
        image_data=image_data,
        finish_photo_url=finish_photo_url,
    )


async def _dispatch_outcome_confirmation_safely(
    db,
    printer_id: int,
    printer_name: str,
    data: dict,
    archive_id: int,
    archive_data: dict | None = None,
) -> None:
    """``dispatch_outcome_confirmation`` for a caller that has more to do on ``db``.

    The completion task sends the per-user print email on the same session
    right after the prompt. A failed statement in the prompt leaves that
    session needing a rollback, and without one the email step fails with
    PendingRollbackError; the prompt is the optional part, so it must not be
    the reason the email never goes out.
    """
    try:
        await dispatch_outcome_confirmation(db, printer_id, printer_name, data, archive_id, archive_data)
    except Exception as e:
        logging.getLogger(__name__).error("[NOTIFY-BG] Outcome-confirmation dispatch failed: %s", e, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            logging.getLogger(__name__).debug("Rollback after a failed outcome confirmation failed too", exc_info=True)


async def dispatch_outcome_confirmation(
    db,
    printer_id: int,
    printer_name: str,
    data: dict,
    archive_id: int,
    archive_data: dict | None = None,
) -> bool:
    """Emit the post-print outcome prompt for a completed archive (#1898).

    Gated on the archive itself: ``confirm_requested`` is the opt-in (from the
    queue item, or from ``confirm_outcome_external_prints`` for a print
    PrintLab did not start) and ``user_verdict`` being unset is what makes the
    question still open. Mints the per-archive capability token the one-tap
    verdict links carry.

    Lives here rather than inline in ``on_print_complete``'s notification task
    because that task swallows every exception: extracted, the gate and the two
    emissions can be driven by a test, which is the only thing standing between
    a regression here and a farm that quietly stops asking.

    Returns whether a prompt was sent.
    """
    logger = logging.getLogger(__name__)
    from backend.app.models.archive import PrintArchive

    confirm_archive = (await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))).scalar_one_or_none()
    if not (confirm_archive and confirm_archive.confirm_requested and confirm_archive.user_verdict is None):
        return False

    import secrets as _secrets

    # A spent token stays on the row so the one-tap route can recognise it, so
    # "has a token" no longer means "answerable". A prompt going out now needs a
    # live one: mint a new token whenever the stored one is already spent, or
    # every button in the new message would land on the already-answered page.
    if not confirm_archive.confirm_token or confirm_archive.confirm_token_used_at is not None:
        confirm_archive.confirm_token = _secrets.token_urlsafe(32)
        confirm_archive.confirm_token_used_at = None
        await db.commit()

    from backend.app.api.routes.settings import get_external_base_url, get_setting

    base = await get_external_base_url(db)
    if not await get_setting(db, "external_url"):
        # Both the Telegram inline keyboard and the ntfy action buttons need an
        # absolute URL, so an unconfigured install used to get a message body
        # with two unusable relative paths and no buttons at all. The shared
        # fallback at least produces tappable links; say which setting makes
        # them resolve from a phone.
        logger.warning(
            "[#1898] No external_url configured — the outcome prompt's Good/Reject links point at %s. "
            "Set Settings → External URL so they resolve away from this host.",
            base,
        )
    token = confirm_archive.confirm_token
    good_url = f"{base}/api/v1/archives/confirm/{token}/good"
    reject_url = f"{base}/api/v1/archives/confirm/{token}/reject"
    confirm_url = f"{base}/archives?confirm={archive_id}"

    await _rt().ws_manager.send_print_confirm_request(
        printer_id,
        {
            "archive_id": archive_id,
            "print_name": confirm_archive.print_name or confirm_archive.filename,
        },
    )
    await _rt().notification_service.on_print_confirm_request(
        printer_id,
        printer_name,
        data,
        db,
        archive_data=archive_data,
        good_url=good_url,
        reject_url=reject_url,
        confirm_url=confirm_url,
        archive_id=archive_id,
    )
    return True


async def _restore_usage_tracking_session(printer_id: int, state, db, logger) -> None:
    """Put the filament-attribution context back after a restart mid-print.

    ``usage_tracker._active_sessions`` and ``PrinterState.tray_change_log``
    both die with the process. The print keeps running, so at completion the
    tracker would fall back to whatever the printer reports *now* — and AMS
    filament backup makes "now" the substitute tray, charging the whole print
    to the spool that only finished it.

    The persisted row is only trusted when its print name still matches what
    the printer says it is running: a row left behind by a completion we never
    saw must not attach itself to the next print.
    """
    try:
        from backend.app.api.routes.settings import get_setting
        from backend.app.services.usage_tracker import (
            clear_persisted_session,
            get_persisted_print_name,
            restore_session,
        )

        persisted_name = await get_persisted_print_name(db, printer_id)
        current_name = (state.subtask_name or "").strip()
        if persisted_name and current_name and persisted_name.strip() != current_name:
            logger.info(
                "[RESTART] Discarding stale print session for printer %s (%r != running %r)",
                printer_id,
                persisted_name,
                current_name,
            )
            await clear_persisted_session(db, printer_id)
            # Fall through to seeding: the print on the printer is real, it just
            # isn't the one the row described.
            persisted_log = None
        else:
            # Spoolman users get the tray-change log back but no in-memory
            # session — see ``on_print_start`` on why that dict is load-bearing
            # for the remain%-sync guard.
            _spoolman_on = await get_setting(db, "spoolman_enabled")
            persisted_log = await restore_session(
                db,
                printer_id,
                register_active=not (bool(_spoolman_on) and _spoolman_on.lower() == "true"),
            )
        if persisted_log:
            restored = [tuple(entry) for entry in persisted_log if isinstance(entry, (list, tuple)) and len(entry) == 2]
            # Anything this process already observed goes after the persisted
            # history — the log is ordered by layer, and a fresh process can
            # only have seen changes from later in the print.
            for entry in state.tray_change_log or []:
                if tuple(entry) not in restored:
                    restored.append(tuple(entry))
            state.tray_change_log = restored

        tray_now = state.tray_now
        if 0 <= tray_now <= 254:
            if not state.tray_change_log:
                # No persisted history — a print that started before this build,
                # or before the row existed. Seed with the tray feeding right
                # now so the remainder of the print is at least attributable to
                # the right spool.
                state.tray_change_log = [(tray_now, state.layer_num)]
                logger.info(
                    "[RESTART] Seeded tray change log for printer %s: tray=%d at layer=%d",
                    printer_id,
                    tray_now,
                    state.layer_num,
                )
            # The tray handler updates ``last_loaded_tray`` on every push
            # regardless of whether it logged a change, so re-align it to avoid
            # a duplicate entry on the next push. Only ever with a real tray:
            # ``last_loaded_tray`` is the "survives the end-of-print retract to
            # 255" fallback, and writing 255 into it would defeat that.
            state.last_loaded_tray = tray_now
    except Exception:
        # Never let attribution recovery cost the caller its timelapse
        # baseline — that capture has to happen before the printer uploads
        # the in-flight MP4 and there is no second chance at it.
        logger.exception("[RESTART] Failed to restore usage-tracking session for printer %s", printer_id)


async def on_print_running_observed(printer_id: int, data: dict):
    """Restart-recovery for a print that started before PrintLab came up.

    bambu_mqtt.py suppresses ``on_print_start`` on the first RUNNING push
    after PrintLab startup (#1304 guard, prevents duplicate archive
    creation). This hook restores the persisted archive into ``_active_prints``
    and captures the timelapse baseline that normally hangs off print start.

    Fires once per session, in lieu of on_print_start when restart-recovery
    kicks in. The printer doesn't upload the timelapse until after PRINT
    COMPLETE, so a baseline captured any time during the print is still
    pre-upload.
    """
    logger = logging.getLogger(__name__)

    async with _rt().async_session() as db:
        from backend.app.models.printer import Printer

        state = _rt().printer_manager.get_status(printer_id)
        if state is not None:
            authorization = await _rt()._is_printlab_authorized_print(printer_id, state, db)
            if authorization is True:
                logger.info("[RESTART] Restored active PrintLab print for printer %s", printer_id)

            await _restore_usage_tracking_session(printer_id, state, db, logger)
            await _rt()._restore_printable_objects(printer_id, state, db, logger)

        result = await db.execute(select(Printer).where(Printer.id == printer_id))
        printer = result.scalar_one_or_none()
        if not printer:
            logger.warning(
                "[TIMELAPSE] on_print_running_observed: printer %s not found in DB, skipping baseline",
                printer_id,
            )
            return

    # Avoid double-capture: ownership reconciliation above must still run when
    # a baseline already exists, but the camera work itself is one-shot.
    if printer_id in _rt()._timelapse_baselines:
        logger.debug(
            "[TIMELAPSE] on_print_running_observed: baseline already present for printer %s, skipping",
            printer_id,
        )
        return

    await _rt()._capture_timelapse_baseline_at_start(printer, printer_id, logger)


def _is_active_archive_stale(archive, state) -> tuple[bool, str]:
    """Return ``(is_stale, reason)`` for an archive in ``status="printing"``
    against the printer's current MQTT state.

    Reconciliation triggers (#1542 follow-up — recovers from missed PRINT
    COMPLETE events, typically a print finishing during an MQTT disconnect
    window followed by a smart-plug power cycle):

      1. Printer state is terminal (IDLE / FINISH / FAILED). The print is
         provably not running anymore — only branch that should fire under
         normal disconnect-then-reconnect timing.
      2. Printer has a different ``subtask_id`` than the archive. Bambu
         firmware mints a fresh ``subtask_id`` for each print, including the
         ghost replay it runs after a power cycle from a leftover SD file —
         so a mismatch unambiguously means the in-DB archive is no longer
         the print on the printer.
      3. Printer is running but ``subtask_name`` is empty. The printer
         doesn't know what it's running; the archive's reference to it is
         already broken.

    Conservative on purpose: PAUSE / PREPARE / SLICING and any RUNNING state
    with matching subtask_id+subtask_name is left alone. The cost of a false
    positive is a duplicate archive on the next real PRINT COMPLETE — the
    reactive handler uses ``_active_prints`` for lookup, which the reconcile
    clears on synthesis, so the real completion creates a fresh row instead
    of overwriting the synthesised one (#1679). The cost of a false negative
    is the ghost-print loop in #1542.

    Pre-push guard (#1679): when ``state.state`` is empty or ``"unknown"``,
    MQTT has connected but the first ``push_status`` response hasn't been
    applied yet — ``PrinterState`` is sitting on its construction defaults.
    The reconcile caller in ``on_printer_status_change`` is already gated
    on a real ``state.state``, so in normal operation this branch is
    unreachable; it's kept as belt-and-braces for future callers and for
    the narrow window where a partial state update could arrive
    (``state.state`` set but ``subtask_name`` not yet populated). Returning
    ``not stale`` on degenerate input is strictly conservative: a real
    stale archive will still be caught by the next push_status arriving
    with terminal state.
    """
    current_state = (state.state or "").upper()
    if current_state in ("", "UNKNOWN"):
        # No real push_status yet — PrinterState defaults are not evidence.
        return False, ""
    if current_state in ("IDLE", "FINISH", "FAILED"):
        return True, f"printer state {current_state}"
    # Below here the printer is in a running / pre-running state (RUNNING /
    # PAUSE / PREPARE / SLICING / etc.) — decide based on subtask identity.
    current_subtask_id = (state.subtask_id or "").strip()
    if archive.subtask_id and current_subtask_id and archive.subtask_id != current_subtask_id:
        return True, f"subtask_id changed ({archive.subtask_id!r} → {current_subtask_id!r})"
    current_subtask_name = (state.subtask_name or "").strip()
    if not current_subtask_name:
        return True, "printer subtask_name empty"
    return False, ""


async def reconcile_stale_active_prints(printer_id: int) -> int:
    """Synthesise ``on_print_complete`` for archives whose print can't be
    running on the printer anymore.

    Called once per MQTT (re)connection (from on_printer_status_change when
    the connected edge flips False → True) and at PrintLab startup (from
    the FastAPI lifespan). Without this, a print that completes during a
    disconnect window — followed by a smart-plug-driven power cycle — leaves
    the ``.3mf`` on the SD card, the firmware auto-replays it on next boot,
    and PrintLab fires a fresh PRINT START for the ghost rather than the
    SD cleanup that PRINT COMPLETE was supposed to run. Repeats every
    power cycle until the operator notices (#1542 follow-up). Reconciliation
    closes the loop by faking the missed PRINT COMPLETE — the existing
    cleanup chain handles SD-file deletion, status updates, usage tracking,
    and notifications.

    Synthesised ``status="aborted"`` is the conservative label: we have no
    proof the print finished successfully (and no progress evidence to
    promote to ``"completed"``). The real PRINT COMPLETE callback, if it
    fires later, overwrites the status with the correct value.

    Returns the number of archives reconciled.
    """
    state = _rt().printer_manager.get_status(printer_id)
    if not state:
        return 0
    # Don't reconcile while disconnected — we'd be making a decision against
    # stale cached state. The connected → reconcile edge handles this.
    if not state.connected:
        return 0

    from backend.app.models.archive import PrintArchive

    reconciled = 0
    async with _rt().async_session() as db:
        result = await db.execute(
            select(PrintArchive).where(
                PrintArchive.printer_id == printer_id,
                PrintArchive.status == "printing",
            )
        )
        active = list(result.scalars().all())

    if not active:
        return 0

    logger = logging.getLogger(__name__)
    for archive in active:
        is_stale, reason = _is_active_archive_stale(archive, state)
        if not is_stale:
            continue
        logger.info(
            "[RECONCILE] Printer %s: synthesising missed PRINT COMPLETE for archive %s (%s) — %s",
            printer_id,
            archive.id,
            archive.filename,
            reason,
        )
        # Synthesised payload: minimal fields the on_print_complete chain
        # needs. `_reconciled` marker lets downstream code distinguish this
        # from a real MQTT-driven completion if it ever needs to (e.g. for
        # metrics / debug logging). raw_data is the live printer state so
        # the usage tracker can compare end-of-print remain% against the
        # captured start values.
        try:
            await _rt().on_print_complete(
                printer_id,
                {
                    "status": "aborted",
                    "filename": archive.filename,
                    "subtask_name": archive.print_name or "",
                    "subtask_id": archive.subtask_id or "",
                    "raw_data": state.raw_data or {},
                    "_reconciled": True,
                },
            )
            reconciled += 1
        except Exception as e:
            # Catch-all: a reconciliation failure must not block the
            # printer's normal status flow. The archive stays in
            # ``status="printing"`` and the next reconnect retries.
            logger.warning(
                "[RECONCILE] on_print_complete synthesis failed for archive %s: %s",
                archive.id,
                e,
            )

    return reconciled


def _subtask_name_from_filename(filename: str) -> str:
    """Recover the subtask name a print command would have carried for *filename*.

    The dispatcher derives the printer-facing subtask name from the archive's
    file name, so stripping the extensions back off gives the value MQTT echoes
    on completion. Only the two extensions PrintLab actually stores are removed,
    and in the order they nest (``.gcode.3mf``), so a model whose own name
    contains a dot -- ``My.Model.3mf`` -- keeps it.
    """
    name = PurePosixPath(filename).name
    for suffix in (".3mf", ".gcode"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _normalise_subtask_name(name: str) -> str:
    """Canonical form for comparing a dispatched name against MQTT's echo.

    The printer does not echo the name back verbatim: it substitutes
    underscores for spaces. ``H2D_Carbon_Filter_(V2)_Body & Solid Lid`` is
    dispatched and ``H2D_Carbon_Filter_(V2)_Body_&_Solid_Lid`` comes back.

    The 3MF lookup in this module has always known that -- it builds
    space-to-underscore variants of every candidate filename, and its
    directory search normalises both sides before comparing. This exists so
    the completion check reads the same rule from the same place instead of
    growing its own, which is exactly how it came to disagree (#2829).
    """
    return name.strip().replace(" ", "_").casefold()


def _subtask_names_match(expected: str, observed: str) -> bool:
    """Whether two subtask names describe the same print.

    Beyond the space/underscore substitution, the printer truncates long names
    and marks the cut with ``...``. A truncated echo has to count as a match or
    every print with a long name strands its queue item the same way.
    """
    expected_n = _normalise_subtask_name(expected)
    observed_n = _normalise_subtask_name(observed)
    if expected_n == observed_n:
        return True

    # Either side can be the truncated one: the printer truncates what it
    # echoes, and an archive whose own filename was recorded from a previous
    # truncated echo carries the marker too.
    for full, cut in ((expected_n, observed_n), (observed_n, expected_n)):
        if cut.endswith(_rt()._SUBTASK_TRUNCATION_MARKER) and full.startswith(
            cut[: -len(_rt()._SUBTASK_TRUNCATION_MARKER)]
        ):
            return True
    return False


async def _completion_belongs_to_queue_item(db, item, data: dict) -> bool:
    """Whether this completion event is plausibly about *item*'s print.

    The caller finds its queue row by printer and ``status='printing'`` alone,
    which is all a completion event gives it -- there is no run identifier in
    the MQTT payload to match on. That makes the lookup indiscriminate: any
    completion delivered for this printer closes whichever row happens to be
    printing, however unrelated. Comparing the subtask name against the archive
    the row was dispatched with costs one primary-key load and rules that out.

    Deliberately permissive: it answers False only on a positive disagreement
    between two names we actually have. A row with no archive, an archive with
    no file name, or an event with no subtask name is unverifiable rather than
    wrong, and refusing those would strand the item in ``printing`` and wedge
    the printer's queue -- a worse failure than the one being prevented.
    """
    observed = (data.get("subtask_name") or "").strip()
    if not observed or item.archive_id is None:
        return True

    from backend.app.models.archive import PrintArchive

    archive = await db.get(PrintArchive, item.archive_id)
    if archive is None or not archive.filename:
        return True

    expected = _subtask_name_from_filename(archive.filename)
    if not expected or _subtask_names_match(expected, observed):
        return True

    logging.getLogger(__name__).warning(
        "Ignoring print completion for queue item %s: it was dispatched as %r "
        "(archive %s, %s) but the completion reports subtask %r. Leaving the item "
        "printing rather than closing a run this event is not about.",
        item.id,
        expected,
        archive.id,
        archive.filename,
        observed,
    )
    return False


async def _recover_fallback_from_cache_before_eviction(printer_id: int, data: dict) -> None:
    """Spend the 3MF download cache on a still-empty fallback archive.

    ``on_print_complete`` drops the cache as its first act, which deletes the
    file. If the cover endpoint (or anything else) pulled the 3MF while the
    print ran and the archive never got one, this is the last moment those bytes
    exist (#2957).
    """
    logger = logging.getLogger(__name__)
    names = [
        n
        for n in (data.get("filename"), data.get("subtask_name"), (data.get("raw_data") or {}).get("subtask_name"))
        if n
    ]
    for name in names:
        try:
            cached = _rt().get_cached_3mf(printer_id, name)
            if cached and await _rt().try_recover_fallback_archive(printer_id, name, cached):
                return
        except Exception as e:
            logger.debug("[RECOVER] Pre-eviction recovery for %s failed: %s", name, e)
