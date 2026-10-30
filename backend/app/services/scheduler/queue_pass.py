"""Eine Runde des Druckplaners über die Warteschlange.

Aus ``print_scheduler.check_queue`` ausgelagert. Der Durchlauf trug seinen
gesamten Zustand — belegte Drucker, Haltegründe, Rücksichten, Sammellisten —
als lokale Variablen und gab ihn an sieben verschachtelte Funktionen weiter, die
ihn mit ``nonlocal``-artigen Zugriffen mitveränderten. Hier ist dieser Zustand
ein Attribut des Durchlaufs: :class:`QueuePass` wird für eine Runde angelegt,
läuft einmal und wird verworfen. Die Helfer sind dadurch echte Methoden statt
Closures.

Die Namen, die die Tests im Modul ``print_scheduler`` patchen
(``printer_manager``, ``time``, ``datetime``, ``async_session``,
``notification_service``, ``ha_sensor_manager``), werden über das Fassadenmodul
aufgelöst — sonst liefen die Attrappen nach dem Umzug ins Leere. Der Planer
selbst hängt als ``self._s`` daran, damit seine Methoden unverändert erreichbar
bleiben.
"""

import logging
from datetime import timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.models.print_queue import PrintQueueItem, PrintQueueVariant
from backend.app.models.printer import Printer
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
    from backend.app.services.print_scheduler import PrintScheduler

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen."""
    import importlib

    return importlib.import_module("backend.app.services.print_scheduler")


class QueuePass:
    """Ein Durchlauf über die Warteschlange: Zustand plus die Schritte dazu."""

    def __init__(self, scheduler: "PrintScheduler") -> None:
        self._s = scheduler

    async def run(self) -> bool:
        """Die Runde ausführen; True, wenn etwas abgesetzt wurde oder noch läuft."""
        async with _rt().async_session() as self.db:
            if not await self._collect():
                return bool(self._s._inflight)
            await self._select()
            return await self._finish()

    async def _collect(self) -> bool:
        """Die fälligen Aufträge holen und die Einstellungen dieser Runde lesen.

        False, wenn nichts abzusetzen ist — dann sind die Prüfungen, die auch
        bei leerer Warteschlange laufen (Trocknung, Filament, Bestand, Warmhalten),
        hier schon erledigt.
        """
        # Check if shortest-job-first scheduling is enabled
        self.sjf_enabled = await self._s._get_bool_setting(self.db, "queue_shortest_first")

        # Get all pending items in the one order the queue page shows them
        # in (#3200). The first eligible item takes a printer, so this order
        # decides who wins a printer that a pinned job and an "Any <model>"
        # job both want. It used to start with ``printer_id``, which made the
        # lane outrank the position: SQLite sorts NULL first, so model-based
        # jobs always won; PostgreSQL sorts it last, so pinned jobs did.
        # Neither is what the user dragged into place.
        if self.sjf_enabled:
            # SJF: items already jumped get top priority (starvation guard),
            # then sort by print_time ascending. Items with no print time go
            # last, and position breaks ties.
            result = await self.db.execute(
                select(PrintQueueItem)
                .where(PrintQueueItem.status == "pending")
                # Never re-select a row a dispatch worker has already claimed
                # (#2615) — belt-and-suspenders with the _inflight exclusion
                # below, and the guard that lets an orphaned claim be ignored
                # until startup reconciliation clears it.
                .where(PrintQueueItem.dispatching_at.is_(None))
                # archive/library_file are read by the cross-model gate
                # (#2578); eager-load once per pass instead of a lazy-load
                # (which would raise in async) per item.
                .options(
                    selectinload(PrintQueueItem.archive),
                    selectinload(PrintQueueItem.library_file),
                    # Cross-model candidates (#671), plus each candidate's file
                    # for the same cross-model gate. Lazy-loading either would
                    # raise in async.
                    selectinload(PrintQueueItem.variants).selectinload(PrintQueueVariant.library_file),
                )
                .order_by(
                    PrintQueueItem.priority.desc(),
                    PrintQueueItem.been_jumped.desc(),
                    PrintQueueItem.print_time_seconds.asc().nullslast(),
                    PrintQueueItem.position,
                    PrintQueueItem.id,
                )
            )
        else:
            result = await self.db.execute(
                select(PrintQueueItem)
                .where(PrintQueueItem.status == "pending")
                # Skip rows already claimed by a dispatch worker (#2615).
                .where(PrintQueueItem.dispatching_at.is_(None))
                .options(
                    selectinload(PrintQueueItem.archive),
                    selectinload(PrintQueueItem.library_file),
                    # Cross-model candidates (#671), plus each candidate's file
                    # for the same cross-model gate. Lazy-loading either would
                    # raise in async.
                    selectinload(PrintQueueItem.variants).selectinload(PrintQueueVariant.library_file),
                )
                .order_by(PrintQueueItem.priority.desc(), PrintQueueItem.position, PrintQueueItem.id)
            )
        self.items = list(result.scalars().all())

        # Drop rows whose upload is still in flight from an earlier pass
        # (#2602). They stay `pending` until the upload finishes, so without
        # this a fast tick would re-select and re-dispatch the same row.
        # Belt-and-suspenders with the printer exclusion below.
        if self._s._inflight:
            inflight_ids = set(self._s._inflight)
            self.items = [it for it in self.items if it.id not in inflight_ids]

        # Read plate-clear setting once per queue check. Default MUST be
        # False to match the schema (SettingsSchema.require_plate_clear
        # defaults False) and the frontend (toggle + card badge both treat a
        # missing value as off). When no settings row exists, a True default
        # here re-enabled the plate-clear gate the UI showed as disabled,
        # blocking dispatch to FINISH-state printers forever with no UI path
        # to clear it (#1865).
        self.require_plate_clear = await self._s._get_bool_setting(self.db, "require_plate_clear", default=False)

        # Dispatch and track scheduled drying runs (#2638)
        await self._s._check_scheduled_dryings(self.db)

        if not self.items:
            # No dispatchable pending items — still check auto-drying on idle
            # printers, but keep any printer with an upload still in flight
            # from an earlier pass out of it (#2602): its print is imminent,
            # so it must not be auto-dried in the gap before the row flips to
            # printing. Report the pass as productive while uploads run so the
            # loop stays on the fast interval.
            #
            # Also release any keep-warm holds that got orphaned by the queue
            # emptying — the normal sweep in `_apply_keep_warm` is skipped by
            # this early return, so call it directly with an empty candidate
            # set. Without this, a printer whose queued item was cancelled or
            # deleted would keep its bed at target until the max-duration
            # timeout expired.
            self._s._sweep_keep_warm(active_candidates=set(), dispatched=set())
            inflight_printers = {pid for (_task, pid) in self._s._inflight.values() if pid is not None}
            await self._s._check_auto_drying(self.db, [], inflight_printers)
            await self._s._check_filament_low(self.db)
            await self._s._check_stock_forecast(self.db)
            return False

        return True

    async def _select(self) -> None:
        """Entscheiden, welcher Auftrag auf welchen Drucker geht, und warum nicht.

        Der eigentliche Durchlauf über die Aufträge: Belegungen, Rücksichten,
        Haltegründe, Modellzuordnung, Düsen- und Filamentprüfungen. Die Auswahl
        landet in ``dispatch_ids``; abgesetzt wird sie erst im Abschluss.
        """
        logger.info(
            "Queue check: found %d pending items: %s",
            len(self.items),
            [(i.id, i.printer_id, i.archive_id, i.library_file_id) for i in self.items],
        )

        # Seed busy_printers with printers that already have an item in 'printing'
        # status. _is_printer_idle() alone is not sufficient as a dispatch gate —
        # on H2D / P1 series the MQTT state transition from IDLE to RUNNING can
        # lag several seconds behind the print command, so the next check_queue
        # tick still sees IDLE and would double-dispatch onto the same printer.
        # Without this guard, two pending items targeting the same printer
        # (e.g. a batch with quantity>1) both end up in 'printing' status —
        # surfaced via the "BUG: Multiple queue items" warning in on_print_complete.
        busy_result = await self.db.execute(
            select(PrintQueueItem.printer_id)
            .where(PrintQueueItem.status == "printing")
            .where(PrintQueueItem.printer_id.is_not(None))
        )
        self.busy_printers: set[int] = {pid for (pid,) in busy_result.all() if pid is not None}

        # Why each printer left this pass, recorded where the decision is
        # made rather than re-derived when the summary is logged. #3018's
        # bundle shows what the old summary produced: "printer 1 not
        # available -- connected=True, state=IDLE" immediately followed by a
        # dispatch to printer 1. Two things went wrong at once. The line read
        # live state at log time, which by then no longer matched the state
        # the decision was made on; and `busy_printers` holds both printers
        # that cannot take work and printers this pass has claimed for it,
        # which are opposite facts. It is the first line anyone greps for
        # "why did my item not go out", so it has to say which.
        self.busy_reasons: dict[int, str] = dict.fromkeys(self.busy_printers, "an item is already printing on it")

        # Printers this pass is dispatching to. They are in busy_printers so
        # nothing else in the pass targets them -- that is a reservation, not
        # an obstruction, and the summary says so.
        self.claimed_printers: set[int] = set()

        # The user-facing half of `busy_reasons` (#3074). The same decisions
        # worded for a different audience: the log wants "still inside its
        # post-dispatch hold window", the queue row wants to know the printer
        # is taken and nothing is broken. Only the cases that would read wrong
        # as a plain "Busy" are recorded here; the rest fall back to it.
        self.item_hold_reasons: dict[int, str] = {}

        # Names and models for the printers this pass may have to write a
        # waiting reason about, read once rather than per skip per tick. The
        # model-based branch already has its names from `_printers_for_model`.
        self.pinned_printer_ids = {i.printer_id for i in self.items if i.printer_id}
        self.pinned_printers: dict[int, tuple[str, str]] = {}
        if self.pinned_printer_ids:
            pinned_rows = await self.db.execute(
                select(Printer.id, Printer.name, Printer.model).where(Printer.id.in_(self.pinned_printer_ids))
            )
            self.pinned_printers = {pid: (name or "", model or "") for pid, name, model in pinned_rows.all()}

        # Defense-in-depth (#1157): augment busy_printers with any printer
        # still in its post-dispatch hold window. Empirically, the DB seed
        # above can miss in-flight items in a multi-plate batch — same-file
        # plates were being dispatched 30 s apart while the H2D was still
        # digesting the first project_file. The hold is keyed in-memory and
        # released by the watchdog on the success path, so it adds a layer
        # that doesn't depend on DB row visibility or completion-callback
        # timing.
        for held_printer_id in list(self._s._dispatch_holds.keys()):
            if self._s._printer_in_dispatch_hold(held_printer_id):
                self.mark_busy(held_printer_id, "still inside its post-dispatch hold window")

        # Exclude printers whose upload is still in flight from an earlier
        # pass (#2602). The row is `pending` until the upload finishes and
        # the printing-state seed / dispatch hold above only arm once the
        # upload completes, so this is what holds the printer (and, via
        # busy_printers, its auto-drying) out of the pass during the upload.
        for _task, inflight_pid in self._s._inflight.values():
            if inflight_pid is not None:
                self.mark_busy(inflight_pid, "an upload to it is still in flight")

        # Snapshot taken here, before the item loop adds anything (#2801).
        #
        # The three sources above all mean the same thing: a print on this
        # printer is running or imminent. Everything the loop adds below
        # means only "the queue could not dispatch to it this pass", which
        # is a different statement -- a printer waiting on a plate-clear
        # acknowledgment, an offline printer, one with no matching file.
        #
        # Auto-drying must only see the first kind. Reading the whole set
        # as "is currently printing" is what put a plate-held printer down
        # the mid-print path: it capped the drying temperature, logged the
        # cycle as (mid-print), and skipped the very gate that was supposed
        # to hold it. The interlock block below already documents the same
        # hazard and works around it by staying out of busy_printers; this
        # generalises that workaround instead of repeating it per case.
        self.dispatching_printers: set[int] = set(self.busy_printers)

        # Printers whose last upload never reached them (#3210). After the
        # snapshot above on purpose: such a printer is idle, not about to
        # print, and auto-drying must keep treating it as idle.
        now_mono = _rt().time.monotonic()
        # In backoff this pass. Kept apart from busy_printers so keep-warm
        # can leave them out: there is no print to keep a bed warm for.
        self.backoff_printers: set[int] = set()
        # In backoff, and the "job waiting" notification for this run of
        # refusals has gone out already. Their holds are written silently.
        self.silent_hold_printers: set[int] = set()
        for backoff_pid, retry_at in list(self._s._upload_backoff.items()):
            if now_mono >= retry_at:
                del self._s._upload_backoff[backoff_pid]
                continue
            self.backoff_printers.add(backoff_pid)
            if backoff_pid in self._s._upload_refusal_notified:
                self.silent_hold_printers.add(backoff_pid)
            else:
                self._s._upload_refusal_notified.add(backoff_pid)
            self.mark_busy(
                backoff_pid,
                f"its file service refused the last upload; retrying in {retry_at - now_mono:.0f}s",
            )
            self.item_hold_reasons.setdefault(
                backoff_pid,
                f"{self.printer_label(backoff_pid)} is not accepting files — PrintLab will retry automatically",
            )

        # Printers held by a Home Assistant sensor interlock (#1148) — an
        # enclosure door left open, say. The fixed-printer branch turns
        # this into a waiting_reason the user can act on; the model-based
        # branch hides these printers from the matcher so an "Any <model>"
        # job runs on a sibling instead of queueing behind the held one.
        #
        # Deliberately NOT merged into busy_printers, even though that set
        # already means "unavailable this pass". _check_auto_drying reads
        # it as "is currently printing" and would put an idle-but-held
        # printer down the mid-print drying path, which caps the drying
        # temperature and skips the queue-only gating. A held printer is
        # idle; it should dry exactly as it did before.
        #
        # Only sensors we actually read and found alerting appear here; see
        # ha_sensor_manager.blocked_printers. A Home Assistant that is down
        # holds nothing.
        self.interlocked: dict[int, str] = {}
        try:
            self.interlocked = await _rt().ha_sensor_manager.blocked_printers(self.db)
        except Exception as e:
            # Never let the interlock stop the queue running. A broken
            # lookup means no holds, not no dispatches.
            logger.warning("Home Assistant interlock check failed: %s", e)
            self.interlocked = {}

        # Printers a smart plug can bring back, read once for the whole pass
        # (#2786). Used by the model-based branch both to word "Offline" in
        # the waiting reason and to decide what the wake step may switch on.
        self.wakeable_printer_ids = await self._s._wakeable_printer_ids(self.db)

        # At most one power-on per queue check. Each one blocks this loop
        # for the boot wait, so a queue of ten class-targeted jobs must not
        # switch on ten printers inside a single pass — the next pass wakes
        # the next one (#2786).
        self.power_on_attempted = False

        # Log skip reasons once per queue check (not per item)
        self.skip_reasons: dict[str, int] = {}

        # Items selected for dispatch in this pass, one per printer. The
        # loop below only *decides* — the uploads happen afterwards, in
        # parallel (#2555). See _dispatch_selected().
        self.dispatch_ids: list[int] = []

        # Library rows queued with `cleanup_library_after_dispatch` (the
        # printer-card "upload and print" flow) are CONSUMED by the dispatch
        # that prints them: the row is deleted and the 3MF is unlinked from
        # disk. That was safe only because dispatch was serial. Run two of
        # them against the same row at once and the second DELETE matches no
        # row (StaleDataError), and the winner's unlink can pull the file out
        # from under the loser's in-flight upload.
        #
        # Only the cleanup flag mutates the row. An ordinary library print
        # just reads it, so the common fan-out — one file, many printers,
        # which is exactly the reporter's workload — still goes out fully in
        # parallel. Narrow the guard to the mutating case; do not serialise
        # the case the whole fix exists for.
        self.dispatch_libs: set[int] = set()
        self.consumed_libs: set[int] = set()

        for item in self.items:
            # Check scheduled time first (scheduled_time is stored in UTC from ISO string)
            if item.scheduled_time:
                sched = item.scheduled_time
                if sched.tzinfo is None:
                    sched = sched.replace(tzinfo=timezone.utc)
                if sched > _rt().datetime.now(timezone.utc):
                    # Waiting on the clock, not on a printer.
                    await self.hold_item(item, None)
                    self.skip_reasons["scheduled_future"] = self.skip_reasons.get("scheduled_future", 0) + 1
                    continue

            # Skip items that require manual start
            if item.manual_start:
                # Waiting on the user, not on a printer. Cleared here because
                # this is the last pass that will look at the row: a staged
                # item never reaches the branches below again, so a reason
                # left from before it was staged would stand forever (#3074).
                await self.hold_item(item, None)
                self.skip_reasons["manual_start"] = self.skip_reasons.get("manual_start", 0) + 1
                continue

            if item.printer_id:
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
                    continue

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
                    continue

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
                                    logger.info(
                                        "Also powered on plug '%s' for printer %s", extra_plug.name, item.printer_id
                                    )
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
                            continue
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
                        continue

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
                    continue

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
                    continue

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
                        continue

                # Resolve the AMS mapping when it's missing OR unresolved
                # (all -1). A stored all-[-1] mapping is a bug artifact — a
                # frontend status-load race can persist [-1] (#2589) — and
                # must be recomputed from live trays rather than trusted.
                unmappable = await self._s._ensure_ams_mapping(self.db, item.printer_id, item)
                if unmappable:
                    await self._s._fail_unmappable_item(self.db, item, item.printer_id, unmappable)
                    continue

                # Filament-deficit pre-dispatch check (#1496). If the
                # assigned spool can't satisfy any required slot grams,
                # promote the item to manual_start so the user must
                # acknowledge via the ▶ button (which re-checks live).
                if await self._s._block_on_filament_deficit(self.db, item):
                    # Now staged for the user to start by hand, and the row
                    # shows the filament-short badge instead. Cleared because
                    # a staged item never reaches this branch again.
                    await self.hold_item(item, None)
                    continue

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
                    continue

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
                if self._s._drying_in_progress.get(
                    item.printer_id
                ) and not await self._s._drying_may_continue_through_print(self.db, item.printer_id):
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

            elif item.target_model or item.variants:
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
                        self.skip_reasons["sliced_model_mismatch"] = (
                            self.skip_reasons.get("sliced_model_mismatch", 0) + 1
                        )
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
                        continue

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
                        continue

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
                            continue

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
                        continue

                    # Filament-deficit pre-dispatch check (#1496).
                    if await self._s._block_on_filament_deficit(self.db, item):
                        continue

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
                                and (
                                    other.print_time_seconds is None
                                    or other.print_time_seconds > item.print_time_seconds
                                )
                            ):
                                other.been_jumped = True
                        await self.db.commit()

        # Log the decisions BEFORE dispatching. The dispatch below blocks for
        # as long as the slowest upload takes (minutes on a big 3MF), and a
        # skip summary that only lands after the transfers have finished is
        # useless for working out why an item did not go out.

    async def _finish(self) -> bool:
        """Melden, absetzen, nachfassen — und sagen, ob die Runde etwas tat.

        Die Reihenfolge ist Teil der Sache: die Begründungen werden protokolliert,
        bevor die Übertragungen laufen, und die Obergrenze für gleichzeitige
        Uploads wird vor dem Commit gelesen (siehe unten), nicht danach.
        """
        if self.skip_reasons:
            logger.info("Queue skip summary: %s", self.skip_reasons)
        for pid in sorted(self.busy_printers):
            reason = self.busy_reasons.get(pid, "no reason recorded")
            if pid in self.claimed_printers:
                logger.info("Queue: printer %d reserved — %s", pid, reason)
                continue
            # The three live fields stay, because they are what someone
            # reading a bundle wants next -- but they are labelled as read
            # now, not as the state the decision was made on, which is what
            # made the old line contradict itself.
            state = _rt().printer_manager.get_status(pid)
            logger.info(
                "Queue: printer %d unavailable — %s (now: connected=%s, state=%s, awaiting_plate_clear=%s)",
                pid,
                reason,
                _rt().printer_manager.is_connected(pid),
                state.state if state else "NO_STATUS",
                _rt().printer_manager.is_awaiting_plate_clear(pid),
            )

        # Keep-warm is a comfort feature; dispatch is not. It sits between
        # selection and `_launch_uploads`, so anything raising here would
        # discard this tick's selections — computed AMS mappings and all —
        # and, on a persistent fault, stop the queue dispatching entirely.
        # Same reasoning as the deficit check's guard below: never let an
        # auxiliary check wedge the queue. The bed simply stays wherever it
        # was, and the next tick tries again.
        try:
            await self._s._apply_keep_warm(
                self.db,
                self.items,
                self.dispatch_ids,
                self.busy_printers - self.backoff_printers,
                self.require_plate_clear,
            )
        except Exception as e:
            logger.warning("Keep-warm pass failed, continuing with dispatch: %s", e, exc_info=True)

        # Read the concurrency limit BEFORE the commit below, not inside
        # _dispatch_selected(). A SELECT on this session after the commit
        # implicitly opens a fresh transaction that nothing then closes, and
        # it would stay open for the whole dispatch — minutes of "idle in
        # transaction" on Postgres (pinned MVCC snapshot, vacuum blocked),
        # and on SQLite a pinned WAL read snapshot that stops the WAL being
        # checkpointed while every dispatch is writing to it.
        upload_limit = max(1, await self._s._get_int_setting(self.db, "queue_max_concurrent_uploads", default=4))

        # Selection is done; every decision above is recorded on `db`
        # (model-based printer assignment, computed ams_mapping). Flush it
        # before the dispatch tasks open their own sessions, or they will
        # read a row that still says printer_id=None. This also releases the
        # connection back to the pool for the duration of the dispatch.
        await self.db.commit()

        if self.dispatch_ids:
            item_printers = {it.id: it.printer_id for it in self.items}
            self._s._launch_uploads(self.dispatch_ids, item_printers, upload_limit)

        # Auto-drying: start drying on idle printers that have no pending queue items
        await self._s._check_auto_drying(self.db, self.items, self.dispatching_printers)

        # Low filament: alert on assigned spools that have crossed their
        # low-stock threshold (#2913). Runs on both paths out of this method
        # for the same reason auto-drying does — an empty queue does not mean
        # the spools in the printers stopped mattering.
        await self._s._check_filament_low(self.db)

        # Stock forecast: alert when a filament SKU reaches its reorder point or
        # is about to run out before a replenishment could arrive (#2955).
        await self._s._check_stock_forecast(self.db)

        # Keep the loop on the fast interval while any upload is in flight so
        # a slot freed mid-tick refills within seconds rather than after the
        # 30 s idle sleep (#2602). Selecting anything this pass (launched or
        # deferred because the pool was full) also counts as productive.
        return bool(self.dispatch_ids) or bool(self._s._inflight)

    def mark_busy(self, printer_id: int, reason: str) -> None:
        """Take ``printer_id`` out of this pass, recording why.

        First reason wins: a printer already excluded by a stronger fact
        -- a print running on it -- must not be relabelled by a weaker
        check that ran later and would have excluded it anyway.
        """
        self.busy_printers.add(printer_id)
        self.busy_reasons.setdefault(printer_id, reason)

    def claim_printer(self, printer_id: int) -> None:
        """Reserve ``printer_id`` for an item this pass is dispatching."""
        self.claimed_printers.add(printer_id)
        self.mark_busy(printer_id, "selected for dispatch in this pass")

    def printer_label(self, printer_id: int) -> str:
        """What to call this printer in a queue row."""
        entry = self.pinned_printers.get(printer_id)
        return (entry[0] if entry else "") or f"printer {printer_id}"

    async def hold_item(self, item: PrintQueueItem, reason: str | None, *, notify: bool = True) -> None:
        """Record why *item* is not going out, in the words the queue row shows.

        The fixed-printer branch's single writer for ``waiting_reason``
        (#3074). Before this, the sensor interlock was the only thing that
        wrote the field there, so an item pinned to a printer that was
        merely printing sat at `pending` with nothing to show for it —
        indistinguishable from a queue that had stopped working — while
        the same job queued as "Any <model>" explained itself.

        Every exit from that branch now calls this, which is also what
        replaced the interlock's old habit of clearing the field up front:
        a lifted hold cannot leave "Waiting on Enclosure Door" standing,
        because whichever exit runs next overwrites it and the dispatch
        path clears it.

        A notification goes out when this item starts asking for
        something, and only then: the new reason needs the user, and what
        it replaced did not. "What it replaced did not" has to include a
        busy-only reason, not just an empty one. The sequence this branch
        actually produces is a print running (``Busy: X1C-01``) and then
        the plate it left behind (``Waiting for plate confirmation``), and
        testing "was the field empty" would call that no transition at all
        and stay quiet through the one case worth saying out loud.

        The cost is that a printer dropping offline, coming back busy and
        dropping again asks twice rather than once. That is the honest
        reading — it went wrong twice — and the alternative was a rule
        that never fired for the case this was built for.

        *notify* is how a caller opts out. The sensor interlock does: it
        has never sent this notification, and a change about what the
        queue *displays* is not the place to start (#1148).
        """
        if item.waiting_reason == reason:
            return
        # Busy-only and empty are the same thing here: neither is the
        # queue asking the user for anything.
        was_asking = bool(item.waiting_reason) and not self._s._is_busy_only(item.waiting_reason)
        item.waiting_reason = reason
        await self.db.commit()
        if not notify or not reason or was_asking or self._s._is_busy_only(reason):
            return
        try:
            job_name = await self._s._get_job_name(self.db, item)
            entry = self.pinned_printers.get(item.printer_id) if item.printer_id else None
            await _rt().notification_service.on_queue_job_waiting(
                job_name=job_name,
                target_model=(entry[1] if entry else "") or "",
                waiting_reason=reason,
                db=self.db,
            )
        except Exception as e:
            # A queue that cannot say why it is waiting is the bug being
            # fixed here; a queue that stops dispatching because a
            # notification provider is down would be a worse one.
            logger.debug("Waiting notification failed for item %s: %s", item.id, e)

    async def hold_for_printer(self, item: PrintQueueItem, printer_id: int, log_reason: str, item_reason: str) -> None:
        """Take *printer_id* out of this pass and tell the item's owner why."""
        self.mark_busy(printer_id, log_reason)
        self.item_hold_reasons.setdefault(printer_id, item_reason)
        await self.hold_item(item, item_reason)

    def _library_row_conflict(self, candidate: PrintQueueItem) -> bool:
        """True if dispatching `candidate` now would race another item's cleanup."""
        lib_id = candidate.library_file_id
        if lib_id is None:
            return False
        if candidate.cleanup_library_after_dispatch:
            # We would delete a row someone else in this pass is reading.
            return lib_id in self.dispatch_libs
        # Someone else in this pass will delete the row out from under us.
        return lib_id in self.consumed_libs

    def _claim_library_row(self, candidate: PrintQueueItem) -> None:
        lib_id = candidate.library_file_id
        if lib_id is None:
            return
        self.dispatch_libs.add(lib_id)
        if candidate.cleanup_library_after_dispatch:
            self.consumed_libs.add(lib_id)
