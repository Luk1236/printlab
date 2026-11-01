"""Die beiden Auswahlzweige des Druckplaners.

Aus ``queue_pass.py`` ausgelagert: ein Auftrag mit festem Drucker und einer, der
sich einen freien desselben Modells sucht, sind je für sich vollständige
Entscheidungen. Sie teilen nur den Durchlauf, nicht den Code — deshalb ein
Mixin statt zweier freier Funktionen: ``self`` bleibt derselbe ``QueuePass``,
samt Haltegründen, Belegungen und Rückrufen.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import TYPE_CHECKING

from backend.app.models.print_queue import PrintQueueItem
from backend.app.services.scheduler.filament import (
    _candidate_model_label,
    _candidates_for,
    _collapse_waiting_reasons,
    _could_take_printer,
    _filament_constraints,
    _ModelCandidate,
)
from backend.app.services.smart_plug_manager import smart_plug_manager
from backend.app.utils.printer_models import is_gcode_compatible

if TYPE_CHECKING:
    from backend.app.services.scheduler.queue_pass import QueuePass

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen."""
    import importlib

    return importlib.import_module("backend.app.services.print_scheduler")


class SelectionMixin:
    """Die Auswahl für feste Drucker und nach Modell; nutzt den Durchlauf als ``self``."""

    async def _select_pinned(self: QueuePass, item: PrintQueueItem) -> None:
        """Auftrag mit festem Drucker: kann er ihn in dieser Runde nehmen?

        Jeder Ausstieg schreibt einen Haltegrund an die Zeile, damit die
        Warteschlange sagt, worauf der Auftrag wartet. Abgesetzt wird nicht
        hier, sondern über ``dispatch_ids`` im Abschluss der Runde.
        """
        # Held by a sensor interlock (#1148). Checked before the
        # busy_printers test that would otherwise swallow it
        # silently — "waiting for a printer" and "waiting for you
        # to shut the enclosure" need to read differently, and only
        # one of them is something the user can fix.
        #
        # It used to be the only thing that wrote a waiting_reason on
        # this branch, and it cleared the field up front so a lifted
        # hold could not leave a shut door reading "Waiting on
        # Enclosure Door". `hold_item` carries that guarantee now —
        # every exit below writes — so the clear is gone and the
        # interlock is an ordinary hold like the rest (#3074).
        interlock_reason = self.interlocked.get(item.printer_id)
        if interlock_reason:
            # Silent, exactly as it has always been. #1148 built this
            # as a hold that shows on the row, never as an alert, and
            # routing it through the shared writer must not quietly
            # turn every open door into a notification.
            await self.hold_item(item, f"Waiting on {interlock_reason}", notify=False)
            self.skip_reasons["sensor_interlock"] = self.skip_reasons.get("sensor_interlock", 0) + 1
            return

        # Specific printer assignment (existing behavior)
        if item.printer_id in self.busy_printers:
            # Whatever took the printer out of this pass — a print
            # already running on it, a post-dispatch hold, an upload
            # still in flight, an item ahead of this one in the same
            # pass — reads the same way from the queue: the printer is
            # taken and this item is in line for it. The exceptions
            # that do not (an offline printer, say) recorded their own
            # wording in `item_hold_reasons` when they held it.
            await self.hold_item(
                item,
                self.item_hold_reasons.get(item.printer_id) or f"Busy: {self.printer_label(item.printer_id)}",
                notify=item.printer_id not in self.silent_hold_printers,
            )
            return

        # Check if printer is idle
        printer_idle = self._s._is_printer_idle(item.printer_id, self.require_plate_clear)
        printer_connected = _rt().printer_manager.is_connected(item.printer_id)

        # If printer not connected, try to power on via smart plug
        if not printer_connected:
            plugs = await self._s._get_smart_plugs(self.db, item.printer_id)
            auto_on_plugs = [p for p in plugs if p.auto_on and p.enabled]
            if auto_on_plugs:
                logger.info("Printer %s offline, attempting to power on via smart plug(s)", item.printer_id)
                # Power on using the plug that actually feeds the printer, and
                # wait for it to boot on that one only (#2629).
                primary_plug = self._s._pick_power_plug(auto_on_plugs)
                powered_on = await self._s._power_on_and_wait(primary_plug, item.printer_id, self.db)
                if powered_on:
                    # Also turn on any remaining auto_on plugs (e.g., filter)
                    for extra_plug in [p for p in auto_on_plugs if p.id != primary_plug.id]:
                        try:
                            service = await smart_plug_manager.get_service_for_plug(extra_plug, self.db)
                            await service.turn_on(extra_plug)
                            logger.info("Also powered on plug '%s' for printer %s", extra_plug.name, item.printer_id)
                        except Exception as e:
                            logger.warning("Failed to power on extra plug '%s': %s", extra_plug.name, e)
                    printer_connected = True
                    printer_idle = self._s._is_printer_idle(item.printer_id, self.require_plate_clear)
                else:
                    logger.warning("Could not power on printer %s via smart plug", item.printer_id)
                    await self.hold_for_printer(
                        item,
                        item.printer_id,
                        "smart-plug power-on failed",
                        f"Offline: {self.printer_label(item.printer_id)} — the smart plug could not power it on",
                    )
                    return
            else:
                # No plug or auto_on disabled. Worded exactly as the
                # model-based branch words it (#2786): this is the one
                # entry on that list the user has to act on, because
                # PrintLab will never switch this printer on itself.
                await self.hold_for_printer(
                    item,
                    item.printer_id,
                    "offline, with no smart plug to power it on",
                    f"Offline, no Auto On smart plug: {self.printer_label(item.printer_id)}",
                )
                return

        # Check if printer is idle (busy with another print)
        if not printer_idle:
            await self.hold_for_printer(
                item,
                item.printer_id,
                "not idle",
                self._s._pinned_hold_reason(
                    item.printer_id, self.printer_label(item.printer_id), self.require_plate_clear
                ),
            )
            return

        # Drying blocks the queue, if the user asked it to. A hold
        # is a skip like any other, so it belongs here with the
        # rest of the availability checks.
        # A parked timer (#2896) never ends, so it must not hold the
        # queue; it stays tracked so the stop paths still reach it.
        if (
            self._s._drying_in_progress.get(item.printer_id)
            and not self._s._drying_is_only_parked(item.printer_id)
            and await self._s._get_bool_setting(self.db, "queue_drying_block")
        ):
            # Busy-shaped on purpose: the cycle ends on its own and
            # the job goes out, so there is nothing to alert about.
            await self.hold_for_printer(
                item,
                item.printer_id,
                "drying, and drying is set to block the queue",
                f"Busy: {self.printer_label(item.printer_id)} (drying)",
            )
            return

        # Check condition (previous print success)
        if item.require_previous_success:
            if not await self._s._check_previous_success(self.db, item):
                item.status = "skipped"
                item.error_message = "Previous print failed or was aborted"
                item.completed_at = _rt().datetime.now(timezone.utc)
                # Not pending any more, so not waiting for anything.
                item.waiting_reason = None
                await self.db.commit()
                logger.info("Skipped queue item %s - previous print failed", item.id)

                # Send notification
                job_name = await self._s._get_job_name(self.db, item)
                printer = await self._s._get_printer(self.db, item.printer_id)
                await _rt().notification_service.on_queue_job_skipped(
                    job_name=job_name,
                    printer_id=item.printer_id,
                    printer_name=printer.name if printer else "Unknown",
                    reason="Previous print failed or was aborted",
                    db=self.db,
                )
                return

        # Resolve the AMS mapping when it's missing OR unresolved
        # (all -1). A stored all-[-1] mapping is a bug artifact — a
        # frontend status-load race can persist [-1] (#2589) — and
        # must be recomputed from live trays rather than trusted.
        unmappable = await self._s._ensure_ams_mapping(self.db, item.printer_id, item)
        if unmappable:
            await self._s._fail_unmappable_item(self.db, item, item.printer_id, unmappable)
            return

        # Filament-deficit pre-dispatch check (#1496). If the
        # assigned spool can't satisfy any required slot grams,
        # promote the item to manual_start so the user must
        # acknowledge via the ▶ button (which re-checks live).
        if await self._s._block_on_filament_deficit(self.db, item):
            # Now staged for the user to start by hand, and the row
            # shows the filament-short badge instead. Cleared because
            # a staged item never reaches this branch again.
            await self.hold_item(item, None)
            return

        # Hold this item back for the next pass rather than racing
        # another dispatch over the same transient library row. The
        # printer is still marked busy so a later item does not jump
        # its place in this printer's queue.
        if self._library_row_conflict(item):
            self.skip_reasons["library_row_in_use"] = self.skip_reasons.get("library_row_in_use", 0) + 1
            await self.hold_for_printer(
                item,
                item.printer_id,
                "holding its place while another item releases a library row",
                f"Busy: {self.printer_label(item.printer_id)}",
            )
            return

        # Print takes priority: stop a cycle PrintLab armed, now
        # that this item is definitely going out.
        #
        # Placement is the whole point (#2801). This used to sit up
        # with the availability checks, inside the not-idle branch
        # -- so it fired only on the passes where the print was NOT
        # going to start, and never on the ones where it was.
        # Drying is not one of the things `_is_printer_idle` looks
        # at, so a stop could never have unblocked that printer
        # anyway; the cycle was spent for nothing, auto-drying
        # re-armed on the next tick, and a plate left
        # unacknowledged turned that into a loop on the scheduler
        # interval. Every skip between there and here -- a failed
        # previous print, an unmappable item, a filament deficit, a
        # contested library row -- is another way to lose a cycle
        # for a print that never happens, which is why this waits
        # until the decision is actually made.
        if self._s._drying_in_progress.get(item.printer_id) and not await self._s._drying_may_continue_through_print(
            self.db, item.printer_id
        ):
            await self._s._stop_drying(item.printer_id)

        # Queue the dispatch instead of running it here — see
        # _dispatch_selected(). busy_printers still gets the printer
        # immediately, so nothing else in this pass can target it.
        #
        # The reason goes first: this item is not waiting for anything
        # any more, and the model-based branch clears its own at the
        # equivalent moment (#3074).
        await self.hold_item(item, None)
        self._claim_library_row(item)
        self.dispatch_ids.append(item.id)
        self.claim_printer(item.printer_id)

        # SJF starvation guard: mark items that were jumped
        if self.sjf_enabled and item.print_time_seconds is not None:
            pinned_model = self.pinned_printers.get(item.printer_id, ("", ""))[1]
            for other in self.items:
                if (
                    other.id != item.id
                    and other.id not in self.dispatch_ids
                    and other.status == "pending"
                    and _could_take_printer(other, item.printer_id, pinned_model)
                    and not other.been_jumped
                    and other.position < item.position
                    and (other.print_time_seconds is None or other.print_time_seconds > item.print_time_seconds)
                ):
                    other.been_jumped = True
            await self.db.commit()

    async def _select_for_model(self: QueuePass, item: PrintQueueItem) -> None:
        """Auftrag ohne festen Drucker: einen freien desselben Modells suchen.

        Bei einem Auftrag über mehrere Modelle (Varianten) wird in der
        Reihenfolge der Varianten der erste passende Drucker genommen, damit
        die Wahl bei mehreren freien Geräten wiederholbar bleibt.
        """
        # Model-based assignment - find any idle printer of matching model.
        # A plain model-based item has exactly one candidate, built from
        # its own columns. A cross-model item (#671) has one per sliced
        # variant and takes the first that matches, walking them in the
        # user's priority order so the pick is reproducible when more
        # than one printer is free in the same pass.
        candidates = _candidates_for(item)
        printer_id = None
        chosen: _ModelCandidate | None = None
        per_model_reasons: list[tuple[str | None, str]] = []
        # Candidates that cleared the cross-model gate below. The
        # smart-plug wake step may only consider these — waking a
        # printer for a file that can never legally run on it is
        # worse than not waking at all (#2786).
        wakeable_candidates: list[_ModelCandidate] = []

        if not candidates:
            # Every candidate file has been deleted or trashed out from
            # under this item. Hold it with something the user can act
            # on rather than letting it look dispatchable forever.
            per_model_reasons.append(
                (
                    item.target_model,
                    "Every file for this job has been deleted — add a file back or remove the item",
                )
            )

        for candidate in candidates:
            effective_types, filament_overrides = _filament_constraints(candidate)

            # Cross-model safety gate (#2578): never hand a 3MF sliced
            # for an incompatible model to a printer, no matter how the
            # row got into the DB (old rows, direct API writes). Held
            # as pending with an actionable waiting_reason — the user
            # fixes it by editing the item's target model.
            if not is_gcode_compatible(candidate.sliced_for, candidate.target_model):
                per_model_reasons.append(
                    (
                        candidate.target_model,
                        f"File was sliced for {candidate.sliced_for}, which is not compatible with "
                        f"{candidate.target_model} — edit the item and fix its target model",
                    )
                )
                self.skip_reasons["sliced_model_mismatch"] = self.skip_reasons.get("sliced_model_mismatch", 0) + 1
                continue

            wakeable_candidates.append(candidate)
            match_id, match_reason = await self._s._find_idle_printer_for_model(
                self.db,
                candidate.target_model,
                # Sensor-held printers are unavailable to the
                # matcher but stay out of busy_printers itself
                # (#1148) — see where `interlocked` is built.
                self.busy_printers | self.interlocked.keys(),
                effective_types,
                item.target_location,
                filament_overrides=filament_overrides,
                require_plate_clear=self.require_plate_clear,
                wakeable_ids=self.wakeable_printer_ids,
            )
            if match_id:
                printer_id = match_id
                chosen = candidate
                break
            per_model_reasons.append((candidate.target_model, match_reason or ""))

        # Nothing is available and nothing has been woken this pass:
        # switch one matching printer on. Assignment is left to the
        # next pass, which sees the booted printer's live state
        # instead of guessing at it seconds after connect (#2786).
        if printer_id is None and not self.power_on_attempted and wakeable_candidates:
            woken_id, attempted_id = await self._s._wake_printer_for_model(
                self.db,
                wakeable_candidates,
                item.target_location,
                self.busy_printers | self.interlocked.keys(),
                self.wakeable_printer_ids,
                self.require_plate_clear,
            )
            # An attempt spends the pass's one wake whether or not
            # it worked: it has already blocked the queue loop for
            # the boot wait. A failed printer is held out of later
            # passes by its own cool-off, deliberately NOT by
            # busy_printers — it is off, not busy, and labelling it
            # busy would both misdescribe it in every later item's
            # waiting reason and suppress the notification, since
            # an all-busy reason is treated as needing no action.
            self.power_on_attempted = attempted_id is not None
            if woken_id is not None:
                # Hold this item back rather than dispatching onto a
                # printer whose AMS has not reported yet.
                self.skip_reasons["powered_on_printer"] = self.skip_reasons.get("powered_on_printer", 0) + 1
                return

        waiting_reason = None if printer_id else _collapse_waiting_reasons(per_model_reasons)

        # Fold the winning variant's file and settings onto the item
        # before anything else looks at them — the guards below and
        # every step of the dispatch read the item's own columns.
        if chosen is not None:
            self._s._resolve_variant(item, chosen)

        # Update waiting_reason if changed and send notification when first waiting
        if item.waiting_reason != waiting_reason:
            was_waiting = item.waiting_reason is not None
            item.waiting_reason = waiting_reason
            await self.db.commit()

            # Send waiting notification only when transitioning to waiting state
            # and the reason requires user action (not just "all printers busy")
            if waiting_reason and not was_waiting and not self._s._is_busy_only(waiting_reason):
                job_name = await self._s._get_job_name(self.db, item)
                await _rt().notification_service.on_queue_job_waiting(
                    job_name=job_name,
                    target_model=_candidate_model_label(candidates) or item.target_model,
                    waiting_reason=waiting_reason,
                    db=self.db,
                )

        if printer_id:
            # Before claiming the printer: hold back rather than race
            # another dispatch over the same transient library row.
            # Checked here so a held item does not get a printer
            # assigned and then sit on it. See _library_row_conflict().
            #
            # No busy_printers.add() here, unlike the fixed-printer
            # branch above: that one protects its printer's own queue
            # ordering, but this item was never assigned to `printer_id`
            # — the matcher merely offered it. Marking it busy would
            # strand an idle printer for the rest of the pass.
            if self._library_row_conflict(item):
                self.skip_reasons["library_row_in_use"] = self.skip_reasons.get("library_row_in_use", 0) + 1
                return

            # Check condition (previous print success) before assigning
            if item.require_previous_success:
                if not await self._s._check_previous_success(self.db, item):
                    item.status = "skipped"
                    item.error_message = "Previous print failed or was aborted"
                    item.completed_at = _rt().datetime.now(timezone.utc)
                    await self.db.commit()
                    logger.info("Skipped queue item %s - previous print failed", item.id)

                    # Send notification
                    job_name = await self._s._get_job_name(self.db, item)
                    printer = await self._s._get_printer(self.db, printer_id)
                    await _rt().notification_service.on_queue_job_skipped(
                        job_name=job_name,
                        printer_id=printer_id,
                        printer_name=printer.name if printer else "Unknown",
                        reason="Previous print failed or was aborted",
                        db=self.db,
                    )
                    return

            # Assign printer and start - clear waiting reason
            item.printer_id = printer_id
            item.waiting_reason = None
            logger.info("Model-based assignment: queue item %s assigned to printer %s", item.id, printer_id)

            # Send assignment notification
            job_name = await self._s._get_job_name(self.db, item)
            printer = await self._s._get_printer(self.db, printer_id)
            await _rt().notification_service.on_queue_job_assigned(
                job_name=job_name,
                printer_id=printer_id,
                printer_name=printer.name if printer else "Unknown",
                target_model=item.target_model,
                db=self.db,
            )

            # Resolve the AMS mapping for the assigned printer when it's
            # missing OR unresolved (all -1). Critical for model-based
            # jobs where mapping wasn't computed upfront, and it also
            # self-heals a bogus stored [-1] (#2589).
            unmappable = await self._s._ensure_ams_mapping(self.db, printer_id, item)
            if unmappable:
                await self._s._fail_unmappable_item(self.db, item, printer_id, unmappable)
                return

            # Filament-deficit pre-dispatch check (#1496).
            if await self._s._block_on_filament_deficit(self.db, item):
                return

            self._claim_library_row(item)
            self.dispatch_ids.append(item.id)
            self.claim_printer(printer_id)

            # SJF starvation guard: mark items that were jumped
            if self.sjf_enabled and item.print_time_seconds is not None:
                for other in self.items:
                    if (
                        other.id != item.id
                        and other.id not in self.dispatch_ids
                        and other.status == "pending"
                        and _could_take_printer(other, printer_id, item.target_model)
                        and not other.been_jumped
                        and other.position < item.position
                        and (other.print_time_seconds is None or other.print_time_seconds > item.print_time_seconds)
                    ):
                        other.been_jumped = True
                await self.db.commit()
