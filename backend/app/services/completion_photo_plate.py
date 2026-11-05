"""
Moment-, Snapshot-, Frame-Bank- und Platten-Park-Hebel des Abschluss-Abflusses

Zustaende und die von den Tests umgebogenen Namen bleiben im Modul main
und werden über :func:`_rt` gelesen. Aufrufer und Tests sehen keinen
Unterschied.
"""

import importlib
import logging
from pathlib import Path

from sqlalchemy import or_, select

from backend.app.core.config import settings as app_settings
from backend.app.services import print_dispatch_context

# der Logger-Name bleibt der der alten Heimat (Backend-Protokolle)
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen."""

    return importlib.import_module("backend.app.main")


async def _capture_snapshot_for_notification(printer_id: int, printer, logger) -> bytes | None:
    """Capture a camera snapshot for notification image attachment.

    Returns JPEG bytes (max 2.5MB) or None if capture fails or is unavailable.
    Uses: external camera > buffered frame > fresh capture.
    """
    if not printer:
        return None

    try:
        from backend.app.api.routes.settings import get_setting

        async with _rt().async_session() as db:
            capture_enabled = await get_setting(db, "capture_finish_photo")

        if capture_enabled is not None and capture_enabled.lower() != "true":
            return None

        # Try external camera first
        if printer.external_camera_enabled and printer.external_camera_url:
            logger.info("[SNAPSHOT] Capturing from external camera for printer %s", printer_id)
            from backend.app.api.routes.camera import live_frame_for_capture
            from backend.app.services.external_camera import capture_frame

            # An external camera allows one reader, so capturing while a viewer
            # is attached fails (#2707). A None here falls through to the paths
            # below exactly as a failed capture did.
            defer, buffered = live_frame_for_capture(printer_id)
            if defer:
                frame_data = buffered
            else:
                frame_data = await capture_frame(
                    printer.external_camera_url,
                    printer.external_camera_type or "mjpeg",
                    snapshot_url=printer.external_camera_snapshot_url,
                )
            if frame_data and len(frame_data) <= 2_500_000:
                logger.info("[SNAPSHOT] External camera frame: %s bytes", len(frame_data))
                return _rt()._apply_camera_rotation(frame_data, printer, logger)

        # Try buffered frame from active stream
        from backend.app.api.routes.camera import _active_chamber_streams, _active_streams, get_buffered_frame

        active_for_printer = [k for k in _active_streams if k.startswith(f"{printer_id}-")]
        active_chamber = [k for k in _active_chamber_streams if k.startswith(f"{printer_id}-")]
        buffered_frame = get_buffered_frame(printer_id)

        if (active_for_printer or active_chamber) and buffered_frame:
            logger.info("[SNAPSHOT] Using buffered frame for printer %s: %s bytes", printer_id, len(buffered_frame))
            if len(buffered_frame) <= 2_500_000:
                return _rt()._apply_camera_rotation(buffered_frame, printer, logger)

        # Fresh capture from printer camera
        logger.info("[SNAPSHOT] Capturing fresh frame for printer %s", printer_id)
        from backend.app.services.camera import capture_camera_frame_bytes

        frame_data = await capture_camera_frame_bytes(
            printer.ip_address, printer.access_code, printer.model, timeout=15
        )
        if frame_data and len(frame_data) <= 2_500_000:
            logger.info("[SNAPSHOT] Fresh camera frame: %s bytes", len(frame_data))
            return _rt()._apply_camera_rotation(frame_data, printer, logger)

    except Exception as e:
        logger.warning("[SNAPSHOT] Failed to capture snapshot for printer %s: %s", printer_id, e)

    return None


async def _maybe_bank_inprint_frame(printer_id: int, layer_num: int) -> None:
    """#1867: bank a recent in-print camera frame for the finish photo.

    Called on every layer change and (#2547) on every print-progress advance.
    Grabs one frame (throttled) into ``_inprint_frame_bank`` so the finish-photo
    path has a pre-End-G-code image for prints that end with a plate swap.

    Both drivers are print telemetry that stops the instant printing ends: no
    further layers, and progress freezes before the End G-code (e.g. SwapMod
    plate swap) executes. So the last banked frame is always the finished print,
    never the swapped plate — that property is what the #1867 path relies on and
    it must survive any change to the throttle below.

    Layer changes alone were not enough: they stop when the *final* layer
    begins, which on a three-minute last layer left the bank stale by the whole
    length of that layer (#2547). Progress keeps ticking through it.

    Best-effort: any failure just leaves the previous banked frame.
    """
    logger = logging.getLogger(__name__)
    client = _rt().printer_manager.get_client(printer_id)
    state = client.state if client else None
    if not state or state.state != "RUNNING":
        return
    # Only during actual extrusion — firmware ticks layer_num during the
    # pre-print calibration sequence, whose sub-stages are non-zero.
    if state.mc_print_sub_stage not in (None, 0):
        return

    # #2547: throttled uniformly, with no last-layer exemption. The old code
    # bypassed the throttle on the final layer to guarantee a fresh frame there;
    # now that progress advances also drive banking, that exemption would fire a
    # camera grab on every percent tick of the last layer. Bambu printers accept
    # one RTSP client at a time, so each grab contends with the live view.
    now = _rt().time.monotonic()
    last = _rt()._inprint_frame_bank_ts.get(printer_id, 0.0)
    if (now - last) < _rt()._INPRINT_BANK_MIN_INTERVAL:
        return
    total = state.total_layers or 0

    try:
        async with _rt().async_session() as db:
            from backend.app.models.printer import Printer

            result = await db.execute(select(Printer).where(Printer.id == printer_id))
            printer = result.scalar_one_or_none()
        if not printer:
            return
        # Reuses the notification snapshot path, which honours the
        # `capture_finish_photo` setting (returns None when disabled) so we
        # don't bank frames the user never asked for.
        frame = await _rt()._capture_snapshot_for_notification(printer_id, printer, logger)
        if frame:
            _rt()._inprint_frame_bank[printer_id] = frame
            _rt()._inprint_frame_bank_ts[printer_id] = now
            logger.debug(
                "[FINISH-PHOTO-BANK] banked in-print frame for printer %s at layer %s/%s (%d bytes)",
                printer_id,
                layer_num,
                total,
                len(frame),
            )
    except Exception as e:
        logger.debug("[FINISH-PHOTO-BANK] bank failed for printer %s: %s", printer_id, e)


def _apply_camera_rotation(image_data: bytes, printer, logger) -> bytes:
    """Apply camera rotation to snapshot image if configured."""
    from backend.app.services.camera import apply_camera_rotation

    return apply_camera_rotation(image_data, getattr(printer, "camera_rotation", 0), logger)


# #2547: clearance left between the nozzle and the top of the print when the
# plate is commanded back into camera framing. The nozzle is parked away from
# the part by then, so this is belt-and-braces against a max_z_height that
# under-reports (e.g. a slicer that excludes a final Z hop).
_PLATE_RESTORE_CLEARANCE_MM = 10.0
# How far below the restored position to drop the plate again afterwards, so
# the print is as reachable as Bambu's own end G-code leaves it. Matches the
# stock `G1 Z{max_layer_z + 100}`; the firmware clamps it to the travel limit
# on machines with less headroom.
_PLATE_PARK_DROP_MM = 100.0
# Feedrate for both moves. F600 is exactly what Bambu's own end G-code uses on
# this axis, so it is a proven-safe speed for the full travel.
_PLATE_RESTORE_FEEDRATE = 600
# Time allowed for the plate to reach the restored position before the camera
# grab. Sized for the ~100 mm the stock end G-code drops at F600 (10 mm/s).
_PLATE_RESTORE_SETTLE_SECONDS = 12.0


async def _max_z_for_current_print(printer_id: int, data: dict, logger) -> float | None:
    """Height of the print that just finished on ``printer_id``, or None (#2547).

    This number becomes the target of a real Z move, so every step here refuses
    rather than guesses. A height belonging to some *other* print is the one
    failure that could drive the nozzle into the model: 20 mm carried onto a
    200 mm print would command the plate up through the part.

    Two independent things therefore have to agree before a height is returned:

    1. **Identity.** The archive is matched by the finished print's own
       ``subtask_name``, by equality rather than a ``LIKE``, so "Cube" can never
       resolve to "Cube v2". Matching on "most recent archive for this printer"
       is not good enough — ``on_print_complete`` pops the ``_active_prints``
       binding concurrently with us, and a print PrintLab failed to archive
       would silently resolve to its predecessor.
    2. **Corroboration.** The archive's layer count (parsed from the 3MF) has to
       match the layer count the printer itself reported over MQTT for the print
       that just ended. These come from genuinely different sources, so a
       mismatch means the row is not this print, whatever its name says.

    ``completed`` is accepted alongside ``printing`` only because
    ``on_print_complete`` may already have flipped the status by the time we
    run; the identity check above is what actually selects the row.
    """
    subtask_name = (data.get("subtask_name") or "").strip()
    if not subtask_name:
        # Nothing to identify the print by — refuse rather than fall back to
        # "whatever ran last on this printer".
        logger.info("[PLATE-RESTORE] printer %s: print has no name to match on — skipping", printer_id)
        return None

    try:
        from backend.app.models.archive import PrintArchive
        from backend.app.utils.threemf_tools import extract_max_z_height_from_3mf

        async with _rt().async_session() as db:
            result = await db.execute(
                select(PrintArchive)
                .where(
                    PrintArchive.printer_id == printer_id,
                    PrintArchive.status.in_(("printing", "completed")),
                    PrintArchive.deleted_at.is_(None),
                    or_(
                        PrintArchive.print_name == subtask_name,
                        PrintArchive.filename == subtask_name,
                        PrintArchive.filename == f"{subtask_name}.3mf",
                        PrintArchive.filename == f"{subtask_name}.gcode.3mf",
                    ),
                )
                .order_by(PrintArchive.id.desc())
                .limit(1)
            )
            archive = result.scalar_one_or_none()
        if archive is None or not archive.file_path:
            logger.info("[PLATE-RESTORE] printer %s: no archive matches %r — skipping", printer_id, subtask_name)
            return None

        client = _rt().printer_manager.get_client(printer_id)
        reported_layers = getattr(getattr(client, "state", None), "total_layers", None)
        if reported_layers and archive.total_layers and reported_layers != archive.total_layers:
            logger.warning(
                "[PLATE-RESTORE] printer %s: archive %s says %s layers but the printer reported %s "
                "— refusing to move the plate on a height that may not be this print's",
                printer_id,
                archive.id,
                archive.total_layers,
                reported_layers,
            )
            return None

        path = Path(archive.file_path)
        if not path.is_absolute():
            # Der absolute Zweig oben stellt sicher, dass hier nur die
            # datenverzeichnis-relative Form verbleibt (archive.file_path
            # entstammt der DB, verwaltet durch ArchiveService).
            path = (
                Path(app_settings.data_dir) / path
            )  # SEC-PATH-OK: relatives DB-Pfad-Fragment unter DATA_DIR; absolute Pfade zweigen oben ab
        return await _rt().asyncio.to_thread(extract_max_z_height_from_3mf, path, archive.plate_id or 1)
    except Exception as e:
        logger.debug("[PLATE-RESTORE] printer %s: no usable print height: %s", printer_id, e)
        return None


async def _restore_plate_for_finish_photo(printer_id: int, max_z_height: float, logger) -> bool:
    """Raise the plate back into camera framing before the finish photo (#2547).

    Bambu's end G-code drops the plate ~100 mm as the last thing it does, so by
    the time ``gcode_state`` reaches FINISH the finished print sits far below
    the camera's natural framing — the complaint behind #1145, #1397 and #1565.
    This commands an absolute ``G1 Z`` back to just above the last printed
    layer.

    Absolute, not relative, is the whole safety argument. ``max_z_height +
    clearance`` is a height the toolhead was physically at seconds earlier, so
    it is inside the travel limits by construction and leaves the nozzle above
    the part. It is also unambiguous across model families: Z is the
    nozzle-to-bed gap whether the bed moves (X1/P1/H2) or the toolhead does
    (A1), so unlike the relative bed-jog path (#1334) there is no sign to get
    wrong. ``M211`` is never touched — see the bed-jog docstring for why
    (#2579).

    Returns True if the move was sent and waited out, False if it was skipped.
    """
    client = _rt().printer_manager.get_client(printer_id)
    if client is None:
        return False

    # Re-read state immediately before commanding motion. If the queue has
    # already started the next print, the printer is no longer ours to move.
    state = getattr(client, "state", None)
    if state is None or state.state != "FINISH":
        logger.info(
            "[PLATE-RESTORE] printer %s is in state %s, not FINISH — skipping",
            printer_id,
            getattr(state, "state", "unknown"),
        )
        return False

    target_z = max_z_height + _PLATE_RESTORE_CLEARANCE_MM
    if not client.send_gcode(f"G90\nG1 Z{target_z:.2f} F{_PLATE_RESTORE_FEEDRATE}"):
        logger.warning("[PLATE-RESTORE] printer %s: send failed — capturing where it is", printer_id)
        return False

    logger.info(
        "[PLATE-RESTORE] printer %s: plate to Z%.2f (print top %.2f + %.1f clearance), settling %.0fs",
        printer_id,
        target_z,
        max_z_height,
        _PLATE_RESTORE_CLEARANCE_MM,
        _PLATE_RESTORE_SETTLE_SECONDS,
    )
    await _rt().asyncio.sleep(_PLATE_RESTORE_SETTLE_SECONDS)
    return True


def _park_plate_after_finish_photo(printer_id: int, max_z_height: float, logger) -> None:
    """Drop the plate again after the finish photo (#2547).

    Without this the user walks up to a finished print sitting just under the
    nozzle, which is exactly the position Bambu's end G-code goes out of its way
    to avoid — awkward to lift the plate out, and easy to knock the toolhead.
    Fire-and-forget: if it doesn't land, the plate is merely high, and the next
    print homes anyway.
    """
    client = _rt().printer_manager.get_client(printer_id)
    state = getattr(client, "state", None) if client else None
    if client is None or state is None or state.state != "FINISH":
        return
    client.send_gcode(f"G90\nG1 Z{max_z_height + _PLATE_PARK_DROP_MM:.2f} F{_PLATE_RESTORE_FEEDRATE}")
    logger.debug("[PLATE-RESTORE] printer %s: plate returned to unload height", printer_id)


async def _plate_restore_is_blocked_by_queue(printer_id: int) -> bool:
    """True if a queue item is about to take this printer (#2547).

    The scheduler dispatches the next job the moment a print completes, and a
    plate move interleaved with a print start is not a race worth having. The
    state re-check in ``_restore_plate_for_finish_photo`` closes the tail of
    this window; this closes the head of it.
    """
    try:
        from backend.app.models.print_queue import PrintQueueItem

        async with _rt().async_session() as db:
            result = await db.execute(
                select(PrintQueueItem.id)
                .where(
                    PrintQueueItem.printer_id == printer_id,
                    PrintQueueItem.status.in_(("pending", "printing")),
                )
                .limit(1)
            )
            return result.scalar_one_or_none() is not None
    except Exception as e:
        # Fail closed: if we can't tell, don't move the plate.
        logging.getLogger(__name__).debug(
            "[PLATE-RESTORE] queue check failed for printer %s: %s — skipping restore", printer_id, e
        )
        return True


async def on_finish_photo_moment(printer_id: int, data: dict):
    """Pre-capture a finish photo when the printer enters stage 22 / FINISH (#1721).

    Fires either at the stage-22 ("Filament unloading") edge — toolhead
    parked, bed not yet dropped, optimal framing — or as a FINISH-state
    fallback for prints that skip stage 22 (cancel, external-spool-only,
    HMS halt, firmware variants). Grabs one frame via the same
    external-camera / RTSP path the post-completion fallback uses, stores
    the JPEG bytes in ``_stage22_finish_frames[printer_id]``, and lets
    ``_background_finish_photo`` consume the cached bytes when it runs.

    Replaces the #1397 "force timelapse on at dispatch" mechanism, which
    caused per-layer nozzle parking on slicer profiles with Timelapse Type
    set to Smooth (#1721). No force-on now means the user's explicit
    timelapse=off in the slicer send dialog is respected.
    """
    logger = logging.getLogger(__name__)
    trigger = data.get("trigger", "unknown")
    timelapse_was_active = bool(data.get("timelapse_was_active"))
    logger.info(
        "[FINISH-PHOTO-MOMENT] printer=%s trigger=%s timelapse_active=%s",
        printer_id,
        trigger,
        timelapse_was_active,
    )

    # If a timelapse is actively recording, skip the pre-capture — the
    # post-completion path will extract the last frame from the recorded
    # video, which still provides the best framing (toolhead parked,
    # before bed drop) without the per-layer parking side effects.
    if timelapse_was_active:
        logger.info(
            "[FINISH-PHOTO-MOMENT] timelapse active for printer %s — skipping pre-capture (last-frame extraction will run post-completion)",
            printer_id,
        )
        return

    # #1790: register the producer-done event BEFORE the first await so the
    # consumer in `_background_finish_photo` — which is dispatched back-to-back
    # with us on the FINISH-state fallback path — sees it as soon as it polls.
    # The `finally` below guarantees `set()` runs on every exit, including
    # early returns and exceptions, so the consumer's bounded wait can't hang.
    producer_done = _rt().asyncio.Event()
    _rt()._stage22_finish_in_flight[printer_id] = producer_done

    # #2547: set once the plate has actually been raised, and read by the
    # `finally` below. Declared out here so a failure anywhere after the move —
    # a camera timeout, a DB error — still lowers the plate again.
    restore_max_z: float | None = None

    try:
        async with _rt().async_session() as db:
            from backend.app.api.routes.settings import get_setting
            from backend.app.models.printer import Printer

            capture_setting = await get_setting(db, "capture_finish_photo")
            if capture_setting is not None and capture_setting.lower() != "true":
                logger.info("[FINISH-PHOTO-MOMENT] capture_finish_photo disabled — skipping pre-capture")
                return

            restore_setting = await get_setting(db, "finish_photo_restore_plate")
            restore_plate_enabled = restore_setting is None or restore_setting.lower() == "true"

            result = await db.execute(select(Printer).where(Printer.id == printer_id))
            printer = result.scalar_one_or_none()
            if printer is None:
                logger.warning(
                    "[FINISH-PHOTO-MOMENT] printer %s not found in DB",
                    printer_id,
                )
                return

        frame_bytes: bytes | None = None
        # #2708: the banked frame arrives already rotated — it comes from
        # `_capture_snapshot_for_notification`, which rotates before returning.
        # Every other source below is a raw grab. Tracking which lets us store
        # exactly one rotation in `_stage22_finish_frames` either way.
        frame_already_rotated = False

        # On the FINISH-state path the End G-code has already run, and two very
        # different situations arrive here needing opposite answers.
        #
        # #1867: if PrintLab injected End G-code into this print, a SwapMod
        # snippet may have ejected the plate — the scene in front of the camera
        # is no longer the finished print, and no amount of moving the plate
        # brings it back. Use the banked in-print frame instead.
        #
        # #2547: otherwise the print is still sitting there, just ~100 mm lower
        # than the camera frames well, and the toolhead is parked out of the
        # way. That is the *best* moment available on firmware that never emits
        # stage 22 (H2C, A1 Mini) — so capture live, after putting the plate
        # back. Preferring the bank here unconditionally, as this code used to,
        # is what shipped a mid-print photo with the toolhead over the part.
        if trigger == "finish_state" and print_dispatch_context.end_gcode_injected(printer_id):
            banked = _rt()._inprint_frame_bank.get(printer_id)
            if banked:
                frame_bytes = banked
                frame_already_rotated = True
                logger.info(
                    "[FINISH-PHOTO-MOMENT] End G-code was injected — using banked in-print "
                    "frame (%d bytes) instead of a post-swap live grab",
                    len(banked),
                )
            else:
                logger.warning(
                    "[FINISH-PHOTO-MOMENT] End G-code was injected for printer %s but the "
                    "in-print bank is empty — falling back to a live grab, which may show a "
                    "swapped or empty plate",
                    printer_id,
                )

        # `restore_max_z` is set only once the plate is actually up, because the
        # `finally` reads it to decide whether it owes a move back down.
        #
        # Never on a print whose End G-code PrintLab injected, even when the bank
        # came up empty above: that machine may have just ejected its plate, and
        # driving Z into whatever a swap mechanism is doing is not a risk worth
        # taking for a photo of a bed we already know may be bare.
        if (
            frame_bytes is None
            and trigger == "finish_state"
            and restore_plate_enabled
            and not print_dispatch_context.end_gcode_injected(printer_id)
        ):
            wants_restore = await _rt()._max_z_for_current_print(printer_id, data, logger)
            if wants_restore is None:
                logger.info(
                    "[PLATE-RESTORE] printer %s: print height unknown — capturing without restore",
                    printer_id,
                )
            elif await _rt()._plate_restore_is_blocked_by_queue(printer_id):
                logger.info(
                    "[PLATE-RESTORE] printer %s has queued work — skipping plate restore",
                    printer_id,
                )
            elif await _rt()._restore_plate_for_finish_photo(printer_id, wants_restore, logger):
                restore_max_z = wants_restore

        if frame_bytes is None and printer.external_camera_enabled and printer.external_camera_url:
            from backend.app.api.routes.camera import live_frame_for_capture
            from backend.app.services.external_camera import capture_frame

            # #2707: this used to collide with the live view and fail, which is
            # how finish-photo notifications went out with no image attached.
            # Leaving frame_bytes None keeps the rest of the fallback chain.
            defer, buffered = live_frame_for_capture(printer_id)
            if defer:
                frame_bytes = buffered
            else:
                frame_bytes = await capture_frame(
                    printer.external_camera_url,
                    printer.external_camera_type or "mjpeg",
                    snapshot_url=printer.external_camera_snapshot_url,
                )
            if frame_bytes:
                logger.info(
                    "[FINISH-PHOTO-MOMENT] captured external-camera frame (%d bytes)",
                    len(frame_bytes),
                )
        elif frame_bytes is None:
            from backend.app.api.routes.camera import get_buffered_frame

            buffered = get_buffered_frame(printer_id)
            if buffered:
                frame_bytes = buffered
                logger.info(
                    "[FINISH-PHOTO-MOMENT] used buffered RTSP frame (%d bytes)",
                    len(frame_bytes),
                )
            else:
                from backend.app.services.camera import capture_camera_frame_bytes

                frame_bytes = await capture_camera_frame_bytes(
                    ip_address=printer.ip_address,
                    access_code=printer.access_code,
                    model=printer.model,
                    timeout=15,
                )
                if frame_bytes:
                    logger.info(
                        "[FINISH-PHOTO-MOMENT] captured RTSP frame (%d bytes)",
                        len(frame_bytes),
                    )

        if frame_bytes:
            if not frame_already_rotated:
                frame_bytes = _rt()._apply_camera_rotation(frame_bytes, printer, logger)
            _rt()._stage22_finish_frames[printer_id] = frame_bytes
        else:
            logger.warning(
                "[FINISH-PHOTO-MOMENT] no frame captured for printer %s — post-completion fallback will retry",
                printer_id,
            )

    except Exception as e:
        logger.warning(
            "[FINISH-PHOTO-MOMENT] pre-capture failed for printer %s: %s",
            printer_id,
            e,
        )
    finally:
        # #2547: we raised the plate, so we own lowering it — including when the
        # capture above failed or threw partway through.
        if restore_max_z is not None:
            try:
                _rt()._park_plate_after_finish_photo(printer_id, restore_max_z, logger)
            except Exception as e:
                logger.warning("[PLATE-RESTORE] printer %s: could not lower plate: %s", printer_id, e)
        # #1790: always unblock the consumer's bounded wait — whether we stored
        # a frame, gave up, or hit an exception. Local ref means cleanup of the
        # dict entry by the consumer doesn't affect signalling.
        producer_done.set()
