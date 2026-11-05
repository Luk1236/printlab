"""MQTT-Druckstart-Abfluss von main.py ausgelagert.

Enthalten: ``on_print_start`` (Archiv je Druck, Platten-Erkennung, Download des
3MF über FTPS mit Sieben und Wiederholungen, Notfallarchiv ohne 3MF,
Energie-Begin, Zeitaufnahme-Basis) samt den Bausteinen, die nur es nutzt:
``_get_start_ams_mapping``, ``_extract_filament_data_from_mqtt`` (#1533),
``_send_print_start_notification``, ``_record_energy_start`` (#941), die
Ausgangsfrage bei fremden Drucken (#1898) und die Nachhole-Eisenbahnen.
Patchbare Namen greift das Modul über :func:`_rt` ab — die Tests lenken sie
weiter im Modul ``main``: ``printer_manager``, ``ws_manager``, ``mqtt_relay``,
``notification_service``, ``smart_plug_manager``, ``async_session``,
``asyncio``, ``time``, ``datetime``, die FTP-Bausteine (Download, Sieb,
Zwischenspeicher) und die gemeldeten Bausteine selbst. Zustaende anderer
Baustellen (erwartete Drucke, aktive Drucke, Stage22/Inprint-Bänke,
Beleuchtwartende) liest es ebenfalls über :func:`_rt`. Aufrufer und Tests
sehen keinen Unterschied.
"""

import asyncio  # noqa: F401 — Annotationen und CancelledError brauchen die echte Klasse
import logging
import posixpath
from pathlib import Path

from sqlalchemy import or_, select

from backend.app.core.config import settings as app_settings
from backend.app.services import print_dispatch_context
from backend.app.services.archive import swap_plate_suffix
from backend.app.services.bambu_ftp import FileNotOnPrinterError, normalize_3mf_name
from backend.app.services.energy_plug import energy_plug_candidates, select_energy_reading
from backend.app.services.print_storage import (
    REASON_FTP_TRANSFER_FAILED,
    REASON_FTPS_COOLOFF,
    ftp_probe_paths,
    print_file_reachable_over_ftp,
)
from backend.app.services.printer_manager import parse_plate_id, resolve_plate_id
from backend.app.services.spool_assignment_notifications import (
    notify_missing_spool_assignments_on_print_start,
)
from backend.app.utils.print_jobs import is_internal_printer_job

# Der Logger-Name bleibt der der alten Heimat, damit Protokollzeilen in den
# Support-Bundles unverändert unter ``backend.app.main`` auftauchen.
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen."""
    import importlib

    return importlib.import_module("backend.app.main")


def _get_start_ams_mapping(data: dict, archive_id: int | None) -> list[int] | None:
    """Resolve AMS mapping for print start without consuming stored queue/reprint state."""
    stored_ams_mapping = data.get("ams_mapping")
    if not stored_ams_mapping and archive_id:
        stored_ams_mapping = _rt()._print_ams_mappings.get(archive_id)
    return stored_ams_mapping


def _extract_filament_data_from_mqtt(data: dict, ams_mapping: list[int] | None = None) -> dict[str, str]:
    """Best-effort filament metadata from the MQTT print-start snapshot.

    Used when the 3MF can't be downloaded (P1S/A1/P2S firmwares lock the
    file during print, see #1533) so the fallback PrintArchive still has
    enough filament info to support the inventory views and AMS-expansion
    planning the operator opens it for. Returns a dict with optional
    ``filament_type`` and ``filament_color`` keys in the same
    comma-separated format the 3MF extractor produces, so the rest of the
    codebase treats the fallback archive identically to a normal one.

    ``ams_mapping`` is the slicer's slot-per-print-filament list captured
    from the MQTT print payload (global tray IDs, possibly -1 for VT-tray
    entries). When supplied, only the slots actually consumed by this
    print contribute. Without it the function falls back to every loaded
    AMS slot — less accurate but still useful.

    Accepts both the raw inner payload (``{"ams": {"ams": [...]}, ...}``)
    that the unit tests pass directly, AND the on_print_start callback
    shape (``{"raw_data": {"ams": {"ams": [...]}, ...}, ...}``) the
    bambu_mqtt service hands to main.py at runtime. The original
    ``_extract_filament_data_from_mqtt(data)`` shipped in #1533 only
    handled the inner shape and silently returned ``{}`` for every real
    print start, leaving fallback archives' filament fields NULL — the
    exact regression the fix was meant to close. Reported with a log
    proving the AMS state was right there at
    ``data["raw_data"]["ams"]["ams"][0]["tray"][0]`` (#1533 follow-up).
    """
    result: dict[str, str] = {}
    # Look at the on_print_start wrapper first, then the inner shape.
    raw_data = (data or {}).get("raw_data")
    ams_root = (raw_data or {}).get("ams") if isinstance(raw_data, dict) else None
    if not isinstance(ams_root, dict):
        ams_root = (data or {}).get("ams") or {}
    ams_units = ams_root.get("ams") if isinstance(ams_root, dict) else None
    if not isinstance(ams_units, list) or not ams_units:
        return result

    # Map global tray id (unit * 4 + tray) → (type, color).
    loaded: dict[int, tuple[str, str]] = {}
    for unit in ams_units:
        if not isinstance(unit, dict):
            continue
        try:
            unit_id = int(unit.get("id", 0))
        except (TypeError, ValueError):
            continue
        for tray in unit.get("tray") or []:
            if not isinstance(tray, dict):
                continue
            try:
                tray_id = int(tray.get("id", 0))
            except (TypeError, ValueError):
                continue
            ttype = (tray.get("tray_type") or "").strip()
            tcolor = (tray.get("tray_color") or "").strip().upper()
            if not ttype:
                continue  # Empty / unloaded slot.
            loaded[unit_id * 4 + tray_id] = (ttype, tcolor)

    if not loaded:
        return result

    if ams_mapping:
        used_ids = [int(x) for x in ams_mapping if isinstance(x, (int, float)) and int(x) >= 0]
        filaments = [loaded[g] for g in used_ids if g in loaded]
        if not filaments:
            return result  # Mapping points entirely at slots we have no data for.
    else:
        filaments = [loaded[g] for g in sorted(loaded.keys())]

    types_joined = ",".join(f[0] for f in filaments)
    colors_joined = ",".join(f[1] for f in filaments if f[1])

    # Column limits per backend/app/models/archive.py: filament_type=50,
    # filament_color=200.
    if types_joined:
        result["filament_type"] = types_joined[:50]
    if colors_joined:
        result["filament_color"] = colors_joined[:200]
    return result


async def _record_energy_start(archive, printer_id: int, db, *, context: str = "") -> bool:
    """Capture the smart plug lifetime counter on the archive at print start.

    Persists `energy_start_kwh` on the archive row (#941) so per-print energy
    tracking survives a backend restart mid-print. The print-end handler reads
    this value back from the DB and computes the delta against the current
    plug counter.
    """
    _logger = logger
    try:
        candidates = await energy_plug_candidates(db, printer_id)
        if not candidates:
            _logger.info("[ENERGY] No smart plug for printer %s (archive %s)", printer_id, archive.id)
            return False
        selected = await select_energy_reading(candidates, _rt()._get_plug_energy, db)
        if selected is None:
            # Naming the plugs matters here: with several linked to one printer
            # this is the difference between "the meter is offline" and "you
            # linked only accessories" (#2859).
            _logger.warning(
                "[ENERGY] No plug on printer %s reports a lifetime energy counter for archive %s (tried: %s)",
                printer_id,
                archive.id,
                ", ".join(plug.name for plug in candidates),
            )
            return False
        plug, energy = selected
        archive.energy_start_kwh = float(energy["total"])
        await db.commit()
        _logger.info(
            "[ENERGY] Recorded starting energy%s for archive %s from plug '%s': %s kWh",
            f" ({context})" if context else "",
            archive.id,
            plug.name,
            energy["total"],
        )
        return True
    except Exception as e:
        _logger.warning("[ENERGY] Failed to record starting energy for archive %s: %s", archive.id, e)
        return False


async def _send_print_start_notification(
    printer_id: int,
    data: dict,
    archive_data: dict | None = None,
    logger=None,
):
    """Helper to send print start notification with optional archive data."""
    if logger is None:
        logger = logging.getLogger("backend.app.main")

    try:
        async with _rt().async_session() as db:
            from backend.app.models.printer import Printer

            result = await db.execute(select(Printer).where(Printer.id == printer_id))
            printer = result.scalar_one_or_none()
            printer_name = printer.name if printer else f"Printer {printer_id}"

            # Capture camera snapshot for notification image attachment
            image_data = await _rt()._capture_snapshot_for_notification(printer_id, printer, logger)
            if image_data:
                if archive_data is None:
                    archive_data = {}
                archive_data["image_data"] = image_data

            await _rt().notification_service.on_print_start(
                printer_id, printer_name, data, db, archive_data=archive_data
            )

            # Send user-specific email notification for print start
            if archive_data and archive_data.get("created_by_id"):
                await _rt().notification_service.send_user_print_email(
                    event_type="user_print_start",
                    created_by_id=archive_data["created_by_id"],
                    printer_name=printer_name,
                    filename=data.get("subtask_name") or data.get("filename", "Unknown"),
                    db=db,
                )
    except Exception as e:
        logger.warning("Notification on_print_start failed: %s", e)


# Retry ladder for a fallback archive created while the printer's FTPS cool-off
# was running (#2957). The cool-off is 300s, so the first attempt is placed just
# past it; the second covers a handshake that failed again on the way back and
# armed a fresh one. Module-level so tests can shrink them.
_FALLBACK_3MF_RETRY_DELAYS_SECONDS: tuple[float, ...] = (310.0, 620.0)

# Retry ladder for the other temporary give-up: the file service answered and
# the transfer still did not finish, which at print start is usually the printer
# serving MQTT, the camera and a job upload at the same time (#3063). Nothing has
# to expire here, so the first attempt comes early -- #3063's reporter had the
# same 19MB file complete 48 seconds after the download budget ran out. The later
# two cover a printer that stays busy well into the print.
_FALLBACK_3MF_TRANSFER_RETRY_DELAYS_SECONDS: tuple[float, ...] = (60.0, 240.0, 600.0)


async def _recover_fallback_archive_locked(archive_id: int, source_3mf: Path, printer_id: int) -> bool:
    """The body of :func:`_recover_fallback_archive`, under its per-printer lock."""
    import zipfile

    from backend.app.models.archive import PrintArchive

    if not source_3mf.exists() or source_3mf.stat().st_size == 0:
        return False
    if not await _rt().asyncio.to_thread(zipfile.is_zipfile, source_3mf):
        # A truncated or half-written download is worse than no download: it
        # would replace an honest empty archive with wrong metadata.
        logger.warning("[RECOVER] %s is not a readable 3MF; leaving archive %s as-is", source_3mf, archive_id)
        return False

    async with _rt().async_session() as db:
        archive = (await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))).scalar_one_or_none()
        if archive is None or archive.deleted_at is not None:
            return False
        if archive.file_path:
            # Already recovered, or never was a fallback. Either way there is a
            # real 3MF attached and overwriting it is not this function's job.
            return False

        print_data = (archive.extra_data or {}).get("_print_data") or {}
        service = _rt().ArchiveService(db)
        recovered = await service.archive_print(
            printer_id=printer_id,
            source_file=source_3mf,
            print_data={**print_data, "status": archive.status or "printing"},
            subtask_id=archive.subtask_id,
            update_archive_id=archive.id,
        )
        if recovered is None:
            return False

        logger.info(
            "[RECOVER] Archive %s filled in from %s (%s bytes) — it started as a no-3MF fallback",
            archive_id,
            source_3mf,
            recovered.file_size,
        )
        # `archive_updated`, not `archive_created` — the row was already on the
        # Archives page as an empty card and is now filled in, not new.
        await _rt().ws_manager.send_archive_updated(
            {
                "id": recovered.id,
                "printer_id": recovered.printer_id,
                "filename": recovered.filename,
                "print_name": recovered.print_name,
                "status": recovered.status,
            }
        )
        return True


async def _recover_fallback_archive(archive_id: int, source_3mf: Path, printer_id: int) -> bool:
    """Fill in a no-3MF archive from a 3MF that turned up later.

    Returns True when the row was upgraded. Safe to call speculatively: it
    verifies the archive still exists, is still a fallback, and that the file
    is a readable 3MF before touching anything.

    Serialised per printer — see ``_rt()._fallback_recovery_locks``.
    """
    lock = _rt()._fallback_recovery_locks.setdefault(printer_id, _rt().asyncio.Lock())
    async with lock:
        return await _recover_fallback_archive_locked(archive_id, source_3mf, printer_id)


async def try_recover_fallback_archive(printer_id: int, name: str, path: Path) -> bool:
    """Offer a freshly-downloaded 3MF to this printer's running fallback archive.

    Called from the paths that pull a 3MF for a print that is already under way
    — chiefly the cover endpoint, which downloads the very file the archive flow
    could not get and, before #2957, used it for a thumbnail and nothing else.
    The bytes are already local, so this costs a parse and a row update.

    No-op when the running print has a real archive, which is the common case.
    """
    from backend.app.models.archive import PrintArchive

    # `_active_prints` is keyed on the raw names seen at print start — the
    # dispatch filename, the subtask name, and the subtask name plus ".3mf".
    # Callers here arrive with whichever variant their own path produced, so
    # match on the same normalization the download cache uses rather than on an
    # exact string; that is what makes "Desktop_Goose.gcode.3mf" from the cover
    # endpoint find an archive registered under "Desktop_Goose".
    wanted = normalize_3mf_name(name)
    archive_id = None
    for (key_printer_id, key_name), value in list(_rt()._active_prints.items()):
        if key_printer_id == printer_id and normalize_3mf_name(key_name) == wanted:
            archive_id = value
            break
    if archive_id is None:
        return False

    async with _rt().async_session() as db:
        archive = (await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))).scalar_one_or_none()
        # Cheap pre-check so the common case (a normal archive) does no work.
        if archive is None or archive.file_path or archive.deleted_at is not None:
            return False

    try:
        return await _recover_fallback_archive(archive_id, path, printer_id)
    except Exception as e:
        # Recovery is opportunistic. A failure here must never take down the
        # caller, which is usually just trying to render a thumbnail.
        logger.warning("[RECOVER] Could not fill in archive %s from %s: %s", archive_id, path, e)
        return False


def _schedule_fallback_3mf_retry(
    printer_id: int,
    archive_id: int,
    filenames: list[str],
    delays: tuple[float, ...] | None = None,
    reason: str = REASON_FTPS_COOLOFF,
) -> None:
    """Re-attempt the 3MF download after a temporary give-up.

    ``reason`` says which give-up this is, and picks the default ladder: an
    FTPS cool-off has to be waited out, while a transfer that timed out under
    contention is worth asking about again straight away (#3063). It is only
    read for the ladder and the log line -- the retry itself is identical, since
    in both cases the file is on the printer and the last attempt at it failed
    for a reason that does not last.
    """

    if delays is None:
        delays = (
            _FALLBACK_3MF_TRANSFER_RETRY_DELAYS_SECONDS
            if reason == REASON_FTP_TRANSFER_FAILED
            else _FALLBACK_3MF_RETRY_DELAYS_SECONDS
        )

    async def _retry() -> None:
        from backend.app.models.archive import PrintArchive
        from backend.app.models.printer import Printer

        for delay in delays:
            await _rt().asyncio.sleep(delay)

            async with _rt().async_session() as db:
                archive = (
                    await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))
                ).scalar_one_or_none()
                if archive is None or archive.deleted_at is not None or archive.file_path:
                    return
                printer = (await db.execute(select(Printer).where(Printer.id == printer_id))).scalar_one_or_none()
                if printer is None:
                    return
                # Read the fields while the session is open rather than touching
                # a detached instance minutes later, mid-download.
                printer_ip = printer.ip_address
                printer_code = printer.access_code
                printer_model = printer.model

            # Someone else may have fetched it in the meantime — the cover
            # endpoint routinely does, and its copy is the same bytes.
            for name in filenames:
                cached = _rt().get_cached_3mf(printer_id, name)
                if cached and await _recover_fallback_archive(archive_id, cached, printer_id):
                    return

            if _rt().ftps_handshake_blocked(printer_ip):
                logger.info(
                    "[RECOVER] Printer %s is still in its FTPS cool-off; archive %s retry deferred",
                    printer_id,
                    archive_id,
                )
                continue

            _, _, _, ftp_timeout = await _rt().get_ftp_retry_settings()
            for candidate in filenames:
                # Bare name only. These come from the print-start flow, which
                # already strips the path, but the local temp write must not
                # depend on that holding for every future caller — a name that
                # is absolute or contains ".." would otherwise escape the data
                # volume via the `/` operator.
                name = Path(candidate).name
                if not name or name in (".", ".."):
                    continue
                if not name.endswith(".3mf"):
                    name = f"{name}.3mf"
                temp_path = _rt().app_settings.archive_dir / "temp" / name
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    hit = await _rt().download_file_try_paths_async(
                        printer_ip,
                        printer_code,
                        ftp_probe_paths(name),
                        temp_path,
                        socket_timeout=ftp_timeout,
                        printer_model=printer_model,
                    )
                except Exception as e:
                    logger.debug("[RECOVER] Retry download of %s failed: %s", name, e)
                    continue
                if not hit:
                    continue
                _rt().cache_3mf_download(printer_id, name, temp_path)
                if await _recover_fallback_archive(archive_id, temp_path, printer_id):
                    return

            logger.info("[RECOVER] Archive %s still has no 3MF after a retry", archive_id)

    async def _guarded() -> None:
        try:
            await _retry()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[RECOVER] Retry task for archive %s failed: %s", archive_id, e)
        finally:
            if _rt()._fallback_3mf_retry_tasks.get(printer_id) is _rt().asyncio.current_task():
                _rt()._fallback_3mf_retry_tasks.pop(printer_id, None)

    existing = _rt()._fallback_3mf_retry_tasks.pop(printer_id, None)
    if existing and not existing.done():
        existing.cancel()
    task = _rt().asyncio.create_task(_guarded())
    _rt()._fallback_3mf_retry_tasks[printer_id] = task
    logger.info(
        "[RECOVER] Archive %s has no 3MF (%s) and the file should still be on printer %s; will retry in %s",
        archive_id,
        reason,
        printer_id,
        ", ".join(f"{d:g}s" for d in delays),
    )


async def _ask_outcome_for_external_print(db, printer_id: int, observed_name: str | None = None) -> bool:
    """Whether an archive created here should ask for the print's outcome (#1898).

    Only a print PrintLab did not dispatch reaches the archive-*creating*
    branches below: a queued job already has its archive and takes the
    expected-print branch, where the queue item's own ``confirm_outcome``
    decides. The queue is still consulted, because a restart mid-print empties
    ``_expected_prints`` — without the check the setting could override a queue
    item that deliberately has the flag off. Any failure answers "don't ask":
    an unwanted prompt is worse than a missing one, and this must never be the
    reason a print goes unarchived.

    A ``printing`` row is not proof on its own, though: PrintLab deliberately
    leaves one behind when a completion cannot be matched to it
    (``_completion_belongs_to_queue_item``), and the scheduler's stranded sweep
    only takes it back once the printer has sat connected and terminal for
    minutes. Until then every screen-started print on that printer would
    silently lose its prompt, so the row is held against ``observed_name`` by
    the same comparison a completion uses: a positive disagreement means the row
    is about some other run and this print is external after all.
    """
    try:
        # A savepoint rather than a rollback of the caller's transaction on
        # failure: a failed statement leaves the transaction unusable, but a
        # full rollback also expires every object the caller has loaded (the
        # printer, the archive it just created), and on an async session the
        # next attribute read then raises instead of reloading. Everything here
        # is a read, so undoing the savepoint loses nothing.
        async with db.begin_nested():
            return await _decide_outcome_for_external_print(db, printer_id, observed_name, logger)
    except Exception as e:
        logger.warning("[CALLBACK] Could not decide the outcome prompt for printer %s: %s", printer_id, e)
        return False


async def _decide_outcome_for_external_print(db, printer_id: int, observed_name: str | None, logger) -> bool:
    """The reads behind ``_ask_outcome_for_external_print``; see there."""
    from backend.app.api.routes.settings import get_setting, setting_is_true

    if not setting_is_true(await get_setting(db, "confirm_outcome_external_prints")):
        return False

    from backend.app.models.print_queue import PrintQueueItem

    dispatched_here = await db.scalar(
        select(PrintQueueItem)
        .where(
            PrintQueueItem.printer_id == printer_id,
            PrintQueueItem.status == "printing",
        )
        .limit(1)
    )
    if dispatched_here is None:
        return True

    expected = await _rt()._queue_item_dispatched_name(db, dispatched_here)
    observed = (observed_name or "").strip()
    if not expected or not observed or _rt()._subtask_names_match(expected, observed):
        logger.info(
            "[CALLBACK] Not asking for the outcome on printer %s: queue item %s is still printing, so "
            "PrintLab dispatched this run and the item's own ask-for-outcome flag decides.",
            printer_id,
            dispatched_here.id,
        )
        return False

    logger.info(
        "[CALLBACK] Queue item %s is still marked printing on printer %s but was dispatched as %r, not "
        "%r; treating this as an externally started print.",
        dispatched_here.id,
        printer_id,
        expected,
        observed,
    )
    return True


async def _queue_item_dispatched_name(db, item) -> str:
    """The subtask name *item* was dispatched under, or "" when unknowable.

    A row with no archive, or an archive with no file name, is unverifiable
    rather than wrong; every caller answers that with its permissive branch.
    """
    if item.archive_id is None:
        return ""

    from backend.app.models.archive import PrintArchive

    archive = await db.get(PrintArchive, item.archive_id)
    if archive is None or not archive.filename:
        return ""
    return _rt()._subtask_name_from_filename(archive.filename)


async def on_print_start(printer_id: int, data: dict):
    """Handle print start - archive the 3MF file immediately."""

    logger.info("[CALLBACK] on_print_start called for printer %s, data keys: %s", printer_id, list(data.keys()))

    # Clear any stale user-stopped flag from previous print cycles
    _rt()._user_stopped_printers.discard(printer_id)
    # A new print starts its milestones from zero (#3211). The status path only
    # resets on progress below 5 while not printing, which a printer that goes
    # from FINISH at 100% straight into a new print at a preparation-phase 85%
    # never shows. This callback does not fire after a PrintLab restart (#1304)
    # or on resume from pause, so it cannot repeat a milestone mid-print.
    _rt()._last_progress_milestone[printer_id] = 0
    _rt()._kill_switch_notification_tasks.pop(printer_id, None)

    # #1721: drop any leftover pre-captured finish frame from a prior print
    # so a never-consumed cache entry can't bleed into the new print's photo.
    _rt()._stage22_finish_frames.pop(printer_id, None)
    # #1867: same for the in-print frame bank — a queued print must not reuse
    # the previous job's banked frame.
    _rt()._inprint_frame_bank.pop(printer_id, None)
    _rt()._inprint_frame_bank_ts.pop(printer_id, None)
    # #2547: bind (or clear) the "this print ends with injected End G-code" flag.
    # Unconditional, so a print PrintLab didn't dispatch drops the previous
    # print's flag instead of inheriting it.
    print_dispatch_context.adopt(printer_id)

    # Cancel any active bed cooldown waiter for this printer
    if _rt()._bed_cool_waiters.pop(printer_id, None):
        logger.info("[BED-COOL] Cancelled bed cooldown waiter for printer %s (new print started)", printer_id)

    # Clear cached cover images so the new print's thumbnail is fetched fresh
    from backend.app.api.routes.printers import clear_cover_cache

    clear_cover_cache(printer_id)

    await _rt().ws_manager.send_print_start(printer_id, data)

    # Notify when the print-start AMS mapping references tray slots without spool assignments.
    await notify_missing_spool_assignments_on_print_start(printer_id, data, logger)

    # MQTT relay - publish print start
    try:
        printer_info = _rt().printer_manager.get_printer(printer_id)
        if printer_info:
            await _rt().mqtt_relay.on_print_start(
                printer_id,
                printer_info.name,
                printer_info.serial_number,
                data.get("filename", ""),
                data.get("subtask_name", ""),
            )
    except Exception:
        pass  # Don't fail print start callback if MQTT fails

    # Capture AMS tray remain%, the assignment snapshot, the dispatched plate
    # and mapping, and the seeded tray-change log.
    #
    # Unconditional, for both inventory backends. This only *captures* — the
    # writing is still split, with the internal tracker skipped at completion
    # when Spoolman owns usage. Spoolman's own durable row (#1820) already
    # carries its plate-scoped 3MF figures and stored mapping, but not the
    # tray-change log, and that log is the only record of which spool fed
    # which layers when AMS Filament Backup swaps trays mid-print. Capturing
    # it on one side only would leave Spoolman users with the mid-print
    # restart bug this fixes for everyone else.
    try:
        async with _rt().async_session() as db:
            from backend.app.api.routes.settings import get_setting
            from backend.app.services.usage_tracker import on_print_start as usage_on_print_start

            _spoolman_on = await get_setting(db, "spoolman_enabled")
            await usage_on_print_start(
                printer_id,
                data,
                _rt().printer_manager,
                db=db,
                spoolman_owns_usage=bool(_spoolman_on) and _spoolman_on.lower() == "true",
            )
    except Exception as e:
        logger.warning("Usage tracker on_print_start failed: %s", e)

    # Track if notification was sent (to avoid sending twice)
    notification_sent = False

    # Smart plug automation: turn on plug when print starts
    try:
        async with _rt().async_session() as db:
            await _rt().smart_plug_manager.on_print_start(printer_id, db)
    except Exception as e:
        logger.warning("Smart plug on_print_start failed: %s", e)

    async with _rt().async_session() as db:
        from backend.app.models.printer import Printer
        from backend.app.services.bambu_ftp import list_files_async

        result = await db.execute(select(Printer).where(Printer.id == printer_id))
        printer = result.scalar_one_or_none()

        # Plate detection check - pause if objects detected on build plate
        logger.info(
            f"[PLATE CHECK] printer_id={printer_id}, plate_detection_enabled={printer.plate_detection_enabled if printer else 'NO PRINTER'}"
        )
        if printer and printer.plate_detection_enabled:
            logger.info("[PLATE CHECK] ENTERING plate detection code for printer %s", printer_id)
            # Release the pooled DB connection before the plate-detection camera
            # work (a 2.5s light-settle sleep + FTP/camera capture). Only the
            # printer SELECT has run so far — nothing to persist — so this commit
            # is a data-noop that ends the read transaction and returns the
            # connection to the pool during the I/O (issue #2572). expire_on_commit
            # =False keeps printer.* readable; on_plate_not_empty (rare) and the
            # archive lookups below re-acquire a fresh connection on next execute.
            await db.commit()
            try:
                from backend.app.services.plate_detection import check_plate_empty

                # Build ROI tuple from printer settings if available
                roi = None
                if all(
                    [
                        printer.plate_detection_roi_x is not None,
                        printer.plate_detection_roi_y is not None,
                        printer.plate_detection_roi_w is not None,
                        printer.plate_detection_roi_h is not None,
                    ]
                ):
                    roi = (
                        printer.plate_detection_roi_x,
                        printer.plate_detection_roi_y,
                        printer.plate_detection_roi_w,
                        printer.plate_detection_roi_h,
                    )

                # Auto-turn on chamber light if it's off for better detection
                light_was_off = False
                client = _rt().printer_manager.get_client(printer_id)
                if client and client.state:
                    light_was_off = not client.state.chamber_light
                    if light_was_off:
                        logger.info("[PLATE CHECK] Turning on chamber light for printer %s", printer_id)
                        client.set_chamber_light(True)
                        # Wait for light to physically turn on and camera to adjust exposure
                        await _rt().asyncio.sleep(2.5)

                plate_photo_data = None
                objects_detected = False
                try:
                    logger.info("[PLATE CHECK] Running plate detection for printer %s", printer_id)
                    plate_result = await check_plate_empty(
                        printer_id=printer_id,
                        ip_address=printer.ip_address,
                        access_code=printer.access_code,
                        model=printer.model,
                        include_debug_image=False,
                        external_camera_url=printer.external_camera_url,
                        external_camera_type=printer.external_camera_type,
                        use_external=printer.external_camera_enabled,
                        roi=roi,
                        external_camera_snapshot_url=printer.external_camera_snapshot_url,
                    )

                    objects_detected = not plate_result.needs_calibration and not plate_result.is_empty
                    if objects_detected:
                        # Objects detected - pause the print!
                        logger.warning(
                            f"[PLATE CHECK] Objects detected on plate for printer {printer_id}! "
                            f"Confidence: {plate_result.confidence:.0%}, Diff: {plate_result.difference_percent:.1f}%"
                        )
                        pause_client = _rt().printer_manager.get_client(printer_id)
                        if pause_client:
                            pause_client.pause_print()
                            logger.info("[PLATE CHECK] Print paused for printer %s", printer_id)

                        # Snapshot while the light's still on — restoring it first
                        # would leave the notification with a dark photo.
                        try:
                            plate_photo_data = await _rt()._capture_snapshot_for_notification(
                                printer_id, printer, logger
                            )
                        except Exception as snap_err:
                            logger.warning(
                                "[PLATE CHECK] Failed to capture snapshot for printer %s: %s", printer_id, snap_err
                            )
                finally:
                    # Restore chamber light to original state as soon as the
                    # camera is done with it, whatever happened above.
                    if light_was_off and client:
                        logger.info("[PLATE CHECK] Restoring chamber light to off for printer %s", printer_id)
                        try:
                            client.set_chamber_light(False)
                        except Exception as light_err:
                            logger.warning(
                                "[PLATE CHECK] Failed to restore chamber light for printer %s: %s",
                                printer_id,
                                light_err,
                            )

                if objects_detected:
                    # Send notification about plate not empty
                    await _rt().ws_manager.broadcast(
                        {
                            "type": "plate_not_empty",
                            "printer_id": printer_id,
                            "printer_name": printer.name,
                            "message": f"Objects detected on build plate! Print paused. (Diff: {plate_result.difference_percent:.1f}%)",
                        }
                    )

                    # Also send push notification
                    try:
                        await _rt().notification_service.on_plate_not_empty(
                            printer_id=printer_id,
                            printer_name=printer.name,
                            db=db,
                            difference_percent=plate_result.difference_percent,
                            image_data=plate_photo_data,
                        )
                    except Exception as notif_err:
                        logger.warning("[PLATE CHECK] Failed to send notification: %s", notif_err)
                else:
                    logger.info("[PLATE CHECK] Plate is empty for printer %s, proceeding with print", printer_id)
            except Exception as plate_err:
                # Don't block print on plate detection errors
                logger.warning("[PLATE CHECK] Plate detection failed for printer %s: %s", printer_id, plate_err)

        if not printer:
            logger.info("[CALLBACK] Skipping archive - printer not found in database")
            if not notification_sent:
                await _rt()._send_print_start_notification(printer_id, data, logger=logger)
            return

        if not printer.auto_archive:
            # auto-archive disabled — check if there's an expected print (dispatched
            # by PrintLab via queue/reprint) that already has an archive to promote.
            # If so, fall through to the expected-print handling below so the archive
            # is tracked in _active_prints and usage tracking works at completion.
            _fn = data.get("filename", "")
            _sn = data.get("subtask_name", "")
            _check_keys: list[tuple[int, str]] = []
            if _sn:
                _check_keys += [
                    (printer_id, _sn),
                    (printer_id, f"{_sn}.3mf"),
                    (printer_id, f"{_sn}.gcode.3mf"),
                ]
            if _fn:
                _base_fn = _fn.split("/")[-1] if "/" in _fn else _fn
                _check_keys.append((printer_id, _base_fn))
                _no_archive_base = _base_fn.replace(".gcode", "").replace(".3mf", "")
                _check_keys += [
                    (printer_id, _no_archive_base),
                    (printer_id, f"{_no_archive_base}.3mf"),
                ]

            _has_expected = any(k in _rt()._expected_prints for k in _check_keys)

            if not _has_expected:
                # No expected print — truly external print (started from slicer/touchscreen)
                logger.info("[CALLBACK] Skipping archive - auto_archive: False, no expected print")
                if not notification_sent:
                    _no_archive_creator: int | None = None
                    for _key in _check_keys:
                        _rt()._expected_prints.pop(_key, None)
                        _rt()._expected_print_registered_at.pop(_key, None)
                        popped_creator = _rt()._expected_print_creators.pop(_key, None)
                        if _no_archive_creator is None:
                            _no_archive_creator = popped_creator
                    _creator_data = {"created_by_id": _no_archive_creator} if _no_archive_creator else None
                    await _rt()._send_print_start_notification(printer_id, data, _creator_data, logger)
                return
            else:
                logger.info("[CALLBACK] auto_archive disabled but expected print found — promoting archive")

        # Get the filename and subtask_name
        filename = data.get("filename", "")
        subtask_name = data.get("subtask_name", "")

        # MQTT subtask_id uniquely identifies a print job on the printer. When
        # present, it lets us match an archive across a backend restart (#972):
        # same id → same print → resume the existing row instead of cancelling
        # it and recreating from scratch (which loses started_at). Treat "0"
        # and "" as absent — Bambu reports "0" for non-cloud / local prints.
        raw_mqtt = data.get("raw_data") or {}
        subtask_id = raw_mqtt.get("subtask_id")
        if subtask_id is not None:
            subtask_id = str(subtask_id).strip()
            if subtask_id in ("", "0"):
                subtask_id = None

        logger.info("[CALLBACK] Print start detected - filename: %s, subtask: %s", filename, subtask_name)

        # Skip the printer's own jobs — a calibration run is not a user's print.
        # See is_internal_printer_job for what counts and why both fields are
        # tested; the pressure-advance line reports as a subtask name with no
        # /usr/ path, which the old prefix-only test here missed entirely.
        #
        # No notification either. The event describes the printer calibrating
        # itself, so "Print started" is as wrong as the archive was, and the
        # matching completion is suppressed in on_print_complete for the same
        # reason.
        if is_internal_printer_job(filename, subtask_name):
            logger.info(
                "[CALLBACK] Skipping archive — internal printer job detected: filename=%s, subtask=%s",
                filename,
                subtask_name,
            )
            return

        if not filename and not subtask_name:
            # Send notification without archive data (no filename)
            logger.info("[CALLBACK] Skipping archive - no filename or subtask_name")
            if not notification_sent:
                await _rt()._send_print_start_notification(printer_id, data, logger=logger)
            return

        # Check if this is an expected print from reprint/scheduled
        # Build list of possible keys to check
        expected_keys = []
        if subtask_name:
            expected_keys.append((printer_id, subtask_name))
            expected_keys.append((printer_id, f"{subtask_name}.3mf"))
            expected_keys.append((printer_id, f"{subtask_name}.gcode.3mf"))
        if filename:
            fname = filename.split("/")[-1] if "/" in filename else filename
            expected_keys.append((printer_id, fname))
            # Strip extensions to match
            base = fname.replace(".gcode", "").replace(".3mf", "")
            expected_keys.append((printer_id, base))
            expected_keys.append((printer_id, f"{base}.3mf"))

        expected_archive_id = None
        for key in expected_keys:
            expected_archive_id = _rt()._expected_prints.pop(key, None)
            _rt()._expected_print_registered_at.pop(key, None)
            if expected_archive_id:
                # Clean up other possible keys for this print
                for other_key in expected_keys:
                    _rt()._expected_prints.pop(other_key, None)
                    _rt()._expected_print_registered_at.pop(other_key, None)
                break

        if expected_archive_id:
            # This is a reprint/scheduled print - use existing archive, don't create new one
            logger.info("Using expected archive %s for print (skipping duplicate)", expected_archive_id)
            from backend.app.models.archive import PrintArchive

            result = await db.execute(select(PrintArchive).where(PrintArchive.id == expected_archive_id))
            archive = result.scalar_one_or_none()

            if archive:
                # Update archive status to printing
                archive.status = "printing"
                archive.started_at = _rt().datetime.now(_rt().timezone.utc)

                # The previous run's answer is still on this row and the
                # completion prompt is gated on ``user_verdict is None`` (#1898),
                # so without a reset the second run inherits the first run's
                # verdict: no prompt at all, and a green "good" badge on a run
                # nobody ever judged.
                if archive.confirm_requested:
                    archive.user_verdict = None
                    archive.user_verdict_source = None
                    archive.user_verdict_at = None
                    archive.confirm_token = None
                    archive.confirm_token_used_at = None

                # Reprint of an archive reuses the source row. Without resetting
                # ``timelapse_path`` _scan_for_timelapse_with_retries early-returns
                # ("already has timelapse") and _capture_finish_photo_from_timelapse
                # extracts the *original* print's last frame, which then ships in
                # the completion notification (#1707). Clear the path so the
                # scanner runs fresh; also unlink the old video file so reprints
                # don't accumulate orphans in the archive directory. Photos list
                # is left alone — accumulating one finish photo per run is fine.
                # The print-start baseline (#2704) is stale for the same reason:
                # it describes the printer before the previous run. The capture
                # below overwrites it, but clear it here too so an early failure
                # can't leave the scan diffing against the wrong snapshot.
                archive.timelapse_baseline = None
                stale_timelapse_relpath = archive.timelapse_path
                if stale_timelapse_relpath:
                    archive.timelapse_path = None
                    try:
                        stale_path = (
                            app_settings.base_dir / stale_timelapse_relpath
                        )  # SEC-PATH-OK: timelapse_relpath ist archive.timelapse_path, DB-erzeugt (keinerlei Anfrage-Eingang)
                        if stale_path.is_file():
                            stale_path.unlink()
                            logger.info(
                                "Deleted stale timelapse %s on reprint of archive %s",
                                stale_timelapse_relpath,
                                expected_archive_id,
                            )
                    except OSError as e:
                        logger.warning(
                            "Failed to delete stale timelapse %s on reprint: %s",
                            stale_timelapse_relpath,
                            e,
                        )
                # Persist a restart-stable id so a later restart resumes this
                # archive by subtask_id instead of name-matching + duplicating
                # it (#1485). The printer often hasn't echoed subtask_id back
                # this soon after dispatch, so fall back to the id PrintLab
                # minted when it sent the print command. Scoped to this
                # expected-print branch on purpose: an expected match means
                # PrintLab dispatched this exact print in this process, so the
                # client's last-dispatch id genuinely belongs to it — using it
                # for an externally-started print could mis-tag the archive.
                effective_subtask_id = subtask_id
                if not effective_subtask_id:
                    _client = _rt().printer_manager.get_client(printer_id)
                    _dispatched = getattr(_client, "last_dispatch_subtask_id", None) if _client else None
                    if _dispatched:
                        effective_subtask_id = str(_dispatched).strip() or None
                # Update on first-set OR on reprint (the queue dispatcher mints
                # a fresh subtask_id per dispatch in bambu_mqtt:3647). Skipping
                # the rewrite for reprints leaves the archive holding the FIRST
                # run's id; if MQTT then reconnects mid-print, the reconciler
                # (#1542) compares the stale stored id against the printer's
                # live id, sees a mismatch, and synthesises a bogus PRINT
                # COMPLETE — exactly the false-positive "Print Stopped" reported
                # in #1807. Inequality check preserves the noop-on-stable-push
                # behaviour the earlier `not archive.subtask_id` guard provided.
                if effective_subtask_id and archive.subtask_id != effective_subtask_id:
                    archive.subtask_id = effective_subtask_id
                # #1403 follow-up: VP-queue archives are created with
                # printer_id=None at queue-add time (we don't know which
                # printer will run the job yet). When the print actually
                # starts on a specific printer the expected-archive lookup
                # used to skip this assignment, leaving printer_id=None
                # forever — which then disables the "Scan for timelapse"
                # button in ArchivesPage (gated on !archive.printer_id).
                if archive.printer_id != printer_id:
                    archive.printer_id = printer_id
                await db.commit()

                # Track as active print
                _rt()._active_prints[(printer_id, archive.filename)] = archive.id
                if subtask_name:
                    _rt()._active_prints[(printer_id, f"{subtask_name}.3mf")] = archive.id

                # Start timelapse session if external camera is enabled (#1353).
                # Queue / VP-dispatched prints land here in the expected-archive
                # branch and used to skip start_session entirely — frames were
                # never captured and the post-print stitch silently returned None.
                _rt()._maybe_start_layer_timelapse(printer, printer_id, archive.id)

                # Inject ams_mapping into usage tracker session — the session was created
                # before expected-print promotion, so it may have ams_mapping=None when
                # the MQTT request topic subscription failed (common on P1S/A1).
                _stored_map = _rt()._print_ams_mappings.get(expected_archive_id)
                _stored_plate_id = _rt()._print_plate_ids.get(expected_archive_id)
                if _stored_map or _stored_plate_id is not None:
                    try:
                        from backend.app.services.usage_tracker import _active_sessions

                        _ut_session = _active_sessions.get(printer_id)
                        if _ut_session and _stored_map and not _ut_session.ams_mapping:
                            _ut_session.ams_mapping = _stored_map
                            logger.info("[CALLBACK] Injected ams_mapping into usage tracker session: %s", _stored_map)
                        # plate_id injection covers direct-Print of plate N of a multi-plate
                        # 3MF — queue prints already capture it via the on_print_start queue
                        # lookup, but direct-Print never goes through the queue (#1697).
                        if _ut_session and _stored_plate_id is not None and _ut_session.plate_id is None:
                            _ut_session.plate_id = _stored_plate_id
                            logger.info("[CALLBACK] Injected plate_id into usage tracker session: %s", _stored_plate_id)
                    except Exception:
                        logger.debug("Could not attach the plate id to the usage-tracker session", exc_info=True)
                # Set up energy tracking (#941: persist start on archive row)
                await _rt()._record_energy_start(archive, printer_id, db, context="expected-print")

                await _rt().ws_manager.send_archive_updated(
                    {
                        "id": archive.id,
                        "status": "printing",
                    }
                )

                # Send notification with archive data (reprint/scheduled)
                if not notification_sent:
                    # Use archive's created_by_id; fall back to the creator registered via
                    # register_expected_print (handles library-file-based queue items where
                    # the freshly-created archive has no created_by_id yet).
                    # Pop ALL matching keys so no stale entries remain in the dict.
                    fallback_creator = None
                    for key in expected_keys:
                        popped = _rt()._expected_print_creators.pop(key, None)
                        if fallback_creator is None:
                            fallback_creator = popped
                    archive_data = {
                        "print_time_seconds": archive.print_time_seconds,
                        "created_by_id": archive.created_by_id or fallback_creator,
                    }
                    await _rt()._send_print_start_notification(printer_id, data, archive_data, logger)

                # Extract printable objects from the archived 3MF file
                _rt()._load_objects_from_archive(archive, printer_id, logger)

                # Store Spoolman tracking data for per-filament usage reporting
                try:
                    await _rt()._store_spoolman_print_data(
                        printer_id,
                        archive.id,
                        archive.file_path,
                        db,
                        _rt().printer_manager,
                        ams_mapping=_get_start_ams_mapping(data, archive.id),
                        plate_id=_rt()._get_start_plate_id(archive.id),
                    )
                except Exception as e:
                    logger.warning("[SPOOLMAN] Failed to store tracking data: %s", e)

                # Capture timelapse file baseline for snapshot-diff on completion
                # (mirrors the new-archive branch). Queue / VP-dispatched prints
                # hit this branch — without the baseline the completion-time scan
                # falls into its "take baseline now" fallback, which snapshots
                # AFTER the new MP4 already exists and never matches a diff
                # (#1403 follow-up — see pwostran's 2026-05-18 support bundle).
                await _rt()._capture_timelapse_baseline_at_start(printer, printer_id, logger, archive_id=archive.id)

            return  # Skip creating a new archive

        # Check if there's already a "printing" archive for this printer/file
        # This prevents duplicates when backend restarts during an active print
        from backend.app.models.archive import PrintArchive

        existing_archive: PrintArchive | None = None

        # Preferred match: subtask_id equality. MQTT reports the same subtask_id
        # across a backend restart for the same print, so this is the most
        # reliable way to reattach. We also accept a previously stale-cancelled
        # archive here so users upgrading mid-print get revived when the row
        # their earlier PrintLab version wrongly cancelled reappears (#972).
        if subtask_id:
            by_id = await db.execute(
                select(PrintArchive)
                .where(PrintArchive.printer_id == printer_id)
                .where(PrintArchive.subtask_id == subtask_id)
                .where(PrintArchive.status.in_(["printing", "cancelled"]))
                .order_by(PrintArchive.created_at.desc())
                .limit(1)
            )
            candidate = by_id.scalar_one_or_none()
            if candidate and (candidate.status == "printing" or (candidate.failure_reason or "").startswith("Stale")):
                existing_archive = candidate

        # Fallback match: name-based lookup. Kept as-is for prints whose
        # subtask_id is missing ("0" / local / non-cloud prints).
        if existing_archive is None:
            check_name = subtask_name or filename.split("/")[-1].replace(".gcode", "").replace(".3mf", "")
            existing = await db.execute(
                select(PrintArchive)
                .where(PrintArchive.printer_id == printer_id)
                .where(PrintArchive.status == "printing")
                .where(
                    or_(
                        PrintArchive.print_name == check_name,
                        PrintArchive.filename.in_(
                            [
                                f"{check_name}.3mf",
                                f"{check_name}.gcode.3mf",
                            ]
                        ),
                    )
                )
                .order_by(PrintArchive.created_at.desc())
                .limit(1)
            )
            existing_archive = existing.scalar_one_or_none()

        if existing_archive:
            # subtask_id match → always resume, regardless of age. Same print,
            # just a backend restart. Revive if it was previously stale-cancelled.
            subtask_match = bool(subtask_id and existing_archive.subtask_id == subtask_id)

            if subtask_match:
                if existing_archive.status == "cancelled":
                    logger.warning(
                        "Reviving stale-cancelled archive %s — matching subtask_id %s confirms same print (#972)",
                        existing_archive.id,
                        subtask_id,
                    )
                    existing_archive.status = "printing"
                    existing_archive.failure_reason = None
                    await db.commit()
                else:
                    logger.info("Resuming archive %s on subtask_id match (%s)", existing_archive.id, subtask_id)
                _rt()._active_prints[(printer_id, existing_archive.filename)] = existing_archive.id
                if existing_archive.energy_start_kwh is None:
                    await _rt()._record_energy_start(existing_archive, printer_id, db, context="subtask-resume")
                if not notification_sent:
                    archive_data = {
                        "print_time_seconds": existing_archive.print_time_seconds,
                        "created_by_id": existing_archive.created_by_id,
                    }
                    await _rt()._send_print_start_notification(printer_id, data, archive_data, logger)
                _rt()._load_objects_from_archive(existing_archive, printer_id, logger)
                return

            # Name-match only (no subtask_id to anchor on): decide resume vs.
            # stale from the printer's *current* progress, not wall-clock age.
            # A genuinely long print used to trip a blind 4h cutoff and have its
            # live archive cancelled + duplicated on every backend restart
            # (#1485). If the printer reports real progress, this name-matched
            # 'printing' archive IS that ongoing print — resume it whatever its
            # age. Only treat it as a stale leftover when the printer clearly
            # shows a different, freshly-started print: near-0% progress on an
            # archive far too old to still be at 0%. Unknown progress (printer
            # not connected) never cancels — resuming is the safe default.
            archive_age = _rt().datetime.now(_rt().timezone.utc) - existing_archive.created_at.replace(
                tzinfo=_rt().timezone.utc
            )
            live_status = _rt().printer_manager.get_status(printer_id)
            live_progress = getattr(live_status, "progress", None) if live_status else None
            looks_stale = (
                live_progress is not None and live_progress < 1.0 and archive_age.total_seconds() > 2 * 60 * 60
            )
            if looks_stale:
                logger.warning(
                    f"Found stale 'printing' archive {existing_archive.id} (age: {archive_age}, "
                    f"printer progress {live_progress:.0f}%) — marking cancelled and creating new archive"
                )
                existing_archive.status = "cancelled"
                # Canonical key, not a sentence (issue #2974). "No status update
                # received" is what both stale paths actually observed; which of
                # the two it was is already carried by ``status`` -- cancelled
                # here, the reconciled outcome at the reconnect site -- so one
                # key loses no information and gives the Statistics breakdown a
                # single bucket instead of two untranslatable prose strings.
                existing_archive.failure_reason = "noStatusUpdate"
                await db.commit()
                # Fall through to create new archive (don't return)
            else:
                logger.info(
                    f"Skipping duplicate - already have printing archive {existing_archive.id} for {check_name}"
                )
                # Track this as the active print
                _rt()._active_prints[(printer_id, existing_archive.filename)] = existing_archive.id
                # Attach subtask_id retroactively so future restarts can resume.
                # Compare for inequality (not "is empty") to also pick up reprint
                # dispatches that mint a fresh id — see #1807 for the bogus
                # "Print Stopped" the strict-empty guard caused on reconnect.
                if subtask_id and existing_archive.subtask_id != subtask_id:
                    existing_archive.subtask_id = subtask_id
                    await db.commit()
                # Also set up energy tracking if not already tracked (#941: persisted column)
                if existing_archive.energy_start_kwh is None:
                    await _rt()._record_energy_start(existing_archive, printer_id, db, context="existing-printing")
                # Send notification with archive data (existing archive)
                if not notification_sent:
                    archive_data = {
                        "print_time_seconds": existing_archive.print_time_seconds,
                        "created_by_id": existing_archive.created_by_id,
                    }
                    await _rt()._send_print_start_notification(printer_id, data, archive_data, logger)
                # Extract printable objects from the archived 3MF file
                _rt()._load_objects_from_archive(existing_archive, printer_id, logger)
                return

        # Build list of possible 3MF filenames to try
        possible_names = []

        # Bambu printers typically store files as "Name.gcode.3mf"
        # The subtask_name is usually the best source for the filename
        if subtask_name:
            # Try common Bambu naming patterns
            possible_names.append(f"{subtask_name}.gcode.3mf")
            possible_names.append(f"{subtask_name}.3mf")

        # Try original filename with .3mf extension
        if filename:
            # Extract just the filename part, not the full path
            fname = filename.split("/")[-1] if "/" in filename else filename
            if fname.endswith(".3mf"):
                possible_names.append(fname)
            elif fname.endswith(".gcode"):
                base = fname.rsplit(".", 1)[0]
                possible_names.append(f"{base}.gcode.3mf")
                possible_names.append(f"{base}.3mf")
            else:
                possible_names.append(f"{fname}.gcode.3mf")
                possible_names.append(f"{fname}.3mf")

        # Also try with spaces converted to underscores (Bambu Studio may normalize filenames)
        space_variants = []
        for name in possible_names:
            if " " in name:
                space_variants.append(name.replace(" ", "_"))
        possible_names.extend(space_variants)

        # Remove duplicates while preserving order
        seen = set()
        possible_names = [x for x in possible_names if not (x in seen or seen.add(x))]

        logger.info("Trying filenames: %s", possible_names)

        # Release the pooled DB connection before the 3MF FTP download. Reaching
        # here means none of the expected-/existing-archive write branches ran
        # (they all return earlier) — only SELECTs have executed on this path, so
        # this commit persists nothing; it ends the read transaction so the
        # connection returns to the pool during the download. That download tries
        # up to five remote paths per candidate filename with retry/backoff and
        # can run for minutes under FTP contention; holding the session across it
        # pinned one pooled connection idle-in-transaction (issue #2572). No DB
        # work runs during the download — the new-archive writes below re-acquire
        # a fresh connection, and expire_on_commit=False keeps printer.* readable.
        await db.commit()

        # Try to find and download the 3MF file
        temp_path = None
        downloaded_filename = None

        # Cache check: cover endpoint may have already pulled this 3MF during
        # the print (frontend opens the card and shows the thumbnail) — reuse
        # that file instead of re-downloading 36MB over the same FTP link that
        # just served it (#972). The cache keys on a normalized filename so
        # variants like "X", "X.3mf", "X.gcode.3mf" all collapse to one entry.
        for try_filename in possible_names:
            if not try_filename.endswith(".3mf"):
                continue
            cached = _rt().get_cached_3mf(printer_id, try_filename)
            if cached:
                logger.info("Reusing cached 3MF from %s (avoided duplicate FTP)", cached)
                temp_path = cached
                downloaded_filename = try_filename
                break

        # Does this printer keep the sliced file somewhere FTPS can reach? On
        # H2-series and P2S the answer is routinely no — the file stays on
        # internal eMMC and port 990 only ever serves external storage — and
        # then the whole sweep below (six filenames x five directories x four
        # retries, then the directory walk) is ~110 connections that cannot
        # succeed. Skip it and say why (#2780).
        storage = print_file_reachable_over_ftp(_rt().printer_manager.get_status(printer_id))

        # Set when a lookup is abandoned because the printer's FTPS cool-off is
        # running rather than because the file is somewhere unreachable. The
        # distinction is the whole of #2957: one is permanent, the other clears
        # in minutes with the file still sitting on the printer.
        blocked_by_ftps_cooloff = False

        # Set when a probe reached the printer and still came back without the
        # file -- a timeout mid-transfer, a refused connection, anything that is
        # not a clean "not here". A 550 raises FileNotOnPrinterError and is
        # caught by name below, so a file that genuinely is not on the card
        # leaves this False and schedules nothing. Anything else means the
        # transfer, not the file, is what failed, and that does not last (#3063).
        ftp_transfer_failed = False

        # The print's name, for a fallback archive whose `subtask_name` the
        # plate guard below had to disown. Display only, and deliberately kept
        # apart from `subtask_name`: that variable is what every file lookup
        # here is built from, and once a name has been shown to fetch another
        # plate's 3MF it must not key `_active_prints` either, or the cover
        # endpoint hands the same contradicted file to
        # `_recover_fallback_archive` and fills the row in with it (#3126).
        display_name_after_plate_reject: str | None = None

        # Get FTP retry settings
        ftp_retry_enabled, ftp_retry_count, ftp_retry_delay, ftp_timeout = await _rt().get_ftp_retry_settings()

        # ...but "the printer put it on eMMC" is where it went, not whether we
        # can read it. An H2D with a card in mirrors the job to /cache and
        # serves it happily, and skipping on the URL alone cost that reporter
        # every archive for two days (#2856). So ask the printer instead of
        # guessing: the dispatch named the exact file, which is one connection
        # walking five paths rather than the sweep's ~110. Only when the probe
        # comes back empty does the verdict's reason stand.
        if not storage.reachable and not downloaded_filename and storage.probe_filename:
            if _rt().ftps_handshake_blocked(printer.ip_address):
                # Deliberately NOT recorded as a cool-off give-up. This branch
                # only runs on an unreachable verdict, and that verdict is the
                # honest, permanent reason the archive is empty — the probe was
                # a long shot on top of it. Blaming the cool-off here would
                # schedule a retry for a file sitting on internal eMMC, which is
                # the sweep #2780 removed (#2957).
                logger.debug(
                    "Not probing for %s on printer %s: its file service is not answering over TLS",
                    storage.probe_filename,
                    printer_id,
                )
            else:
                probe_path = app_settings.archive_dir / "temp" / storage.probe_filename
                probe_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    probe_hit = await _rt().download_file_try_paths_async(
                        printer.ip_address,
                        printer.access_code,
                        ftp_probe_paths(storage.probe_filename),
                        probe_path,
                        socket_timeout=ftp_timeout,
                        printer_model=printer.model,
                    )
                except Exception as e:
                    logger.debug("3MF probe for %s failed: %s", storage.probe_filename, e)
                    probe_hit = False
                if probe_hit:
                    downloaded_filename = storage.probe_filename
                    temp_path = probe_path
                    _rt().cache_3mf_download(printer_id, downloaded_filename, probe_path)
                    # Naming the path, not just the file: a printer that keeps
                    # uploads around for weeks can serve a same-named copy of an
                    # earlier slice, and without the directory in the log that
                    # mismatch is invisible rather than merely rare (#1820).
                    logger.info(
                        "Found %s at %s over FTPS for printer %s even though the printer reported %s",
                        downloaded_filename,
                        probe_hit,
                        printer_id,
                        storage.reason,
                    )

        if not storage.reachable and not downloaded_filename:
            # Same opening words whether or not a probe ran, because that is
            # the phrase support asks people to grep for — only the tail says
            # which of the two happened.
            logger.info(
                "Skipping the 3MF lookup for printer %s: %s — %s",
                printer_id,
                storage.reason,
                "no copy of it on external storage either"
                if storage.probe_filename
                else "the print file is not on storage PrintLab can read over FTPS, so no path would find it",
            )

        for try_filename in possible_names if not downloaded_filename and storage.reachable else []:
            if not try_filename.endswith(".3mf"):
                continue

            # Root (/) is where BambuStudio/OrcaSlicer uploads land on A1/P1-series
            # printers, so try it first — deferring it to last cost #972's reporter
            # ~48 minutes of retries on /cache//model//data//data/Metadata before
            # landing on the path that actually had the file.
            remote_paths = [
                f"/{try_filename}",
                f"/cache/{try_filename}",
                f"/model/{try_filename}",
                f"/data/{try_filename}",
                f"/data/Metadata/{try_filename}",
            ]

            temp_path = app_settings.archive_dir / "temp" / try_filename
            temp_path.parent.mkdir(parents=True, exist_ok=True)

            for remote_path in remote_paths:
                if _rt().ftps_handshake_blocked(printer.ip_address):
                    # The printer's FTPS service is not completing a TLS
                    # handshake, so it has no path we could reach — walking the
                    # remaining candidates only re-runs the same failure
                    # (#2780). Fall through to the no-3MF archive now.
                    #
                    # Remember *why*, though. This is the one give-up that is
                    # temporary: the cool-off clears in minutes and the file was
                    # on the printer the whole time. The fallback archive is
                    # stamped with it so a retry can be scheduled, and so the
                    # Archives banner stops blaming storage (#2957).
                    blocked_by_ftps_cooloff = True
                    logger.warning(
                        "Giving up on the 3MF for printer %s: its file service is not answering over TLS",
                        printer_id,
                    )
                    break
                logger.debug("Trying FTP download: %s", remote_path)
                try:
                    if ftp_retry_enabled:
                        downloaded = await _rt().with_ftp_retry(
                            _rt().download_file_async,
                            printer.ip_address,
                            printer.access_code,
                            remote_path,
                            temp_path,
                            timeout=ftp_timeout,
                            socket_timeout=ftp_timeout,
                            printer_model=printer.model,
                            max_retries=ftp_retry_count,
                            retry_delay=ftp_retry_delay,
                            operation_name=f"Download 3MF from {remote_path}",
                            cooloff_ip=printer.ip_address,
                            non_retry_exceptions=(FileNotOnPrinterError,),
                        )
                    else:
                        downloaded = await _rt().download_file_async(
                            printer.ip_address,
                            printer.access_code,
                            remote_path,
                            temp_path,
                            timeout=ftp_timeout,
                            socket_timeout=ftp_timeout,
                            printer_model=printer.model,
                        )
                    if downloaded:
                        downloaded_filename = try_filename
                        logger.info("Downloaded: %s", remote_path)
                        # Populate shared cache so the cover endpoint (if it
                        # runs next) doesn't refetch the same 36MB over FTP.
                        _rt().cache_3mf_download(printer_id, try_filename, temp_path)
                        break
                    # with_ftp_retry returns None once it has spent its budget,
                    # and download_file_async returns False on a timeout, so an
                    # exhausted transfer arrives here rather than as an
                    # exception (#3063).
                    ftp_transfer_failed = True
                except FileNotOnPrinterError:
                    # 550 — file isn't at this path. Advance to next candidate
                    # without burning the retry budget.
                    logger.debug("3MF not at %s (550), trying next path", remote_path)
                except Exception as e:
                    ftp_transfer_failed = True
                    logger.debug("FTP download failed for %s: %s", remote_path, e)

            if downloaded_filename or _rt().ftps_handshake_blocked(printer.ip_address):
                break

        # If still not found, try listing directories to find matching file
        # Different printer models use different directory structures. Skipped
        # when the printer's FTPS handshake is failing — the directory walk is
        # five more connections that cannot get further than the download did.
        if (
            not downloaded_filename
            and storage.reachable
            and (filename or subtask_name)
            and not _rt().ftps_handshake_blocked(printer.ip_address)
        ):
            search_term = (subtask_name or filename).lower().replace(".gcode", "").replace(".3mf", "")
            logger.info("Direct FTP download failed, searching directories for '%s'", search_term)
            search_dirs = ["/cache", "/model", "/data", "/data/Metadata", "/"]
            for search_dir in search_dirs:
                if downloaded_filename:
                    break
                try:
                    dir_files = await list_files_async(
                        printer.ip_address, printer.access_code, search_dir, printer_model=printer.model
                    )
                    threemf_files = [f.get("name") for f in dir_files if f.get("name", "").endswith(".3mf")]
                    if threemf_files:
                        logger.info(
                            f"Found {len(threemf_files)} 3MF files in {search_dir}: {threemf_files[:5]}{'...' if len(threemf_files) > 5 else ''}"
                        )
                    for f in dir_files:
                        if f.get("is_directory"):
                            continue
                        fname = f.get("name", "")
                        # Normalize both for comparison (spaces and underscores are equivalent)
                        fname_normalized = fname.lower().replace(" ", "_")
                        search_normalized = search_term.replace(" ", "_")
                        if fname.endswith(".3mf") and search_normalized in fname_normalized:
                            logger.info("Found matching file in %s: %s", search_dir, fname)
                            temp_path = app_settings.archive_dir / "temp" / fname
                            temp_path.parent.mkdir(parents=True, exist_ok=True)
                            remote_full_path = posixpath.join(search_dir, fname)
                            if ftp_retry_enabled:
                                downloaded = await _rt().with_ftp_retry(
                                    _rt().download_file_async,
                                    printer.ip_address,
                                    printer.access_code,
                                    remote_full_path,
                                    temp_path,
                                    timeout=ftp_timeout,
                                    socket_timeout=ftp_timeout,
                                    printer_model=printer.model,
                                    max_retries=ftp_retry_count,
                                    retry_delay=ftp_retry_delay,
                                    operation_name=f"Download 3MF from {remote_full_path}",
                                    cooloff_ip=printer.ip_address,
                                )
                            else:
                                downloaded = await _rt().download_file_async(
                                    printer.ip_address,
                                    printer.access_code,
                                    remote_full_path,
                                    temp_path,
                                    timeout=ftp_timeout,
                                    socket_timeout=ftp_timeout,
                                    printer_model=printer.model,
                                )
                            if downloaded:
                                downloaded_filename = fname
                                logger.info("Found and downloaded from %s: %s", search_dir, fname)
                                _rt().cache_3mf_download(printer_id, fname, temp_path)
                                break
                            # The listing named the file, so it is on the card;
                            # only the transfer failed (#3063).
                            ftp_transfer_failed = True
                except Exception as e:
                    logger.debug("Failed to list %s: %s", search_dir, e)

        # Validate the downloaded 3MF actually matches the plate that's running
        # (#1204): subtask_name lags across consecutive plates of the same model,
        # so the first FTP candidate (built from subtask_name) can land on the
        # previous plate's still-resident upload. Cross-check the slice_info
        # plate index against the plate parsed from gcode_file (always fresh —
        # it's the field whose change triggered this callback).
        if downloaded_filename and temp_path:
            expected_plate = parse_plate_id(filename)
            actual_plate = _rt().peek_plate_index_in_3mf(temp_path) if expected_plate is not None else None
            if expected_plate is not None and actual_plate is not None and actual_plate != expected_plate:
                logger.warning(
                    "[CALLBACK] 3MF plate mismatch: downloaded %s reports plate %s but printer is "
                    "running plate %s — subtask_name=%r appears stale, retrying with corrected name",
                    downloaded_filename,
                    actual_plate,
                    expected_plate,
                    subtask_name,
                )
                corrected_subtask = swap_plate_suffix(subtask_name, expected_plate)
                retry_succeeded = False
                if corrected_subtask and corrected_subtask != subtask_name:
                    for try_filename in (f"{corrected_subtask}.gcode.3mf", f"{corrected_subtask}.3mf"):
                        retry_temp_path = app_settings.archive_dir / "temp" / try_filename
                        retry_temp_path.parent.mkdir(parents=True, exist_ok=True)
                        for remote_path in (
                            f"/{try_filename}",
                            f"/cache/{try_filename}",
                            f"/model/{try_filename}",
                            f"/data/{try_filename}",
                            f"/data/Metadata/{try_filename}",
                        ):
                            try:
                                if ftp_retry_enabled:
                                    downloaded = await _rt().with_ftp_retry(
                                        _rt().download_file_async,
                                        printer.ip_address,
                                        printer.access_code,
                                        remote_path,
                                        retry_temp_path,
                                        timeout=ftp_timeout,
                                        socket_timeout=ftp_timeout,
                                        printer_model=printer.model,
                                        max_retries=ftp_retry_count,
                                        retry_delay=ftp_retry_delay,
                                        operation_name=f"Re-download 3MF from {remote_path}",
                                        cooloff_ip=printer.ip_address,
                                        non_retry_exceptions=(FileNotOnPrinterError,),
                                    )
                                else:
                                    downloaded = await _rt().download_file_async(
                                        printer.ip_address,
                                        printer.access_code,
                                        remote_path,
                                        retry_temp_path,
                                        timeout=ftp_timeout,
                                        socket_timeout=ftp_timeout,
                                        printer_model=printer.model,
                                    )
                                if downloaded and _rt().peek_plate_index_in_3mf(retry_temp_path) == expected_plate:
                                    logger.info(
                                        "[CALLBACK] Re-download succeeded with corrected name %s "
                                        "(plate %s) — replacing wrong file",
                                        try_filename,
                                        expected_plate,
                                    )
                                    try:
                                        temp_path.unlink(missing_ok=True)
                                    except OSError:
                                        pass
                                    temp_path = retry_temp_path
                                    downloaded_filename = try_filename
                                    subtask_name = corrected_subtask
                                    _rt().cache_3mf_download(printer_id, try_filename, temp_path)
                                    retry_succeeded = True
                                    break
                                elif downloaded:
                                    # Wrong plate again — discard and keep trying
                                    try:
                                        retry_temp_path.unlink(missing_ok=True)
                                    except OSError:
                                        pass
                            except FileNotOnPrinterError:
                                continue
                            except Exception as e:
                                logger.debug("Re-download failed for %s: %s", remote_path, e)
                        if retry_succeeded:
                            break
                # If the retry didn't find a matching file, drop the wrong 3MF
                # so the no-3MF fallback below creates an archive whose name
                # at least reflects the right plate.
                if not retry_succeeded:
                    logger.warning(
                        "[CALLBACK] Could not re-download correct plate %s — falling back to no-3MF archive",
                        expected_plate,
                    )
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    temp_path = None
                    downloaded_filename = None
                    # Whatever the sweep's transport did earlier, it is not why
                    # this archive ends up empty: a 3MF downloaded fine, it was
                    # just the wrong plate. Retrying would re-fetch that same
                    # contradicted file under the same stale names and hand it
                    # to _recover_fallback_archive, which checks that a
                    # candidate is a readable 3MF but not which plate it is --
                    # so the row would be filled in with another plate's
                    # filament and cost, the exact swap #2957 removed (#3063).
                    ftp_transfer_failed = False
                    # Disown the name for *lookups*: it has just been shown to
                    # fetch another plate's 3MF, and it keys `_active_prints`
                    # below, where the cover endpoint's own download of that
                    # same name would find this archive and fill it in with the
                    # file we are discarding here.
                    #
                    # Keep it for the *title*, which is a separate question.
                    # ``swap_plate_suffix`` returns None both for a name that
                    # carries no "- Plate N" / "_plate_N" suffix and for no
                    # name at all, and those are not the same situation: a name
                    # without a suffix holds no stale plate number to be wrong
                    # about. Blanking both uses at once dropped the project
                    # name too, and the row fell through to the gcode_file path
                    # titled "plate_1" though the real name was in hand.
                    # #1204's own premise is consecutive plates *of the same
                    # model*, so the project part is right either way (#3126).
                    display_name_after_plate_reject = corrected_subtask or subtask_name or None
                    subtask_name = corrected_subtask or ""

        if not downloaded_filename or not temp_path:
            logger.warning("Could not find 3MF file for print: %s", filename or subtask_name)
            # Create a fallback archive without 3MF data so the print is still tracked
            # This commonly happens with P1S/A1 printers where FTP has file size limitations
            try:
                from backend.app.models.archive import PrintArchive

                # Why the card is empty. The two temporary causes outrank the
                # storage verdict because they say the sweep never got a fair
                # answer: a cool-off skipped it at the transport, and a failed
                # transfer reached the printer but never finished. Either way
                # the file is still on the card, so reporting where the printer
                # files its jobs would describe a setting that is not the
                # problem (#2957, #3063).
                if blocked_by_ftps_cooloff:
                    no_3mf_reason = REASON_FTPS_COOLOFF
                elif storage.reachable and ftp_transfer_failed:
                    no_3mf_reason = REASON_FTP_TRANSFER_FAILED
                else:
                    no_3mf_reason = storage.reason

                # Derive print name from subtask_name or filename. The
                # plate guard's disowned name comes second: it is a real name
                # for a real print, and only the gcode_file path is left
                # otherwise -- which titles the row "plate_1" (#3126).
                print_name = subtask_name or display_name_after_plate_reject or filename
                if print_name:
                    # Clean up the name (remove extensions, path parts)
                    print_name = print_name.split("/")[-1]
                    print_name = print_name.replace(".gcode.3mf", "").replace(".gcode", "").replace(".3mf", "")
                else:
                    print_name = "Unknown Print"

                # Recover estimated print time from MQTT (best-effort for notifications)
                fallback_print_time = None
                mqtt_remaining = data.get("remaining_time")
                if mqtt_remaining and isinstance(mqtt_remaining, (int, float)) and mqtt_remaining > 0:
                    fallback_print_time = int(mqtt_remaining)
                if fallback_print_time is None:
                    mc_remaining = (data.get("raw_data") or {}).get("mc_remaining_time")
                    if mc_remaining and isinstance(mc_remaining, (int, float)) and mc_remaining > 0:
                        fallback_print_time = int(mc_remaining * 60)

                # Best-effort filament metadata from MQTT — see
                # _extract_filament_data_from_mqtt. Without this the fallback
                # archive's filament fields stayed NULL even though the AMS
                # state at print start was sitting right there in `data`.
                # The slicer's ams_mapping (when present) narrows the result
                # to slots actually used by the print (#1533).
                mqtt_filament_meta = _extract_filament_data_from_mqtt(data, _get_start_ams_mapping(data, None))

                # Create minimal archive entry
                fallback_archive = PrintArchive(
                    printer_id=printer_id,
                    filename=filename or f"{print_name}.3mf",
                    file_path="",  # Empty - no 3MF file available
                    file_size=0,
                    print_name=print_name,
                    print_time_seconds=fallback_print_time,
                    status="printing",
                    started_at=_rt().datetime.now(_rt().timezone.utc),
                    subtask_id=subtask_id,
                    confirm_requested=await _rt()._ask_outcome_for_external_print(db, printer_id, subtask_name),
                    filament_type=mqtt_filament_meta.get("filament_type"),
                    filament_color=mqtt_filament_meta.get("filament_color"),
                    extra_data={
                        "no_3mf_available": True,
                        # Why the card is empty, when we know -- see above. The
                        # banner reads this to stop telling H2/P2 owners to
                        # switch on a setting that is already on and would not
                        # have helped (#2780).
                        "no_3mf_reason": no_3mf_reason,
                        "original_subtask": subtask_name or display_name_after_plate_reject or "",
                        "_print_data": data,
                    },
                )

                db.add(fallback_archive)
                await db.commit()
                await db.refresh(fallback_archive)

                logger.info("Created fallback archive %s for %s (no 3MF available)", fallback_archive.id, print_name)

                _rt()._maybe_start_layer_timelapse(printer, printer_id, fallback_archive.id)

                # Track as active print
                _rt()._active_prints[(printer_id, fallback_archive.filename)] = fallback_archive.id
                if filename:
                    _rt()._active_prints[(printer_id, filename)] = fallback_archive.id
                if subtask_name:
                    _rt()._active_prints[(printer_id, f"{subtask_name}.3mf")] = fallback_archive.id
                    _rt()._active_prints[(printer_id, subtask_name)] = fallback_archive.id

                # Record starting energy if smart plug available (#941: persisted column)
                await _rt()._record_energy_start(fallback_archive, printer_id, db, context="fallback")

                # Send WebSocket notification
                await _rt().ws_manager.send_archive_created(
                    {
                        "id": fallback_archive.id,
                        "printer_id": fallback_archive.printer_id,
                        "filename": fallback_archive.filename,
                        "print_name": fallback_archive.print_name,
                        "status": fallback_archive.status,
                    }
                )

                # MQTT relay - publish archive created
                try:
                    await _rt().mqtt_relay.on_archive_created(
                        archive_id=fallback_archive.id,
                        print_name=fallback_archive.print_name,
                        printer_name=printer.name,
                        status=fallback_archive.status,
                    )
                except Exception:
                    pass  # Don't fail if MQTT fails

                # Store Spoolman tracking data (may not work for fallback since no 3MF)
                try:
                    await _rt()._store_spoolman_print_data(
                        printer_id,
                        fallback_archive.id,
                        fallback_archive.file_path,
                        db,
                        _rt().printer_manager,
                        ams_mapping=_get_start_ams_mapping(data, fallback_archive.id),
                        plate_id=_rt()._get_start_plate_id(fallback_archive.id),
                    )
                except Exception as e:
                    logger.debug("[SPOOLMAN] Could not store tracking for fallback archive: %s", e)

                # Both temporary give-ups are worth coming back for, and for
                # the same reason: the file is on the printer and the last look
                # failed at the transport rather than finding nothing. One waits
                # out the handshake block (#2957), the other waits for the
                # printer to stop being busy (#3063). Deliberately not scheduled
                # for a storage verdict: a file on internal eMMC will not appear
                # at any FTPS path however long we wait, and retrying it is
                # exactly the sweep #2780 removed.
                if no_3mf_reason in (REASON_FTPS_COOLOFF, REASON_FTP_TRANSFER_FAILED) and possible_names:
                    # `possible_names`, not the raw MQTT strings: it is the exact
                    # list this flow just tried, already stripped of any path
                    # (`filename` arrives as "/data/Metadata/plate_1.gcode" on
                    # some firmware) and deduped.
                    _rt()._schedule_fallback_3mf_retry(
                        printer_id=printer_id,
                        archive_id=fallback_archive.id,
                        filenames=list(possible_names),
                        reason=no_3mf_reason,
                    )

                # Send notification without archive data (file not found)
                if not notification_sent:
                    await _rt()._send_print_start_notification(printer_id, data, logger=logger)

                # The same baseline the other two on_print_start branches take
                # (#2704), and last for the same reason they are: it lists the
                # printer's timelapse directory, so a slow card must not delay
                # the _active_prints registration, the energy reading, the
                # archive-created event or the start notification above it.
                #
                # This branch never took one, so every no-3MF archive reached
                # completion with no baseline in memory and none on the row, and
                # the completion scan fell into its "snapshot now" fallback --
                # which runs after the printer has written the video, so the new
                # file landed inside the baseline and no diff ever matched
                # (#2957 follow-up).
                #
                # Skipped when the FTPS cool-off is what produced this fallback:
                # the listing needs the same connection that just failed, so it
                # could only record that the card was unreadable. The scan
                # handles that case by refusing to choose between candidates.
                if not blocked_by_ftps_cooloff:
                    await _rt()._capture_timelapse_baseline_at_start(
                        printer, printer_id, logger, archive_id=fallback_archive.id
                    )
                return
            except Exception as e:
                logger.error("Failed to create fallback archive: %s", e)
                # Send notification without archive data (file not found)
                if not notification_sent:
                    await _rt()._send_print_start_notification(printer_id, data, logger=logger)
                return

        try:
            # Archive the file with status "printing"
            service = _rt().ArchiveService(db)
            archive = await service.archive_print(
                printer_id=printer_id,
                source_file=temp_path,
                print_data={**data, "status": "printing"},
                subtask_id=subtask_id,
            )

            if archive:
                # Ask-for-outcome for a print PrintLab did not dispatch (#1898).
                # Set on the row rather than passed to archive_print, which also
                # serves the queue dispatcher — there the queue item decides.
                # Guarded because this branch has no ``except``: an unhandled
                # write error would take the _active_prints registration, the
                # start notification, the energy reading and the timelapse
                # baseline below it with it, and a missing prompt is by far the
                # cheaper failure.
                archive_id = archive.id
                try:
                    if await _rt()._ask_outcome_for_external_print(db, printer_id, subtask_name):
                        archive.confirm_requested = True
                        await db.commit()
                except Exception as e:
                    logger.warning("Could not flag archive %s for the outcome prompt: %s", archive_id, e)
                    # The rollback expires every loaded object, and on an async
                    # session reading one afterwards raises instead of
                    # reloading, so the two this branch goes on to use are
                    # fetched again. The archive itself was committed by
                    # archive_print; only the flag is lost.
                    try:
                        await db.rollback()
                        archive = await db.get(PrintArchive, archive_id)
                        printer = await db.get(Printer, printer_id)
                    except Exception as reload_error:
                        logger.warning(
                            "Could not reload archive %s after the failed flag write: %s", archive_id, reload_error
                        )

                # Track this active print (use both original filename and downloaded filename)
                _rt()._active_prints[(printer_id, downloaded_filename)] = archive.id
                if filename and filename != downloaded_filename:
                    _rt()._active_prints[(printer_id, filename)] = archive.id
                if subtask_name:
                    _rt()._active_prints[(printer_id, f"{subtask_name}.3mf")] = archive.id

                logger.info("Created archive %s for %s", archive.id, downloaded_filename)

                _rt()._maybe_start_layer_timelapse(printer, printer_id, archive.id)

                # Record starting energy from smart plug if available (#941: persisted column)
                await _rt()._record_energy_start(archive, printer_id, db, context="auto-archive")

                await _rt().ws_manager.send_archive_created(
                    {
                        "id": archive.id,
                        "printer_id": archive.printer_id,
                        "filename": archive.filename,
                        "print_name": archive.print_name,
                        "status": archive.status,
                    }
                )

                # MQTT relay - publish archive created
                try:
                    await _rt().mqtt_relay.on_archive_created(
                        archive_id=archive.id,
                        print_name=archive.print_name,
                        printer_name=printer.name,
                        status=archive.status,
                    )
                except Exception:
                    pass  # Don't fail if MQTT fails

                # Send notification with archive data (new archive created)
                if not notification_sent:
                    archive_data = {
                        "print_time_seconds": archive.print_time_seconds,
                        "created_by_id": archive.created_by_id,
                    }
                    await _rt()._send_print_start_notification(printer_id, data, archive_data, logger)

                # Extract printable objects for skip object functionality
                try:
                    from backend.app.services.archive import extract_printable_objects_from_3mf

                    client = _rt().printer_manager.get_client(printer_id)
                    if client:
                        with open(temp_path, "rb") as f:
                            threemf_data = f.read()
                        # Extract with positions for UI overlay, scoped to the
                        # plate that is printing — an all-plates 3MF carries
                        # every plate's objects (#2522).
                        printable_objects, bbox_all = extract_printable_objects_from_3mf(
                            threemf_data,
                            plate_number=resolve_plate_id(client.state),
                            include_positions=True,
                        )
                        if printable_objects:
                            # Store objects in printer state
                            client.state.printable_objects = printable_objects
                            client.state.printable_objects_bbox_all = bbox_all
                            client.state.skipped_objects = []  # Reset skipped objects for new print
                            logger.info(
                                "Loaded %s printable objects for printer %s", len(printable_objects), printer_id
                            )
                except Exception as e:
                    logger.debug("Failed to extract printable objects: %s", e)

                # Store Spoolman tracking data for per-filament usage reporting
                try:
                    await _rt()._store_spoolman_print_data(
                        printer_id,
                        archive.id,
                        archive.file_path,
                        db,
                        _rt().printer_manager,
                        ams_mapping=_get_start_ams_mapping(data, archive.id),
                        plate_id=_rt()._get_start_plate_id(archive.id),
                    )
                except Exception as e:
                    logger.warning("[SPOOLMAN] Failed to store tracking data: %s", e)

                # Capture timelapse file baseline for snapshot-diff on completion
                await _rt()._capture_timelapse_baseline_at_start(printer, printer_id, logger, archive_id=archive.id)
        finally:
            # Keep temp_path around until print completes so the cover endpoint
            # can reuse it (#972). Cache eviction in on_print_complete deletes
            # the file. If the cache entry was evicted early (file vanished),
            # clean up any stragglers here to avoid leaking disk on retries.
            cached_now = _rt().get_cached_3mf(printer_id, downloaded_filename) if downloaded_filename else None
            if temp_path and temp_path.exists() and cached_now != temp_path:
                temp_path.unlink()
