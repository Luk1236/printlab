"""Zeitraffer von Druckern: Basisaufnahme, Scan, Anhang und Erinnerungsfoto.

Aus ``backend/app/main.py`` ausgelagert: alles, was das Drucker-Zeitraffer
eines Prints findet, an das Archiv hängt und daraus das Abschlussfoto zieht.
Das Layer-Zeitraffer (externe Kamera) bleibt in ``services/layer_timelapse``;
die Konstanten für die Zeitgrenzen und der Baseline-Speicher bleiben im
``main``-Namensraum, weil die Tests sie dort setzen — das Modul liest sie
deshalb über :func:`_rt` frisch vom Fassadenmodul. Aufrufer und Tests sehen
keinen Unterschied.
"""

import logging
from pathlib import Path

from sqlalchemy import select

from backend.app.services.print_storage import external_storage_present

# Der Logger-Name bleibt der der alten Heimat, damit Protokollzeilen in den
# Support-Bundles unverändert unter ``backend.app.main`` auftauchen.
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen.

    Die Funktionen sind hierher gewandert; gepatcht und gesetzt werden
    ``ws_manager``, ``async_session``, ``ArchiveService``, ``printer_manager``,
    ``time``, ``asyncio``, ``app_settings``, ``_timelapse_baselines`` und die
    Zeitkonstanten aber weiterhin im Modul ``main``. Der Zugriff über das Modul
    hält beides zusammen: Test-Attrappe und Produktionspfad.
    """
    import importlib

    return importlib.import_module("backend.app.main")


def _maybe_start_layer_timelapse(printer, printer_id: int, archive_id: int) -> bool:
    """Start a layer-timelapse session for *archive_id* when the printer has
    an external camera configured. Returns True if a session was started.

    Three call sites in on_print_start (expected-archive promotion, fallback
    archive creation, fresh-archive creation) used to inline this same
    if-block; the inline copies kept drifting (#1353 fixed only one of them
    on the first pass). Centralising the conditional + call here makes the
    contract testable in isolation and keeps the three sites locked in step.
    """
    if not (printer.external_camera_enabled and printer.external_camera_url):
        return False
    from backend.app.services.layer_timelapse import start_session

    start_session(
        printer_id,
        archive_id,
        printer.external_camera_url,
        printer.external_camera_type or "mjpeg",
        snapshot_url=printer.external_camera_snapshot_url,
        rotation=getattr(printer, "camera_rotation", 0),
    )
    logger.info("Started layer timelapse for printer %s, archive %s", printer_id, archive_id)
    return True


def _timelapse_scan_max_attempts() -> int:
    """Round cap for the poll, derived from the wall-clock budget.

    The deadline alone is not a sufficient bound: it assumes each round really
    waits, which stops being true the moment ``asyncio.sleep`` is patched out,
    and an FTP list that fails immediately would otherwise spin against the
    printer at full speed for the whole window. Whichever bound is reached
    first ends the poll.
    """
    if _rt()._TIMELAPSE_SCAN_POLL_INTERVAL_SECONDS <= 0:
        # A zero interval makes the wall-clock budget meaningless; fall back to
        # the round count the production interval would have given.
        return 32
    return max(
        1,
        int(_rt()._TIMELAPSE_SCAN_TIMEOUT_SECONDS // _rt()._TIMELAPSE_SCAN_POLL_INTERVAL_SECONDS) + 1,
    )


async def _claimed_timelapse_names(db, printer_id: int, exclude_archive_id: int) -> set[str]:
    """Video filenames already attached to some other archive of this printer.

    Used to disambiguate when more than one file is new since the baseline —
    which happens when a previous print's video landed after this print's
    baseline was taken. Ordering the candidates would be the obvious fix and is
    the wrong one: it can only be done on mtime or on the filename timestamp,
    both of which come from the printer's own clock, and a LAN-only printer
    can't reach Bambu's NTP server. Exclusion needs no clock at all.

    ``attach_timelapse`` saves the video into the archive directory under the
    printer's original filename, and the later MP4 conversion keeps the stem,
    so the stem of ``timelapse_path`` recovers what was claimed.
    """
    from backend.app.models.archive import PrintArchive

    rows = await db.execute(
        select(PrintArchive.timelapse_path).where(
            PrintArchive.printer_id == printer_id,
            PrintArchive.id != exclude_archive_id,
            PrintArchive.timelapse_path.is_not(None),
        )
    )
    return {Path(p).stem for p in rows.scalars().all() if p}


def _timelapse_listing_is_trustworthy(printer) -> bool:
    """Whether an *empty* timelapse listing for *printer* can be believed.

    ``list_files_async`` answers ``[]`` when its connect fails rather than
    raising, so a card behind the FTPS handshake cool-off is indistinguishable
    from one holding no videos. Everywhere that only wants to know "is there a
    video yet" the difference does not matter — both mean "not yet, retry".

    It matters where an empty listing is recorded as a *baseline*. Recording
    "the card held nothing" for a card that was never read means every video on
    it counts as new once the cool-off expires, and the completion scan then
    attaches a stale video to this print and deletes it from the printer
    (#2957 follow-up). Those two callers ask this first.
    """
    from backend.app.services.bambu_ftp import ftps_handshake_blocked

    ip_address = getattr(printer, "ip_address", None)
    if not ip_address:
        return True
    return not ftps_handshake_blocked(ip_address)


async def _list_timelapse_videos(printer) -> tuple[list[dict], str | None]:
    """List video files from printer's timelapse directory.

    Finds MP4 (X1/A1 series) and AVI (P1 series) timelapse files.
    Returns (video_files, found_path) where video_files is a list of file dicts
    and found_path is the directory where they were found, or ([], None).

    An empty return does not distinguish "no videos" from "could not read the
    card" — see :func:`_timelapse_listing_is_trustworthy`, which the two
    baseline callers consult before believing one.
    """
    from backend.app.services.bambu_ftp import list_files_async

    # No card in the slot means no /timelapse to walk — four connections that
    # can only fail, on a path whose failures are swallowed and so would go on
    # costing time silently forever (#2780).
    #
    # ``getattr`` rather than ``printer.id``: every dereference below happens
    # inside the loop's own try/except, so a caller that passed something
    # unexpected used to get an empty listing rather than an exception. Keep
    # that, instead of making this gate the first thing that can raise here.
    printer_id = getattr(printer, "id", None)
    if printer_id is not None and not external_storage_present(_rt().printer_manager.get_status(printer_id)):
        logger.debug("[TIMELAPSE] Skipping the scan for printer %s: it reports no external storage", printer_id)
        return [], None

    for timelapse_path in ["/timelapse", "/timelapse/video", "/record", "/recording"]:
        try:
            found_files = await list_files_async(
                printer.ip_address, printer.access_code, timelapse_path, printer_model=printer.model
            )
            if found_files:
                video_files = [
                    f
                    for f in found_files
                    if not f.get("is_directory") and f.get("name", "").lower().endswith(_rt()._TIMELAPSE_VIDEO_EXTENSIONS)
                ]
                if video_files:
                    return video_files, timelapse_path
        except Exception as e:
            logger.debug("[TIMELAPSE] Path %s failed: %s", timelapse_path, e)
            continue

    return [], None


async def _capture_timelapse_baseline_at_start(
    printer, printer_id: int, logger: logging.Logger, archive_id: int | None = None
) -> None:
    """Snapshot the printer's timelapse directory at print start so the
    completion-time scan can pick the new file by set-difference.

    Must be called from every on_print_start path that proceeds to a real
    print — both the new-archive branch and the expected-archive branch (which
    queue / VP-dispatched prints take). Without a baseline,
    _scan_for_timelapse_with_retries falls into its "take baseline now"
    fallback that runs AFTER the new MP4 has already landed on the SD card,
    so the new file ends up in the "baseline" set and no diff ever matches.

    Bambu printers in LAN-only mode don't sync NTP, so mtime ordering is
    unreliable — the snapshot-diff approach sidesteps that entirely.

    When ``archive_id`` is known the baseline is also written to the archive
    row, so it survives a restart and the manual "Scan for Timelapse" button
    can run the same diff instead of falling back to clock-based matching
    (#2704). Only baselines taken at print start are persisted — one taken at
    completion already contains the new video and would poison a later scan.
    """
    names: set[str] | None = None
    try:
        if not _timelapse_listing_is_trustworthy(printer):
            # Recorded anyway, deliberately. An empty baseline taken off a card
            # we could not read is not authoritative, but it is still the right
            # *default*: PrintLab deletes each video from the printer once it is
            # attached, so the usual card holds exactly one video at completion
            # and an empty baseline resolves it correctly. Persisting NULL
            # instead would send completion to take its own snapshot, by which
            # point this print's video is on the card and would be swallowed by
            # it. The ambiguity is handled where it actually bites — see
            # ``require_unambiguous`` in the scan (#2957 follow-up).
            logger.warning(
                "[TIMELAPSE] Baseline for printer %s taken while its file service is in the FTPS "
                "handshake cool-off, so the card could not be read — treating it as empty",
                printer_id,
            )
        baseline_files, _ = await _rt()._list_timelapse_videos(printer)
        names = {f.get("name", "") for f in baseline_files}
        _rt()._timelapse_baselines[printer_id] = names
        logger.info(
            "[TIMELAPSE] Baseline at print start: %s video files for printer %s",
            len(names),
            printer_id,
        )
    except Exception as e:
        logger.warning("[TIMELAPSE] Failed to capture baseline at print start: %s", e)

    if archive_id is None:
        return
    try:
        async with _rt().async_session() as db:
            from backend.app.models.archive import PrintArchive

            archive = await db.get(PrintArchive, archive_id)
            if archive is not None:
                # Written even when the listing failed, and then as NULL. A
                # reprint reuses the archive row, so leaving the previous run's
                # baseline in place would have the scan diff this print against
                # the state of the printer before the *last* one — and a stale
                # baseline reads as authoritative, where NULL correctly falls
                # back to a fresh snapshot.
                archive.timelapse_baseline = sorted(names) if names is not None else None
                await db.commit()
    except Exception as e:
        # In-memory baseline still covers the normal completion path.
        logger.warning("[TIMELAPSE] Failed to persist baseline for archive %s: %s", archive_id, e)


async def _scan_for_timelapse_with_retries(archive_id: int, baseline_names: set[str] | None = None):
    """Poll the printer for this print's timelapse and attach it.

    Snapshot diff, not timestamp matching: a printer in LAN-only mode cannot
    reach Bambu's NTP server, so the clock behind both the filename and the FTP
    mtime is arbitrarily wrong — one reporter's P1S was six and a half days out
    (#2704). Comparing the current listing against the set of filenames that
    existed when the print started needs no clock at all, because the printer
    writes the video only once the print has ended.

    Baseline precedence: the caller's in-memory set, then the one persisted on
    the archive at print start, then a snapshot taken now. The last of those is
    a poor substitute — by completion the new video may already be on the card,
    in which case it lands in the "baseline" and no diff can ever match — but it
    is all that is available for a print that began before PrintLab started.

    On success the video is deleted from the printer, which keeps ``/timelapse``
    down to the unclaimed files and makes the next diff unambiguous.
    """

    # Cleared when the baseline had to be taken off a card we could not read, so
    # the attach step refuses to choose between several candidates (#2957).
    baseline_trusted = True

    # --- Phase 1: establish the baseline -------------------------------------
    try:
        async with _rt().async_session() as db:
            from backend.app.models.printer import Printer

            service = _rt().ArchiveService(db)
            archive = await service.get_archive(archive_id)

            if not archive:
                logger.warning("[TIMELAPSE] Archive %s not found, aborting", archive_id)
                return
            if archive.timelapse_path:
                logger.info("[TIMELAPSE] Archive %s already has timelapse attached", archive_id)
                return
            if not archive.printer_id:
                logger.warning("[TIMELAPSE] Archive %s has no printer, aborting", archive_id)
                return

            if baseline_names is not None:
                logger.info(
                    "[TIMELAPSE] Using print-start baseline: %s existing video files for archive %s",
                    len(baseline_names),
                    archive_id,
                )
            elif archive.timelapse_baseline is not None:
                # Persisted at print start — survives a restart mid-print.
                baseline_names = set(archive.timelapse_baseline)
                logger.info(
                    "[TIMELAPSE] Using stored baseline: %s existing video files for archive %s",
                    len(baseline_names),
                    archive_id,
                )
            else:
                result = await db.execute(select(Printer).where(Printer.id == archive.printer_id))
                printer = result.scalar_one_or_none()
                if not printer:
                    logger.warning("[TIMELAPSE] Printer not found for archive %s, aborting", archive_id)
                    return

                if not _timelapse_listing_is_trustworthy(printer):
                    # The card is unreadable at the one moment a baseline has to
                    # be taken, so the empty listing below means "we never
                    # looked", not "these are all new". Carry on with it anyway
                    # — the usual card holds exactly one video, which resolves
                    # correctly — but stop the poll from *choosing* between
                    # several, which is how a stale video got attached to this
                    # print and then deleted off the printer (#2957 follow-up).
                    baseline_trusted = False
                    logger.warning(
                        "[TIMELAPSE] Baseline for archive %s taken while printer %s is in the FTPS "
                        "handshake cool-off. A single new video still resolves; several will not be "
                        "guessed between — use Scan for Timelapse to pick one by hand",
                        archive_id,
                        archive.printer_id,
                    )

                baseline_files, _ = await _rt()._list_timelapse_videos(printer)
                baseline_names = {f.get("name", "") for f in baseline_files}
                logger.info(
                    "[TIMELAPSE] Baseline snapshot (fallback): %s existing video files for archive %s",
                    len(baseline_names),
                    archive_id,
                )

    except Exception as e:
        logger.warning("[TIMELAPSE] Failed to take baseline snapshot for archive %s: %s", archive_id, e)
        return

    # --- Phase 2: poll for a file that was not there when the print began -----
    deadline = _rt().time.monotonic() + _rt()._TIMELAPSE_SCAN_TIMEOUT_SECONDS
    max_attempts = _timelapse_scan_max_attempts()
    seen_names: set[str] = set()
    delay = _rt()._TIMELAPSE_SCAN_FIRST_DELAY_SECONDS
    attempt = 0

    while True:
        await _rt().asyncio.sleep(delay)
        delay = _rt()._TIMELAPSE_SCAN_POLL_INTERVAL_SECONDS
        attempt += 1

        try:
            from backend.app.models.printer import Printer

            # Read phase: fetch archive + printer in a short session and release
            # the pooled connection BEFORE the FTP list/download below. Holding it
            # across the FTP round-trips left one connection idle-in-transaction per
            # in-flight scan (issue #2572).
            async with _rt().async_session() as db:
                service = _rt().ArchiveService(db)
                archive = await service.get_archive(archive_id)

                if not archive:
                    logger.warning("[TIMELAPSE] Archive %s not found, stopping poll", archive_id)
                    return
                if archive.timelapse_path:
                    logger.info("[TIMELAPSE] Archive %s already has timelapse attached, stopping poll", archive_id)
                    return

                result = await db.execute(select(Printer).where(Printer.id == archive.printer_id))
                printer = result.scalar_one_or_none()
                if not printer:
                    logger.warning("[TIMELAPSE] Printer not found for archive %s, stopping poll", archive_id)
                    return

                claimed = await _claimed_timelapse_names(db, archive.printer_id, archive_id)

            # I/O phase (no DB connection held): FTP list + download.
            video_files, found_path = await _rt()._list_timelapse_videos(printer)

            # The poll can run for dozens of rounds, so only narrate a round
            # that saw something change. Repeating the whole listing every 30 s
            # would bury the one interesting line in the support bundle.
            names_now = {f.get("name", "") for f in video_files}
            changed = attempt == 1 or names_now != seen_names
            seen_names = names_now
            speak = logger.info if changed else logger.debug

            if video_files:
                speak("[TIMELAPSE] Attempt %s: Found %s video files in %s", attempt, len(video_files), found_path)
                if changed:
                    for f in video_files[:5]:
                        logger.info("[TIMELAPSE]   - %s", f.get("name"))

                attached = await _attach_first_unclaimed_timelapse(
                    archive_id,
                    printer,
                    video_files,
                    baseline_names,
                    claimed,
                    attempt,
                    logger,
                    quiet=not changed,
                    require_unambiguous=not baseline_trusted,
                )
                if attached:
                    return
            else:
                speak("[TIMELAPSE] Attempt %s: No video files found, will retry", attempt)

        except Exception as e:
            logger.warning("[TIMELAPSE] Attempt %s failed with error: %s", attempt, e)

        if attempt >= max_attempts or _rt().time.monotonic() >= deadline:
            break

    # No name-match fallback: it compared the print name against the filename,
    # and Bambu firmware only ever writes "video_<timestamp>". Across 247 support
    # bundles it fired 159 times and matched zero times, so all it added was a
    # misleading log line before giving up.
    logger.warning(
        "[TIMELAPSE] No new video appeared for archive %s within %ss, giving up",
        archive_id,
        int(_rt()._TIMELAPSE_SCAN_TIMEOUT_SECONDS),
    )


async def _attach_first_unclaimed_timelapse(
    archive_id: int,
    printer,
    video_files: list[dict],
    baseline_names: set[str],
    claimed: set[str],
    attempt: int,
    logger: logging.Logger,
    *,
    quiet: bool = False,
    require_unambiguous: bool = False,
) -> bool:
    """Download and attach the one video that belongs to this print.

    A candidate is any file absent from the print-start baseline. More than one
    can qualify when a previous print's video landed late, after this print's
    baseline was taken — those are filtered out by name, because they are
    already attached to another archive. Sorting the candidates instead would
    mean sorting on mtime or on the filename timestamp, both of which come from
    the printer's unsynced clock.

    Returns True once a video is attached. The printer's copy is deleted only
    after the attach succeeds on bytes whose length matched the listing.

    ``quiet`` downgrades the "nothing yet" lines to DEBUG when the caller has
    already seen this exact listing — the poll runs for many rounds and only the
    rounds where something changed are worth an INFO line.
    """
    from backend.app.services.bambu_ftp import (
        delete_archived_timelapse,
        download_file_bytes_async,
        remote_file_settled,
    )

    speak = logger.debug if quiet else logger.info

    new_files = [f for f in video_files if f.get("name", "") not in baseline_names]
    if not new_files:
        speak("[TIMELAPSE] Attempt %s: No new files since baseline, will retry", attempt)
        return False

    candidates = [f for f in new_files if Path(f.get("name", "")).stem not in claimed]
    if not candidates:
        speak(
            "[TIMELAPSE] Attempt %s: %s new file(s), all already attached to other archives, will retry",
            attempt,
            len(new_files),
        )
        return False
    if len(candidates) > 1:
        if require_unambiguous:
            # The baseline is not evidence -- it was taken off a card that could
            # not be read -- so "new since the baseline" does not narrow these
            # down at all. Taking the first would attach an arbitrary video to
            # this print and then delete it from the printer.
            logger.warning(
                "[TIMELAPSE] Attempt %s: %s unclaimed videos (%s) and no baseline to tell them apart — "
                "leaving all of them on the printer for manual selection",
                attempt,
                len(candidates),
                ", ".join(str(f.get("name")) for f in candidates),
            )
            return False
        logger.warning(
            "[TIMELAPSE] Attempt %s: %s unclaimed new files (%s) — taking the first; "
            "the rest stay on the printer for manual selection",
            attempt,
            len(candidates),
            ", ".join(str(f.get("name")) for f in candidates),
        )

    target = candidates[0]
    file_name = target.get("name")
    remote_path = target.get("path") or f"/timelapse/{file_name}"
    logger.info(
        "[TIMELAPSE] Attempt %s: New file detected: %s (downloading for archive %s)",
        attempt,
        file_name,
        archive_id,
    )

    # The listing always carries a size (`list_files` skips entries it can't
    # parse), but read it explicitly: the delete below is destructive and must
    # depend on a size we actually had, not on one we hoped was there.
    expected_size = target.get("size")

    timelapse_data = await download_file_bytes_async(
        printer.ip_address,
        printer.access_code,
        remote_path,
        printer_model=printer.model,
        expected_size=expected_size,
    )
    if not timelapse_data:
        # Short or failed transfer. The printer keeps its copy, so the next
        # round can try again — which is exactly why the delete below is
        # gated on a verified download.
        logger.warning("[TIMELAPSE] Attempt %s: Failed to download new file, will retry", attempt)
        return False

    # The length check above proves we got what the listing said, not that the
    # printer had finished writing. A video still being written can be listed
    # short, served short, and pass — so confirm it has stopped growing before
    # committing to it and deleting the original (#2704).
    if not await remote_file_settled(
        printer.ip_address,
        printer.access_code,
        remote_path,
        len(timelapse_data),
        printer_model=printer.model,
    ):
        return False

    # Write phase: attach in a fresh short-lived session.
    async with _rt().async_session() as db:
        success = await _rt().ArchiveService(db).attach_timelapse(archive_id, timelapse_data, file_name)
    if not success:
        logger.warning("[TIMELAPSE] Failed to attach timelapse to archive %s", archive_id)
        return False

    logger.info("[TIMELAPSE] Successfully attached timelapse to archive %s", archive_id)
    await _rt().ws_manager.send_archive_updated({"id": archive_id, "timelapse_attached": True})

    await delete_archived_timelapse(
        printer.ip_address,
        printer.access_code,
        remote_path,
        verified=expected_size is not None,
        printer_model=printer.model,
        printer_name=printer.name,
    )
    return True


async def _capture_finish_photo_from_timelapse(
    archive_id: int,
    archive_dir: Path,
    timeout: float | None = None,
    rotation: int = 0,
) -> tuple[str | None, bool]:
    """Wait for the per-print timelapse to land on the archive and extract its
    last frame as the finish photo (#1397).

    Bambu firmware stops timelapse recording after the toolhead parks but
    before the bed-drop end-gcode runs, so the last frame frames the finished
    print correctly. A live camera grab at gcode_state=FINISH captures the
    bed already lowered.

    ``_scan_for_timelapse_with_retries`` runs in parallel and writes
    ``archive.timelapse_path`` when the file lands. This function polls for
    that field.

    Returns ``(filename, still_pending)``. ``still_pending`` is True only when
    the wait ran out with no video on the archive yet — i.e. the video may
    still be coming and a later attempt could succeed. It is False when the
    video landed (whether or not extraction worked), because in that case
    waiting longer changes nothing. The caller uses that to decide between
    falling back permanently and scheduling a background upgrade.

    ``rotation`` is the printer's camera_rotation, applied to the extracted
    still (#2708) so this source agrees with every other finish-photo source.
    The archived video itself is the printer's own file and is left alone —
    rotating it would mean re-encoding it.
    """
    import uuid

    from backend.app.models.archive import PrintArchive
    from backend.app.services.camera import apply_camera_rotation_to_file, extract_video_last_frame

    budget = _rt()._FINISH_PHOTO_TIMELAPSE_POLL_TIMEOUT_SECONDS if timeout is None else timeout
    deadline = _rt().asyncio.get_event_loop().time() + budget
    poll_interval = _rt()._FINISH_PHOTO_TIMELAPSE_POLL_INTERVAL_SECONDS

    while True:
        async with _rt().async_session() as db:
            result = await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))
            archive = result.scalar_one_or_none()
            timelapse_relpath = archive.timelapse_path if archive else None

        if timelapse_relpath:
            video_path = _rt().app_settings.base_dir / timelapse_relpath
            if video_path.exists() and video_path.stat().st_size > 0:
                photos_dir = archive_dir / "photos"
                photos_dir.mkdir(parents=True, exist_ok=True)
                timestamp = _rt().datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"finish_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
                output_path = photos_dir / filename
                if await extract_video_last_frame(video_path, output_path):
                    await apply_camera_rotation_to_file(output_path, rotation, logger)
                    logger.info(
                        "[PHOTO-BG] Extracted finish photo from timelapse %s for archive %s",
                        video_path.name,
                        archive_id,
                    )
                    return filename, False
                logger.warning(
                    "[PHOTO-BG] Timelapse %s landed but last-frame extraction failed for archive %s; falling back",
                    video_path.name,
                    archive_id,
                )
                return None, False

        if _rt().asyncio.get_event_loop().time() >= deadline:
            logger.info(
                "[PHOTO-BG] Timelapse for archive %s didn't land within %.0fs; falling back to live camera",
                archive_id,
                budget,
            )
            return None, True

        await _rt().asyncio.sleep(poll_interval)


async def _upgrade_finish_photo_from_timelapse(archive_id: int, archive_dir: Path, rotation: int = 0) -> None:
    """Add the timelapse's last frame to an archive after the fact (#2704).

    The print-complete notification waits only ~60s for the video, because
    holding a notification for minutes is worse than sending it with a live
    camera grab. On a P1-series printer the video often lands well after that,
    so the archive used to be stuck with the live grab — which is taken at
    ``gcode_state=FINISH``, after the end G-code has dropped the bed, and is
    the worse photo of the two.

    This keeps waiting in the background and, when the video arrives, extracts
    the frame and puts it *first* in the archive's photo list, so opening the
    gallery shows it. The live grab is deliberately kept: the notification that
    already went out links to that exact file, and deleting it would leave a
    broken image in Discord or Telegram.
    """

    filename, _ = await _rt()._capture_finish_photo_from_timelapse(
        archive_id, archive_dir, timeout=_rt()._FINISH_PHOTO_UPGRADE_TIMEOUT_SECONDS, rotation=rotation
    )
    if not filename:
        logger.info("[PHOTO-UPGRADE] No timelapse frame for archive %s; keeping the live grab", archive_id)
        return

    try:
        async with _rt().async_session() as db:
            from backend.app.models.archive import PrintArchive

            archive = await db.get(PrintArchive, archive_id)
            if archive is None:
                return
            photos = list(archive.photos or [])
            if filename in photos:
                return
            # Front of the list: PhotoGalleryModal opens at index 0.
            archive.photos = [filename, *photos]
            await db.commit()
    except Exception as e:
        logger.warning("[PHOTO-UPGRADE] Failed to attach upgraded photo to archive %s: %s", archive_id, e)
        return

    logger.info("[PHOTO-UPGRADE] Archive %s now leads with the timelapse frame %s", archive_id, filename)
    await _rt().ws_manager.send_archive_updated({"id": archive_id, "photo_added": filename})
