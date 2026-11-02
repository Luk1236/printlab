"""Start-Wächter des Druckplaners nach dem Absetzen eines Druckbefehls.

Aus ``print_scheduler.py`` ausgelagert: beobachtet in zwei Phasen, ob der
Drucker den ``project_file``-Befehl annimmt und in einen aktiven Druckzustand
wechselt, oder setzt den Auftrag andernfalls zurück. ``PrintScheduler`` erbt
die Methode über :class:`WatchdogMixin`.
"""

from __future__ import annotations

import importlib
from datetime import timezone

from sqlalchemy import update

from backend.app.models.print_queue import PrintQueueItem, PrintQueueVariant


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen."""
    return importlib.import_module("backend.app.services.print_scheduler")


class WatchdogMixin:
    """Überwachung des Druckstarts nach dem Senden von ``project_file``."""

    @staticmethod
    async def _watchdog_print_start(
        queue_item_id: int,
        printer_id: int,
        pre_state: str,
        pre_subtask_id: str | None = None,
        pre_gcode_file: str | None = None,
        timeout: float = 90.0,
        phase_b_timeout: float = 180.0,
        poll_interval: float = 3.0,
        created_by_id: int | None = None,
    ) -> None:
        """Revert a queue item if the printer never acknowledges the start command.

        PrintLab optimistically marks the queue item as "printing" right after the
        MQTT project_file publish succeeds locally. The watchdog runs in two phases:

        Phase A (up to ``timeout``): wait for either an active-state transition
        or a ``subtask_id`` advance past ``pre_subtask_id``. State alone is the
        primary signal; subtask_id advance handles the H2D case where state can
        sit at FINISH for ~50 s after the printer accepted ``project_file``
        before flipping to PREPARE (#1078). If neither happens, the MQTT publish
        was lost on a half-broken session (#887/#936) — revert and force
        reconnect (the #967 recovery path).

        Phase B (up to ``phase_b_timeout``, only if Phase A exited on subtask_id
        alone): keep watching for the active-state transition. subtask_id alone
        proves the file landed but not that the printer started — and a printer
        that accepts the command but stays at IDLE/FINISH indefinitely (e.g.
        cloud+LAN re-auth dance after a power cycle on old firmware, #1678)
        used to leave the queue item stuck in 'printing' forever because the
        old watchdog returned success as soon as subtask_id advanced. If Phase
        B times out, revert the queue item so the user can retry without
        restarting PrintLab. Skip ``force_reconnect`` here: the file landed and
        a forced reconnect mid-parse triggers 0500_4003 (#1150).

        Phase A timeout raised from 45 s → 90 s as belt-and-braces for slow
        transitions that also don't emit an early subtask_id tick.

        Both phases also watch for ``HMS_MQTT_VERIFY_FAILED``. A printer that
        refuses to verify our commands will never start this job or any other,
        so waiting out the full 270 s and re-uploading the 3MF twice more only
        burns an upload slot the rest of the farm is queued behind — that path
        is for a printer that might still come good, which this one cannot
        (#2732). It fails the item on the spot with the actual reason instead.
        """
        rt = _rt()
        last_status = None
        landed_on_subtask = False
        # Latched, not level-tested: state.hms_errors is rebuilt from scratch on
        # every push carrying an `hms` key, so the fault can come and go between
        # 3-second polls. Seeing it once inside the dispatch window is enough.
        command_rejected = False
        # Latched for the same reason as command_rejected: drying can finish, or
        # be stopped by the user, part-way through the dispatch window. Seeing it
        # once is what matters — it is the state the printer was in when it
        # declined to start (#2758).
        drying_ams_ids: list[int] = []
        deadline = rt.time.monotonic() + timeout
        while rt.time.monotonic() < deadline:
            await rt.asyncio.sleep(poll_interval)
            status = rt.printer_manager.get_status(printer_id)
            if not status:
                # Printer disconnected — don't mess with the DB. Drop the
                # in-memory dispatch hold too so a fresh dispatch can retry
                # once the printer comes back; the hard timeout would
                # otherwise hold the printer unnecessarily.
                rt.scheduler._release_dispatch_hold(printer_id)
                return
            last_status = status
            if status.state in rt._ACTIVE_PRINT_STATES:
                # Printer is actively processing the job — release the
                # post-dispatch hold so the next pending item for this printer
                # can be evaluated normally. We do NOT accept arbitrary state
                # transitions: a printer going FINISH -> IDLE (user dismissed
                # the post-print prompt without accepting our project_file)
                # would otherwise look like "command landed" and leave the
                # queue item stuck in 'printing' forever (#1370).
                rt.scheduler._release_dispatch_hold(printer_id)
                try:
                    await rt.ws_manager.send_queue_item_acked(
                        user_id=created_by_id,
                        queue_item_id=queue_item_id,
                        printer_id=printer_id,
                    )
                except Exception:
                    rt.logger.debug("Could not send the queue-item acked event", exc_info=True)
                return
            drying_ams_ids = drying_ams_ids or rt._drying_ams_ids(status)
            # Checked only after the active-state exit above: a stale HMS left
            # over from an earlier job must never abort a print that is visibly
            # running. An actually-refused command leaves the printer idle, so
            # this ordering costs the detection nothing.
            if rt._mqtt_commands_rejected(status):
                command_rejected = True
                break
            if pre_subtask_id is not None and status.subtask_id is not None and status.subtask_id != pre_subtask_id:
                # Phase A exit — printer accepted the file (subtask_id flipped
                # to our submission id). Don't return yet: the printer may
                # have accepted the command but never actually start (e.g.
                # cloud+LAN re-auth dance after a power cycle, #1678). Phase
                # B watches for the active-state transition.
                landed_on_subtask = True
                break

        if landed_on_subtask and not command_rejected:
            phase_b_deadline = rt.time.monotonic() + phase_b_timeout
            while rt.time.monotonic() < phase_b_deadline:
                await rt.asyncio.sleep(poll_interval)
                status = rt.printer_manager.get_status(printer_id)
                if not status:
                    rt.scheduler._release_dispatch_hold(printer_id)
                    return
                last_status = status
                if status.state in rt._ACTIVE_PRINT_STATES:
                    rt.scheduler._release_dispatch_hold(printer_id)
                    try:
                        await rt.ws_manager.send_queue_item_acked(
                            user_id=created_by_id,
                            queue_item_id=queue_item_id,
                            printer_id=printer_id,
                        )
                    except Exception:
                        rt.logger.debug("Could not send the queue-item acked event", exc_info=True)
                    return
                drying_ams_ids = drying_ams_ids or rt._drying_ams_ids(status)
                # Same ordering rule as Phase A: a running print wins over a
                # lingering HMS.
                if rt._mqtt_commands_rejected(status):
                    command_rejected = True
                    break

        # No active-state transition. Revert the item so the scheduler can retry.
        # Drop the in-memory hold so the retry isn't blocked by it.
        rt.scheduler._release_dispatch_hold(printer_id)

        # Logged on every failed dispatch window, not just the last one, so a
        # support bundle shows the correlation from the first attempt rather than
        # only after the retry budget is spent (#2758).
        if drying_ams_ids:
            rt.logger.info(
                "Queue item %s: printer %d never started while AMS %s drying — this may be why, see #2758",
                queue_item_id,
                printer_id,
                ", ".join(str(i) for i in drying_ams_ids),
            )

        # Four outcomes from the revert attempt, each routed differently:
        #   "reverted":          row flipped from printing -> pending, run recovery
        #   "gave_up":           same, but the retry budget is spent — row failed
        #                        rather than pending, so it stops going round again
        #   "already_moved_on":  item.status != 'printing' (completed/cancelled by
        #                        on_print_complete or user). Skip recovery entirely
        #                        — the print clearly landed somewhere even if the
        #                        watchdog didn't see the active-state transition.
        #   "revert_failed":     SQLite contention exhausted retries. Still run
        #                        recovery so the MQTT session gets a fresh client_id
        #                        on the half-broken-session path.
        #
        # The retry budget (#2555): reverting to 'pending' hands the item straight
        # back to the next queue pass, which re-uploads the whole 3MF and waits out
        # the watchdog again. For a printer that is genuinely wedged that loop never
        # ends — the reporter had one printer "since this morning still not launch"
        # — and each lap also consumes an upload slot that the other printers in the
        # farm are waiting on. Retrying is right; retrying forever is not.
        async def _do_revert(db):
            item = await db.get(PrintQueueItem, queue_item_id)
            if not item or item.status != "printing":
                return "already_moved_on"
            item.dispatch_attempts = (item.dispatch_attempts or 0) + 1
            item.started_at = None
            # Charge the attempt to the candidate that was actually dispatched, so
            # a cross-model item (#671) reaches for its other file next lap instead
            # of retrying the printer that just failed to start. Matched by file
            # because that is what the resolver copied onto the row.
            if item.library_file_id is not None:
                await db.execute(
                    update(PrintQueueVariant)
                    .where(PrintQueueVariant.queue_item_id == item.id)
                    .where(PrintQueueVariant.library_file_id == item.library_file_id)
                    .values(attempt_count=PrintQueueVariant.attempt_count + 1)
                )
            if command_rejected:
                # No retry budget for this one: the printer refused to verify the
                # command, and re-uploading the same 3MF to the same printer will
                # be refused the same way. Fail now with the fix rather than after
                # three laps of a message about SD cards (#2732).
                item.status = "failed"
                item.error_message = (
                    "The printer rejected the print command: MQTT command verification failed "
                    "(HMS 0500-0500-0001-0007). Enable Developer Mode on the printer, restart it, "
                    "then start the job again."
                )
                item.completed_at = rt.datetime.now(timezone.utc)
                await db.commit()
                return "command_rejected"
            if item.dispatch_attempts >= rt.DISPATCH_MAX_ATTEMPTS:
                item.status = "failed"
                if drying_ams_ids:
                    # #2758: the generic message below sent the reporter looking
                    # at the SD card while the actual obstacle — AMS units in a
                    # drying cycle — was on screen the whole time. Name what we
                    # observed and let the user judge it; PrintLab does not stop
                    # the cycle itself, because on this hardware drying can run
                    # alongside a print and stopping it may not be the fix.
                    units = ", ".join(f"AMS {i}" for i in drying_ams_ids)
                    item.error_message = (
                        f"The printer accepted the file but never started printing, after "
                        f"{item.dispatch_attempts} attempts. {units} "
                        f"{'was' if len(drying_ams_ids) == 1 else 'were'} drying throughout — "
                        f"some printers refuse to begin a print while an AMS is in a drying "
                        f"cycle, and an AMS drying without its external power supply can also "
                        f"leave too little power for the start-of-print calibration. Stop the "
                        f"drying, or connect the AMS power supply, and start the job again."
                    )
                else:
                    item.error_message = (
                        f"The printer accepted the file but never started printing, after "
                        f"{item.dispatch_attempts} attempts. Check the printer's screen for a "
                        f"prompt or error, confirm its SD card is readable, and start the job again."
                    )
                item.completed_at = rt.datetime.now(timezone.utc)
                await rt.release_budget_reservation(
                    db,
                    source_type="print_queue",
                    source_id=item.id,
                    status="released",
                )
                await db.commit()
                return "gave_up"
            item.status = "pending"
            await db.commit()
            return "reverted"

        try:
            revert_outcome = await rt.run_with_retry(_do_revert, label=f"watchdog revert item={queue_item_id}")
        except Exception as e:
            rt.logger.warning(
                "Queue item %s: failed to revert to 'pending' (printer %d): %s — "
                "scheduler may keep treating this item as in-flight",
                queue_item_id,
                printer_id,
                e,
            )
            revert_outcome = "revert_failed"

        if revert_outcome == "already_moved_on":
            # Preserves the pre-#1370 early-return: if on_print_complete (or any
            # other path) already moved the item past 'printing', don't run the
            # MQTT session-recovery logic below — a forced reconnect on a healthy
            # session breaks ongoing prints on the same printer.
            return

        total_timeout = timeout + (phase_b_timeout if landed_on_subtask else 0.0)
        if revert_outcome == "command_rejected":
            rt.logger.error(
                "Queue item %s: printer %d reported HMS %s (MQTT command verification "
                "failed) — the print command was rejected, not lost. Failing the item "
                "without retrying; enable Developer Mode on the printer and restart it (#2732)",
                queue_item_id,
                printer_id,
                rt.HMS_MQTT_VERIFY_FAILED,
            )
            await rt.scheduler._notify_dispatch_gave_up(
                queue_item_id,
                printer_id,
                created_by_id,
                reason="Printer rejected the print command (MQTT command verification failed)",
            )
            # Same reasoning as the landed_on_subtask path below: the file is on
            # the printer and a forced reconnect would only add 0500_4003 to a
            # problem that has nothing to do with the MQTT session (#1150).
            return
        if revert_outcome == "gave_up":
            rt.logger.error(
                "Queue item %s: printer %d never started the print after %d dispatch "
                "attempts (last one waited %.0fs) — marking the item failed instead of "
                "re-uploading it again (#2555)",
                queue_item_id,
                printer_id,
                rt.DISPATCH_MAX_ATTEMPTS,
                total_timeout,
            )
            await rt.scheduler._notify_dispatch_gave_up(queue_item_id, printer_id, created_by_id)
        elif revert_outcome == "reverted":
            if landed_on_subtask:
                rt.logger.warning(
                    "Queue item %s: printer %d accepted project_file (subtask_id "
                    "advanced) but never transitioned to an active state within "
                    "%.0fs — printer wedged post-acceptance; reverted to 'pending' "
                    "for retry (#1678)",
                    queue_item_id,
                    printer_id,
                    total_timeout,
                )
            else:
                rt.logger.warning(
                    "Queue item %s: printer %d did not respond to print command within "
                    "%.0fs (state still %s, subtask_id still %s) — reverted to 'pending' "
                    "for retry (#967)",
                    queue_item_id,
                    printer_id,
                    timeout,
                    pre_state,
                    pre_subtask_id,
                )

        # Phase B was entered iff subtask_id advanced, which means the
        # project_file landed on the printer. A forced reconnect at this point
        # would interrupt the printer's parse and trigger 0500_4003 (#1150) —
        # skip the recovery entirely.
        if landed_on_subtask:
            return

        # Phase A timeout path: if the printer's gcode_file changed since
        # pre-dispatch, the project_file command landed and the printer is
        # parsing — a forced reconnect mid-parse triggers 0500_4003 (#1150).
        # If gcode_file is unchanged, the publish was silently swallowed
        # (#887/#936) and force_reconnect recovery is what we want.
        client = rt.printer_manager.get_client(printer_id)
        current_gcode_file = getattr(last_status, "gcode_file", None) if last_status else None
        publish_landed = current_gcode_file is not None and current_gcode_file != pre_gcode_file
        if publish_landed:
            rt.logger.warning(
                "Queue item %s: gcode_file changed to %r (was %r) — printer "
                "received the command and is parsing slowly. Skipping forced "
                "MQTT reconnect to avoid 0500_4003 mid-parse (#1150).",
                queue_item_id,
                current_gcode_file,
                pre_gcode_file,
            )
        elif client and hasattr(client, "force_reconnect_stale_session"):
            client.force_reconnect_stale_session(
                f"queue print command unacknowledged after {timeout:.0f}s "
                f"(state still {pre_state}, gcode_file {current_gcode_file!r})"
            )
