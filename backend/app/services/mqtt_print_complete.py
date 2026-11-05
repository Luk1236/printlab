"""
MQTT-Druckabschluss-Abfluss: on_print_complete mit seinen verschachtelten
Hintergrund-Aufgaben (Energie, Foto, Meldungen, Fassadenspeicherung).

Zustaende und die von den Tests umgebogenen Namen bleiben im Modul main und
werden über :func:`_rt` gelesen. Aufrufer und Tests sehen keinen Unterschied.
"""

import asyncio
import importlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from backend.app.api.routes.maintenance import _get_printer_maintenance_internal, ensure_default_types
from backend.app.core.config import settings as app_settings
from backend.app.core.database import async_session
from backend.app.core.tasks import spawn_background_task
from backend.app.core.websocket import ws_manager
from backend.app.services import print_dispatch_context
from backend.app.services.archive import ArchiveService
from backend.app.services.bambu_ftp import clear_3mf_cache
from backend.app.services.completion_photo_plate import (
    _apply_camera_rotation,
    _max_z_for_current_print,
    _park_plate_after_finish_photo,
    _plate_restore_is_blocked_by_queue,
    _restore_plate_for_finish_photo,
)
from backend.app.services.energy_plug import energy_plug_candidates, select_energy_reading
from backend.app.services.expected_prints import _print_ams_mappings, _print_cost_center_ids, _print_plate_ids
from backend.app.services.mqtt_relay import mqtt_relay
from backend.app.services.notification_service import notification_service
from backend.app.services.print_complete_flow import (
    _completion_belongs_to_queue_item,
    _compute_run_filament_grams,
    _dispatch_outcome_confirmation_safely,
    _dispatch_user_print_email,
    _finish_photo_for_notification,
    _partial_progress_scale,
    _recover_fallback_from_cache_before_eviction,
    _scope_notification_archive_data_to_plate,
)
from backend.app.services.print_cost_estimate import plate_scoped_run_estimate as _plate_scoped_run_estimate
from backend.app.services.printer_manager import printer_manager
from backend.app.services.smart_plug_manager import smart_plug_manager
from backend.app.services.spoolman_tracking import (
    cleanup_tracking as _cleanup_spoolman_tracking,
    report_usage as _report_spoolman_usage,
)
from backend.app.services.timelapse import (
    _capture_finish_photo_from_timelapse,
    _scan_for_timelapse_with_retries,
    _upgrade_finish_photo_from_timelapse,
)
from backend.app.utils.print_jobs import is_internal_printer_job

# der Logger-Name bleibt der der alten Heimat (Backend-Protokolle)
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen."""

    return importlib.import_module("backend.app.main")


async def on_print_complete(printer_id: int, data: dict):
    """Handle print completion - update the archive status."""
    import time

    logger = logging.getLogger(__name__)
    start_time = time.time()

    def log_timing(section: str):
        elapsed = time.time() - start_time
        logger.info("[TIMING] %s: %.3fs elapsed", section, elapsed)

    logger.info("[CALLBACK] on_print_complete started for printer %s", printer_id)

    # A kill-switch stop sends its provider notification immediately. Keep the
    # task so the later notification path can await it and avoid a duplicate;
    # if that immediate attempt failed, the regular completion path retries.
    kill_switch_notification_task = _rt()._kill_switch_notification_tasks.pop(printer_id, None)

    # Last chance before the bytes go: if this print's archive is still an empty
    # fallback and something downloaded the 3MF while it ran, fill the archive in
    # now. The cover endpoint's copy lives in exactly this cache, and clearing it
    # below deletes the file (#2957).
    await _recover_fallback_from_cache_before_eviction(printer_id, data)

    # A pending cool-off retry has nothing left to recover for — the cache is
    # about to be dropped and the print is over.
    retry_task = _rt()._fallback_3mf_retry_tasks.pop(printer_id, None)
    if retry_task and not retry_task.done():
        retry_task.cancel()

    # Drop the 3MF download cache for this printer (#972). The print is over,
    # nothing else legitimately needs the bytes; keeping them would only risk
    # handing a stale file to the next print if it reuses the same name.
    clear_3mf_cache(printer_id)

    try:
        ws_data = {
            "status": data.get("status"),
            "filename": data.get("filename"),
            "subtask_name": data.get("subtask_name"),
            "timelapse_was_active": data.get("timelapse_was_active"),
        }
        await ws_manager.send_print_complete(printer_id, ws_data)
        log_timing("WebSocket send_print_complete")
    except Exception as e:
        logger.warning("[CALLBACK] WebSocket send_print_complete failed: %s", e)

    # Capture user info before clearing (needed for print log entry)
    _print_user_info = printer_manager.get_current_print_user(printer_id)

    # Clear current print user tracking (Issue #206)
    printer_manager.clear_current_print_user(printer_id)

    # If the user explicitly stopped this print from the queue UI the printer will
    # report "failed" or "aborted" via MQTT.  Override that to "cancelled" so the
    # correct "print stopped" notification/email is sent instead of a failure alert.
    _raw_status = data.get("status", "completed")
    if printer_id in _rt()._user_stopped_printers and _raw_status in ("failed", "aborted"):
        logger.info(
            "[CALLBACK] Overriding status '%s' -> 'cancelled' for printer %s (print was stopped from queue by user)",
            _raw_status,
            printer_id,
        )
        data = {**data, "status": "cancelled"}
    _rt()._user_stopped_printers.discard(printer_id)

    # Raise the plate-clear gate for queued dispatch (#961). Any terminal status
    # may have left material on the bed: a user can cancel ten hours into a
    # twelve-hour print, a printer can self-abort mid-job after a clog, and a
    # touchscreen-stop reports `aborted` rather than `cancelled` because
    # `_user_stopped_printers` is only populated when the user stops via the
    # PrintLab queue UI. Earlier code raised the flag only for completed/failed,
    # which auto-dispatched the next queued print onto a fouled bed two seconds
    # after a touchscreen-abort (#1171). Persisted to DB so the gate survives
    # Auto Off power cycles and PrintLab restarts.
    _final_status = data.get("status", "completed")
    if _final_status in ("completed", "failed", "aborted", "cancelled"):
        printer_manager.set_awaiting_plate_clear(printer_id, True)

    # Automatischer Plattenwechsel (Monitor-Port P2): nur nach "completed" und
    # nur wenn die Automatik in data/hardware.json eingeschaltet ist. Läuft als
    # eigener Task; ein Fehler meldet sich nur, blockiert aber nie die
    # Aufräum-Schritte weiter unten.
    if _final_status == "completed":
        try:
            from backend.app.services import auto_plate_change

            auto_plate_change.schedule(printer_id, data.get("subtask_name", ""))
        except Exception as e:
            logger.warning("[CALLBACK] auto plate change schedule failed for printer %s: %s", printer_id, e)

    # MQTT relay - publish print complete
    try:
        printer_info = printer_manager.get_printer(printer_id)
        if printer_info:
            await mqtt_relay.on_print_complete(
                printer_id,
                printer_info.name,
                printer_info.serial_number,
                data.get("filename", ""),
                data.get("subtask_name", ""),
                data.get("status", "completed"),
            )
    except Exception:
        pass  # Don't fail print complete callback if MQTT fails

    filename = data.get("filename", "")
    subtask_name = data.get("subtask_name", "")

    if not filename and not subtask_name:
        logger.warning("Print complete without filename or subtask_name")
        return

    logger.info("Print complete - filename: %s, subtask: %s, status: %s", filename, subtask_name, data.get("status"))

    # Build list of possible keys to try (matching how they were registered in on_print_start)
    possible_keys = []

    # Try subtask_name variations first (most reliable for matching)
    if subtask_name:
        possible_keys.append((printer_id, f"{subtask_name}.3mf"))
        possible_keys.append((printer_id, f"{subtask_name}.gcode.3mf"))
        possible_keys.append((printer_id, subtask_name))

    # Try filename variations
    if filename:
        # Extract just the filename if it's a path
        fname = filename.split("/")[-1] if "/" in filename else filename

        if fname.endswith(".3mf"):
            possible_keys.append((printer_id, fname))
        elif fname.endswith(".gcode"):
            base_name = fname.rsplit(".", 1)[0]
            possible_keys.append((printer_id, f"{base_name}.gcode.3mf"))
            possible_keys.append((printer_id, f"{base_name}.3mf"))
            possible_keys.append((printer_id, fname))
        else:
            possible_keys.append((printer_id, f"{fname}.gcode.3mf"))
            possible_keys.append((printer_id, f"{fname}.3mf"))
            possible_keys.append((printer_id, fname))

        # Also try full path versions
        if filename.endswith(".3mf"):
            possible_keys.append((printer_id, filename))
        elif filename.endswith(".gcode"):
            base_name = filename.rsplit(".", 1)[0]
            possible_keys.append((printer_id, f"{base_name}.3mf"))
            possible_keys.append((printer_id, filename))
        else:
            possible_keys.append((printer_id, f"{filename}.3mf"))
            possible_keys.append((printer_id, filename))

    # Find the archive for this print
    logger.info("Looking for archive in _active_prints, keys to try: %s...", possible_keys[:5])
    logger.info("Current _active_prints: %s", list(_rt()._active_prints.keys()))
    archive_id = None
    for key in possible_keys:
        archive_id = _rt()._active_prints.pop(key, None)
        if archive_id:
            logger.info("Found archive %s with key %s", archive_id, key)
            # Also clean up any other keys pointing to this archive
            keys_to_remove = [k for k, v in _rt()._active_prints.items() if v == archive_id]
            for k in keys_to_remove:
                _rt()._active_prints.pop(k, None)
            break

    if not archive_id:
        # Try to find by filename or subtask_name if not tracked (for prints started before app)
        async with async_session() as db:
            from backend.app.models.archive import PrintArchive

            # Try matching by subtask_name (stored as print_name) first
            if subtask_name:
                result = await db.execute(
                    select(PrintArchive)
                    .where(PrintArchive.printer_id == printer_id)
                    .where(PrintArchive.status == "printing")
                    .where(
                        or_(
                            PrintArchive.print_name.ilike(f"%{subtask_name}%"),
                            PrintArchive.filename.ilike(f"%{subtask_name}%"),
                        )
                    )
                    .order_by(PrintArchive.created_at.desc())
                    .limit(1)
                )
                archive = result.scalar_one_or_none()
                if archive:
                    archive_id = archive.id
                    logger.info("Found archive %s by subtask_name match: %s", archive_id, subtask_name)

            # Also try by filename
            if not archive_id and filename:
                result = await db.execute(
                    select(PrintArchive)
                    .where(PrintArchive.printer_id == printer_id)
                    .where(PrintArchive.filename == filename)
                    .where(PrintArchive.status == "printing")
                    .order_by(PrintArchive.created_at.desc())
                    .limit(1)
                )
                archive = result.scalar_one_or_none()
                if archive:
                    archive_id = archive.id

    # Cleanup: delete uploaded file from printer SD card to prevent phantom prints (Issue #374, #1542)
    # The print scheduler uploads files to the SD card root (/). Some printers (e.g. P1S, A1)
    # auto-start files found in root on power cycle, causing ghost prints.
    # Must run before the archive_id early-return so it executes even when archiving is disabled.
    try:
        if subtask_name:
            archive_filename: str | None = None
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive
                from backend.app.models.printer import Printer

                result = await db.execute(select(Printer).where(Printer.id == printer_id))
                printer = result.scalar_one_or_none()
                if archive_id:
                    archive_row = await db.execute(select(PrintArchive.filename).where(PrintArchive.id == archive_id))
                    archive_filename = archive_row.scalar_one_or_none()

            if printer:
                from backend.app.services.bambu_ftp import DeleteResult, delete_file_async
                from backend.app.utils.filename import derive_remote_filename

                # Primary candidate: the exact path the dispatcher uploaded to
                # (derived from archive.filename via the same rule as upload).
                # Without it, a library row that ended up with a doubled
                # .gcode.3mf (#1542) leaves the real file behind because the
                # subtask_name + ext fallbacks below don't match what's on the
                # SD card. Fallbacks remain for archive-less prints (subtask
                # never resolved to an archive) and for older naming variants.
                candidate_paths: list[str] = []
                if archive_filename:
                    candidate_paths.append(f"/{derive_remote_filename(archive_filename)}")
                for ext in (".3mf", ".gcode"):
                    fallback = f"/{subtask_name}{ext}"
                    if fallback not in candidate_paths:
                        candidate_paths.append(fallback)

                # Three outcomes track across all candidates so the final log
                # line reflects what actually happened. The A1 in #1721 always
                # ends here with ``any_not_found=True`` and the others False
                # — its firmware auto-cleans the SD card before our cleanup
                # runs, every candidate FTP-DELE returns 550, and the old
                # code burned 3 retries × 2 s × 3 candidates per print
                # logging a misleading "may linger" WARNING on a successful
                # print.
                any_deleted = False
                any_real_failure = False
                any_not_found = False

                for remote_path in candidate_paths:
                    # Retry only the FAILED case — 550 NOT_FOUND will never
                    # recover by waiting, so a "file isn't here" answer
                    # advances immediately to the next candidate without
                    # consuming the retry budget.
                    for attempt in range(1, 4):
                        try:
                            delete_result = await delete_file_async(
                                printer.ip_address,
                                printer.access_code,
                                remote_path,
                                printer_model=printer.model,
                            )
                        except Exception as e:
                            delete_result = DeleteResult.FAILED
                            logger.warning(
                                "SD card cleanup attempt %d/3 raised for %s: %s",
                                attempt,
                                remote_path,
                                e,
                            )

                        if delete_result == DeleteResult.DELETED:
                            any_deleted = True
                            logger.info("Deleted %s from printer %s SD card", remote_path, printer.name)
                            break
                        if delete_result == DeleteResult.NOT_FOUND:
                            any_not_found = True
                            break  # 550 will not recover; try next candidate
                        # FAILED: real error — retry with backoff, then give up
                        if attempt < 3:
                            await _rt().asyncio.sleep(2)
                        else:
                            any_real_failure = True
                            logger.warning(
                                "SD card cleanup failed after 3 attempts for %s "
                                "(network/auth/transient error — file may linger on SD card)",
                                remote_path,
                            )

                if not any_deleted and not any_real_failure and any_not_found:
                    # Every candidate said "not here." Either the printer
                    # firmware swept the SD card itself (common on A1) or the
                    # dispatcher's upload path doesn't match our candidate
                    # rule. Either way: nothing to clean up, no warning.
                    logger.debug(
                        "SD card cleanup: nothing to delete on %s — every candidate returned 550 "
                        "(printer likely self-cleaned)",
                        printer.name,
                    )
    except Exception as e:
        logger.warning("SD card file cleanup failed for printer %s: %s", printer_id, e)

    log_timing("SD card cleanup")

    # Update queue item status early — must run before the archive_id early-return
    # so queue items don't get stuck in "printing" when archive lookup fails.
    # Uses run_with_retry to handle SQLite "database is locked" errors (#897).
    queue_item_id = None
    billing_run_id: str | None = None
    billing_user_id: int | None = None
    billing_cost_center_id: int | None = None
    billing_plate_id: int | None = None
    queue_status = None
    queue_auto_off = False
    try:
        from backend.app.core.database import run_with_retry
        from backend.app.models.print_queue import PrintQueueItem

        async def _update_queue_status(db):
            nonlocal billing_run_id, billing_user_id, billing_cost_center_id, billing_plate_id
            nonlocal queue_item_id, queue_status, queue_auto_off
            result = await db.execute(
                select(PrintQueueItem)
                .where(PrintQueueItem.printer_id == printer_id)
                .where(PrintQueueItem.status == "printing")
            )
            printing_items = list(result.scalars().all())
            if len(printing_items) > 1:
                logger.warning(
                    "BUG: Multiple queue items in 'printing' status for printer %s: %s",
                    printer_id,
                    [(i.id, i.archive_id, i.library_file_id) for i in printing_items],
                )
            item = printing_items[0] if printing_items else None
            if item is not None and not await _completion_belongs_to_queue_item(db, item, data):
                return
            if item:
                queue_status = data.get("status", "completed")
                # MQTT sends "aborted" for cancelled prints; normalise to
                # "cancelled" so it matches the queue schema Literal.
                if queue_status == "aborted":
                    queue_status = "cancelled"
                item.status = queue_status
                item.completed_at = datetime.now(timezone.utc)
                if queue_status == "failed" and not item.error_message:
                    item.error_message = _rt()._format_hms_error_summary(data.get("hms_errors") or [])

                # Bump usage counters on the source library file so admins can
                # sort by "last printed" and (eventually) auto-purge stale
                # files — #1008.
                await _rt()._bump_library_file_usage_if_completed(db, item, queue_status)

                await db.commit()
                queue_item_id = item.id
                billing_run_id = item.billing_run_id
                billing_user_id = item.created_by_id
                billing_cost_center_id = item.cost_center_id
                billing_plate_id = item.plate_id
                queue_auto_off = item.auto_off_after
                logger.info("Updated queue item %s status to %s", item.id, queue_status)

        await run_with_retry(_update_queue_status, label="queue status update")

        # Automatische Umverteilung nach einem echten Fehlschlag (abschaltbar,
        # höchstens einmal je Auftragskette, Ziel: anderes Gerät desselben Modells).
        if queue_item_id is not None and queue_status == "failed":
            try:
                from backend.app.services import auto_requeue

                async with async_session() as requeue_db:
                    await auto_requeue.maybe_requeue(requeue_db, queue_item_id, queue_status)
            except Exception as e:
                logger.warning("Auto-requeue failed for queue item %s: %s", queue_item_id, e)

        # Post-commit side effects (notifications, MQTT relay, auto-off) use
        # their own sessions and have their own error handling — no retry needed.
        if queue_item_id is not None:
            # Batch orders (#342): this run may have been the last one an order
            # owed. Re-evaluate here rather than lazily on read, so a finished
            # order reports itself complete without someone opening the page.
            try:
                from backend.app.services.print_batch import refresh_batch_status_for_item

                async with async_session() as db:
                    await refresh_batch_status_for_item(db, queue_item_id)
                    await db.commit()
            except Exception as e:
                logger.warning("[BATCH] Failed to refresh batch status for queue item %s: %s", queue_item_id, e)

            # MQTT relay - publish queue job completed
            try:
                printer_info = printer_manager.get_printer(printer_id)
                await mqtt_relay.on_queue_job_completed(
                    job_id=queue_item_id,
                    filename=filename or subtask_name,
                    printer_id=printer_id,
                    printer_name=printer_info.name if printer_info else "Unknown",
                    status=queue_status,
                )
            except Exception:
                pass  # Don't fail if MQTT fails

            # Check if queue is now empty and send notification
            try:
                from sqlalchemy import func as sa_func

                async with async_session() as db:
                    count_result = await db.execute(
                        select(sa_func.count(PrintQueueItem.id)).where(PrintQueueItem.status == "pending")
                    )
                    pending_count = count_result.scalar() or 0

                    if pending_count == 0:
                        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                        completed_result = await db.execute(
                            select(sa_func.count(PrintQueueItem.id)).where(
                                PrintQueueItem.status.in_(["completed", "failed", "skipped"]),
                                PrintQueueItem.completed_at >= today_start,
                            )
                        )
                        completed_count = completed_result.scalar() or 1

                        await notification_service.on_queue_completed(
                            completed_count=completed_count,
                            db=db,
                        )
            except Exception:
                pass  # Don't fail if notification fails

            # Handle auto_off_after - power off printer if the queue item opted
            # in. Delegates to the smart-plug manager so the off honours each
            # plug's configured strategy (time delay or temperature threshold),
            # is cancelled if the printer starts printing again, and never cuts
            # power on a loaded print (#1890). Previously an inline block here
            # hardcoded a 50°C / 600s cooldown wait and powered off on the
            # timeout regardless of print state — cutting a touchscreen reprint.
            if queue_auto_off:
                try:
                    async with async_session() as db:
                        await smart_plug_manager.schedule_off_after_queue_job(printer_id, db)
                except Exception as e:
                    logger.warning("Failed to schedule queue auto-off for printer %s: %s", printer_id, e)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Queue item update failed: {e}")

    log_timing("Queue item update")

    # Register bed cooldown waiter (event-driven via on_bed_temp_update callback).
    # Must run before archive_id early-return so it fires for all prints (including
    # prints started from BambuStudio/touchscreen that have no archive).
    if data.get("status") == "completed":
        try:
            from backend.app.api.routes.settings import get_setting

            async with async_session() as db:
                threshold_str = await get_setting(db, "bed_cooled_threshold")
            threshold = float(threshold_str) if threshold_str else 35.0

            # Check if any provider has on_bed_cooled enabled (skip registration if none)
            async with async_session() as db:
                providers = await notification_service._get_providers_for_event(db, "on_bed_cooled", printer_id)
            if providers:
                _rt()._bed_cool_waiters[printer_id] = {
                    "threshold": threshold,
                    "filename": filename or subtask_name or "",
                    "registered_at": time.time(),
                }
                logger.info(
                    "[BED-COOL] Registered waiter for printer %s (threshold: %.0f°C)",
                    printer_id,
                    threshold,
                )
            else:
                logger.debug("[BED-COOL] No providers enabled for bed_cooled on printer %s", printer_id)
        except Exception as e:
            logger.warning("[BED-COOL] Failed to register waiter: %s", e)

    # Capture the slicer estimate before usage tracking runs. The tracker may
    # update archive.cost with this run's measured cost; billing partial runs
    # against that already-partial value would discount the charge twice.
    billing_planned_grams: float | None = None
    billing_base_cost: float | None = None
    if archive_id:
        try:
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive

                billing_archive = await db.get(PrintArchive, archive_id)
                if billing_archive:
                    billing_path = (
                        app_settings.base_dir / billing_archive.file_path if billing_archive.file_path else None
                    )  # SEC-PATH-OK: archive.file_path is DB-stored, internally generated
                    billing_planned_grams, billing_base_cost = _plate_scoped_run_estimate(
                        billing_archive,
                        billing_path,
                        billing_plate_id if billing_plate_id is not None else _rt()._get_start_plate_id(archive_id),
                    )
        except Exception as e:
            logger.warning("[FINANCE] Failed to capture planned usage for archive %s: %s", archive_id, e)

    # --- Track filament consumption (must run before archive_id early-return so usage
    # is recorded even when auto-archive is disabled) ---
    usage_results: list[dict] = []
    # Prefer ams_mapping captured from MQTT request topic (works for all print sources)
    stored_ams_mapping = data.get("ams_mapping")
    # Fallback to _print_ams_mappings for queue/reprint (set before print starts)
    if not stored_ams_mapping and archive_id:
        stored_ams_mapping = _print_ams_mappings.pop(archive_id, None)

    # Always drain the plate_id register on completion — the session already
    # consumed it at print-start injection; leaving it would leak into the next
    # print on the same archive_id (rare but possible with reprints) (#1697).
    # Capture the popped value so the completion notification can scope the
    # archive-level (summed-across-plates per #1593) filament + time totals
    # down to the single plate that was actually printed (#1785).
    notify_plate_id: int | None = None
    if archive_id:
        notify_plate_id = _print_plate_ids.pop(archive_id, None)

    # Internal inventory: track AMS remain% deltas (skip if Spoolman handles usage)
    try:
        async with async_session() as db:
            from backend.app.api.routes.settings import get_setting

            _spoolman_on = await get_setting(db, "spoolman_enabled")
        if not _spoolman_on or _spoolman_on.lower() != "true":
            from backend.app.services.usage_tracker import on_print_complete as usage_on_print_complete

            async with async_session() as db:
                usage_results = await usage_on_print_complete(
                    printer_id,
                    data,
                    printer_manager,
                    db,
                    archive_id=archive_id,
                    ams_mapping=stored_ams_mapping,
                )
                if usage_results:
                    await ws_manager.broadcast(
                        {
                            "type": "spool_usage_logged",
                            "printer_id": printer_id,
                            "usage": usage_results,
                        }
                    )
                    log_timing("Usage tracker")

    except Exception as e:
        logger.warning("Usage tracker on_print_complete failed: %s", e)

    # Drop the print-start context unconditionally — the Spoolman branch above
    # skips the internal tracker entirely, so nothing else would clear what
    # print start captured, and a row surviving its print would be restored
    # onto the next one after a restart.
    try:
        from backend.app.services.usage_tracker import discard_session

        async with async_session() as db:
            await discard_session(db, printer_id)
    except Exception as e:
        logger.warning("Failed to clear persisted print session for printer %s: %s", printer_id, e)

    # Spoolman: report filament usage (requires archive_id for tracking data lookup)
    if archive_id:
        if data.get("status") == "completed":
            try:
                await _report_spoolman_usage(printer_id, archive_id)
                log_timing("Spoolman usage report")
            except Exception as e:
                logger.warning("Spoolman usage reporting failed: %s", e)
        else:
            # Report partial usage if tracking data exists (only stored when weight sync is disabled)
            try:
                async with async_session() as db:
                    await _cleanup_spoolman_tracking(
                        printer_id,
                        archive_id,
                        db,
                        last_layer_num=data.get("last_layer_num"),
                        last_progress=data.get("last_progress"),
                    )
            except Exception as e:
                logger.debug("[SPOOLMAN] Cleanup failed: %s", e)

    log_timing("Filament usage tracking")

    if not archive_id:
        # The printer's own calibration run has no archive by design, so this
        # arrives here every time one finishes. Returning before the no-archive
        # notification is not just noise control: that path attributes an
        # unmatched completion to any queue item this printer finished in the
        # last five minutes, which for a calibration that runs alongside a real
        # print means emailing its owner that their print is done, twice and
        # early. Everything above this point has already run — the plate-clear
        # gate, the queue reconciliation, the SD-card cleanup — so only the
        # notification is skipped.
        if is_internal_printer_job(filename, subtask_name):
            logger.info(
                "[CALLBACK] Internal printer job completed, no notification: filename=%s, subtask=%s",
                filename,
                subtask_name,
            )
            return

        logger.warning("Could not find archive for print complete: filename=%s, subtask=%s", filename, subtask_name)

        # Still send print-complete/failed/stopped notifications even without an archive.
        # Try to enrich with queue/library-file data so user-specific emails work too.
        async def _notify_no_archive():
            try:
                async with async_session() as db:
                    from backend.app.models.library import LibraryFile
                    from backend.app.models.print_queue import PrintQueueItem
                    from backend.app.models.printer import Printer

                    result = await db.execute(select(Printer).where(Printer.id == printer_id))
                    printer_obj = result.scalar_one_or_none()
                    p_name = printer_obj.name if printer_obj else f"Printer {printer_id}"

                    # Try to find the most-recent queue item for this printer so we can
                    # recover created_by_id and estimated print time.
                    # NOTE: By the time this task runs the queue item status has already
                    # been updated to a terminal state (completed/failed/cancelled), so
                    # we look for recently-completed items (within the last 5 minutes).
                    no_archive_data: dict | None = None
                    try:
                        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
                        q_result = await db.execute(
                            select(PrintQueueItem)
                            .where(PrintQueueItem.printer_id == printer_id)
                            .where(PrintQueueItem.status.in_(["completed", "failed", "cancelled"]))
                            .where(PrintQueueItem.completed_at >= cutoff)
                            .order_by(PrintQueueItem.completed_at.desc())
                            .limit(1)
                        )
                        queue_item = q_result.scalar_one_or_none()
                        if queue_item:
                            no_archive_data = {"created_by_id": queue_item.created_by_id}
                            # Pull estimated time from library file when available
                            if queue_item.library_file_id:
                                lib_result = await db.execute(
                                    select(LibraryFile).where(LibraryFile.id == queue_item.library_file_id)
                                )
                                lib_file = lib_result.scalar_one_or_none()
                                if lib_file and lib_file.print_time_seconds:
                                    no_archive_data["print_time_seconds"] = lib_file.print_time_seconds
                    except Exception as lookup_err:
                        logger.debug(
                            "[NOTIFY-BG] Could not look up queue item for no-archive notification: %s", lookup_err
                        )

                    # Enrich with usage tracker results (captured in enclosing scope)
                    if usage_results:
                        if no_archive_data is None:
                            no_archive_data = {}
                        total_from_usage = sum(r.get("weight_used", 0) for r in usage_results)
                        if total_from_usage > 0:
                            no_archive_data["actual_filament_grams"] = round(total_from_usage, 1)
                        no_archive_data["usage_results"] = usage_results

                    # Try MQTT remaining_time for print duration when no queue/library data
                    if no_archive_data and not no_archive_data.get("print_time_seconds"):
                        mqtt_remaining = data.get("remaining_time")
                        if mqtt_remaining and isinstance(mqtt_remaining, (int, float)) and mqtt_remaining > 0:
                            no_archive_data["print_time_seconds"] = int(mqtt_remaining)

                    ps = data.get("status", "completed")
                    logger.info(
                        "[NOTIFY-BG] Sending notification without archive: printer=%s, status=%s", printer_id, ps
                    )
                    if not await _rt()._kill_switch_notification_already_sent(kill_switch_notification_task):
                        await notification_service.on_print_complete(
                            printer_id, p_name, ps, data, db, archive_data=no_archive_data
                        )
                    else:
                        logger.info("[NOTIFY-BG] Skipped duplicate kill-switch provider notification")

                    # Send user-specific email if we have a created_by_id
                    if no_archive_data and no_archive_data.get("created_by_id"):
                        raw_filename = data.get("subtask_name") or data.get("filename", "Unknown")
                        await _dispatch_user_print_email(
                            ps,
                            no_archive_data["created_by_id"],
                            p_name,
                            raw_filename,
                            db,
                        )
                    logger.info("[NOTIFY-BG] Completed (no-archive path)")
            except Exception as e:
                logger.warning("[NOTIFY-BG] Failed to send notification without archive: %s", e, exc_info=True)

        spawn_background_task(_notify_no_archive(), name="notify-no-archive")
        return

    log_timing("Archive lookup")

    # Update archive status
    logger.info("[ARCHIVE] Updating archive %s status...", archive_id)
    try:
        async with async_session() as db:
            service = ArchiveService(db)
            status = data.get("status", "completed")

            hms_errors = data.get("hms_errors", []) if status == "failed" else None
            if hms_errors:
                logger.info("[ARCHIVE] HMS errors at failure: %s", hms_errors)
            failure_reason = _rt().derive_failure_reason(status, hms_errors)
            if data.get("_reconciled"):
                # A reconciled completion closes out a stale archive at
                # reconnect — it is not a user action, so don't mislabel it
                # "userCancelled". It shares the stale-cleanup path's key
                # (issue #2974) and records that the real end time is unknown,
                # which is also why its logged duration is 0 (#2592).
                failure_reason = "noStatusUpdate"
            if failure_reason:
                logger.info("[ARCHIVE] failure_reason=%r (status=%s)", failure_reason, status)
            elif status == "failed" and hms_errors:
                logger.info("[ARCHIVE] HMS errors present but none matched a known failure-reason short code")

            await service.update_archive_status(
                archive_id,
                status=status,
                completed_at=(
                    datetime.now(timezone.utc) if status in ("completed", "failed", "aborted", "cancelled") else None
                ),
                failure_reason=failure_reason,
            )
            logger.info(
                "[ARCHIVE] Archive %s status updated to %s, failure_reason=%s", archive_id, status, failure_reason
            )

            await ws_manager.send_archive_updated(
                {
                    "id": archive_id,
                    "status": status,
                }
            )
            logger.info("[ARCHIVE] WebSocket notification sent for archive %s", archive_id)

            # MQTT relay - publish archive updated
            try:
                await mqtt_relay.on_archive_updated(
                    archive_id=archive_id,
                    print_name=filename or subtask_name,
                    status=status,
                )
            except Exception:
                pass  # Don't fail if MQTT fails
    except Exception as e:
        logger.error("[ARCHIVE] Failed to update archive %s status: %s", archive_id, e, exc_info=True)
        # Continue with other operations even if archive update fails

    log_timing("Archive status update")

    # Apply finance wallet charge or release reservations once. For all partial
    # terminal states (failed, aborted at the printer display, or cancelled via
    # PrintLab) use this run's measured spool delta, falling back to the last
    # valid printer progress. PrintArchive.filament_used_grams is the slicer
    # estimate and therefore cannot represent an interrupted run.
    try:
        if data.get("status") in ("completed", "failed", "aborted", "cancelled"):
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive
                from backend.app.services.finance_billing import apply_print_charge_for_archive

                archive = await db.get(PrintArchive, archive_id)
                if archive and billing_run_id is None:
                    billing_run_id = getattr(archive, "billing_run_id", None)
                if archive and archive.created_by_id is None and _print_user_info:
                    archive.created_by_id = _print_user_info.get("user_id")
                    await db.flush()

                run_status = data.get("status", "completed")
                last_progress = data.get("last_progress")
                if last_progress is None:
                    last_progress = data.get("progress")
                actual_run_grams = _compute_run_filament_grams(
                    run_status,
                    billing_planned_grams,
                    last_progress,
                    usage_results,
                )
                filament_usage = (actual_run_grams, billing_planned_grams) if run_status != "completed" else None
                in_memory_cost_center_id = _print_cost_center_ids.pop(archive_id, None)
                charged = await apply_print_charge_for_archive(
                    db,
                    archive_id,
                    charged_user_id=billing_user_id,
                    cost_center_id=(
                        billing_cost_center_id if billing_cost_center_id is not None else in_memory_cost_center_id
                    ),
                    print_queue_id=queue_item_id,
                    print_run_id=billing_run_id,
                    base_cost_override=billing_base_cost,
                    filament_usage=filament_usage,
                )
                await db.commit()
                if charged:
                    logger.info("[FINANCE] Applied print charge for archive %s", archive_id)
    except Exception as e:
        logger.warning("[FINANCE] Failed to apply print charge for archive %s: %s", archive_id, e)
        printer_info = printer_manager.get_printer(printer_id)
        billing_printer_name = printer_info.name if printer_info else f"Printer {printer_id}"
        billing_filename = filename or subtask_name or "Unknown"
        billing_error = str(e)
        try:
            await ws_manager.broadcast(
                {
                    "type": "billing_charge_failed",
                    "printer_id": printer_id,
                    "printer_name": billing_printer_name,
                    "filename": billing_filename,
                    "archive_id": archive_id,
                }
            )
        except Exception as notification_error:
            logger.error(
                "[FINANCE] Failed to broadcast billing error for archive %s: %s",
                archive_id,
                notification_error,
            )

        async def _notify_billing_charge_failed() -> None:
            try:
                async with async_session() as notification_db:
                    await notification_service.on_billing_charge_failed(
                        printer_id,
                        billing_printer_name,
                        billing_filename,
                        archive_id,
                        billing_error,
                        notification_db,
                    )
            except Exception as provider_error:
                logger.error(
                    "[FINANCE] Failed to send provider billing alert for archive %s: %s",
                    archive_id,
                    provider_error,
                    exc_info=True,
                )

        spawn_background_task(
            _notify_billing_charge_failed(),
            name=f"billing-charge-failed-{archive_id}",
        )

    log_timing("Finance charge update")

    # Write independent print log entry (separate table, never touches archives)
    try:
        async with async_session() as db:
            from backend.app.models.archive import PrintArchive
            from backend.app.services.print_log import write_log_entry

            archive = await db.get(PrintArchive, archive_id)
            if archive:
                # Back-fill created_by_id on reprint (#730): reprint reuses the
                # source archive row rather than creating a new one, so an
                # archive that was auto-created from a printer-initiated
                # print (created_by_id=NULL) would otherwise stay unattributed
                # forever. When we have a print-session user AND the archive
                # has no attribution yet, credit the current user. Never
                # overwrite an existing attribution — the original uploader
                # keeps ownership.
                _print_user_id = _print_user_info.get("user_id") if _print_user_info else None
                if archive.created_by_id is None and _print_user_id is not None:
                    archive.created_by_id = _print_user_id
                p_info = printer_manager.get_printer(printer_id)
                # Per-run actuals — written to PrintLogEntry so stats reflect
                # what THIS print actually used, not the source archive's
                # first-run values (#1378). Helper handles the partial-print
                # math (failed / cancelled / stopped get scaled to progress
                # or to tracked spool deltas).
                _run_status = data.get("status", "completed")
                # #2614: scope the per-run estimate to the printed plate. For a
                # multi-plate 3MF dispatched one plate at a time, the archive's
                # filament/cost are the whole-file totals; the PrintLogEntry must
                # reflect only this plate. No effect on single-plate archives (the
                # plate estimate equals the whole-file value) or on the tracker
                # path (measured spool deltas win in _compute_run_filament_grams).
                _est_full_path = (
                    app_settings.base_dir / archive.file_path if archive.file_path else None
                )  # SEC-PATH-OK: archive.file_path is DB-stored, internally generated
                _est_grams, _est_cost = _plate_scoped_run_estimate(archive, _est_full_path)
                _run_grams = _compute_run_filament_grams(
                    _run_status,
                    _est_grams,
                    data.get("last_progress", data.get("progress")),
                    usage_results,
                )

                # Per-run cost — prefer usage_results sum. For partial prints
                # we deliberately skip the topup-to-estimate logic in
                # usage_tracker (which assumes the print completed); the raw
                # tracked-spool sum is closer to what THIS run actually cost.
                _run_cost: float | None = None
                if usage_results:
                    _run_cost = sum(r.get("cost") or 0 for r in usage_results) or None
                if _run_cost is None and _run_status == "completed":
                    _run_cost = _est_cost

                await write_log_entry(
                    db,
                    archive_id=archive.id,
                    # Captured by _update_queue_status above; None for
                    # printer-initiated prints with no queue row. Batch
                    # cost/energy roll-up joins on it (#342).
                    queue_item_id=queue_item_id,
                    status=_run_status,
                    print_name=archive.print_name,
                    printer_name=p_info.name if p_info else None,
                    printer_id=printer_id,
                    started_at=archive.started_at,
                    completed_at=archive.completed_at,
                    filament_type=archive.filament_type,
                    filament_color=archive.filament_color,
                    filament_used_grams=_run_grams,
                    cost=_run_cost,
                    failure_reason=archive.failure_reason,
                    thumbnail_path=archive.thumbnail_path,
                    created_by_id=archive.created_by_id,
                    created_by_username=_print_user_info.get("username") if _print_user_info else None,
                    # Reconciled completions have an unknown real end time —
                    # log 0 duration instead of the whole disconnect gap (#2592).
                    reconciled=bool(data.get("_reconciled")),
                )
                await db.commit()
                logger.info("[PRINT_LOG] Log entry written for archive %s", archive_id)
    except Exception as e:
        logger.warning("[PRINT_LOG] Failed to write log entry for archive %s: %s", archive_id, e)

    log_timing("Print log entry")

    # Run slow operations as background tasks to avoid blocking the event loop
    # These operations can take 5-10+ seconds and would freeze the UI if awaited

    async def _background_energy_calculation():
        """Calculate and save energy usage in background.

        Reads the starting kWh from the archive row (#941: persisted so a mid-print
        backend restart no longer loses per-print energy data).
        """
        try:
            logger.info("[ENERGY-BG] Starting energy calculation for archive %s", archive_id)
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive

                archive = await db.get(PrintArchive, archive_id)
                if archive is None:
                    logger.warning("[ENERGY-BG] Archive %s no longer exists", archive_id)
                    return
                starting_kwh = archive.energy_start_kwh
                if starting_kwh is None:
                    logger.info("[ENERGY-BG] No start kWh recorded for archive %s", archive_id)
                    return

                candidates = await energy_plug_candidates(db, printer_id)
                if not candidates:
                    logger.info("[ENERGY-BG] No smart plug for printer %s", printer_id)
                    return

                # Same ordering as the start reading, so the delta below is
                # against the counter that produced `starting_kwh` (#2859).
                selected = await select_energy_reading(candidates, _rt()._get_plug_energy, db)
                if selected is None:
                    logger.warning(
                        "[ENERGY-BG] No plug on printer %s reports a lifetime energy counter (tried: %s)",
                        printer_id,
                        ", ".join(plug.name for plug in candidates),
                    )
                    return
                plug, energy = selected
                logger.info("[ENERGY-BG] Energy response from plug '%s': %s", plug.name, energy)

                energy_used = round(energy["total"] - starting_kwh, 4)
                logger.info("[ENERGY-BG] Per-print energy: %s kWh", energy_used)
                if energy_used < 0:
                    logger.warning(
                        "[ENERGY-BG] Negative energy delta for archive %s (start=%s, end=%s) — counter reset?",
                        archive_id,
                        starting_kwh,
                        energy["total"],
                    )
                    return

                from backend.app.api.routes.settings import get_setting

                energy_cost_per_kwh = await get_setting(db, "energy_cost_per_kwh")
                cost_per_kwh = float(energy_cost_per_kwh) if energy_cost_per_kwh else 0.15
                energy_cost_value = round(energy_used * cost_per_kwh, 3)

                # First-run-only overwrite of archive.energy_kwh / energy_cost so a
                # reprint doesn't visually clobber the source archive's energy data
                # (#1378). Reprint energy lives in the matching PrintLogEntry below.
                from sqlalchemy import func

                from backend.app.models.print_log import PrintLogEntry

                existing_runs = await db.scalar(
                    select(func.count(PrintLogEntry.id)).where(PrintLogEntry.archive_id == archive_id)
                )
                if (existing_runs or 0) <= 1:
                    # 0 = legacy archive that pre-dates per-run logging; 1 = the row
                    # we just wrote for THIS print. Either way it's the first run.
                    archive.energy_kwh = energy_used
                    archive.energy_cost = energy_cost_value

                # Backfill the latest PrintLogEntry for this archive with energy
                # (write_log_entry above ran before this background task completed,
                # so energy fields are still NULL on that row).
                latest_run = await db.execute(
                    select(PrintLogEntry)
                    .where(PrintLogEntry.archive_id == archive_id)
                    .order_by(PrintLogEntry.id.desc())
                    .limit(1)
                )
                run_row = latest_run.scalar_one_or_none()
                if run_row is not None:
                    run_row.energy_kwh = energy_used
                    run_row.energy_cost = energy_cost_value

                await db.commit()
                logger.info("[ENERGY-BG] Saved: %s kWh, cost=%s", energy_used, energy_cost_value)
        except Exception as e:
            logger.warning("[ENERGY-BG] Failed: %s", e)

    async def _background_finish_photo() -> str | None:
        """Capture finish photo in background. Returns photo filename if captured."""
        # #2547: set once this function has raised the plate itself (the
        # timelapse path, where the moment producer returned without doing it).
        # Declared out here so the `finally` can lower it again no matter where
        # the capture below fails.
        plate_restored_z: float | None = None
        try:
            logger.info("[PHOTO-BG] Starting finish photo capture for archive %s", archive_id)

            from backend.app.api.routes.camera import _active_chamber_streams, _active_streams, get_buffered_frame

            # Read phase: settings + printer + archive in a short session, released
            # BEFORE the capture pipeline below. The capture (timelapse last-frame,
            # stage-22 wait, external-camera grab, or a fresh RTSP shot) can take
            # tens of seconds; holding this session across it pinned one pooled
            # connection idle-in-transaction per finishing print (issue #2572).
            async with async_session() as db:
                from backend.app.api.routes.settings import get_setting
                from backend.app.models.archive import PrintArchive
                from backend.app.models.printer import Printer

                capture_enabled = await get_setting(db, "capture_finish_photo")
                if capture_enabled is not None and capture_enabled.lower() != "true":
                    return None
                if not archive_id:
                    return None

                printer = (await db.execute(select(Printer).where(Printer.id == printer_id))).scalar_one_or_none()
                archive = (
                    await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))
                ).scalar_one_or_none()

            if not printer or not archive:
                return None

            import uuid
            from datetime import datetime

            from backend.app.utils.archive_paths import archive_dir as resolve_archive_dir

            if not archive.file_path:
                logger.warning("[PHOTO-BG] Archive %s has no file_path, using fallback dir", archive_id)
            archive_dir = resolve_archive_dir(archive)
            photo_filename = None

            # Prefer the timelapse last-frame source when a timelapse was
            # recording — it captures the moment after the toolhead parks
            # but before the bed drops, which the live-camera grab below
            # would miss (#1397). Skipped for external cameras (those have
            # their own framing and don't see a Bambu timelapse). Only
            # runs when the USER explicitly enabled timelapse for this
            # print — #1721 removed PrintLab's force-on at dispatch
            # because it caused per-layer nozzle parking on Smooth-mode
            # slicer profiles.
            prefer_timelapse_source = bool(data.get("timelapse_was_active")) and not (
                printer.external_camera_enabled and printer.external_camera_url
            )

            timelapse_still_pending = False
            if prefer_timelapse_source:
                photo_filename, timelapse_still_pending = await _capture_finish_photo_from_timelapse(
                    archive_id=archive_id,
                    archive_dir=archive_dir,
                    rotation=getattr(printer, "camera_rotation", 0),
                )

            # #1721: replacement framing path — on_finish_photo_moment
            # pre-captured a frame at the stage-22 / FINISH edge (toolhead
            # parked, bed not yet dropped) and cached the JPEG bytes in
            # _stage22_finish_frames. Consume them now so the saved photo
            # has the better framing instead of the post-bed-drop angle
            # the live-camera fallback below would give.
            if not photo_filename:
                # #1790: on the FINISH-state fallback path the producer
                # task is dispatched back-to-back with this consumer, so
                # a bare pop would race past with an empty result and
                # the RTSP fallback below would collide with the
                # producer's still-in-flight grab (single-client RTSP
                # on Bambu printers). Wait for the producer to finish
                # or give up before touching the cache.
                #
                # #2547: 20s was enough when the producer only ever grabbed a
                # frame. It now also raises the plate first, which costs the
                # settle window before the grab even starts — so the budget has
                # to cover settle + a worst-case 15s RTSP timeout, and still sit
                # under the notification's own photo wait below.
                in_flight = _rt()._stage22_finish_in_flight.pop(printer_id, None)
                if in_flight is not None:
                    try:
                        await asyncio.wait_for(in_flight.wait(), timeout=_rt()._FINISH_PHOTO_PRODUCER_WAIT_SECONDS)
                    except asyncio.TimeoutError:
                        logger.warning(
                            "[PHOTO-BG] timed out waiting for stage-22 producer for printer %s — proceeding to fallback",
                            printer_id,
                        )
                cached_frame = _rt()._stage22_finish_frames.pop(printer_id, None)
                if cached_frame:
                    # Already rotated by the producer (#2708) — rotating again
                    # here would undo the fix on the banked-frame path, whose
                    # bytes reach the cache having been rotated once already.
                    photos_dir = archive_dir / "photos"
                    photos_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    photo_filename = f"finish_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
                    photo_path = (
                        photos_dir / photo_filename
                    )  # SEC-PATH-OK: photo_filename wird je Zweig intern aus Zeitstempel+UUID bzw. dem zwischengespeicherten Frame-Schlüssel gebaut, keine Anfrage-Eingabe
                    await _rt().asyncio.to_thread(photo_path.write_bytes, cached_frame)
                    logger.info(
                        "[PHOTO-BG] Saved stage-22 pre-captured frame: %s (%d bytes)",
                        photo_filename,
                        len(cached_frame),
                    )

            # #2547: the timelapse path reaches the live grab below whenever the
            # video hasn't landed in time — the documented usual outcome on
            # P1-series, where transfers are slowest. `on_finish_photo_moment`
            # returned early for those prints without raising the plate, so
            # without this the photo that actually ships in the notification is
            # of an already-dropped plate: exactly the framing #1145/#1397/#1565
            # asked us to fix. The archive still gets the better video frame
            # later; this is about the image the user is sent.
            #
            # Gated on `timelapse_was_active` precisely because that is the
            # condition under which the producer skipped. On every other path it
            # has already raised and lowered the plate, and repeating that here
            # would be a second pointless round trip.
            if (
                not photo_filename
                and data.get("timelapse_was_active")
                and not print_dispatch_context.end_gcode_injected(printer_id)
            ):
                try:
                    async with async_session() as db:
                        from backend.app.api.routes.settings import get_setting

                        restore_setting = await get_setting(db, "finish_photo_restore_plate")
                    if restore_setting is None or restore_setting.lower() == "true":
                        max_z = await _max_z_for_current_print(printer_id, data, logger)
                        if max_z is not None and not await _plate_restore_is_blocked_by_queue(printer_id):
                            if await _restore_plate_for_finish_photo(printer_id, max_z, logger):
                                plate_restored_z = max_z
                except Exception as e:
                    logger.warning("[PLATE-RESTORE] printer %s: restore failed: %s", printer_id, e)

            # Fallback chain: external camera → buffered live frame →
            # fresh RTSP capture. Only runs if the timelapse path above
            # didn't already produce a photo.
            if not photo_filename:
                if printer.external_camera_enabled and printer.external_camera_url:
                    logger.info("[PHOTO-BG] Using external camera")
                    from backend.app.api.routes.camera import live_frame_for_capture
                    from backend.app.services.external_camera import capture_frame

                    # #2707: the second half of the finish-photo failure — the
                    # pre-capture and this fallback both collided with the live
                    # view. None here continues down the fallback chain.
                    defer, buffered = live_frame_for_capture(printer_id)
                    if defer:
                        frame_data = buffered
                    else:
                        frame_data = await capture_frame(
                            printer.external_camera_url,
                            printer.external_camera_type or "mjpeg",
                            snapshot_url=printer.external_camera_snapshot_url,
                        )
                    if frame_data:
                        frame_data = _apply_camera_rotation(frame_data, printer, logger)
                        photos_dir = archive_dir / "photos"
                        photos_dir.mkdir(parents=True, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        photo_filename = f"finish_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
                        photo_path = (
                            photos_dir / photo_filename
                        )  # SEC-PATH-OK: photo_filename aus Zeitstempel+UUID intern gebaut, keine Anfrage-Eingabe
                        await _rt().asyncio.to_thread(photo_path.write_bytes, frame_data)
                        logger.info("[PHOTO-BG] Saved external camera frame: %s", photo_filename)
                else:
                    # Check if camera stream is active - use buffered frame to avoid freeze
                    # Check both RTSP streams (_active_streams) and chamber image streams (_active_chamber_streams)
                    active_for_printer = [k for k in _active_streams if k.startswith(f"{printer_id}-")]
                    active_chamber_for_printer = [k for k in _active_chamber_streams if k.startswith(f"{printer_id}-")]
                    buffered_frame = get_buffered_frame(printer_id)

                    if (active_for_printer or active_chamber_for_printer) and buffered_frame:
                        # Use frame from active stream
                        logger.info("[PHOTO-BG] Using buffered frame from active stream")
                        buffered_frame = _apply_camera_rotation(buffered_frame, printer, logger)
                        photos_dir = archive_dir / "photos"
                        photos_dir.mkdir(parents=True, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        photo_filename = f"finish_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
                        photo_path = (
                            photos_dir / photo_filename
                        )  # SEC-PATH-OK: photo_filename aus Zeitstempel+UUID intern gebaut, keine Anfrage-Eingabe
                        await _rt().asyncio.to_thread(photo_path.write_bytes, buffered_frame)
                        logger.info("[PHOTO-BG] Saved buffered frame: %s", photo_filename)
                    else:
                        # No active stream - capture new frame
                        from backend.app.services.camera import capture_finish_photo

                        photo_filename = await capture_finish_photo(
                            printer_id=printer_id,
                            ip_address=printer.ip_address,
                            access_code=printer.access_code,
                            model=printer.model,
                            archive_dir=archive_dir,
                            rotation=getattr(printer, "camera_rotation", 0),
                        )

            # Write phase: attach the photo in a fresh short-lived session.
            if photo_filename:
                async with async_session() as db:
                    from backend.app.models.archive import PrintArchive

                    arch = await db.get(PrintArchive, archive_id)
                    if arch is not None:
                        photos = arch.photos or []
                        photos.append(photo_filename)
                        arch.photos = photos
                        await db.commit()
                logger.info("[PHOTO-BG] Saved: %s", photo_filename)

            # The short wait above is bounded so a slow printer can't hold up
            # the print-complete notification, which is what the caller is
            # blocking on. When it ran out with the video still on its way,
            # keep waiting off to the side and add the better frame to the
            # archive once it arrives (#2704 follow-up) — otherwise P1-series
            # users, whose videos routinely take minutes to transfer, never get
            # the pre-bed-drop framing this path exists to provide.
            #
            # Spawned here rather than at the point the wait gave up: both this
            # function and the upgrade do a read-modify-write on `photos`, and
            # the live-camera fallback above can take tens of seconds. Starting
            # the upgrade before that write means the two can interleave and one
            # silently drops the other's entry, leaving a JPEG on disk that the
            # gallery never lists.
            if timelapse_still_pending:
                spawn_background_task(
                    _upgrade_finish_photo_from_timelapse(
                        archive_id, archive_dir, rotation=getattr(printer, "camera_rotation", 0)
                    ),
                    name=f"finish-photo-upgrade-{archive_id}",
                )

            return photo_filename
        except Exception as e:
            logger.warning("[PHOTO-BG] Failed: %s", e)
            return None
        finally:
            # #2547: we raised the plate, so we owe the move back down — even if
            # the capture in between threw. Otherwise the user finds the print
            # pinned under the nozzle.
            if plate_restored_z is not None:
                try:
                    _park_plate_after_finish_photo(printer_id, plate_restored_z, logger)
                except Exception as e:
                    logger.warning("[PLATE-RESTORE] printer %s: could not lower plate: %s", printer_id, e)

    spawn_background_task(_background_energy_calculation(), name="background-energy-calc")
    # Photo capture task - result will be used by notifications
    photo_task = spawn_background_task(_background_finish_photo(), name="background-finish-photo")
    log_timing("Background tasks scheduled (energy, photo)")

    # Also run smart plug, notifications, and maintenance as background tasks
    print_status = data.get("status", "completed")

    async def _background_smart_plug():
        """Handle smart plug automation in background."""
        try:
            logger.info("[AUTO-OFF-BG] Starting smart plug automation for printer %s", printer_id)
            async with async_session() as db:
                await smart_plug_manager.on_print_complete(printer_id, print_status, db)
                logger.info("[AUTO-OFF-BG] Completed")
        except Exception as e:
            logger.warning("[AUTO-OFF-BG] Failed: %s", e)

    async def _background_notifications(finish_photo_filename: str | None = None):
        """Send print complete notifications in background."""
        try:
            logger.info(
                "[NOTIFY-BG] Starting notifications for printer %s, photo=%s", printer_id, finish_photo_filename
            )
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive
                from backend.app.models.printer import Printer

                result = await db.execute(select(Printer).where(Printer.id == printer_id))
                printer = result.scalar_one_or_none()
                printer_name = printer.name if printer else f"Printer {printer_id}"

                archive_data = None
                if archive_id:
                    archive_result = await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))
                    archive = archive_result.scalar_one_or_none()
                    if archive:
                        # Actual elapsed time from started_at/completed_at when both are
                        # populated (every terminal status sets completed_at after #1198).
                        # Falls back to None so the notification path can decide whether to
                        # render the slicer estimate as a last resort.
                        actual_time_seconds = None
                        if archive.started_at and archive.completed_at:
                            elapsed = (archive.completed_at - archive.started_at).total_seconds()
                            if elapsed > 0:
                                actual_time_seconds = int(elapsed)

                        archive_data = {
                            "print_time_seconds": archive.print_time_seconds,
                            "actual_time_seconds": actual_time_seconds,
                            "actual_filament_grams": archive.filament_used_grams,
                            "failure_reason": archive.failure_reason,
                            "created_by_id": archive.created_by_id,
                        }

                        # Scale filament usage for partial prints
                        if print_status != "completed" and archive.filament_used_grams:
                            progress = data.get("progress") or 0
                            scale = _partial_progress_scale(progress)
                            archive_data["actual_filament_grams"] = round(archive.filament_used_grams * scale, 1)
                            archive_data["progress"] = progress

                        # Pass per-slot data from archive.extra_data
                        if archive.extra_data and archive.extra_data.get("filament_slots"):
                            slots = archive.extra_data["filament_slots"]
                            if print_status != "completed":
                                scale = _partial_progress_scale(data.get("progress"))
                                slots = [{**s, "used_g": round(s["used_g"] * scale, 1)} for s in slots]
                            archive_data["filament_slots"] = slots

                        # Scope project-summed totals down to the plate that was
                        # actually printed — see _scope_notification_archive_data_to_plate
                        # for the why (#1785).
                        archive_data = _scope_notification_archive_data_to_plate(
                            archive_data,
                            archive.file_path,
                            notify_plate_id,
                            print_status,
                            data.get("progress"),
                            app_settings.base_dir,
                        )

                        # Enrich filament_grams from usage_results when archive has no 3MF data
                        if not archive_data.get("actual_filament_grams") and usage_results:
                            total_from_usage = sum(r.get("weight_used", 0) for r in usage_results)
                            if total_from_usage > 0:
                                archive_data["actual_filament_grams"] = round(total_from_usage, 1)

                        # Pass usage tracker results for AMS slot info in notifications
                        if usage_results:
                            archive_data["usage_results"] = usage_results
                        # Add finish photo URL and image bytes if available
                        if finish_photo_filename:
                            photo_url, photo_bytes = await _finish_photo_for_notification(
                                db, archive, archive_id, finish_photo_filename
                            )
                            if photo_url:
                                archive_data["finish_photo_url"] = photo_url
                            if photo_bytes:
                                archive_data["image_data"] = photo_bytes

                if not await _rt()._kill_switch_notification_already_sent(kill_switch_notification_task):
                    await notification_service.on_print_complete(
                        printer_id, printer_name, print_status, data, db, archive_data=archive_data
                    )
                else:
                    logger.info("[NOTIFY-BG] Skipped duplicate kill-switch provider notification")

                # Post-print outcome confirmation (#1898). Runs in this
                # background task so the finish photo fetched above rides
                # along with the prompt.
                if print_status == "completed" and archive_id:
                    await _dispatch_outcome_confirmation_safely(
                        db, printer_id, printer_name, data, archive_id, archive_data
                    )

                # Send user-specific email notification
                if archive_data:
                    created_by_id = archive_data.get("created_by_id")
                    raw_filename = data.get("subtask_name") or data.get("filename", "Unknown")
                    await _dispatch_user_print_email(
                        print_status,
                        created_by_id,
                        printer_name,
                        raw_filename,
                        db,
                        image_data=archive_data.get("image_data"),
                        finish_photo_url=archive_data.get("finish_photo_url"),
                    )

                logger.info("[NOTIFY-BG] Completed")
        except Exception as e:
            logger.error("[NOTIFY-BG] Failed: %s", e, exc_info=True)

    async def _background_maintenance_check():
        """Check for maintenance due in background."""
        if print_status != "completed":
            return
        try:
            logger.info("[MAINT-BG] Starting maintenance check for printer %s", printer_id)
            async with async_session() as db:
                from backend.app.models.printer import Printer

                result = await db.execute(select(Printer).where(Printer.id == printer_id))
                printer = result.scalar_one_or_none()
                printer_name = printer.name if printer else f"Printer {printer_id}"

                await ensure_default_types(db)
                overview = await _get_printer_maintenance_internal(printer_id, db, commit=True)

                items_needing_attention = [
                    {"name": item.maintenance_type_name, "is_due": item.is_due, "is_warning": item.is_warning}
                    for item in overview.maintenance_items
                    if item.enabled and (item.is_due or item.is_warning)
                ]

                if items_needing_attention:
                    await notification_service.on_maintenance_due(printer_id, printer_name, items_needing_attention, db)
                    logger.info("[MAINT-BG] Sent notification: %s items need attention", len(items_needing_attention))

                    # MQTT relay - publish maintenance alerts
                    for item in items_needing_attention:
                        try:
                            await mqtt_relay.on_maintenance_alert(
                                printer_id=printer_id,
                                printer_name=printer_name,
                                maintenance_type=item["name"],
                                current_value=0,  # Not easily available here
                                threshold=0,  # Not easily available here
                            )
                        except Exception:
                            pass  # Don't fail if MQTT fails
                else:
                    logger.info("[MAINT-BG] Completed (no items need attention)")
        except Exception as e:
            logger.warning("[MAINT-BG] Failed: %s", e)

    spawn_background_task(_background_smart_plug(), name="background-smart-plug")
    spawn_background_task(_background_maintenance_check(), name="background-maintenance-check")

    # Notification task waits for photo capture to complete first (with timeout).
    # When a timelapse was recording, photo sourcing polls the per-print
    # timelapse for up to 60s (#1397) — extend the budget so the notification
    # carries the correct bed-up photo instead of falling through to the
    # live-cam grab. Adds ~30s of notification latency at worst on slow links.
    #
    # #2547: both budgets now have to cover a plate restore as well.
    #
    # Without timelapse, the wait is on the moment producer, which raises the
    # plate before its grab — so this has to outlast that producer's own budget.
    #
    # With timelapse, the capture polls up to
    # `_FINISH_PHOTO_TIMELAPSE_POLL_TIMEOUT_SECONDS` for the video and only then
    # falls back to a live grab, which is the case that raises the plate. At the
    # old flat 75s that fallback was guaranteed to be cut off mid-settle, so the
    # restore would have moved the plate for a photo nobody waited for.
    photo_wait_timeout = (
        _rt()._FINISH_PHOTO_TIMELAPSE_POLL_TIMEOUT_SECONDS + _rt()._FINISH_PHOTO_PRODUCER_WAIT_SECONDS
        if data.get("timelapse_was_active")
        else _rt()._FINISH_PHOTO_PRODUCER_WAIT_SECONDS + 15
    )

    async def _photo_then_notify():
        """Wait for photo capture, then send notification with photo URL."""
        finish_photo = None
        try:
            finish_photo = await asyncio.wait_for(photo_task, timeout=photo_wait_timeout)
            logger.info("[PHOTO-NOTIFY] Photo task returned: %s", finish_photo)
        except TimeoutError:
            logger.warning(
                "[PHOTO-NOTIFY] Photo capture timed out after %ss, sending notification without photo",
                photo_wait_timeout,
            )
        except Exception as e:
            logger.warning("[PHOTO-NOTIFY] Photo task failed: %s", e)
        try:
            await _background_notifications(finish_photo)
        except Exception as e:
            logger.error("[PHOTO-NOTIFY] Notification sending failed: %s", e, exc_info=True)

    spawn_background_task(_photo_then_notify(), name="photo-then-notify")

    # Stitch external camera layer timelapse if session was active
    print_status = data.get("status", "completed")

    async def _background_layer_timelapse():
        """Stitch layer timelapse and attach to archive."""
        from backend.app.services.layer_timelapse import cancel_session, on_print_complete as tl_complete

        try:
            if print_status == "completed":
                logger.info("[LAYER-TL] Stitching layer timelapse for printer %s", printer_id)
                timelapse_path = await tl_complete(printer_id)
                if timelapse_path and archive_id:
                    logger.info("[LAYER-TL] Attaching timelapse %s to archive %s", timelapse_path, archive_id)
                    async with async_session() as db:
                        service = ArchiveService(db)
                        timelapse_data = await _rt().asyncio.to_thread(timelapse_path.read_bytes)
                        await service.attach_timelapse(archive_id, timelapse_data, "layer_timelapse.mp4")
                        # Clean up the temp file
                        await _rt().asyncio.to_thread(timelapse_path.unlink, missing_ok=True)
                        logger.info("[LAYER-TL] Layer timelapse attached successfully")
                elif timelapse_path:
                    # Timelapse created but no archive - just clean up
                    await _rt().asyncio.to_thread(timelapse_path.unlink, missing_ok=True)
            else:
                # Print failed or cancelled - cancel timelapse session
                cancel_session(printer_id)
                logger.info(
                    "[LAYER-TL] Cancelled layer timelapse for printer %s (status: %s)", printer_id, print_status
                )
        except Exception as e:
            logger.warning("[LAYER-TL] Failed: %s", e)
            # Try to cancel session on error
            try:
                cancel_session(printer_id)
            except Exception:
                pass  # Best-effort timelapse session cancellation on error

    spawn_background_task(_background_layer_timelapse(), name="background-layer-timelapse")

    log_timing("All background tasks scheduled")

    # Auto-scan for timelapse if recording was active during the print
    if archive_id and data.get("timelapse_was_active") and data.get("status") == "completed":
        logger.info("[TIMELAPSE] Timelapse was active during print, scheduling auto-scan for archive %s", archive_id)
        # Schedule timelapse scan as background task with retries
        # The printer needs time to encode the video after print completion
        baseline = _rt()._timelapse_baselines.pop(printer_id, None)
        spawn_background_task(
            _scan_for_timelapse_with_retries(archive_id, baseline),
            name=f"scan-timelapse-{archive_id}",
        )
        log_timing("Timelapse scan scheduled")

    logger.info("[CALLBACK] on_print_complete finished for printer %s, archive %s", printer_id, archive_id)
