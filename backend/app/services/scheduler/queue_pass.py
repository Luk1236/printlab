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
from backend.app.services.scheduler.reservations import release_orphaned_reservations
from backend.app.services.scheduler.selection import SelectionMixin

if TYPE_CHECKING:
    from backend.app.services.print_scheduler import PrintScheduler

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen."""
    import importlib

    return importlib.import_module("backend.app.services.print_scheduler")


class QueuePass(SelectionMixin):
    """Ein Durchlauf über die Warteschlange: Zustand plus die Schritte dazu."""

    def __init__(self, scheduler: "PrintScheduler") -> None:
        self._s = scheduler

    async def run(self) -> bool:
        """Die Runde ausführen; True, wenn etwas abgesetzt wurde oder noch läuft."""
        async with _rt().async_session() as self.db:
            # Reservierungen beendeter Aufträge freigeben, die sonst Budget binden (T4-02); selbst gedrosselt.
            await release_orphaned_reservations(self.db)
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

        # Printers whose plate check saw objects on the bed (see scheduler/plate_hold.py). Inside
        # the window they sit out like a refused upload: the row keeps the plate reason, there is
        # no "job waiting" notification (the plate check sent its own) and no keep-warm. After the
        # window the printer is picked again so the camera can look.
        for plate_pid, (retry_at, plate_text) in list(self._s._plate_blocks.items()):
            if now_mono >= retry_at:
                continue
            self.backoff_printers.add(plate_pid)
            self.silent_hold_printers.add(plate_pid)
            self.mark_busy(
                plate_pid, f"its plate check saw objects on the bed; looking again in {retry_at - now_mono:.0f}s"
            )
            self.item_hold_reasons.setdefault(plate_pid, plate_text)

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

        # Model-based items that got a printer this pass: item id -> the AMS mapping they had before
        # (T4-03). Used to undo the assignment for items the upload pool defers.
        self.model_assigned: dict[int, str | None] = {}

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
            await self._select_item(item)

        # Log the decisions BEFORE dispatching. The dispatch below blocks for
        # as long as the slowest upload takes (minutes on a big 3MF), and a
        # skip summary that only lands after the transfers have finished is
        # useless for working out why an item did not go out.

    async def _select_item(self, item: PrintQueueItem) -> None:
        """Einen Auftrag entscheiden: erst die Bedingungen, dann der Zweig.

        Die beiden Zweige sind eigene Methoden, weil sie nichts teilen außer dem
        Auftrag: der eine bedient einen festen Drucker, der andere sucht einen
        nach Modell. Ein ``continue`` der früheren Schleife ist hier ein
        ``return`` — beide Zweige standen am Ende des Schleifenkörpers, für
        diesen Auftrag folgte nichts mehr.
        """
        if item.scheduled_time:
            sched = item.scheduled_time
            if sched.tzinfo is None:
                sched = sched.replace(tzinfo=timezone.utc)
            if sched > _rt().datetime.now(timezone.utc):
                # Waiting on the clock, not on a printer.
                await self.hold_item(item, None)
                self.skip_reasons["scheduled_future"] = self.skip_reasons.get("scheduled_future", 0) + 1
                return

        # Skip items that require manual start
        if item.manual_start:
            # Waiting on the user, not on a printer. Cleared here because
            # this is the last pass that will look at the row: a staged
            # item never reaches the branches below again, so a reason
            # left from before it was staged would stand forever (#3074).
            await self.hold_item(item, None)
            self.skip_reasons["manual_start"] = self.skip_reasons.get("manual_start", 0) + 1
            return
        if item.printer_id:
            await self._select_pinned(item)
        elif item.target_model or item.variants:
            await self._select_for_model(item)

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
        self._unpin_deferred(upload_limit)

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

    def _unpin_deferred(self, upload_limit: int) -> list[int]:
        """Model-based items the upload pool cannot take this tick go back to "any printer of the model".

        ``_launch_uploads`` takes the first ``limit - in flight`` selected ids and defers the rest.
        A deferred item that came from ``_select_for_model`` already carries the printer chosen for it,
        and from the next pass on it would count as pinned to that printer and could no longer move to a
        sibling that is free (T4-03). Put its printer and AMS mapping back; items whose printer the user
        picked are not in ``model_assigned`` and stay as they are. Mirrors the slicing in
        ``_launch_uploads`` and runs before the commit, so the undo is written with the rest of the pass.
        """
        free = max(upload_limit - len(self._s._inflight), 0)
        released: list[int] = []
        by_id = {it.id: it for it in self.items}
        for item_id in self.dispatch_ids[free:]:
            item = by_id.get(item_id)
            if item is None or item_id not in self.model_assigned:
                continue
            item.printer_id = None
            item.ams_mapping = self.model_assigned[item_id]
            released.append(item_id)
        if released:
            logger.info("Upload pool full: model-based item(s) %s keep no printer until a later tick", released)
        return released

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
