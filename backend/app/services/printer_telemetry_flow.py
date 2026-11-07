"""
Drucker-Telemetrie-Abfluss: Callbacks für Schichtwechsel, Fortschritt,
Betttemperatur, Trocknungsende, Spoolzuordnung und Tray-Wechsel.

Zustaende und die von den Tests umgebogenen Namen bleiben im Modul main
und werden über :func:`_rt` gelesen. Aufrufer und Tests sehen keinen
Unterschied.
"""

import importlib
import logging

from sqlalchemy import select

from backend.app.core.websocket import ws_manager
from backend.app.services.completion_photo_plate import (
    _capture_snapshot_for_notification,
    _maybe_bank_inprint_frame,
)
from backend.app.services.notification_service import notification_service
from backend.app.services.printer_manager import printer_manager
from backend.app.services.smart_plug_manager import smart_plug_manager

# der Logger-Name bleibt der der alten Heimat (Backend-Protokolle)
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen."""

    return importlib.import_module("backend.app.main")


async def calibrate_snapshot(printer_id: int, image: bytes) -> bytes | None:
    """Ein gemessenes Bild (Plattenaufsicht) anliefern, wenn eingerückt.

    - Einmessung vorhanden, Warp gelingt: das gewarppte Bild.
    - Einmessung vorhanden, Warp scheitert: ``None`` — ein Vergleich mit
      einer gewarppten Referenz wäre sonst unstatthaft (gewarpt gegen
      ungewarpt). Die Beobachter überspringen die Prüfung dann.
    - Keine Einmessung: das Original — Beobachter ohne Referenz rechnen
      einheitlich mit ungewarpten Bildern weiter, nie mit nichts.
    """
    try:
        from backend.app.services.plate_calibration import has_calibration, warp_snapshot

        if not has_calibration(printer_id):
            return image
        return await warp_snapshot(printer_id, image) or None
    except Exception as exc:  # noqa: BLE001 - Kamerapfad darf nicht abbrechen
        logger.warning("Platteinmessung übersprungen: %s", exc)
        return None


async def on_layer_change(printer_id: int, layer_num: int):
    """Capture timelapse frame on layer change + first layer notification."""
    from backend.app.services.first_layer_inspector import first_layer_inspector as first_layer_service
    from backend.app.services.layer_alerts import layer_alerts as layer_alert_service
    from backend.app.services.part_watcher import part_watcher as part_watcher_service

    await layer_alert_service.observe(printer_id, layer_num, printer_manager.get_client(printer_id))

    # Erste-Schicht-Inspektor: Bild der ersten Schichten ohne Referenz beurteilen.
    fl_client = printer_manager.get_client(printer_id)
    fl_state = fl_client.state if fl_client else None
    if fl_state is not None:
        fl_key = fl_state.subtask_id or fl_state.gcode_file or ""
        if first_layer_service.needs_frame(printer_id, layer_num, fl_key):
            try:
                from backend.app.models.printer import Printer

                async with _rt().async_session() as fl_db:
                    result = await fl_db.execute(select(Printer).where(Printer.id == printer_id))
                    fl_printer = result.scalar_one_or_none()
                    if fl_printer:
                        image = await _capture_snapshot_for_notification(printer_id, fl_printer, logger)
                        image = await calibrate_snapshot(printer_id, image)
                        warning = (
                            first_layer_service.observe(printer_id, layer_num, image, fl_key)
                            if image is not None
                            else None
                        )
                        if warning:
                            # Erste-Schicht-Gate: optional pausieren statt nur warnen —
                            # einmalig je Druck (observe markiert ihn als geprüft).
                            if first_layer_service.pause_on_warning(printer_id) and fl_client.state.state == "RUNNING":
                                try:
                                    await fl_client.pause_print()
                                    warning["paused"] = True
                                    logger.warning(
                                        "Erste Schicht auffällig (Drucker %s) — Druck pausiert.",
                                        printer_id,
                                    )
                                except Exception as pause_exc:  # noqa: BLE001
                                    logger.warning("Pause nach Erste-Schicht-Warnung fehlgeschlagen: %s", pause_exc)
                            await notification_service.on_ai_failure_detection(
                                printer_id,
                                fl_printer.name,
                                fl_state.subtask_name or "",
                                0.5,
                                "first_layer_inspector",
                                fl_db,
                                image_data=image,
                            )
            except Exception as exc:  # noqa: BLE001 - Callback darf nicht abbrechen
                logger.warning("Erste-Schicht-Inspektor fehlgeschlagen: %s", exc)

    # Bauteil-Wächter: Schicht 2 als Referenz, Mitte des Drucks als Vergleich.
    pw_client = printer_manager.get_client(printer_id)
    pw_state = pw_client.state if pw_client else None
    if pw_state is not None:
        pw_key = pw_state.subtask_id or pw_state.gcode_file or ""
        if part_watcher_service.needs_frame(printer_id, layer_num, pw_state.total_layers, pw_key):
            try:
                from backend.app.models.printer import Printer

                async with _rt().async_session() as pw_db:
                    result = await pw_db.execute(select(Printer).where(Printer.id == printer_id))
                    pw_printer = result.scalar_one_or_none()
                    if pw_printer:
                        image = await _capture_snapshot_for_notification(printer_id, pw_printer, logger)
                        image = await calibrate_snapshot(printer_id, image)
                        warning = (
                            part_watcher_service.observe(
                                printer_id,
                                pw_printer.name,
                                layer_num,
                                pw_state.total_layers,
                                image,
                                pw_key,
                            )
                            if image is not None
                            else None
                        )
                        if warning:
                            await notification_service.on_ai_failure_detection(
                                printer_id,
                                pw_printer.name,
                                pw_state.subtask_name or "",
                                0.5,
                                "part_watcher",
                                pw_db,
                                image_data=image,
                            )
            except Exception as exc:  # noqa: BLE001 - Callback darf nicht abbrechen
                logger.warning("Bauteil-Wächter fehlgeschlagen: %s", exc)

    # Kontinuierliche Schichtanalyse & Edge-Spaghetti-Detektor
    from backend.app.services.layer_inspection import layer_inspection_service

    if layer_inspection_service.should_inspect(printer_id, layer_num):
        li_client = printer_manager.get_client(printer_id)
        li_state = li_client.state if li_client else None
        if li_state and li_state.state == "RUNNING":
            try:
                from backend.app.models.printer import Printer

                async with _rt().async_session() as li_db:
                    result = await li_db.execute(select(Printer).where(Printer.id == printer_id))
                    li_printer = result.scalar_one_or_none()
                    if li_printer:
                        raw_image = await _capture_snapshot_for_notification(printer_id, li_printer, logger)
                        if raw_image:
                            calibrated = await calibrate_snapshot(printer_id, raw_image)
                            is_warped = calibrated is not None and calibrated != raw_image
                            image_to_use = calibrated if is_warped else raw_image
                            await layer_inspection_service.observe(
                                printer_id=printer_id,
                                printer_name=li_printer.name,
                                layer_num=layer_num,
                                image_data=image_to_use,
                                client=li_client,
                                db=li_db,
                                task_name=li_state.subtask_name or li_state.gcode_file or "",
                                is_warped=is_warped,
                            )
            except Exception as exc:  # noqa: BLE001 - Callback darf nicht abbrechen
                logger.warning("Kontinuierliche Schichtanalyse fehlgeschlagen: %s", exc)

    from backend.app.services.layer_timelapse import on_layer_change as tl_layer_change

    await tl_layer_change(printer_id, layer_num)

    # #1867: bank a recent in-print frame so the finish-photo path has a
    # pre-End-G-code image to use instead of a live grab of a swapped plate.
    # #2547 added `on_print_progress` as a second driver — this one alone
    # stops firing once the final layer begins.
    await _maybe_bank_inprint_frame(printer_id, layer_num)

    # First layer complete notification (layer_num >= 2 means layer 1 is done).
    # Gate on actual printing state — Bambu firmware ticks layer_num during
    # the pre-print calibration sequence (homing / mesh-level / bed scan /
    # nozzle clean), so a bare layer_num check can fire minutes before the
    # first real extrusion. We require gcode_state == RUNNING and
    # mc_print_sub_stage in (0 = "Printing", None) so calibration sub-stages
    # (1, 9, 14, ...) are excluded. The window widens to [2, 10] because if
    # the layer counter advanced past 2 during PREPARE, the next on_layer_change
    # edge fires later; _first_layer_notified stays clear until we actually send
    # so a deferred re-evaluation can win. See issue #1837.
    first_layer_notified = _rt()._first_layer_notified
    if 2 <= layer_num <= 10 and not first_layer_notified.get(printer_id, False):
        client = printer_manager.get_client(printer_id)
        state = client.state if client else None
        if not state or state.state != "RUNNING":
            return
        if state.mc_print_sub_stage not in (None, 0):
            return
        first_layer_notified[printer_id] = True
        try:
            async with _rt().async_session() as db:
                from backend.app.models.printer import Printer

                result = await db.execute(select(Printer).where(Printer.id == printer_id))
                printer = result.scalar_one_or_none()
                if not printer:
                    return
                printer_name = printer.name
                filename = (state.subtask_name or state.gcode_file or "Unknown") if state else "Unknown"
                total_layers = state.total_layers if state else 0

                image_data = await _capture_snapshot_for_notification(printer_id, printer, logger)
                await notification_service.on_first_layer_complete(
                    printer_id, printer_name, filename, total_layers, db, image_data=image_data
                )
        except Exception as e:
            logger.warning("First layer notification failed: %s", e)


async def on_print_progress(printer_id: int, percent: int):
    """#2547: keep the in-print frame bank fresh through the final layer.

    `on_layer_change` stops the moment the last layer starts, which on the
    H2C capture that closed #2547 left the bank stale for the three minutes
    that layer took. Progress is the only field that keeps advancing there,
    and it freezes before the End G-code runs — so banking on it stays
    inside the print and never sees a swapped plate.
    """
    client = printer_manager.get_client(printer_id)
    state = client.state if client else None
    await _maybe_bank_inprint_frame(printer_id, state.layer_num if state else 0)


async def on_bed_temp_update(printer_id: int, bed_temp: float):
    """Event-driven bed cooldown: fires whenever bed_temper arrives via MQTT."""
    waiter = _rt()._bed_cool_waiters.get(printer_id)
    if not waiter:
        return
    threshold = waiter["threshold"]
    if bed_temp > threshold:
        return
    # Bed is at or below threshold — fire notification and remove waiter
    waiter_info = _rt()._bed_cool_waiters.pop(printer_id, None)
    if not waiter_info:
        return  # Another callback already handled it
    logger.info(
        "[BED-COOL] Bed cooled to %.1f°C on printer %s (threshold: %.0f°C)",
        bed_temp,
        printer_id,
        threshold,
    )
    try:
        printer_info = printer_manager.get_printer(printer_id)
        p_name = printer_info.name if printer_info else "Unknown"
        async with _rt().async_session() as db:
            await notification_service.on_bed_cooled(
                printer_id=printer_id,
                printer_name=p_name,
                bed_temp=bed_temp,
                threshold=threshold,
                filename=waiter_info["filename"],
                db=db,
            )
    except Exception as e:
        logger.warning("[BED-COOL] Failed to send notification: %s", e)


async def on_drying_complete(printer_id: int, ams_id: int):
    """Smart-plug auto-off-after-drying trigger (#1349).

    Fires once per AMS unit when ``dry_time`` falls from >0 to 0. The
    manager walks all plugs linked to this printer and turns off only
    the ones with ``auto_off_after_drying`` enabled, after their
    per-plug delay. Multiple AMS units finishing close together (e.g. a
    dual-AMS dry that ends within the same MQTT push) call this once
    per unit — the manager's ``_cancel_pending_off`` collapses
    repeated scheduling on the same plug to one timer, so duplicate
    fires are safe.
    """
    try:
        async with _rt().async_session() as db:
            await smart_plug_manager.on_drying_complete(printer_id, db)
    except Exception as e:
        logger.warning(
            "Failed to schedule auto-off-after-drying for printer %d (AMS %d): %s",
            printer_id,
            ams_id,
            e,
        )


async def on_assignment_verified(printer_id: int, ams_id: int, tray_id: int, verified: bool, detail: dict):
    """Surface the read-back result of a spool assignment to the UI (#2582).

    The MQTT client confirms (or fails to confirm) that the tray telemetry
    echoed back the filament id we pushed. We relay that as a websocket
    event so the frontend can toast "loaded" / "assignment didn't take"
    instead of the historic silent fire-and-forget, which made the
    AMS→Studio hand-off feel random to users.
    """
    try:
        from backend.app.services.spool_assignment_notifications import (
            _slot_label_from_global_tray,
        )

        if ams_id == 255:
            global_id = 254 + tray_id
        elif ams_id >= 128:
            global_id = ams_id
        else:
            global_id = ams_id * 4 + tray_id
        slot_label = _slot_label_from_global_tray(global_id)

        printer_info = printer_manager.get_printer(printer_id)
        printer_name = printer_info.name if printer_info else f"Printer {printer_id}"

        await ws_manager.broadcast(
            {
                "type": "spool_assignment_verified",
                "printer_id": printer_id,
                "printer_name": printer_name,
                "ams_id": ams_id,
                "tray_id": tray_id,
                "slot": slot_label,
                "verified": verified,
                # Present on success: False means the filament setting landed
                # but the K-profile (cali_idx) did not — the reporter's exact
                # "loaded but no flow profile" symptom.
                "kprofile_applied": detail.get("kprofile_applied", True),
                # Present on failure: whether any tray telemetry was seen in
                # the window (distinguishes "printer silent" from "printer
                # stored something else").
                "saw_tray": detail.get("saw_tray", False),
            }
        )
    except Exception as e:
        logger.warning(
            "Failed to broadcast assignment verification for printer %d AMS%d-T%d: %s",
            printer_id,
            ams_id,
            tray_id,
            e,
        )


async def on_tray_change(printer_id: int, tray_global: int, layer_num: int):
    """Persist a mid-print tray change for completion-time attribution.

    AMS filament backup switches trays without telling the slicer, so the
    tray-change log is the only record of which spool fed which layers.
    Keeping it only in memory meant a restart mid-print charged everything
    to the tray that finished the job.
    """
    try:
        from backend.app.services.usage_tracker import record_tray_change

        async with _rt().async_session() as db:
            await record_tray_change(db, printer_id, tray_global, layer_num)
    except Exception as e:
        logger.warning(
            "Failed to persist tray change for printer %d (tray=%d, layer=%d): %s",
            printer_id,
            tray_global,
            layer_num,
            e,
        )
