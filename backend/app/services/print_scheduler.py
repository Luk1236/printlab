"""Print scheduler service - processes the print queue.

Die Bausteine, die vorher hier standen (Filament- und AMS-Abgleich, Düsen-Prüfung,
Kammer-Grenzwerte, Übertragung), liegen in ``backend.app.services.scheduler``, ebenso
Vorheizen/Warmhalten (``preheat``) und Trocknung (``drying``) als Mixins. Die
FTP-Übertragung einer Druckdatei steht in ``upload``, der Zusammenbau des
Startbefehls in ``delivery``. Alle Namen werden hier weiter importiert, damit
Aufrufer und Tests unverändert über dieses Modul arbeiten. Neuer Code gehört in das
Paket, nicht in diese Datei.
"""

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, false, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.config import settings
from backend.app.core.database import async_session, run_with_retry
from backend.app.core.tasks import spawn_background_task
from backend.app.core.websocket import ws_manager
from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile
from backend.app.models.print_queue import PrintQueueItem, PrintQueueVariant
from backend.app.models.printer import Printer
from backend.app.models.settings import Settings
from backend.app.models.smart_plug import SmartPlug
from backend.app.models.spool_assignment import SpoolAssignment
from backend.app.models.spoolman_slot_assignment import SpoolmanSlotAssignment
from backend.app.services import kprofile_drift, print_dispatch_context, stock_forecast
from backend.app.services.bambu_ftp import (
    cache_3mf_download,
    delete_file_async,
    # Beide nur noch über die Fassade benutzt (``scheduler/upload.py``), aber
    # hier importiert: die Tests patchen diese Namen im Modulnamensraum.
    get_ftp_retry_settings,  # noqa: F401 — Test-Patch-Ziel
    upload_file_async,  # noqa: F401 — Test-Patch-Ziel
)
from backend.app.services.bambu_mqtt import HMS_MQTT_VERIFY_FAILED
from backend.app.services.filament_deficit import compute_deficit_for_queue_item
from backend.app.services.finance_budget import (
    create_budget_reservation,
    release_budget_reservation,
    validate_print_budget,
)
from backend.app.services.ha_sensor_manager import ha_sensor_manager  # noqa: F401 — Test-Patch-Ziel
from backend.app.services.notification_service import notification_service
from backend.app.services.print_cost_estimate import estimate_queue_source_cost
from backend.app.services.printer_manager import (  # noqa: F401 — Test-Patch-Ziel
    printer_manager,
    supports_drying,  # wird von der Trocknung über dieses Modul aufgelöst
)
from backend.app.services.queue_priority import printer_usage_seconds
from backend.app.services.scheduler.chamber import (  # noqa: F401 — Namensraum bleibt hier
    _AIRDUCT_MODE_COOLING,
    _AIRDUCT_MODE_HEATING,
    _CHAMBER_DIP_GRACE_SECONDS,
    _CHAMBER_HISTORY_TTL_SECONDS,
    _CHAMBER_SAMPLE_MAX_GAP_SECONDS,
    _KEEP_WARM_MAX_MINUTES_DEFAULT,
    _PREHEAT_CANCEL_CHECK_SECONDS,
    AUTO_DRY_MAX_UNPRODUCTIVE_CYCLES,
    AUTO_DRY_REARM_COOLDOWN_SECONDS,
    AUTO_DRY_SUSTAINED_GAP_FLOOR_SECONDS,
    SCHEDULED_DRYING_PRUNE_INTERVAL_SECONDS,
    SCHEDULED_DRYING_RETENTION_DAYS,
    _KeepWarmEntry,
)
from backend.app.services.scheduler.delivery import (  # noqa: F401 — Namensraum bleibt hier
    StartPlan,
    StartRefusal,
    prepare_start,
)
from backend.app.services.scheduler.dispatch import (  # noqa: F401 — Namensraum bleibt hier
    _ACTIVE_PRINT_STATES,
    _DISPATCH_PROGRESS_BYTE_STEP,
    _DISPATCH_PROGRESS_MIN_INTERVAL_SECS,
    _UPLOAD_REQUEUE_KINDS,
    DISPATCH_MAX_ATTEMPTS,
    UPLOAD_FAILURE_BACKOFF_MAX_SECONDS,
    UPLOAD_FAILURE_BACKOFF_SECONDS,
    _effective_plate_id,
    _upload_backoff_seconds,
    _UploadProgressBridge,
)
from backend.app.services.scheduler.drying import DryingMixin
from backend.app.services.scheduler.filament import (  # noqa: F401 — Namensraum bleibt hier
    _EXTERNAL_TRAY_ID_MIN,
    _ams_slot_label,
    _candidate_model_label,
    _candidates_for,
    _collapse_waiting_reasons,
    _consumed_mapping_entries,
    _could_take_printer,
    _drying_ams_ids,
    _filament_constraints,
    _global_tray_id,
    _int_or,
    _is_busy_only,
    _is_external_tray,
    _mapping_is_all_unresolved,
    _might_be_dual_nozzle,
    _ModelCandidate,
    _mqtt_commands_rejected,
    _remaining_percent,
    _sliced_for_model,
    _used_global_tray_ids,
)
from backend.app.services.scheduler.nozzles import (  # noqa: F401 — Namensraum bleibt hier
    _EMPTY_NOZZLE_SERIAL,
    _describe_filament,
    _format_diameters,
    _installed_nozzle_diameters,
    _nozzle_info_by_id,
    _nozzle_is_mounted,
    _nozzle_mismatch_message,
    _parse_diameter,
    _rack_nozzle_diameters,
    _unmatched_filament_message,
)
from backend.app.services.scheduler.preheat import PreheatMixin
from backend.app.services.scheduler.queue_pass import QueuePass
from backend.app.services.scheduler.upload import (  # noqa: F401 — Namensraum bleibt hier
    UploadOutcome,
    deliver_file,
)
from backend.app.services.smart_plug_manager import smart_plug_manager
from backend.app.utils.archive_paths import archive_photos_dir
from backend.app.utils.color_utils import perceptual_color_distance
from backend.app.utils.filament_types import canonical_filament_type
from backend.app.utils.library_paths import move_library_photos
from backend.app.utils.local_time import utcnow_naive
from backend.app.utils.printer_models import normalize_printer_model

logger = logging.getLogger(__name__)


# Minimum seconds between low-filament checks. Matches the scheduler's idle
# interval: the fast path runs every 3 s while an upload is in flight, and a
# low spool does not need answering at that resolution (#2913).
_FILAMENT_LOW_MIN_INTERVAL = 30.0

# Minimum seconds between stock forecast checks (#2955). The forecast is in whole
# days, so a finer check would only repeat the same answer.
_STOCK_FORECAST_MIN_INTERVAL = 3600.0

# The settings row that holds which stock alerts have already been sent (#2955).
_STOCK_ALERTS_SETTING_KEY = "stock_alerts_notified"

# The Inventory page asks for this many usage records and the forecast panel
# builds its rates from them; the alert reads the same window so the two agree.
_STOCK_FORECAST_HISTORY_LIMIT = 5000


# How long a queue row may stay 'printing' while its printer sits in a terminal
# state before the scheduler closes it itself (#2829).
#
# A real completion arrives within seconds of the printer going terminal, so
# five minutes is far outside the normal path — this only ever sees a row whose
# completion was refused or never delivered. It is the whole cost of the
# failure to the user, though: a stranded row blocks every later job for that
# printer, so it should not be raised without reason.
_STRANDED_PRINTING_GRACE_SECONDS = 300.0

# gcode_state values that mean the print is over, mapped to the queue status
# they imply. Mirrors the mapping in bambu_mqtt's completion detection
# (FINISH -> completed, FAILED -> failed, anything else terminal -> aborted,
# which the queue calls cancelled) so a recovered row cannot disagree with one
# closed by the normal path.
_TERMINAL_STATE_QUEUE_STATUS = {
    "FINISH": "completed",
    "FAILED": "failed",
    "IDLE": "cancelled",
}


def _terminal_queue_status(state) -> str | None:
    """Queue status implied by *state*, or None if the print is not over.

    None for a disconnected printer as well as a busy one: a printer we are not
    talking to has a stale ``state`` field that proves nothing about what it is
    doing now.
    """
    if state is None or not getattr(state, "connected", False):
        return None
    return _TERMINAL_STATE_QUEUE_STATUS.get(getattr(state, "state", None))


class PrintScheduler(PreheatMixin, DryingMixin):
    """Background scheduler that processes the print queue."""

    # Built-in drying presets per filament type (from BambuStudio filament profiles)
    # Format: { n3f_temp, n3s_temp, n3f_hours, n3s_hours }
    DEFAULT_DRYING_PRESETS: dict[str, dict[str, int]] = {
        "PLA": {"n3f": 45, "n3s": 45, "n3f_hours": 12, "n3s_hours": 12},
        "PETG": {"n3f": 65, "n3s": 65, "n3f_hours": 12, "n3s_hours": 12},
        "TPU": {"n3f": 65, "n3s": 75, "n3f_hours": 12, "n3s_hours": 18},
        "ABS": {"n3f": 65, "n3s": 80, "n3f_hours": 12, "n3s_hours": 8},
        "ASA": {"n3f": 65, "n3s": 80, "n3f_hours": 12, "n3s_hours": 8},
        "PA": {"n3f": 65, "n3s": 85, "n3f_hours": 12, "n3s_hours": 12},
        "PC": {"n3f": 65, "n3s": 80, "n3f_hours": 12, "n3s_hours": 8},
        "PVA": {"n3f": 65, "n3s": 85, "n3f_hours": 12, "n3s_hours": 18},
    }

    def __init__(self):
        self._running = False
        self._check_interval = 30  # seconds
        # After a pass that actually dispatched something, loop again almost
        # immediately instead of sleeping the full interval (#2555). A dispatch
        # changes printer state — a batch launch fans out over several passes as
        # printers free up, a wedged head-of-line job reverts to pending, an
        # upload slot opens — and the next batch of ready work should not have to
        # wait 30 s behind an idle sleep. When a pass dispatches nothing (all
        # pending items are behind printers that are genuinely busy printing),
        # there is nothing to react to, so we fall back to the normal interval;
        # that also means this can never tight-loop, since fast ticks only
        # continue while dispatches keep happening and the queue is draining.
        self._fast_check_interval = 3  # seconds
        self._power_on_wait_time = 180  # seconds to wait for printer after power on (3 min)
        self._power_on_check_interval = 10  # seconds between connection checks
        # Printers whose class-target power-on failed, mapped to the monotonic
        # time their cool-off expires (#2786).
        #
        # Without this, one printer with an unreachable plug starves every
        # sibling of its model forever: the wake step walks candidates in id
        # order, spends the pass's single attempt on the same broken printer
        # every time, and the healthy one two slots down is never reached. It
        # also costs a full ``_power_on_wait_time`` out of every 30 s pass,
        # which delays the whole queue, not just this job.
        #
        # Entries expire on read rather than being cleared on success: a printer
        # inside its cool-off is skipped before the power-on is reached, so a
        # live entry can never be overwritten by a success anyway. A printer
        # that comes back by any other route stops being a wake candidate the
        # moment it connects.
        self._wake_failures: dict[int, float] = {}
        self._wake_failure_cooloff = 600  # seconds
        # Printers whose last upload never reached them, mapped to the monotonic
        # time they may be dispatched to again (#3210). Same expire-on-read shape
        # as `_wake_failures`. Without it, a printer that cannot take files is
        # idle on every pass, so it is picked on every pass.
        self._upload_backoff: dict[int, float] = {}
        # Refused uploads in a row per printer, which sets the next backoff
        # window. Cleared by a successful upload to that printer.
        self._upload_refusals: dict[int, int] = {}
        # Printers whose current run of refusals has already sent its one
        # "job waiting" notification. Each retry clears the item's waiting
        # reason and the next refusal sets it again, which `hold_item` reads as
        # a new reason; without this, every retry would notify. Cleared with
        # `_upload_refusals`.
        self._upload_refusal_notified: set[int] = set()
        # Track which printers are currently auto-drying (printer_id -> start timestamp)
        self._drying_in_progress: dict[int, float] = {}
        # Per-AMS memory of the auto-drying cycles WE armed, keyed by
        # (printer_id, ams_id) (#2770). Entries only exist between arming a
        # cycle and the humidity finally coming down, so the normal steady
        # state is an empty dict. Fields:
        #   running      — a cycle we armed is (or should be) on the firmware
        #   ended_at     — monotonic when we observed that cycle end
        #   unproductive — consecutive armed cycles that ended with the reading
        #                  still above the threshold
        #   suspended    — we have stopped arming this unit and said so
        self._auto_dry_units: dict[tuple[int, int], dict[str, object]] = {}
        # Sustained-humidity streaks for the ambient-drying wait (#2518). Keyed
        # like _auto_dry_units but deliberately a SEPARATE dict: membership in
        # _auto_dry_units means "PrintLab armed a cycle on this unit", and the
        # print-takes-priority stop, the manual-cycle adoption guard, and the
        # arming setdefault all act on that meaning -- a unit that is merely
        # waiting out its streak must not become stoppable or judgeable.
        #   since -- monotonic stamp when the current continuous above-threshold
        #            streak began
        #   last  -- monotonic stamp of the last pass that observed the streak
        self._auto_dry_above: dict[tuple[int, int], dict[str, float]] = {}
        # Slots already notified as low on filament:
        # {(printer_id, ams_id, tray_id, spool_id)}.
        # Cleared when the slot goes back above its threshold rather than on a
        # timer, mirroring _notified_hms_errors — a spool hovering at the
        # boundary must not produce an alert on every pass, and a slot that has
        # been refilled has to be able to alert again. See #2913.
        #
        # The spool id is part of the key because the slot alone cannot clear
        # itself. Pull a low spool and put a different part-used one in the same
        # slot: the key survives the pass where the slot resolves to nothing --
        # deliberately, so a brief Spoolman outage does not re-alert everything
        # when it returns -- and the replacement never goes above the threshold,
        # so it can never re-arm. Keyed with the spool, the new spool is simply a
        # different key and the stale one is inert.
        self._notified_filament_low: set[tuple[int, int, int, int]] = set()
        # Earliest monotonic time the next low-filament check may run (#2913).
        self._filament_low_next_check: float = 0.0
        # SKU key -> (condition, events told) for a SKU that is alerting (#2955): the
        # condition is "reorder" or "break", the events are those that had a
        # subscriber when it was sent. Absent means not alerting. Cleared when the
        # condition clears, so it can alert again, and when nobody wants either
        # event. Mirrored to one settings row (_STOCK_ALERTS_SETTING_KEY), because the
        # first check runs as soon as PrintLab starts and a restart would otherwise
        # re-send one message per SKU that is still low.
        self._notified_stock_alerts: dict[stock_forecast.SkuKey, tuple[str, frozenset[str]]] = {}
        # The JSON last read from or written to that row; None until it has been read.
        self._stock_alerts_persisted: str | None = None
        # Earliest monotonic time the next stock forecast check may run (#2955).
        self._stock_forecast_next_check: float = 0.0
        # Printers with a "running" scheduled drying row (#2638). Rebuilt from the
        # DB on every _check_scheduled_dryings call so route-side cancels show up.
        # Auto-drying's stop-all branches must not stop or untrack these printers;
        # both features share _drying_in_progress.
        self._scheduled_drying_printer_ids: set[int] = set()
        # Monotonic stamp of the last scheduled-drying prune. None = never, so
        # the first pass after a restart reaps anything left behind.
        self._last_scheduled_drying_prune: float | None = None
        # Defensive in-memory dispatch hold (#1157): a printer that just received
        # a project_file command must not get a second dispatch until either it
        # transitions out of pre_state OR the hard timeout expires. The H2D Pro
        # can take 80–210 s to flip FINISH→PREPARE after project_file, and
        # during that window the DB busy_printers seed is empirically unreliable
        # (multi-plate batches double-/triple-dispatched onto the same printer
        # 30 s apart). Keyed by printer_id; cleared by the watchdog on success
        # or revert.
        # printer_id -> (monotonic_started_at, pre_state, pre_subtask_id)
        self._dispatch_holds: dict[int, tuple[float, str, str | None]] = {}
        # Minimum cooldown between dispatches to the same printer (covers the
        # H2D's project_file digestion window).
        self._dispatch_min_cooldown = 60.0
        # Hard timeout — drop the hold even if we never observed a transition,
        # so a lost MQTT session can't lock a printer out of the queue forever.
        # Matches the watchdog timeout (90 s) plus a safety margin so the
        # watchdog runs first on the unhappy path.
        self._dispatch_max_hold = 180.0
        # Refillable upload pool (#2602). Items whose FTP upload was launched by
        # an earlier pass and is still running. `_start_print` flips the row
        # pending -> printing only *after* the upload completes, so until then
        # the row stays `pending`: each tick, check_queue excludes these
        # item_ids from re-selection and their printers from new dispatch /
        # auto-drying, and launches only `limit - len(_inflight)` new uploads so
        # freed slots refill on the next fast tick. check_queue is the sole,
        # sequential caller and the prune done-callbacks run in the same
        # event-loop thread, so this dict needs no lock.
        # item_id -> (task, printer_id)
        self._inflight: dict[int, tuple[asyncio.Task, int | None]] = {}
        # Expected prints registered by `_start_print` that have not yet had a
        # print command sent. Populated at registration, dropped once
        # `start_print()` succeeds, and rolled back by `_dispatch_one` on every
        # other exit. Same threading argument as `_inflight` above: one
        # sequential caller, callbacks on the same loop, so no lock.
        # item_id -> (printer_id, remote_filename, archive_id)
        self._unconfirmed_expected_print: dict[int, tuple[int, str, int]] = {}
        # Budget reservations created for a dispatch whose print command has
        # not been confirmed yet. `_dispatch_one` releases these on every
        # unsuccessful exit; a successful start removes the item id and leaves
        # the reservation for finance_billing to consume with the archive.
        self._unconfirmed_budget_reservations: set[int] = set()
        # Chamber temperature history for smart soak-time reduction.
        # printer_id -> deque of (monotonic_timestamp, celsius) sampled each scheduler tick.
        # Entries older than _chamber_history_ttl are pruned on write.
        self._chamber_history: dict[int, deque[tuple[float, float]]] = {}
        self._chamber_history_ttl = _CHAMBER_HISTORY_TTL_SECONDS
        # Per-printer keep-warm state (see `_KeepWarmEntry` at module top).
        # Populated on engagement in `_apply_keep_warm`, cleared by
        # `_sweep_keep_warm` when the printer leaves the candidate set (or
        # when a gate setting toggles off mid-hold — the release publishes
        # bed → 0 first).
        self._keep_warm: dict[int, _KeepWarmEntry] = {}
        # Preheat rollback registry: printer_id -> subset of
        # {"bed", "chamber", "airduct"} listing which preheat commands
        # actually fired for the in-flight dispatch. `_dispatch_one` unwinds
        # every entry still present at exit unless the print successfully
        # started, so a failed upload / cancel / exception never leaves the
        # printer heating for a job that isn't happening.
        self._preheat_pin: dict[int, set[str]] = {}
        # Bed target (°C) that the pinned "bed" entry above actually set, so the
        # rollback can tell its own target from one someone else has since
        # chosen — the same guard `_release_keep_warm` applies to a keep-warm
        # hold. Written wherever `"bed"` joins the pin, evicted alongside it.
        self._preheat_pin_bed: dict[int, int] = {}
        # Item ids whose in-flight dispatch has been cancelled or deleted while
        # its preheat was still holding at temperature. Set by
        # `notify_dispatch_cancelled` from the queue routes, consumed by
        # `_preheat_sleep`, and cleared when the dispatch exits.
        self._cancelled_dispatches: set[int] = set()
        # printer_id -> monotonic time it was first seen terminal while one of
        # its queue rows was still 'printing'. Reset by any non-terminal
        # observation, so it measures an unbroken run rather than a total.
        # In-memory on purpose: a restart re-arms the grace period, which only
        # delays a recovery that is already the exceptional path (#2829).
        self._terminal_since: dict[int, float] = {}

    async def run(self):
        """Main loop - check queue every interval."""
        self._running = True
        logger.info("Print scheduler started")

        await self._clear_stale_dispatch_claims(at_startup=True)

        while self._running:
            dispatched = False
            try:
                self._sample_chamber_temps()
                # No-op while any upload is in flight; on a quiet tick it releases
                # a claim whose best-effort clear failed (e.g. the database was
                # briefly unreachable), instead of leaving the row wedged until
                # the next restart.
                await self._clear_stale_dispatch_claims()
                await self._close_stranded_printing_items()
                dispatched = await self.check_queue()
            except Exception as e:
                logger.error("Scheduler error: %s", e)

            # Re-check quickly after a productive pass so a draining batch does
            # not stall behind the idle interval; otherwise sleep normally (#2555).
            await asyncio.sleep(self._fast_check_interval if dispatched else self._check_interval)

    async def _close_stranded_printing_items(self) -> None:
        """Close a ``printing`` row the completion event never closed (#2829).

        ``on_print_complete`` refuses to close a row when the completion's
        subtask name disagrees with the file the row was dispatched with, so a
        completion meant for something else (the printer's own
        ``auto_pa_line_calib_mode`` run, say) cannot end someone's job early.
        The refusal has no way back, though: nothing else ever closes the row,
        and ``check_queue`` treats every ``printing`` row as a busy printer, so
        one bad comparison wedges that printer's queue until a human presses
        cancel. That is what #2829's reporters hit, and the guard's own
        docstring already called stranding the worse of the two failures.

        This is the way back. When a row has been ``printing`` while its
        printer sat in a terminal state for the whole grace period, the print
        is over however the event was read, and the row is closed with the
        status the printer's own state implies.

        Deliberately conservative:

        * Only a connected printer counts. A disconnected one has a stale
          ``state`` and proves nothing.
        * The clock is reset by any non-terminal observation, so this cannot
          fire on a printer that is merely between stages.
        * The grace period is far longer than the gap between a printer
          finishing and its completion arriving, so the normal path always
          wins the race and this only ever sees genuine strandings.

        What it does *not* do is replay the completion's side effects --
        notifications, billing, auto-off. It restores the queue, which is the
        harm being undone; the archive was updated by the normal path
        regardless, since only the queue block refuses. A recovery that
        silently re-fired notifications minutes late would be its own bug.
        """
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(PrintQueueItem)
                    .where(PrintQueueItem.status == "printing")
                    .where(PrintQueueItem.printer_id.is_not(None))
                )
                items = list(result.scalars().all())
                if not items:
                    self._terminal_since.clear()
                    return

                now = time.monotonic()
                seen_printers: set[int] = set()
                closed = False
                for item in items:
                    printer_id = item.printer_id
                    seen_printers.add(printer_id)
                    state = printer_manager.get_status(printer_id)
                    status = _terminal_queue_status(state)
                    if status is None:
                        self._terminal_since.pop(printer_id, None)
                        continue
                    since = self._terminal_since.setdefault(printer_id, now)
                    if now - since < _STRANDED_PRINTING_GRACE_SECONDS:
                        continue

                    item.status = status
                    item.completed_at = datetime.now(timezone.utc)
                    closed = True
                    logger.warning(
                        "Queue item %s was still 'printing' after printer %s reported %s for %.0fs — "
                        "closing it as %s. Its completion event was never matched to it, which blocks "
                        "every later job for this printer (#2829).",
                        item.id,
                        printer_id,
                        getattr(state, "state", None),
                        now - since,
                        status,
                    )
                if closed:
                    await db.commit()
                for printer_id in list(self._terminal_since):
                    if printer_id not in seen_printers:
                        del self._terminal_since[printer_id]
        except Exception as e:
            # Best-effort, same as the claim sweep beside it: a recovery path
            # that can itself break the scheduler loop is worse than the strand.
            logger.error("Stranded-item sweep failed: %s", e)

    async def _clear_stale_dispatch_claims(self, *, at_startup: bool = False) -> None:
        """Clear dispatch claims with no live dispatch coroutine behind them (#2615).

        A claim is only ever held by a live dispatch coroutine, so when this
        process has nothing in ``_inflight`` every ``dispatching_at`` in the table
        is stale. At startup that is trivially true — no coroutine survives a
        restart. It is equally true on any later tick where no upload is running,
        which is what makes this safe to repeat rather than only run once.

        Repeating it matters because ``_clear_dispatch_claim`` is best-effort: if
        the database is briefly unreachable at exactly the moment dispatch ends,
        the claim survives and the row is wedged out of the selection query. That
        used to last until the next restart (#2702 follow-up, seen when
        PostgreSQL refused a connection mid-dispatch).

        ``_inflight`` is populated when the task is spawned, before the coroutine
        claims its row, and pruned by a done-callback that cannot run before the
        coroutine's own ``finally`` — so "claim present, nothing in flight" has no
        race window and needs no age threshold. A size-derived upload deadline
        (``max(600s, size/25KB/s)``) has no safe fixed bound anyway.
        """
        if self._inflight:
            return
        try:
            async with async_session() as db:
                res = await db.execute(
                    update(PrintQueueItem).where(PrintQueueItem.dispatching_at.is_not(None)).values(dispatching_at=None)
                )
                await db.commit()
                if res.rowcount:
                    logger.info(
                        "Cleared %d orphaned dispatch claim(s)%s (#2615)",
                        res.rowcount,
                        " at startup" if at_startup else "",
                    )
        except Exception as exc:
            logger.error("Failed to clear orphaned dispatch claims: %s", exc)

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        logger.info("Print scheduler stopped")

    async def check_queue(self) -> bool:
        """Check for prints ready to start.

        Returns True if this pass dispatched at least one item, so the caller
        can loop again quickly instead of sleeping the full interval (#2555).
        """
        return await QueuePass(self).run()

    def _launch_uploads(self, item_ids: list[int], item_printers: dict[int, int | None], limit: int) -> None:
        """Launch selected uploads as a refillable pool, capped at ``limit`` (#2602).

        Dispatch used to happen inline in the selection loop: ``await
        _start_print(db, item)`` per item in turn. Since ``_start_print``
        performs the FTP upload, that serialized every printer behind every
        other printer's transfer even though the printers are independent
        machines; #2555 moved it to a parallel ``asyncio.gather()``. But that
        gather was awaited before ``check_queue`` returned, so the run loop
        stayed blocked until the *slowest* upload in the batch finished — a
        513 s upload left 15 of 16 configured slots idle for 8.5 minutes on a
        93-printer farm even as other printers came free (#2602).

        Each upload now runs as an independent background task tracked in
        ``self._inflight``. check_queue excludes in-flight item_ids (still
        `pending` until their upload completes) and their printers from the
        next pass's selection, and this method launches at most
        ``limit - len(self._inflight)`` new uploads, so a freed slot refills on
        the next fast tick instead of waiting out the whole batch. The bound
        exists because the printers are independent but the host is not: each
        in-flight upload holds a thread in the FTP pool, a TLS session and a
        file handle.

        The no-overlapping-dispatch invariant the batch-await used to provide
        is now carried by the in-flight exclusion in check_queue. Everything
        else — the pending->printing CAS, the busy-printer guard (#2598), the
        per-printer hold, and each item's independent failure handling — still
        lives in ``_start_print`` and runs per task exactly as before.

        Synchronous on purpose: it registers every launched task into
        ``self._inflight`` before returning, so the next (sequential) tick sees
        an accurate in-flight count with no interleaving await.
        """
        free = limit - len(self._inflight)
        if free <= 0:
            logger.info(
                "Upload pool full (%d/%d in flight) — deferring %d item(s) to a later tick: %s",
                len(self._inflight),
                limit,
                len(item_ids),
                item_ids,
            )
            return

        to_launch = item_ids[:free]
        deferred = item_ids[free:]
        logger.info(
            "Launching %d upload(s) (pool %d/%d in flight)%s",
            len(to_launch),
            len(self._inflight),
            limit,
            f" — deferring {deferred} to a later tick" if deferred else "",
        )

        for item_id in to_launch:
            task = spawn_background_task(
                self._dispatch_one(item_id, item_printers.get(item_id)),
                name=f"queue-upload-{item_id}",
            )
            self._inflight[item_id] = (task, item_printers.get(item_id))
            # Prune on completion so the freed slot is refillable next tick.
            # spawn_background_task already logs any uncaught exception; this
            # only reclaims the pool slot (fires on success, failure, or cancel).
            task.add_done_callback(lambda _t, iid=item_id: self._inflight.pop(iid, None))

    async def _dispatch_one(self, item_id: int, selected_printer_id: int | None = None) -> None:
        """Upload + start one queue item in its own session (pool worker, #2602).

        Its own session: pool workers run concurrently and an AsyncSession is
        not safe to share across tasks; it also keeps a slow upload from pinning
        the scheduler's session (and, on SQLite, its transaction) open for the
        transfer's duration.

        ``selected_printer_id`` is the printer this item was selected for, taken
        from the same snapshot the caller used. It exists so the preheat pin can
        be unwound on the paths that never reach the ``finally`` below — see the
        claim failure a few lines down. Optional so the direct-call tests keep
        working; when it is absent those paths simply behave as they did before.
        """
        async with async_session() as item_db:
            # Claim the row for dispatch BEFORE reading the printer snapshot or
            # touching any slow I/O (#2615). The claim is an atomic CAS on
            # (status='pending', dispatching_at IS NULL); while it's held the edit
            # routes reject reassignment (409), so printer_id can't change out from
            # under the in-flight upload and split the queue row from the
            # archive/expected-print/physical command.
            if not await self._claim_for_dispatch(item_db, item_id):
                logger.info(
                    "Queue item %s not claimable for dispatch (cancelled, removed, or already claimed) — skipping",
                    item_id,
                )
                # This return is outside the try/finally below, so the rollback
                # has to happen here. Selecting this item already handed any
                # keep-warm hold on its printer over to the preheat pin
                # (`_sweep_keep_warm`), on the promise that this dispatch would
                # unwind it. Bailing without doing so leaves the bed hot with
                # nothing tracking it: the keep-warm entry is gone, so the
                # max-duration cap no longer applies, and if this was the
                # printer's last pending item nothing else will ever turn it
                # off. Reachable whenever a cancel or delete lands between
                # selection and the claim.
                if selected_printer_id is not None:
                    self._rollback_preheat_pin(item_id, selected_printer_id)
                return
            # Seeded from the caller's snapshot so the `item vanished` return
            # below still unwinds the pin; overwritten with the row's own
            # printer_id as soon as we have it.
            item_printer_id: int | None = selected_printer_id
            try:
                item = await item_db.get(PrintQueueItem, item_id)
                if not item:
                    logger.info("Queue item %s vanished after claim — skipping", item_id)
                    return
                item_printer_id = item.printer_id
                await self._start_print(item_db, item)
            finally:
                # Undo an expected-print registration whose print command never
                # went out. One choke point covers every way `_start_print` can
                # end without sending: a raised exception (a DB failure mid-
                # dispatch is the reported case), an early return, a cancel
                # winning the #1853 CAS, or `start_print()` returning False.
                # A confirmed send removes the entry itself, so this is a no-op
                # on the happy path.
                self._rollback_unconfirmed_expected_print(item_id)
                # Mirror the pre-#1625 background-dispatch lifecycle: a
                # reservation survives only after start_print() accepted the
                # command. Failure, cancellation, deferral, and exceptions all
                # release it here.
                await asyncio.shield(self._release_unconfirmed_budget_reservation(item_id))
                # Unwind preheat state (bed/chamber/airduct) if the
                # dispatch aborted before the print's own gcode took over.
                # `_start_print` clears the pin on successful `start_print()`;
                # anything still present here is by definition an aborted
                # dispatch and gets rolled back so the printer isn't left
                # heating for a job that isn't happening.
                if item_printer_id is not None:
                    self._rollback_preheat_pin(item_id, item_printer_id)
                # The cancellation flag only has meaning while this dispatch is
                # running; drop it so the set cannot grow without bound and a
                # re-queued item never inherits a stale cancellation.
                self._cancelled_dispatches.discard(item_id)
                # Release the claim on every exit. Once dispatch has finished the
                # row's status carries the lock (printing/failed/cancelled are all
                # != pending), so the token is only needed for the duration of the
                # upload. A row left pending (e.g. busy-printer deferral) becomes
                # dispatchable again on the next tick.
                await self._clear_dispatch_claim(item_db, item_id)

    async def _requeue_after_upload_refused(
        self,
        db: AsyncSession,
        item: PrintQueueItem,
        printer: Printer,
        error_msg: str,
        toast_uid: int | None,
    ) -> None:
        """Put an item back in the queue after its file never reached the printer (#3210).

        The item keeps its printer. Its AMS mapping was computed against that
        printer's trays, and nothing on the row says whether a mapping was
        computed or set by the user, so moving it to a sibling could print from
        the wrong slots. The printer goes into `_upload_backoff` instead, which
        keeps every other item away from it; this one waits there and is the
        only thing that knocks again, once per backoff window. The window
        grows with each refusal in a row; see ``_upload_backoff_seconds``.

        `dispatch_attempts` is not charged: that budget bounds a printer that
        takes the file and then never starts, which this is not.
        """
        refusals = self._upload_refusals.get(printer.id, 0) + 1
        self._upload_refusals[printer.id] = refusals
        backoff = _upload_backoff_seconds(refusals)
        self._upload_backoff[printer.id] = time.monotonic() + backoff
        # The row is still `pending` -- it only moves to `printing` after a
        # successful upload -- so there is no status to write back. Writing one
        # anyway would undo a cancel that landed during the upload.
        if item.error_message:
            item.error_message = None
            await db.commit()
        logger.warning(
            "Queue item %s: upload to printer %s (%s) never reached it — %s Kept in the queue; "
            "refusal %d in a row, so the printer is out of dispatch for %ds.",
            item.id,
            printer.id,
            printer.name,
            error_msg,
            refusals,
            backoff,
        )
        try:
            # Closes the dispatch toast for this attempt. Without it the toast
            # keeps spinning on an upload that has ended.
            await ws_manager.send_queue_item_failed(
                user_id=toast_uid,
                queue_item_id=item.id,
                printer_id=item.printer_id,
                reason="upload_failed",
            )
        except Exception:
            pass  # toast is best-effort

    def _rollback_unconfirmed_expected_print(self, item_id: int) -> None:
        """Drop an expectation for a print command that was never sent.

        Best-effort and never raises: this runs in the ``finally`` of dispatch,
        where the interesting exception is usually the one already propagating.
        """
        pending = self._unconfirmed_expected_print.pop(item_id, None)
        if pending is None:
            return
        printer_id, remote_filename, archive_id = pending
        try:
            from backend.app.main import unregister_expected_print

            unregister_expected_print(printer_id, remote_filename, archive_id)
        except Exception:
            logger.warning(
                "Queue item %s: failed to unregister expected print (printer=%s, file=%s, archive=%s)",
                item_id,
                printer_id,
                remote_filename,
                archive_id,
                exc_info=True,
            )

    async def _release_unconfirmed_budget_reservation(self, item_id: int) -> None:
        """Release a queue reservation without touching the dispatch session."""
        if item_id not in self._unconfirmed_budget_reservations:
            return

        for attempt in range(1, 4):
            async with async_session() as cleanup_db:
                try:
                    await release_budget_reservation(
                        cleanup_db,
                        source_type="print_queue",
                        source_id=item_id,
                        status="released",
                    )
                    await cleanup_db.commit()
                    self._unconfirmed_budget_reservations.discard(item_id)
                    return
                except Exception as exc:
                    try:
                        await cleanup_db.rollback()
                    except Exception:
                        pass
                    if attempt == 3:
                        logger.error(
                            "Queue item %s: failed to release budget reservation after %d attempts: %s",
                            item_id,
                            attempt,
                            exc,
                        )
                        return
                    await asyncio.sleep(0.5 * attempt)

    @staticmethod
    def _reported_bed_target(printer_id: int) -> int | None:
        """The bed target firmware currently reports, or None if it can't be read.

        None means "no evidence", not "zero" — callers must not treat it as a
        temperature. Deliberately total: this feeds cleanup paths that run in a
        ``finally``, where a malformed status must not become the exception the
        caller sees.
        """
        try:
            state = printer_manager.get_status(printer_id)
            if state is None:
                return None
            temps = state.temperatures
            if not isinstance(temps, dict):
                return None
            return int(float(temps.get("bed_target", 0) or 0))
        except (TypeError, ValueError, AttributeError):
            return None

    def _rollback_preheat_pin(self, item_id: int, printer_id: int) -> None:
        """Unwind everything preheat set when dispatch did NOT hand off to a running print.

        Turns the bed heater off, the chamber heater off, and opens the
        airduct flap back to cooling — for whichever of those preheat
        actually applied. `_start_print` clears the pin on successful
        `start_print()`; anything still present when `_dispatch_one` exits
        is by definition an aborted dispatch and gets rolled back here.

        The bed is the one action that can be declined: if firmware has since
        been given a target other than the one we pinned, it belongs to someone
        else and is left alone. See the comment at that branch.

        Also called directly from `_dispatch_one`'s claim-failure return, which
        never reaches the ``finally``.

        Best-effort and never raises — this runs in the ``finally`` of dispatch.
        """
        pin = self._preheat_pin.pop(printer_id, set())
        pinned_bed = self._preheat_pin_bed.pop(printer_id, None)
        if not pin:
            return
        client = printer_manager.get_client(printer_id)
        if client is None:
            logger.info(
                "Dispatch item %s (printer %d): preheat rollback skipped — no client",
                item_id,
                printer_id,
            )
            return
        if "bed" in pin:
            # Only undo our own target. If firmware reports something else, the
            # user or another writer owns the bed now and zeroing it would
            # clobber their choice -- the same guard `_release_keep_warm`
            # applies to a keep-warm hold.
            #
            # Every uncertain case switches the bed off rather than leaving it:
            # no recorded target (a pin written before this bookkeeping, or a
            # setter that raised after pinning) and an unreadable status both
            # fall through. A bed left hot with no owner is the worse failure,
            # and this runs in a `finally` where raising would mask the real
            # exception.
            cur_bed_target = self._reported_bed_target(printer_id) if pinned_bed is not None else None
            if cur_bed_target is not None and cur_bed_target != pinned_bed:
                logger.info(
                    "Dispatch item %s (printer %d): rollback skipped bed → 0 (firmware target %d != pinned %d)",
                    item_id,
                    printer_id,
                    cur_bed_target,
                    pinned_bed,
                )
            else:
                try:
                    client.set_bed_temperature(0)
                except Exception as exc:
                    logger.warning("Dispatch item %s: rollback bed → 0 failed: %s", item_id, exc)
        if "chamber" in pin:
            try:
                client.set_chamber_temperature(0)
            except Exception as exc:
                logger.warning("Dispatch item %s: rollback chamber → 0 failed: %s", item_id, exc)
        if "airduct" in pin:
            try:
                client.set_airduct_mode("cooling")
            except Exception as exc:
                logger.warning("Dispatch item %s: rollback airduct → cooling failed: %s", item_id, exc)
        logger.info(
            "Dispatch item %s (printer %d): preheat rollback → %s",
            item_id,
            printer_id,
            sorted(pin),
        )

    async def _claim_for_dispatch(self, db: AsyncSession, item_id: int) -> bool:
        """Atomically stamp ``dispatching_at`` on a still-pending, unclaimed row.

        Returns True if this call won the claim, False if the row was already
        claimed, no longer pending (cancelled mid-tick), or removed. The CAS is
        the load-bearing guard against reassign-during-dispatch (#2615)."""
        res = await db.execute(
            update(PrintQueueItem)
            .where(PrintQueueItem.id == item_id)
            .where(PrintQueueItem.status == "pending")
            .where(PrintQueueItem.dispatching_at.is_(None))
            .values(dispatching_at=datetime.now(timezone.utc))
        )
        await db.commit()
        return res.rowcount > 0

    async def _clear_dispatch_claim(self, db: AsyncSession, item_id: int) -> None:
        """Clear the dispatch claim (#2615). Best-effort: a failure here must not
        mask the dispatch outcome.

        Retried, because the failure mode in practice is transient and narrow: a
        database that is momentarily unreachable — PostgreSQL out of connection
        slots is the observed case — refuses this write for a second or two while
        the dispatch that just ended is still holding the row out of the selection
        query. One attempt was enough to wedge the item; a couple of spaced
        attempts clear it. Each attempt rolls back first, since a failed write
        leaves the session needing it before it can be reused.

        If every attempt fails, ``_clear_stale_dispatch_claims`` picks the row up
        on the next quiet tick.
        """
        for attempt in range(1, 4):
            try:
                await db.execute(update(PrintQueueItem).where(PrintQueueItem.id == item_id).values(dispatching_at=None))
                await db.commit()
                return
            except Exception as exc:
                try:
                    await db.rollback()
                except Exception:
                    pass
                if attempt == 3:
                    logger.warning(
                        "Queue item %s: failed to clear dispatch claim after %d attempts: %s "
                        "— a later quiet tick will release it",
                        item_id,
                        attempt,
                        exc,
                    )
                    return
                await asyncio.sleep(0.5 * attempt)

    async def _printers_for_model(
        self,
        db: AsyncSession,
        model: str,
        target_location: str | None = None,
    ) -> list[Printer]:
        """Active printers of *model*, optionally narrowed to one location.

        Shared by the matcher and by the smart-plug wake step (#2786) so both
        answer "which printers can this job run on" from one query — a job can
        only be woken onto a printer the matcher would also have considered.
        """
        normalized_model = normalize_printer_model(model) or model
        query = (
            select(Printer)
            .where(func.lower(Printer.model) == normalized_model.lower())
            .where(Printer.is_active == True)  # noqa: E712
        )
        if target_location:
            query = query.where(Printer.location == target_location)
        result = await db.execute(query)
        # PrintLab: gleichmäßig auslasten. Der Drucker mit der geringsten Betriebszeit kommt zuerst dran, denn der
        # Planer nimmt bei gleicher Eignung den ersten freien (und der Aufwecker den ersten ausgeschalteten).
        return sorted(
            result.scalars().all(),
            key=lambda p: (printer_usage_seconds(p.runtime_seconds, p.print_hours_offset), p.id),
        )

    async def _wakeable_printer_ids(self, db: AsyncSession) -> set[int]:
        """Printer IDs that at least one enabled ``auto_on`` plug can power on.

        Read once per queue check rather than per printer: it decides both
        whether the wake step has anything to do and how an offline printer is
        worded in the waiting reason — "Offline" and "offline with no Auto On
        plug" are different problems, and the second is the one the user has to
        fix themselves (#2786).
        """
        result = await db.execute(
            select(SmartPlug.printer_id)
            .where(SmartPlug.printer_id.is_not(None))
            .where(SmartPlug.enabled == True)  # noqa: E712
            .where(SmartPlug.auto_on == True)  # noqa: E712
        )
        return {pid for (pid,) in result.all() if pid is not None}

    def _wake_recently_failed(self, printer_id: int) -> bool:
        """True while this printer's failed power-on is still cooling off (#2786)."""
        deadline = self._wake_failures.get(printer_id)
        if deadline is None:
            return False
        if time.monotonic() >= deadline:
            del self._wake_failures[printer_id]
            return False
        return True

    async def _wake_printer_for_model(
        self,
        db: AsyncSession,
        candidates: list[_ModelCandidate],
        target_location: str | None,
        exclude_ids: set[int],
        wakeable_ids: set[int],
        require_plate_clear: bool,
    ) -> tuple[int | None, int | None]:
        """Power on one offline printer a model-based item could run on (#2786).

        The fixed-printer branch has powered a printer on since smart plugs
        existed. The model-based branch never could: its matcher drops an
        offline printer into the "Offline:" waiting reason and nothing looks at
        its plugs, so a class-targeted job with every matching printer switched
        off sat pending forever. The reporter's log is the controlled
        experiment — the same item, same plug, same Auto On setting, dispatched
        the moment they edited it onto a specific printer.

        Returns ``(woken_id, attempted_id)``. ``attempted_id`` is set whenever a
        power-on was actually tried, so the caller can tell "nothing here was
        wakeable" (both None — cheap, other items may still find something)
        from "we tried and it did not come up" (only ``attempted_id`` — the
        boot timeout has already been spent).

        A printer whose last known trays cannot satisfy the job is passed over
        rather than woken (#2876): the colours are readable while it is off, so
        switching a farm on one machine at a time to discover them wakes
        printers that could never have taken the job.

        Deliberately does NOT go on to match the job once a printer is up: AMS
        trays arrive with the first status push after connect, so a filament
        check against a printer that booted seconds ago can reject the printer
        we just woke. The next queue pass matches it with live state.

        At most one printer per pass. Each wake blocks the queue loop for the
        boot wait, and a queue of ten class-targeted jobs must not switch on
        ten printers inside one check.
        """
        for candidate in candidates:
            if not candidate.target_model:
                continue
            required_types, filament_overrides = _filament_constraints(candidate)
            printers = await self._printers_for_model(db, candidate.target_model, target_location)
            for printer in sorted(printers, key=lambda p: p.id):
                if printer.id in exclude_ids or printer.id not in wakeable_ids:
                    continue
                if printer_manager.is_connected(printer.id):
                    continue
                if self._wake_recently_failed(printer.id):
                    # Its plug did not bring it back a moment ago. Move on to a
                    # sibling instead of spending this pass — and every pass —
                    # on the same printer.
                    continue
                if require_plate_clear and printer_manager.is_awaiting_plate_clear(printer.id):
                    # Waking this one buys nothing: it would boot into IDLE and
                    # then be held by the plate-clear gate, which is exactly
                    # what the reporter's log shows happening for 80 minutes
                    # after a fixed-printer wake. The flag is PrintLab-side and
                    # persisted, so it is readable while the printer is off.
                    logger.info(
                        "Not powering on printer %s for a %s job: it is awaiting plate-clear acknowledgment",
                        printer.id,
                        candidate.target_model,
                    )
                    continue

                shortfall = self._cached_filament_shortfall(printer.id, required_types, filament_overrides)
                if shortfall:
                    logger.info(
                        "Not powering on printer %s for a %s job: last known filament cannot satisfy it (needs %s)",
                        printer.id,
                        candidate.target_model,
                        ", ".join(shortfall),
                    )
                    continue

                plugs = await self._get_smart_plugs(db, printer.id)
                auto_on_plugs = [p for p in plugs if p.auto_on and p.enabled]
                if not auto_on_plugs:
                    # wakeable_ids said otherwise — the plug changed under us
                    # mid-pass. Nothing to do but move on.
                    continue

                logger.info(
                    "No %s printer available for a queued job; powering on offline printer %s via smart plug(s)",
                    candidate.target_model,
                    printer.id,
                )
                primary_plug = self._pick_power_plug(auto_on_plugs)
                if not await self._power_on_and_wait(primary_plug, printer.id, db):
                    logger.warning(
                        "Could not power on printer %s via smart plug; not trying it again for %ss",
                        printer.id,
                        self._wake_failure_cooloff,
                    )
                    self._wake_failures[printer.id] = time.monotonic() + self._wake_failure_cooloff
                    return None, printer.id

                for extra_plug in [p for p in auto_on_plugs if p.id != primary_plug.id]:
                    try:
                        service = await smart_plug_manager.get_service_for_plug(extra_plug, db)
                        await service.turn_on(extra_plug)
                        logger.info("Also powered on plug '%s' for printer %s", extra_plug.name, printer.id)
                    except Exception as e:
                        logger.warning("Failed to power on extra plug '%s': %s", extra_plug.name, e)
                return printer.id, printer.id
        return None, None

    async def _find_idle_printer_for_model(
        self,
        db: AsyncSession,
        model: str,
        exclude_ids: set[int],
        required_filament_types: list[str] | None = None,
        target_location: str | None = None,
        filament_overrides: list[dict] | None = None,
        require_plate_clear: bool = True,
        wakeable_ids: set[int] | None = None,
    ) -> tuple[int | None, str | None]:
        """Find an idle, connected printer matching the model with compatible filaments.

        Args:
            db: Database session
            model: Printer model to match (e.g., "X1C", "P1S")
            exclude_ids: Printer IDs to exclude (already busy)
            required_filament_types: Optional list of filament types needed (e.g., ["PLA", "PETG"])
                                     If provided, only printers with all required types loaded will match.
            target_location: Optional location filter. If provided, only printers in this location are considered.
            filament_overrides: Optional list of override dicts. Each entry may include
                                 ``force_color_match: true`` to require an exact type+color match
                                 on the printer for that slot. Without the flag the existing
                                 colour-preference logic applies.
            wakeable_ids: Printers a smart plug can power on (#2786). Only changes how an
                          offline printer is worded: one PrintLab will switch on reads
                          differently from one the user has to go and switch on themselves.

        Returns:
            Tuple of (printer_id, waiting_reason):
            - (printer_id, None) if a matching printer was found
            - (None, reason) if no printer is available, with explanation
        """
        normalized_model = normalize_printer_model(model) or model
        printers = await self._printers_for_model(db, model, target_location)

        location_suffix = f" in {target_location}" if target_location else ""
        if not printers:
            return None, f"No active {normalized_model} printers{location_suffix} configured"

        # Separate force-matched overrides from preference-only overrides
        force_overrides = [o for o in (filament_overrides or []) if o.get("force_color_match")]
        pref_overrides = [o for o in (filament_overrides or []) if not o.get("force_color_match")]

        # Track reasons for skipping printers
        printers_busy = []
        printers_offline = []
        printers_offline_no_plug = []
        printers_missing_filament: list[tuple[str, list[str]]] = []
        candidates: list[tuple[int, int]] = []  # (printer_id, color_match_count)

        for printer in printers:
            if printer.id in exclude_ids:
                # Printer is already claimed by another job in this scheduling run.
                # For force-color jobs, still check if the color would match — if not,
                # report it as a color mismatch rather than plain "Busy" so the user
                # knows the job needs a filament change, not just to wait for availability.
                if force_overrides and not pref_overrides:
                    missing_colors = self._get_missing_force_color_slots(printer.id, force_overrides)
                    if missing_colors:
                        printers_missing_filament.append((printer.name, missing_colors))
                        continue
                printers_busy.append(printer.name)
                continue

            is_connected = printer_manager.is_connected(printer.id)
            is_idle = self._is_printer_idle(printer.id, require_plate_clear) if is_connected else False

            if not is_connected:
                # An offline printer whose last known filament cannot run this
                # job is reported as needing filament rather than as offline
                # (#2876). It is also the printer the smart-plug step will now
                # decline to switch on, and "Offline:" on its own would leave
                # that decision looking like nothing happening at all.
                shortfall = self._cached_filament_shortfall(printer.id, required_filament_types, filament_overrides)
                if shortfall:
                    printers_missing_filament.append((printer.name, shortfall))
                elif wakeable_ids is not None and printer.id not in wakeable_ids:
                    printers_offline_no_plug.append(printer.name)
                else:
                    printers_offline.append(printer.name)
                continue

            if not is_idle:
                # Printer is currently printing.  For force-color jobs, check whether the
                # loaded color would satisfy the requirement — if not, surface it as a
                # color-mismatch reason rather than plain "Busy" so the user understands
                # that the job is waiting for a filament change, not just printer availability.
                if force_overrides and not pref_overrides:
                    missing_colors = self._get_missing_force_color_slots(printer.id, force_overrides)
                    if missing_colors:
                        printers_missing_filament.append((printer.name, missing_colors))
                        logger.debug(
                            "Printer %s (%s) is busy but also has wrong force-color: %s",
                            printer.id,
                            printer.name,
                            missing_colors,
                        )
                        continue
                printers_busy.append(printer.name)
                continue

            # Validate filament compatibility if required types are specified
            if required_filament_types:
                missing = self._get_missing_filament_types(printer.id, required_filament_types)
                if missing:
                    # When force_overrides are present, enrich missing entries with color info
                    # so the "Waiting on" message includes "TYPE (color)" instead of just "TYPE"
                    if force_overrides:
                        force_color_map = {
                            (o.get("type") or "").upper(): o.get("color_name") or o.get("color", "?")
                            for o in force_overrides
                        }
                        missing_enriched = [
                            f"{t} ({force_color_map[t_upper]})" if (t_upper := t.upper()) in force_color_map else t
                            for t in missing
                        ]
                        printers_missing_filament.append((printer.name, missing_enriched))
                    else:
                        printers_missing_filament.append((printer.name, missing))
                    logger.debug("Skipping printer %s (%s) - missing filaments: %s", printer.id, printer.name, missing)
                    continue

            # Force color match: ALL flagged slots must have an exact type+color match
            if force_overrides:
                missing_colors = self._get_missing_force_color_slots(printer.id, force_overrides)
                if missing_colors:
                    printers_missing_filament.append((printer.name, missing_colors))
                    logger.debug(
                        "Skipping printer %s (%s) - missing force-matched colors: %s",
                        printer.id,
                        printer.name,
                        missing_colors,
                    )
                    continue

            # If preference-only overrides exist, rank by color matches (existing behaviour)
            if pref_overrides:
                color_matches = self._count_override_color_matches(printer.id, pref_overrides)
                if color_matches > 0:
                    candidates.append((printer.id, color_matches))
                else:
                    override_colors = [f"{o.get('type', '?')} ({o.get('color', '?')})" for o in pref_overrides]
                    printers_missing_filament.append((printer.name, override_colors))
                    logger.debug("Skipping printer %s (%s) - no matching override colors", printer.id, printer.name)
                    continue
            elif force_overrides:
                # Passed all force checks — immediately eligible (no preference ordering needed)
                return printer.id, None
            else:
                # No overrides at all - take first available (existing behavior)
                return printer.id, None

        # If we have candidates from preference override matching, pick the one with most color matches
        if candidates:
            candidates.sort(key=lambda c: c[1], reverse=True)
            return candidates[0][0], None

        # Build waiting reason from what we found
        reasons = []
        if printers_missing_filament:
            # Filament/color mismatch is most actionable - show first
            if force_overrides and not pref_overrides:
                # All mismatches are force-color failures — use descriptive message only;
                # but only if there are no busy printers that DO have the matching color.
                # If a printer has the right color but is busy, surface "Busy" instead so
                # the user knows the job will start automatically once that printer is free.
                # Same for a printer that is merely offline: PrintLab switches that one on
                # by itself, so the job is not actually waiting on anybody to change a
                # spool (#2876 — offline printers reach this list now that a switched-off
                # printer's own filament is read).
                if not printers_busy and not printers_offline:
                    all_missing = sorted({c for _, cols in printers_missing_filament for c in cols})
                    return None, f"No matching material/color. Waiting on {', '.join(all_missing)}"
                # else: fall through — the self-resolving entries are appended below
            else:
                names_and_missing = [
                    f"{name} (needs {', '.join(missing)})" for name, missing in printers_missing_filament
                ]
                reasons.append(f"Waiting for filament: {'; '.join(names_and_missing)}")
        if printers_busy:
            reasons.append(f"Busy: {', '.join(printers_busy)}")
        if printers_offline:
            reasons.append(f"Offline: {', '.join(printers_offline)}")
        if printers_offline_no_plug:
            # Named separately because it is the one entry on this list the
            # user has to act on: no enabled Auto On plug means PrintLab will
            # never power this printer on for the queue (#2786).
            reasons.append(f"Offline, no Auto On smart plug: {', '.join(printers_offline_no_plug)}")

        return None, " | ".join(reasons) if reasons else f"No available {model} printers{location_suffix}"

    @staticmethod
    def _is_busy_only(waiting_reason: str) -> bool:
        """Check if the waiting reason only contains 'Busy' entries.

        The decision itself lives in :mod:`backend.app.services.scheduler.filament`,
        because the waiting-reason text is built there; this keeps the class method
        as the name callers already use.
        """
        return _is_busy_only(waiting_reason)

    def _get_missing_force_color_slots(
        self, printer_id: int, force_overrides: list[dict], raw_data: dict | None = None
    ) -> list[str]:
        """Return descriptive strings for force_color_match slots not satisfied by the printer.

        Each entry in ``force_overrides`` must have ``type`` and ``color`` fields and is expected
        to carry ``force_color_match: True``.  The printer must have **every** such slot loaded
        with an exact type+color match.

        When both the override and a candidate tray carry a ``tray_info_idx``, they must also
        match on it: Bambu reports every PLA variant as ``tray_type == "PLA"``, so the
        Basic/Matte/Silk distinction lives only in ``tray_info_idx`` (GFA00/GFA01/GFA06/...).
        Without this, a job sliced for PLA Matte matched every white PLA regardless of variant
        (#2650). If either side lacks an idx (custom/third-party spools report a blank one, and
        older 3MFs carry none) we fall back to the historical type+colour behaviour so those
        setups are unaffected.

        Returns:
            List of ``"TYPE (color)"`` strings for unmatched slots (empty list means all match).
        """
        if raw_data is None:
            status = printer_manager.get_status(printer_id)
            if not status:
                return [f"{o.get('type', '?')} ({o.get('color_name') or o.get('color', '?')})" for o in force_overrides]
            raw_data = status.raw_data

        # Build loaded (type, colour, tray_info_idx) triples from AMS and external spool.
        loaded: list[tuple[str, str, str]] = []
        for ams_unit in raw_data.get("ams", []):
            for tray in ams_unit.get("tray", []):
                tray_type = tray.get("tray_type")
                if tray_type:
                    color_norm = (tray.get("tray_color", "") or "").replace("#", "").lower()[:6]
                    loaded.append((canonical_filament_type(tray_type), color_norm, tray.get("tray_info_idx", "") or ""))
        for vt in raw_data.get("vt_tray") or []:
            vt_type = vt.get("tray_type")
            if vt_type:
                color_norm = (vt.get("tray_color", "") or "").replace("#", "").lower()[:6]
                loaded.append((canonical_filament_type(vt_type), color_norm, vt.get("tray_info_idx", "") or ""))

        missing = []
        for o in force_overrides:
            o_type = canonical_filament_type(o.get("type") or "")
            o_color = (o.get("color") or "").replace("#", "").lower()[:6]
            o_idx = o.get("tray_info_idx") or ""
            satisfied = any(
                t_type == o_type and t_color == o_color and (not o_idx or not t_idx or o_idx == t_idx)
                for t_type, t_color, t_idx in loaded
            )
            if not satisfied:
                color_label = o.get("color_name") or o.get("color", "?")
                missing.append(f"{o_type} ({color_label})")
        return missing

    def _get_missing_filament_types(
        self, printer_id: int, required_types: list[str], raw_data: dict | None = None
    ) -> list[str]:
        """Get the list of required filament types that are not loaded on the printer.

        Args:
            printer_id: The printer ID
            required_types: List of filament types needed (e.g., ["PLA", "PETG"])

        Returns:
            List of missing filament types (empty if all are loaded)
        """
        if raw_data is None:
            status = printer_manager.get_status(printer_id)
            if not status:
                return required_types  # Can't determine, assume all missing
            raw_data = status.raw_data

        # Collect all filament types loaded on this printer (AMS units + external spool)
        # Use canonical types so equivalence groups (e.g. PA-CF/PA12-CF/PAHT-CF) match.
        loaded_types: set[str] = set()

        # Check AMS units (stored in raw_data["ams"])
        ams_data = raw_data.get("ams", [])
        if ams_data:
            for ams_unit in ams_data:
                for tray in ams_unit.get("tray", []):
                    tray_type = tray.get("tray_type")
                    if tray_type:
                        loaded_types.add(canonical_filament_type(tray_type))

        # Check external spool(s) (virtual tray, stored in raw_data["vt_tray"] as list)
        for vt in raw_data.get("vt_tray") or []:
            vt_type = vt.get("tray_type")
            if vt_type:
                loaded_types.add(canonical_filament_type(vt_type))

        # Find which required types are missing (using canonical type for equivalence)
        missing = []
        for req_type in required_types:
            if canonical_filament_type(req_type) not in loaded_types:
                missing.append(req_type)

        return missing

    def _count_override_color_matches(
        self, printer_id: int, overrides: list[dict], raw_data: dict | None = None
    ) -> int:
        """Count how many filament overrides have an exact color match on the printer.

        Used to prefer printers that already have the desired override colors loaded.
        """
        if raw_data is None:
            status = printer_manager.get_status(printer_id)
            if not status:
                return 0
            raw_data = status.raw_data

        # Collect loaded filaments' type+color pairs
        loaded: set[tuple[str, str]] = set()
        for ams_unit in raw_data.get("ams", []):
            for tray in ams_unit.get("tray", []):
                tray_type = tray.get("tray_type")
                # `or ""`, not a dict default: a slot can carry the key with a
                # null value, and this now runs against switched-off printers
                # too, where nobody is watching for the AttributeError.
                tray_color = tray.get("tray_color") or ""
                if tray_type:
                    color_norm = tray_color.replace("#", "").lower()[:6]
                    loaded.add((tray_type.upper(), color_norm))
        for vt in raw_data.get("vt_tray") or []:
            vt_type = vt.get("tray_type")
            if vt_type:
                color_norm = (vt.get("tray_color", "") or "").replace("#", "").lower()[:6]
                loaded.add((vt_type.upper(), color_norm))

        matches = 0
        for o in overrides:
            o_type = (o.get("type") or "").upper()
            o_color = (o.get("color") or "").replace("#", "").lower()[:6]
            if (o_type, o_color) in loaded:
                matches += 1
        return matches

    @staticmethod
    def _tray_reading(printer_id: int) -> dict:
        """The best tray reading available for a printer that is not printing.

        Live status first: a printer keeps its last status after the power
        goes, because ``mark_power_off`` blanks ``connected`` and ``state`` and
        leaves ``raw_data`` alone. The manager's own record is the fallback,
        for when the client itself has been dropped and taken its status with
        it — which is what every power-on attempt does.

        An empty result means "we have never heard", not "nothing is loaded":
        the two are indistinguishable from here, and only the second would be
        safe to act on.
        """
        status = printer_manager.get_status(printer_id)
        raw = (status.raw_data if status else None) or {}
        for ams_unit in raw.get("ams") or []:
            if any(tray.get("tray_type") for tray in ams_unit.get("tray", [])):
                return raw
        if any(vt.get("tray_type") for vt in raw.get("vt_tray") or []):
            return raw
        return printer_manager.last_known_trays(printer_id)

    def _cached_filament_shortfall(
        self,
        printer_id: int,
        required_types: list[str] | None,
        filament_overrides: list[dict] | None,
    ) -> list[str]:
        """What a switched-off printer's last known filament cannot provide (#2876).

        The smart-plug wake step used to consider only the model, so a job for a
        colour loaded on the last printer in ID order switched on every earlier
        one in turn, evaluated it, rejected it on colour and left it running.
        PrintLab knew those colours the whole time. This asks the same three
        questions the matcher asks a live printer — required types, forced
        colours, preferred colours — of the trays it last reported, and returns
        the answers in the same shape the "Waiting for filament" reason uses.

        Empty means the printer may still be able to take the job.

        Fails open, and deliberately: with no tray reading (never connected
        since PrintLab started, or the cache dropped by a reconnect) this
        returns nothing to report and the printer is treated as it was before.
        A farm restarted while its printers were off must not conclude that
        none of them can print.
        """
        if not required_types and not filament_overrides:
            return []

        raw_data = self._tray_reading(printer_id)
        if not raw_data:
            return []

        force_overrides = [o for o in (filament_overrides or []) if o.get("force_color_match")]
        pref_overrides = [o for o in (filament_overrides or []) if not o.get("force_color_match")]

        if required_types:
            missing = self._get_missing_filament_types(printer_id, required_types, raw_data)
            if missing:
                # Same enrichment the live path applies: a bare "PLA" is not
                # much help when what is missing is a particular PLA.
                force_color_map = {
                    (o.get("type") or "").upper(): o.get("color_name") or o.get("color", "?") for o in force_overrides
                }
                return [
                    f"{t} ({force_color_map[t_upper]})" if (t_upper := t.upper()) in force_color_map else t
                    for t in missing
                ]

        if force_overrides:
            missing_colors = self._get_missing_force_color_slots(printer_id, force_overrides, raw_data)
            if missing_colors:
                return missing_colors

        # Preference overrides read as a preference but the matcher treats zero
        # matches as a skip, so a printer with none of the wanted colours is
        # rejected there too. Waking it would only produce that same rejection.
        if pref_overrides and self._count_override_color_matches(printer_id, pref_overrides, raw_data) == 0:
            return [f"{o.get('type', '?')} ({o.get('color_name') or o.get('color', '?')})" for o in pref_overrides]

        return []

    def _resolve_variant(self, item: PrintQueueItem, candidate: _ModelCandidate) -> None:
        """Fold the winning candidate's file and settings onto the queue row (#671).

        This is the whole trick that keeps cross-model items cheap: the many-to-many
        never escapes the selection loop. By the time the pass commits, the row
        looks exactly like an ordinary single-file model-based item, so the upload,
        archive creation, expected-print registration, print history and reprint
        paths need no knowledge that variants exist.

        No-ops for a non-variant candidate, which is already the item's own columns.

        Safe to run and re-run: the item's file columns are only ever *read* when it
        has no variants, so an item that gets resolved and then skipped (library-row
        conflict, previous-print gate) is simply resolved again on the next pass.
        """
        variant = candidate.variant
        if variant is None:
            return

        item.library_file_id = variant.library_file_id
        item.library_file = variant.library_file
        # The dispatcher checks archive_id first and would print that instead of
        # the file we just picked. Creation refuses to combine the two, so this
        # only ever fires on a hand-written row — clear it rather than silently
        # dispatch something the matcher never considered.
        item.archive_id = None
        item.archive = None

        item.target_model = variant.target_model
        item.plate_id = variant.plate_id
        item.ams_mapping = variant.ams_mapping
        item.nozzle_mapping = variant.nozzle_mapping
        item.nozzle_rack_choice = variant.nozzle_rack_choice
        item.filament_overrides = variant.filament_overrides
        item.required_filament_types = variant.required_filament_types
        if variant.print_time_seconds is not None:
            # The row carried the shortest candidate's estimate so SJF could order
            # it before a printer was known; now that one is chosen, record what is
            # actually going to run so history and the ETA agree with reality.
            item.print_time_seconds = variant.print_time_seconds

    async def _ensure_ams_mapping(self, db: AsyncSession, printer_id: int, item: PrintQueueItem) -> str | None:
        """Ensure the queue item carries a usable AMS mapping before dispatch.

        Recomputes from live printer status when the stored mapping is missing OR
        unresolved (all -1). A stored all-[-1] mapping is a bug artifact — a
        frontend status-load race can serialize [-1] before the printer's AMS
        trays are known (#2589) — and must not be trusted: downstream it would be
        silently downgraded to external-spool mode and print against an empty
        feed. A resolved mapping (including manual overrides, or a partially
        padded one) is left untouched.

        When recompute cannot resolve it either (no compatible tray loaded), the
        bogus [-1] is cleared to None so it is not later mistaken for an explicit
        external selection; the print command then keeps use_ams=True and the
        firmware surfaces a clear AMS-mapping error instead of silently printing
        to the empty external feed.

        Returns an actionable message when that firmware error is the only
        possible outcome — the matcher ran, matched nothing, and the printer has
        no AMS to load a different spool into (#2771). The caller fails the item
        on it instead of spending an upload on a print that cannot start.
        Returns None everywhere else, including every case where we simply lack
        the data to judge, so dispatch is only ever blocked on a positive
        finding.
        """
        stored_mapping: list | None = None
        if item.ams_mapping:
            try:
                stored_mapping = json.loads(item.ams_mapping)
            except (json.JSONDecodeError, TypeError):
                stored_mapping = None

        # Already resolved (present and not all-unresolved) — keep as-is so a
        # user's manual mapping is never overwritten.
        if item.ams_mapping and not _mapping_is_all_unresolved(stored_mapping):
            return None

        computed_mapping = await self._compute_ams_mapping_for_printer(db, printer_id, item)
        if computed_mapping and not _mapping_is_all_unresolved(computed_mapping):
            item.ams_mapping = json.dumps(computed_mapping)
            logger.info(
                "Queue item %s: Computed AMS mapping for printer %s: %s",
                item.id,
                printer_id,
                computed_mapping,
            )
            await db.commit()
            return None

        if _mapping_is_all_unresolved(stored_mapping):
            logger.warning(
                "Queue item %s: stored ams_mapping %s is unresolved and could not be recomputed "
                "from live status on printer %s; clearing it so dispatch does not treat it as external",
                item.id,
                stored_mapping,
                printer_id,
            )
            item.ams_mapping = None
            await db.commit()

        return await self._unmappable_without_ams_message(db, printer_id, item, computed_mapping)

    async def _unmappable_without_ams_message(
        self,
        db: AsyncSession,
        printer_id: int,
        item: PrintQueueItem,
        computed_mapping: list[int] | None,
    ) -> str | None:
        """Message for a mapping that resolved nothing on an AMS-less printer (#2771).

        A print dispatched with no mapping goes out as ``use_ams: true`` with no
        ``ams_mapping`` and no ``ams_mapping2``, which the firmware rejects with
        0700_8012 "Failed to get AMS mapping table" — after PrintLab has already
        uploaded several megabytes and burned its dispatch retries. With an AMS
        attached that error is worth reaching: the user can load the right spool
        and press Resume, so this returns None and today's behaviour stands. With
        no AMS there is nothing to resume into — the external spool holder is the
        whole inventory — so the useful answer is to say which filament is
        missing and stop.

        Fail-safe by construction, mirroring the nozzle-diameter guard (#1899):
        every branch that lacks the evidence to be sure returns None.
        """
        # None means the matcher never ran (no requirements parsed from the 3MF,
        # or nothing loaded at all) rather than "ran and matched nothing". Those
        # dispatch as they always have.
        if not _mapping_is_all_unresolved(computed_mapping):
            return None

        status = printer_manager.get_status(printer_id)
        if status is None:
            return None

        # "No AMS" has to be a fact the printer stated, not the absence of a
        # statement. `raw_data["ams"]` is written only once an AMS push has been
        # handled and is preserved across partial pushes thereafter, so a missing
        # key means we have not heard yet — most likely a reconnect, where the
        # trays of a fully loaded AMS would be invisible for a few seconds. An
        # empty list is the positive report of a printer with no AMS.
        ams_units = status.raw_data.get("ams")
        if not isinstance(ams_units, list) or ams_units:
            return None

        required = await self._get_filament_requirements(db, item)
        loaded = self._build_loaded_filaments(status)
        if not required or not loaded:
            # Both were non-empty moments ago or the matcher could not have run.
            # If the picture changed under us, say nothing rather than fail an
            # item on stale evidence.
            return None
        self._apply_filament_overrides(item, required)
        return _unmatched_filament_message(required, loaded)

    async def _fail_unmappable_item(
        self, db: AsyncSession, item: PrintQueueItem, printer_id: int, message: str
    ) -> None:
        """Fail a queue item whose filament mapping cannot resolve (#2771).

        This replaces a failure, not a success: without it the item is uploaded,
        rejected by the firmware with 0700_8012, retried twice more and failed
        anyway with "never started the print after N dispatch attempts". So this
        applies on the model-based path too, even though it means an "Any <model>"
        job stops at the first printer offered rather than trying its siblings —
        deferring instead would need the check to move inside
        ``_find_printer_for_model``'s candidate loop, since un-assigning here just
        re-assigns the same printer on the next tick.
        """
        item.status = "failed"
        item.error_message = message
        item.completed_at = datetime.now(timezone.utc)
        item.waiting_reason = None
        await db.commit()
        logger.warning(
            "Queue item %s: no usable AMS mapping on printer %s — %s",
            item.id,
            printer_id,
            message,
        )

        job_name = await self._get_job_name(db, item)
        printer = await self._get_printer(db, printer_id)
        await notification_service.on_queue_job_failed(
            job_name=job_name,
            printer_id=printer_id,
            printer_name=printer.name if printer else "Unknown",
            reason=message,
            db=db,
        )
        try:
            await ws_manager.send_queue_item_failed(
                user_id=item.created_by_id,
                queue_item_id=item.id,
                printer_id=printer_id,
                reason="filament_unmappable",
            )
        except Exception:
            pass

    async def _compute_ams_mapping_for_printer(
        self, db: AsyncSession, printer_id: int, item: PrintQueueItem
    ) -> list[int] | None:
        """Compute AMS mapping for a printer based on filament requirements.

        Called when a queue item has no ams_mapping set — either for model-based
        items after printer assignment, or printer-specific items (e.g. from VP).

        Args:
            db: Database session
            printer_id: The assigned printer ID
            item: The queue item (contains archive_id or library_file_id)

        Returns:
            AMS mapping array or None if no mapping needed/possible
        """
        # Get printer status
        status = printer_manager.get_status(printer_id)
        if not status:
            logger.warning("Cannot compute AMS mapping: printer %s status unavailable", printer_id)
            return None

        # Filament Track Switch (FTS): when installed it routes any AMS slot to
        # either extruder, so the per-nozzle hard filter below must NOT apply.
        # Otherwise a print on one nozzle can't use a spool physically loaded in
        # an AMS on the *other* nozzle, and the matcher falls through to a
        # same-type wrong-colour spool on the target nozzle — the H2C + FTS
        # wrong-filament bug (#2186). Mirrors the frontend skip added for #1162.
        fts_installed = bool(getattr(getattr(status, "fila_switch", None), "installed", False))

        # Get filament requirements from source file
        filament_reqs = await self._get_filament_requirements(db, item)
        if not filament_reqs:
            # When the 3MF can't be read but force-color overrides are present, build a
            # direct mapping from the overrides so the printer uses the correct AMS slot.
            if item.filament_overrides:
                try:
                    overrides = json.loads(item.filament_overrides)
                    force_overrides = [o for o in overrides if o.get("force_color_match")]
                    if force_overrides:
                        logger.info(
                            "Queue item %s: No filament reqs from 3MF; building AMS mapping from %d "
                            "force-color override(s)",
                            item.id,
                            len(force_overrides),
                        )
                        return self._build_override_direct_mapping(force_overrides, status)
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning("Queue item %s: Force-color fallback mapping failed: %s", item.id, e)
            logger.debug("No filament requirements found for queue item %s", item.id)
            return None

        self._apply_filament_overrides(item, filament_reqs)

        # Build loaded filaments from printer status
        loaded_filaments = self._build_loaded_filaments(status)
        if not loaded_filaments:
            logger.debug("No filaments loaded on printer %s", printer_id)
            return None

        # Check if user prefers lowest remaining filament when multiple spools match
        prefer_lowest = await self._get_bool_setting(db, "prefer_lowest_filament")

        # Gate prefer_lowest on the printer's AMS Filament Backup state (#1766).
        # Without backup, the printer will not switch to a second spool when the
        # picked one runs out — so sorting toward the lowest leaves the print
        # at risk of running dry mid-job. None (unknown / A1 family) preserves
        # today's behaviour intentionally.
        if prefer_lowest and status.ams_filament_backup is False:
            logger.info("[prefer-lowest] skipped (AMS Backup OFF on printer %s)", printer_id)
            prefer_lowest = False

        # When the preference is on, surface PrintLab's inventory-side
        # remaining for each slot that's bound to a tracked spool, so the
        # sort beats the MQTT-only blind spot (#1508). Skip the lookup
        # entirely when the preference is off — no behaviour change for
        # users who haven't opted in.
        inventory_remain_overrides: dict[int, float] | None = None
        if prefer_lowest:
            inventory_remain_overrides = await self._build_inventory_remain_overrides(db, printer_id, loaded_filaments)

        # Compute mapping: match required filaments to available slots
        return self._match_filaments_to_slots(
            filament_reqs, loaded_filaments, prefer_lowest, inventory_remain_overrides, fts_installed
        )

    def _apply_filament_overrides(self, item: PrintQueueItem, filament_reqs: list[dict]) -> None:
        """Rewrite ``filament_reqs`` in place with the item's per-slot overrides.

        Extracted from ``_compute_ams_mapping_for_printer`` so the unmappable
        diagnosis (#2771) describes the filament the matcher actually looked
        for, not the one the 3MF was sliced with — naming the pre-override
        filament in a user-facing error would send the user to load the wrong
        spool.
        """
        if not item.filament_overrides:
            return
        try:
            overrides = json.loads(item.filament_overrides)
            override_map = {o["slot_id"]: o for o in overrides}
            for req in filament_reqs:
                if req["slot_id"] in override_map:
                    override = override_map[req["slot_id"]]
                    req["type"] = override["type"]
                    req["color"] = override["color"]
                    # A manual/preference override SWAPS the slot's filament, so the
                    # 3MF's original tray_info_idx now points at the old spool and must
                    # be cleared — matching then falls back to type+colour. A
                    # force_color_match override is not a swap: it carries the 3MF's
                    # intended variant (Basic GFA00 / Matte GFA01 / Silk GFA06), so keep
                    # it here too, letting the matcher pin the correct variant slot on a
                    # printer holding two same-colour spools of different variants (#2650).
                    # If that variant isn't loaded the matcher falls back to type+colour,
                    # so an eligible printer never fails to map.
                    req["tray_info_idx"] = (
                        override.get("tray_info_idx", "") if override.get("force_color_match") else ""
                    )
                    logger.debug(
                        "Queue item %s: Override slot %d -> %s %s",
                        item.id,
                        req["slot_id"],
                        override["type"],
                        override["color"],
                    )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to apply filament overrides for queue item %s: %s", item.id, e)

    def _build_override_direct_mapping(self, force_overrides: list[dict], status) -> list[int] | None:
        """Build an AMS mapping directly from force-color overrides without a 3MF.

        Used when ``_get_filament_requirements`` returns nothing (e.g. the 3MF's
        slice_info is missing or unreadable) but ``force_color_match`` overrides
        are present. Each override's ``slot_id``, ``type``, and ``color`` are
        treated as the filament requirement for that slot and matched against the
        current AMS state of the printer.

        Returns the same format as ``_match_filaments_to_slots``, or None when
        the AMS has no loaded filaments.
        """
        loaded = self._build_loaded_filaments(status)
        if not loaded:
            return None

        reqs = [
            {
                "slot_id": o["slot_id"],
                "type": o.get("type", ""),
                "color": o.get("color", ""),
                # These are all force_color_match overrides, so the idx (when the
                # 3MF carried one) is the intended variant, not a stale swap —
                # keep it so the matcher pins the right variant slot, falling back
                # to type+colour when it isn't loaded (#2650).
                "tray_info_idx": o.get("tray_info_idx", ""),
            }
            for o in force_overrides
        ]
        return self._match_filaments_to_slots(reqs, loaded)

    async def _get_filament_requirements(self, db: AsyncSession, item: PrintQueueItem) -> list[dict] | None:
        """Resolve the queue item's source 3MF and parse the per-slot
        filament requirements out of it. Thin DB-resolver wrapper around
        ``filament_requirements.extract_filament_requirements`` so the VP
        queue-mode write path (#1188) can reuse the same parser at upload
        time.
        """
        from backend.app.services.filament_requirements import extract_filament_requirements

        file_path: Path | None = None
        if item.archive_id:
            result = await db.execute(select(PrintArchive).where(PrintArchive.id == item.archive_id))
            archive = result.scalar_one_or_none()
            if archive:
                file_path = settings.base_dir / archive.file_path
        elif item.library_file_id:
            result = await db.execute(LibraryFile.active().where(LibraryFile.id == item.library_file_id))
            library_file = result.scalar_one_or_none()
            if library_file:
                lib_path = Path(library_file.file_path)
                file_path = lib_path if lib_path.is_absolute() else settings.base_dir / library_file.file_path

        if not file_path or not file_path.exists():
            return None

        filaments = extract_filament_requirements(file_path, plate_id=item.plate_id)
        return filaments if filaments else None

    def _build_loaded_filaments(self, status) -> list[dict]:
        """Build list of loaded filaments from printer status.

        Args:
            status: PrinterState from printer_manager

        Returns:
            List of loaded filament dicts with type, color, ams_id, tray_id, global_tray_id
        """
        filaments = []

        # Get ams_extruder_map for dual-nozzle printers (H2D, H2D Pro)
        ams_extruder_map = status.raw_data.get("ams_extruder_map", {})

        # Dual-nozzle detection, used below to route external spools to an
        # extruder (#2771). Mirrors `buildLoadedFilaments` in the frontend,
        # which was corrected for #1257 while this copy kept the old signal.
        #
        # `ams_extruder_map` is derived from AMS info bits, so a dual-nozzle
        # printer with zero AMS units reports an empty map — and every external
        # spool then got `extruder_id=None`, which the nozzle-aware filter in
        # `_match_filaments_to_slots` rejects outright because `None` equals
        # neither 0 nor 1. On an X2D feeding from external spools only that left
        # nothing to match, the mapping came back all -1, and the print went out
        # with `use_ams: true` and no mapping table at all — firmware 0700_8012,
        # "Failed to get AMS mapping table".
        #
        # `nozzles` is always a two-entry list (the state seeds it with two empty
        # NozzleInfo stubs), so its length proves nothing; only a populated
        # diameter on the second entry means real hardware. The other two signals
        # are fallbacks for firmware revisions that surface one but not the
        # other: a populated `ams_extruder_map` is dual-nozzle by construction,
        # and so is more than one `vt_tray` entry, since single-nozzle printers
        # expose exactly one external feed.
        nozzles = getattr(status, "nozzles", None) or []
        vt_trays = status.raw_data.get("vt_tray") or []
        is_dual_nozzle = bool(
            (len(nozzles) > 1 and getattr(nozzles[1], "nozzle_diameter", ""))
            or ams_extruder_map
            # isinstance, because a dict here would count its ~30 keys as trays.
            # bambu_mqtt normalises vt_tray to a list before it reaches raw_data,
            # so this is unreachable — but the loop below would raise on a dict
            # and that is the pre-existing behaviour to keep, not to paper over.
            or (isinstance(vt_trays, list) and len(vt_trays) > 1)
        )

        # Parse AMS units from raw_data
        ams_data = status.raw_data.get("ams", [])
        for ams_unit in ams_data:
            ams_id = int(ams_unit.get("id", 0))
            trays = ams_unit.get("tray", [])
            is_ht = len(trays) == 1  # AMS-HT has single tray

            for tray in trays:
                tray_type = tray.get("tray_type")
                if tray_type:
                    tray_id = int(tray.get("id", 0))
                    tray_color = tray.get("tray_color", "")
                    # tray_info_idx identifies the specific spool (e.g., "GFA00", "P4d64437")
                    tray_info_idx = tray.get("tray_info_idx", "")
                    # Normalize color: remove alpha, add hash
                    color = self._normalize_color(tray_color)
                    # Calculate global tray ID
                    # AMS-HT units have IDs starting at 128 with a single tray
                    global_tray_id = ams_id if ams_id >= 128 else ams_id * 4 + tray_id

                    filaments.append(
                        {
                            "type": tray_type,
                            "color": color,
                            "tray_info_idx": tray_info_idx,
                            "ams_id": ams_id,
                            "tray_id": tray_id,
                            "is_ht": is_ht,
                            "is_external": False,
                            "global_tray_id": global_tray_id,
                            "extruder_id": ams_extruder_map.get(str(ams_id)),
                            "remain": tray.get("remain", -1),
                        }
                    )

        # Check external spool(s) (vt_tray is a list)
        for idx, vt in enumerate(vt_trays):
            if vt.get("tray_type"):
                color = self._normalize_color(vt.get("tray_color", ""))
                tray_id = int(vt.get("id", 254))
                filaments.append(
                    {
                        "type": vt["tray_type"],
                        "color": color,
                        "tray_info_idx": vt.get("tray_info_idx", ""),
                        "ams_id": -1,
                        "tray_id": idx,
                        "is_ht": False,
                        "is_external": True,
                        "global_tray_id": tray_id,
                        # 254 = VIRTUAL_TRAY_DEPUTY_ID feeds extruder 1 (left),
                        # 255 = VIRTUAL_TRAY_MAIN_ID feeds extruder 0 (right).
                        "extruder_id": (255 - tray_id) if is_dual_nozzle else None,
                        "remain": vt.get("remain", -1),
                    }
                )

        return filaments

    def _normalize_color(self, color: str | None) -> str:
        """Normalize color to #RRGGBB format."""
        if not color:
            return "#808080"
        hex_color = color.replace("#", "")[:6]
        return f"#{hex_color}"

    def _normalize_color_for_compare(self, color: str | None) -> str:
        """Normalize color for comparison (lowercase, no hash)."""
        if not color:
            return ""
        return color.replace("#", "").lower()[:6]

    def _color_distance(self, color1: str | None, color2: str | None) -> float | None:
        """Perceptual (CIEDE2000) distance, or None when either colour is unusable.

        Ranks the candidates ``_colors_are_similar`` admits (#2804). Eligibility
        stays the per-channel box that shipped — this only decides which of
        several eligible spools is closest, so nothing becomes usable or
        unusable because of it.

        It ranks by how far apart the colours *look*, not how far apart their
        numbers are. RGB distance overweights blue badly enough to invert the
        answer: against a required ``#1E4821`` green, a purple ``#38202F`` is
        the nearer of two eligible spools by RGB and the further by a factor of
        four once measured perceptually.

        Alpha is ignored, deliberately: the alpha a slicer writes for a
        transparent filament is not a colour the user chose, and counting it
        would stop a transparent filament matching itself.
        """
        return perceptual_color_distance(color1, color2)

    def _colors_are_similar(self, color1: str | None, color2: str | None, threshold: int = 40) -> bool:
        """Check if two colors are visually similar within a threshold."""
        hex1 = self._normalize_color_for_compare(color1)
        hex2 = self._normalize_color_for_compare(color2)
        if not hex1 or not hex2 or len(hex1) < 6 or len(hex2) < 6:
            return False

        try:
            r1 = int(hex1[0:2], 16)
            g1 = int(hex1[2:4], 16)
            b1 = int(hex1[4:6], 16)
            r2 = int(hex2[0:2], 16)
            g2 = int(hex2[2:4], 16)
            b2 = int(hex2[4:6], 16)
            return abs(r1 - r2) <= threshold and abs(g1 - g2) <= threshold and abs(b1 - b2) <= threshold
        except ValueError:
            return False

    async def _build_inventory_remain_overrides(
        self, db: AsyncSession, printer_id: int, loaded: list[dict]
    ) -> dict[int, float]:
        """Return ``{global_tray_id: remaining_grams}`` for AMS slots the user
        has bound to an inventory spool — PrintLab-side or Spoolman-side.

        The MQTT ``remain`` field on a tray is the printer firmware's
        RFID-decremented value, which has two limitations the "Prefer Lowest
        Remaining Filament" feature has been ignoring (#1508):

        - it's only meaningful for Bambu RFID spools; everything else reports
          ``-1`` (then clamped to a sentinel), so multiple non-RFID trays
          compare equal and the sort collapses to AMS-slot order — the user
          who's curating inventory weights gets the lower-slot pick instead
          of the lower-remaining pick;
        - even when set, it's the *printer's* counter, not PrintLab's
          ``label_weight - weight_used`` (internal mode) or Spoolman's
          ``remaining_weight`` (Spoolman mode) — the two diverge any time the
          user re-spools, swaps cardboard, or runs a print outside PrintLab.

        When the user has bound a spool to a slot, their own inventory
        tracking is authoritative; this helper surfaces that value so the
        sort can prefer it. Slots without a binding are absent from the
        returned map — the caller then falls back to MQTT ``remain`` for
        those, preserving the pre-#1508 behaviour for un-tracked spools.

        Returns an empty map on any failure (no inventory bindings, DB
        error, Spoolman unreachable). A best-effort lookup; "Prefer Lowest"
        is a preference, not a guarantee.
        """
        if not loaded:
            return {}
        # External / virtual-tray slots are tracked separately from AMS — skip
        # them so a VT-loaded spool doesn't accidentally inherit a tracked
        # AMS binding (the tables use ams_id 254/255 for VT, but the cross
        # match is fiddly and out of scope for this fix).
        tracked_slots = [(f["ams_id"], f["tray_id"], f["global_tray_id"]) for f in loaded if not f.get("is_external")]
        if not tracked_slots:
            return {}

        is_spoolman = await self._is_spoolman_mode(db)
        overrides: dict[int, float] = {}

        if is_spoolman:
            result = await db.execute(
                select(SpoolmanSlotAssignment).where(SpoolmanSlotAssignment.printer_id == printer_id)
            )
            assignments = list(result.scalars().all())
            by_slot = {(a.ams_id, a.tray_id): a.spoolman_spool_id for a in assignments}
            from backend.app.services.filament_deficit import _spoolman_remaining_grams

            for ams_id, tray_id, gtid in tracked_slots:
                spoolman_id = by_slot.get((ams_id, tray_id))
                if spoolman_id is None:
                    continue
                grams = await _spoolman_remaining_grams(spoolman_id)
                if grams is not None:
                    overrides[gtid] = grams
            return overrides

        # Internal inventory mode (default). selectinload matches the pattern
        # used elsewhere (inventory.py, spoolman.py routes) — a single query
        # plus an eager-loaded relationship rather than an explicit join, so
        # the row-attribute shape is exactly what those routes already rely on.
        result = await db.execute(
            select(SpoolAssignment)
            .options(selectinload(SpoolAssignment.spool))
            .where(SpoolAssignment.printer_id == printer_id)
        )
        assignments = list(result.scalars().all())
        by_slot = {(a.ams_id, a.tray_id): a.spool for a in assignments}
        for ams_id, tray_id, gtid in tracked_slots:
            spool = by_slot.get((ams_id, tray_id))
            if spool is None:
                continue
            label = float(spool.label_weight or 0)
            used = float(spool.weight_used or 0)
            overrides[gtid] = max(0.0, label - used)
        return overrides

    @staticmethod
    async def _is_spoolman_mode(db: AsyncSession) -> bool:
        """Mirror of ``filament_deficit._is_spoolman_mode`` — kept private
        here to avoid making this module import-dependent on that private
        helper's signature."""
        try:
            from backend.app.api.routes.settings import get_setting

            v = await get_setting(db, "spoolman_enabled")
            return bool(v) and v.lower() == "true"
        except Exception:
            return False

    @staticmethod
    def _slot_priority(ams_id: int | None, tray_id: int | None) -> int:
        """Deterministic slot-position tie-breaker for the prefer-lowest sort.

        Three bands, matched to the emission order in ``_build_loaded_filaments``
        so a tied sort produces the same physical-position order the pre-#1508
        stable sort did (preserves the regression-free baseline):

        - Regular AMS (``ams_id`` 0..7): ``ams_id * 4 + tray_id`` → 0..31
        - AMS-HT (``ams_id`` >= 128, single tray): ``1000 + (ams_id - 128) * 4``
        - External / VT (``ams_id`` < 0, or ``None``): ``10_000``

        Banding ensures regular AMS < AMS-HT < external on ties, regardless of
        what the raw ``ams_id`` happens to be (in particular, ``ams_id = -1``
        for VT must NOT sort to a negative number or it would beat AMS slot 0).
        """
        if ams_id is None or ams_id < 0:
            return 10_000
        if ams_id >= 128:
            return 1_000 + (ams_id - 128) * 4 + (tray_id or 0)
        return ams_id * 4 + (tray_id or 0)

    @staticmethod
    def _prefer_lowest_sort_key(f: dict, overrides: dict[int, float] | None) -> tuple[int, float, int]:
        """Sort key for the "Prefer Lowest Remaining Filament" preference.

        Two-tier ordering: inventory-tracked spools always sort BEFORE
        non-tracked spools (the user has told us they care about these
        specifically), then ascending by remaining within each tier, then
        ascending by AMS slot position as the deterministic tie-breaker.

        Tiers are flagged by the first tuple element (0 = inventory-tracked,
        1 = MQTT-only / unknown). Cross-tier value comparisons never run
        because the tier flag dominates — which is what lets us mix grams
        (inventory) and percent (MQTT) without a unit conversion.

        Within the MQTT tier ``remain = -1`` (unknown) is mapped to 101 so
        spools the printer DOES know something about sort ahead of those
        it knows nothing about — preserves pre-#1508 behaviour for the
        no-inventory-binding case.

        Slot tie-breaker via ``_slot_priority`` so regular AMS < AMS-HT <
        external on ties, matching the legacy emission-order stable sort.
        """
        gtid = f.get("global_tray_id")
        slot_order = PrintScheduler._slot_priority(f.get("ams_id"), f.get("tray_id"))
        if overrides and gtid in overrides:
            return (0, overrides[gtid], slot_order)
        remain = f.get("remain", -1)
        return (1, float(remain) if remain is not None and remain >= 0 else 101.0, slot_order)

    def _match_filaments_to_slots(
        self,
        required: list[dict],
        loaded: list[dict],
        prefer_lowest: bool = False,
        inventory_remain_overrides: dict[int, float] | None = None,
        fts_installed: bool = False,
    ) -> list[int] | None:
        """Match required filaments to loaded filaments and build AMS mapping.

        Priority: unique tray_info_idx match > exact color match > similar color match > type-only match

        The tray_info_idx is a filament type identifier stored in the 3MF file when the user
        slices (e.g., "GFA00" for generic PLA, "P4d64437" for custom presets). If the same
        tray_info_idx appears in only ONE available tray, we use that tray. If multiple trays
        have the same tray_info_idx (e.g., two spools of generic PLA), we fall back to color
        matching among those trays.

        Args:
            required: List of required filaments with slot_id, type, color, tray_info_idx
            loaded: List of loaded filaments with type, color, tray_info_idx, global_tray_id

        Returns:
            AMS mapping array (position = slot_id - 1, value = global_tray_id or -1)
        """
        if not required:
            return None

        # Track used trays to avoid duplicate assignment
        used_tray_ids: set[int] = set()
        comparisons = []

        for req in required:
            req_type = (req.get("type") or "").upper()
            req_color = req.get("color", "")
            req_tray_info_idx = req.get("tray_info_idx", "")

            # Find best match: unique tray_info_idx > exact color > similar color > type-only
            idx_match = None
            exact_match = None
            similar_match = None
            similar_distance = float("inf")
            type_only_match = None

            # Get available trays (not already used)
            available = [f for f in loaded if f["global_tray_id"] not in used_tray_ids]

            # Nozzle-aware filtering: restrict to trays on the correct nozzle.
            # Hard filter — cross-nozzle assignment causes print failures
            # ("position of left hotend is abnormal"), so never fall back.
            # Skipped when an FTS is installed: it routes any AMS slot to either
            # extruder, so restricting to one nozzle would wrongly exclude the
            # correct spool sitting in the other nozzle's AMS (#2186).
            req_nozzle_id = req.get("nozzle_id")
            if req_nozzle_id is not None and not fts_installed:
                available = [f for f in available if f.get("extruder_id") == req_nozzle_id]

            # Sort by remaining filament (ascending) so lowest-remain spool wins .find().
            # Inventory-tracked spools sort before MQTT-only ones (#1508); see
            # _prefer_lowest_sort_key for the full rationale.
            if prefer_lowest:
                available.sort(key=lambda f: self._prefer_lowest_sort_key(f, inventory_remain_overrides))
                # INFO-level decision trace for "Prefer Lowest Filament" #1766.
                # One line per filament req so a bug report can be diagnosed
                # without enabling debug logging: shows what the matcher saw
                # (req shape + sorted candidate trays with their remain values
                # and any inventory override that was applied). Mirrored by
                # the picked-match log at the bottom of the loop.
                logger.info(
                    "[prefer-lowest] req slot=%s type=%r color=%r tii=%r nozzle=%s; available (sorted lowest-first): %s",
                    req.get("slot_id"),
                    req_type,
                    req_color,
                    req_tray_info_idx,
                    req_nozzle_id,
                    [
                        {
                            "gtid": f.get("global_tray_id"),
                            "type": f.get("type"),
                            "color": f.get("color"),
                            "tii": f.get("tray_info_idx"),
                            "remain": f.get("remain"),
                            "inv_g": (
                                inventory_remain_overrides.get(f.get("global_tray_id"))
                                if inventory_remain_overrides
                                else None
                            ),
                        }
                        for f in available
                    ],
                )

            # Check if tray_info_idx is unique among available trays
            if req_tray_info_idx:
                idx_matches = [f for f in available if f.get("tray_info_idx") == req_tray_info_idx]
                if len(idx_matches) == 1:
                    # Unique tray_info_idx - use it as definitive match
                    idx_match = idx_matches[0]
                    logger.debug(
                        f"Matched filament slot {req.get('slot_id')} by unique tray_info_idx={req_tray_info_idx} "
                        f"-> tray {idx_match['global_tray_id']}"
                    )
                elif len(idx_matches) > 1:
                    # Multiple trays with same tray_info_idx - use color matching among them
                    logger.debug(
                        f"Non-unique tray_info_idx={req_tray_info_idx} found in {len(idx_matches)} trays, "
                        f"using color matching among trays: {[f['global_tray_id'] for f in idx_matches]}"
                    )
                    if prefer_lowest:
                        idx_matches.sort(key=lambda f: self._prefer_lowest_sort_key(f, inventory_remain_overrides))
                    # Use color matching within this subset
                    for f in idx_matches:
                        f_color = f.get("color", "")
                        if self._normalize_color_for_compare(f_color) == self._normalize_color_for_compare(req_color):
                            if not exact_match:
                                exact_match = f
                        elif self._colors_are_similar(f_color, req_color):
                            distance = self._color_distance(f_color, req_color)
                            if distance is not None and distance < similar_distance:
                                similar_match = f
                                similar_distance = distance
                        elif not type_only_match:
                            type_only_match = f

            # If no idx_match yet, do standard type/color matching on all available trays
            if not idx_match and not exact_match and not similar_match and not type_only_match:
                for f in available:
                    f_type = (f.get("type") or "").upper()
                    if canonical_filament_type(f_type) != canonical_filament_type(req_type):
                        continue

                    # Type matches - check color
                    f_color = f.get("color", "")
                    if self._normalize_color_for_compare(f_color) == self._normalize_color_for_compare(req_color):
                        if not exact_match:
                            exact_match = f
                    elif self._colors_are_similar(f_color, req_color):
                        # Nearest wins, not first-in-tray-order. `available` is
                        # already in the caller's order (slot order, or the
                        # prefer-lowest sort), and `<` keeps the earliest of
                        # equally close spools — so that order survives as the
                        # tie-break (#2804).
                        distance = self._color_distance(f_color, req_color)
                        if distance is not None and distance < similar_distance:
                            similar_match = f
                            similar_distance = distance
                    elif not type_only_match:
                        type_only_match = f

            match = idx_match or exact_match or similar_match or type_only_match
            if match:
                used_tray_ids.add(match["global_tray_id"])
                comparisons.append({"slot_id": req.get("slot_id", 0), "global_tray_id": match["global_tray_id"]})
            else:
                comparisons.append({"slot_id": req.get("slot_id", 0), "global_tray_id": -1})
            # Which bucket won, always — not only under Prefer Lowest (#2804).
            # "Why did it pick that spool" is the question every wrong-filament
            # report starts with, and a `similar_color` win is now a ranked
            # choice among several eligible spools rather than whichever tray
            # came first, so it is worth being able to see after the fact.
            # Pairs with the "available (sorted)" log above when Prefer Lowest
            # is on (#1766).
            if match:
                bucket = (
                    "idx"
                    if idx_match is not None
                    else "exact_color"
                    if exact_match is not None
                    else "similar_color"
                    if similar_match is not None
                    else "type_only"
                )
                logger.info(
                    "[ams-match] picked gtid=%s via %s for req slot=%s%s",
                    match["global_tray_id"],
                    bucket,
                    req.get("slot_id"),
                    f" (deltaE {similar_distance:.2f})" if bucket == "similar_color" else "",
                )
            else:
                logger.info(
                    "[ams-match] NO MATCH for req slot=%s (type=%r color=%r tii=%r)",
                    req.get("slot_id"),
                    req_type,
                    req_color,
                    req_tray_info_idx,
                )

        # Build mapping array
        if not comparisons:
            return None

        max_slot_id = max(c["slot_id"] for c in comparisons)
        if max_slot_id <= 0:
            return None

        mapping = [-1] * max_slot_id
        for c in comparisons:
            slot_id = c["slot_id"]
            if slot_id and slot_id > 0:
                mapping[slot_id - 1] = c["global_tray_id"]

        return mapping

    def _mark_printer_dispatched(
        self,
        printer_id: int,
        pre_state: str | None,
        pre_subtask_id: str | None,
    ) -> None:
        """Record that a print command was just sent to ``printer_id``.

        Held until either the watchdog observes a state/subtask transition
        (success path) or the hard timeout expires. See ``_dispatch_holds``.
        """
        if not pre_state:
            # No pre_state means we can't detect a transition — fall back to a
            # pure time-based hold using empty string as a sentinel that won't
            # match any real printer state.
            pre_state = ""
        self._dispatch_holds[printer_id] = (time.monotonic(), pre_state, pre_subtask_id)

    def _release_dispatch_hold(self, printer_id: int) -> None:
        """Drop the dispatch hold for ``printer_id`` (called by the watchdog)."""
        self._dispatch_holds.pop(printer_id, None)

    def _printer_in_dispatch_hold(self, printer_id: int) -> bool:
        """True if ``printer_id`` is still inside its post-dispatch hold window.

        Returns False (and clears the hold) once any of these are true:
          - hard timeout (``_dispatch_max_hold``) has elapsed
          - the printer has transitioned out of pre_state and we're past the
            minimum cooldown
          - the printer's subtask_id has advanced past pre_subtask_id and we're
            past the minimum cooldown
        Otherwise the printer is held — caller should treat it as busy.
        """
        entry = self._dispatch_holds.get(printer_id)
        if not entry:
            return False
        started_at, pre_state, pre_subtask_id = entry
        elapsed = time.monotonic() - started_at

        if elapsed >= self._dispatch_max_hold:
            self._dispatch_holds.pop(printer_id, None)
            return False

        # Without a pre_state we can't detect a transition — fall back to the
        # min cooldown alone, then drop the hold.
        if not pre_state:
            if elapsed >= self._dispatch_min_cooldown:
                self._dispatch_holds.pop(printer_id, None)
                return False
            return True

        status = printer_manager.get_status(printer_id)
        current_state = getattr(status, "state", None) if status else None
        current_subtask_id = getattr(status, "subtask_id", None) if status else None
        transitioned = (current_state is not None and current_state != pre_state) or (
            pre_subtask_id is not None and current_subtask_id is not None and current_subtask_id != pre_subtask_id
        )

        if transitioned and elapsed >= self._dispatch_min_cooldown:
            self._dispatch_holds.pop(printer_id, None)
            return False

        return True

    def _is_printer_idle(self, printer_id: int, require_plate_clear: bool = True) -> bool:
        """Check if a printer is connected and idle."""
        if not printer_manager.is_connected(printer_id):
            logger.debug("Printer %d: not connected", printer_id)
            return False

        state = printer_manager.get_status(printer_id)
        if not state:
            logger.debug("Printer %d: no status available", printer_id)
            return False

        # Plate-clear gate: if the printer finished/failed a previous print and the user
        # hasn't acknowledged the plate was cleared, the queue must not dispatch the next
        # job — even if the printer currently reports IDLE. After Auto Off cycles the
        # printer, it boots back into IDLE with no memory of the previous finish; without
        # the persisted awaiting flag we'd bypass the confirmation prompt (#961).
        if require_plate_clear and printer_manager.is_awaiting_plate_clear(printer_id):
            logger.debug(
                "Printer %d: not idle — awaiting plate-clear acknowledgment (state=%s)",
                printer_id,
                state.state,
            )
            return False

        idle = state.state in ("IDLE", "FINISH", "FAILED")
        if not idle:
            logger.debug("Printer %d: not idle — state=%s", printer_id, state.state)
        return idle

    @staticmethod
    def _pinned_hold_reason(printer_id: int, printer_name: str, require_plate_clear: bool) -> str:
        """Why a connected, non-idle printer cannot take this job, for the queue row (#3074).

        Only ever asked about a printer :meth:`_is_printer_idle` has just refused
        and that the fixed-printer branch has already found connected, so the two
        offline cases answer at their own exits and never arrive here.

        The default is the model-based branch's ``Busy:`` wording, which
        :meth:`_is_busy_only` reads as "resolves itself, stay quiet". That is also
        the right answer for the connected-but-no-telemetry second or two after a
        reconnect: the model-based branch has always reported it that way, and it
        is not something to wake anybody up for.

        A plate nobody has confirmed is the one case here that does not resolve
        itself — somebody has to walk over to the printer — so it is worded as
        itself and allowed to notify.
        """
        if require_plate_clear and printer_manager.is_awaiting_plate_clear(printer_id):
            return f"Waiting for plate confirmation: {printer_name}"
        return f"Busy: {printer_name}"

    async def _get_setting(self, db: AsyncSession, key: str) -> str | None:
        """Read a setting value from the database."""
        result = await db.execute(select(Settings).where(Settings.key == key))
        setting = result.scalar_one_or_none()
        return setting.value if setting else None

    async def _get_bool_setting(self, db: AsyncSession, key: str, default: bool = False) -> bool:
        """Read a boolean setting from the database."""
        result = await db.execute(select(Settings).where(Settings.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            return setting.value.lower() == "true"
        return default

    async def _get_int_setting(self, db: AsyncSession, key: str, default: int) -> int:
        """Read an int setting; falls back to default on missing/unparseable rows."""
        result = await db.execute(select(Settings).where(Settings.key == key))
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            try:
                return int(setting.value)
            except ValueError:
                pass
        return default

    # Materials whose AMS spelling differs from the key the tables above use.
    # Bambu labels nylon "PA" while its own composites spell the family out, so
    # PA6, PA11, PA12 and PAHT would otherwise miss a table with a perfectly
    # good PA row (#3067).
    #
    # Mirrors DRYING_MATERIAL_ALIASES in frontend/src/utils/dryingPresets.ts.
    # The drying popover has resolved these correctly since #2774 and the
    # scheduler never did, which is exactly why #3067's reporter could dry a
    # PA6-CF spool by hand while auto-drying skipped it every pass.
    #
    # PPA is here too. Polyphthalamide is a distinct polymer rather than a grade
    # of nylon, so it is the one entry that is a judgement rather than a
    # spelling -- but it is an aromatic polyamide, it absorbs moisture the same
    # way, and PA's row is the hottest the table has. Drying it there is closer
    # to right than not drying it at all, which is what it got before.
    FILAMENT_KEY_ALIASES: dict[str, str] = {
        "NYLON": "PA",
        "PA6": "PA",
        "PA11": "PA",
        "PA12": "PA",
        "PAHT": "PA",
        "PPA": "PA",
    }

    @classmethod
    def _resolve_filament_key(cls, tray_type: str | None, table: Mapping[str, object]) -> str | None:
        """The key in *table* that answers for this tray's material, or None.

        The printer reports the material in ``tray_type``, and it spells filled
        and foamed variants out: PLA-CF, PETG-CF, ABS-GF, PLA-AERO, PA6-CF. The
        tables here are keyed by base material, so matching the raw string alone
        found a row for 8 of the 41 types a printer can report and skipped the
        rest -- silently, because every caller reads "no row" as "nothing to do
        for this tray". Auto-drying therefore ignored every composite spool on
        the install (#3067).

        Exact match first, so a table the user has extended with a row of its
        own -- ``PA6-CF`` at a temperature they picked -- still wins over the
        base material's. Then the suffix is dropped, then the alias map above
        answers for the polyamide spellings.

        Returns None rather than a default: what to do with an unrecognised
        material differs per caller, and only the caller knows whether "no row"
        means skip the tray or fall back to a catch-all. Nothing here invents a
        temperature for a material the table does not list.
        """
        raw = cls._normalize_filament_type(tray_type or "")
        if not raw:
            return None
        for candidate in (raw, raw.split("-")[0]):
            key = cls.FILAMENT_KEY_ALIASES.get(candidate, candidate)
            if key in table:
                return key
        return None

    async def _check_filament_low(self, db: AsyncSession) -> None:
        """Alert on AMS slots whose assigned spool has crossed its low-stock threshold (#2913).

        ``on_filament_low`` has had a column, a schema field, a route, a template
        and a UI toggle since the notification system was built, and no caller --
        so the toggle could be switched on and could never fire. This is the
        producer.

        No new setting. ``low_stock_threshold`` (default 20%) with the per-spool
        ``low_stock_threshold_pct`` override is already exactly this decision:
        already configurable, already surfaced, already driving the Inventory
        page's Low Stock count. The AMS ``remain`` percentage is deliberately not
        consulted -- it has been measured up to 56 points out against a scale,
        which is not a number to page someone on.

        Only slots with an assigned spool produce an event. A slot PrintLab
        cannot resolve to a spool has no remaining weight it can stand behind,
        and guessing one is how the remain percentage would have got in.
        """
        from backend.app.models.spool import Spool

        # Time-gated rather than run on every pass. run() sleeps
        # _fast_check_interval -- 3 seconds -- on any productive pass, and the
        # early-return path counts as productive while an upload is in flight
        # (#2602), so an unthrottled check would re-read the whole spool
        # collection every 3 seconds for the length of a batch drain. In
        # Spoolman mode that is a request storm against a third-party service,
        # which is the thing this producer's design note argues against; and
        # when Spoolman is down, _get_with_retry burns ~16 s inside
        # check_queue holding the scheduler's session, so the outage would
        # throttle the print queue itself. A low spool is not a 3-second
        # concern -- the idle interval is the natural resolution.
        now = time.monotonic()
        if now < self._filament_low_next_check:
            return
        self._filament_low_next_check = now + _FILAMENT_LOW_MIN_INTERVAL

        try:
            # on_filament_low defaults to off on every provider, so on most
            # installs nobody wants this alert. Without this the check would
            # still read every assigned spool each interval -- the whole
            # collection over HTTP in Spoolman mode -- for an event that is
            # switched off. One query against the provider table settles it
            # before any spool work, the same guard the bed-cooled waiter uses.
            # No printer_id: this asks whether any provider wants the event at
            # all; per-printer scoping is applied when the event is sent.
            #
            # While nobody wants it, no pass sees a slot go back above its
            # threshold, so nothing can re-arm; a spool refilled under the same
            # id in that time would stay silenced until a restart. Forgetting
            # what was sent is right anyway: whoever switches the event back on
            # is told about the spools that are low now.
            if not await notification_service._get_providers_for_event(db, "on_filament_low"):
                self._notified_filament_low.clear()
                return

            global_threshold = await self._get_low_stock_threshold(db)
            spoolman_on = await self._get_bool_setting(db, "spoolman_enabled")

            # (printer_id, ams_id, tray_id, spool_id) -> (remaining_pct, threshold, colour name)
            slots: dict[tuple[int, int, int, int], tuple[float, float, str | None]] = {}

            if spoolman_on:
                slots = await self._filament_low_slots_spoolman(db, global_threshold)
            else:
                rows = (
                    await db.execute(
                        select(SpoolAssignment, Spool)
                        .join(Spool, SpoolAssignment.spool_id == Spool.id)
                        # An archived spool is not stock. The Inventory page's
                        # Low Stock count skips them (InventoryPage.tsx:1089)
                        # and get_all_spools without allow_archived already
                        # excludes them in Spoolman mode, so without this the
                        # internal path is the only one that alerts on them.
                        .where(Spool.archived_at.is_(None))
                    )
                ).all()
                for assignment, spool in rows:
                    pct = _remaining_percent(spool.label_weight, spool.weight_used)
                    if pct is None:
                        continue
                    threshold = float(spool.low_stock_threshold_pct or global_threshold)
                    slots[(assignment.printer_id, assignment.ams_id, assignment.tray_id, spool.id)] = (
                        pct,
                        threshold,
                        spool.color_name,
                    )

            if not slots:
                # Nothing resolvable this pass. Deliberately not clearing the
                # notified set: a Spoolman that is briefly unreachable would
                # otherwise re-alert on every spool as soon as it came back.
                return

            await self._emit_filament_low(db, slots)
        except Exception as e:
            logger.warning("Low-filament check failed: %s", e, exc_info=True)

    async def _get_low_stock_threshold(self, db: AsyncSession) -> float:
        """The global low-stock percentage, defaulting to the schema's 20.0."""
        raw = (await db.execute(select(Settings).where(Settings.key == "low_stock_threshold"))).scalar_one_or_none()
        if raw is None or raw.value is None:
            return 20.0
        try:
            value = float(raw.value)
        except (TypeError, ValueError):
            return 20.0
        return value if 0 < value <= 100 else 20.0

    async def _filament_low_slots_spoolman(
        self, db: AsyncSession, global_threshold: float
    ) -> dict[tuple[int, int, int, int], tuple[float, float, str | None]]:
        """Resolve Spoolman-mode slots to (remaining %, threshold, colour name).

        Spoolman spools carry no per-spool override -- ``low_stock_threshold_pct``
        is a column on PrintLab's own spool table and has no Spoolman equivalent,
        so the global threshold is the only one that applies here. That matches
        what the Inventory page already does in this mode.

        One ``get_all_spools`` call covers every slot rather than a request per
        spool. Archived spools do not appear -- ``get_all_spools`` excludes them
        without ``allow_archived`` -- which is the behaviour the internal path
        has to ask for explicitly.

        An unreachable Spoolman returns no slots rather than raising. It is an
        ordinary state for a third-party service, not an error in this pass: the
        caller's "nothing resolvable" branch already leaves the notified set
        alone, which is exactly right here, whereas letting it reach the broad
        ``except`` would write a full traceback every time the check runs.
        """
        from backend.app.api.routes._spoolman_helpers import _map_spoolman_spool
        from backend.app.services.spoolman import SpoolmanUnavailableError, get_spoolman_client

        assignments = (await db.execute(select(SpoolmanSlotAssignment))).scalars().all()
        if not assignments:
            return {}

        client = await get_spoolman_client()
        if client is None:
            return {}

        try:
            all_spools = await client.get_all_spools()
        except SpoolmanUnavailableError as e:
            logger.debug("Low-filament check skipped, Spoolman unreachable: %s", e)
            return {}

        by_id: dict[int, dict] = {}
        for raw in all_spools:
            raw_id = raw.get("id")
            if isinstance(raw_id, int):
                by_id[raw_id] = raw

        slots: dict[tuple[int, int, int, int], tuple[float, float, str | None]] = {}
        for assignment in assignments:
            raw = by_id.get(assignment.spoolman_spool_id)
            if raw is None:
                continue
            try:
                mapped = _map_spoolman_spool(raw)
            except ValueError:
                continue
            pct = _remaining_percent(mapped.get("label_weight"), mapped.get("weight_used"))
            if pct is None:
                continue
            key = (assignment.printer_id, assignment.ams_id, assignment.tray_id, assignment.spoolman_spool_id)
            slots[key] = (pct, global_threshold, mapped.get("color_name"))
        return slots

    async def _emit_filament_low(
        self, db: AsyncSession, slots: dict[tuple[int, int, int, int], tuple[float, float, str | None]]
    ) -> None:
        """Send one notification per slot that has newly crossed its threshold."""
        printer_names: dict[int, str] = {}
        for key, (pct, threshold, color) in slots.items():
            printer_id, ams_id, tray_id, _spool_id = key
            if pct >= threshold:
                # Back above the line: re-arm rather than expire on a timer, so a
                # refilled slot can alert again and a spool sitting just under the
                # threshold stays quiet.
                self._notified_filament_low.discard(key)
                continue
            if key in self._notified_filament_low:
                continue
            # Marked before sending, which is a choice rather than the only
            # option, and it is the opposite failure mode from the one the
            # debounce argues against: one transient provider failure loses this
            # alert until the spool goes back above the threshold and crosses it
            # again. Marking after a successful send would trade that for
            # re-alerting on every pass while a provider is down -- which is the
            # repetition the whole debounce exists to prevent, and the louder of
            # the two failures. A spool that is low stays low, so the next real
            # signal is not far away; a provider stuck retrying is a signal that
            # never stops.
            self._notified_filament_low.add(key)

            if printer_id not in printer_names:
                printer = (await db.execute(select(Printer).where(Printer.id == printer_id))).scalar_one_or_none()
                if printer is None:
                    continue
                printer_names[printer_id] = printer.name
            try:
                await notification_service.on_filament_low(
                    printer_id,
                    printer_names[printer_id],
                    _ams_slot_label(ams_id, tray_id),
                    int(pct),
                    db,
                    color=color,
                )
            except Exception as e:
                logger.warning("Low-filament notification failed for slot %s: %s", key, e)

    async def _check_stock_forecast(self, db: AsyncSession) -> None:
        """Alert when a filament SKU reaches its reorder point or is about to break (#2955).

        ``on_stock_reorder_alert`` and ``on_stock_break_alert`` have had a column,
        a schema field, a template and a UI toggle, and nothing that computes the
        condition -- the Forecast panel does it in the browser, so with no page
        open nothing could ever alert. This runs the same arithmetic
        (``stock_forecast``) from the scheduler loop.

        An alert is sent when a SKU *moves into* a condition, once, and again
        after the condition has cleared. A SKU that worsens from reorder to break
        alerts again as a break, because the panel treats the two as exclusive; one
        that eases from break back to reorder does not alert again.
        A SKU with alerts snoozed is treated as not alerting, so un-snoozing it
        while it is still low tells you.

        Time-gated to hourly for the reasons ``_check_filament_low`` is gated: the
        loop runs every 3 s while an upload is in flight, and the whole spool
        collection is read over HTTP in Spoolman mode. Both events default to off
        on every provider, so nothing is read unless a provider wants one.
        """
        now = time.monotonic()
        if now < self._stock_forecast_next_check:
            return
        self._stock_forecast_next_check = now + _STOCK_FORECAST_MIN_INTERVAL

        try:
            if self._stock_alerts_persisted is None:
                await self._load_stock_alerts(db)
            wanted = {
                "reorder": bool(await notification_service._get_providers_for_event(db, "on_stock_reorder_alert")),
                "break": bool(await notification_service._get_providers_for_event(db, "on_stock_break_alert")),
            }
            if not any(wanted.values()):
                # Nobody wants either event. Forget what was sent, so whoever
                # switches one on is told about the SKUs that are low now.
                self._notified_stock_alerts.clear()
                await self._save_stock_alerts(db)
                return

            forecasts = await self._stock_forecasts(db)
            if forecasts is None:
                # Spoolman unreachable. Deliberately not clearing the notified
                # set: a brief outage would otherwise re-alert every SKU when it
                # came back.
                return

            await self._emit_stock_alerts(db, forecasts, wanted)
            await self._save_stock_alerts(db)
        except Exception as e:
            logger.warning("Stock forecast check failed: %s", e, exc_info=True)

    def _serialize_stock_alerts(self) -> str:
        """The notified set as JSON, in a fixed order so an unchanged set compares equal."""
        rows = sorted([list(key), kind, sorted(events)] for key, (kind, events) in self._notified_stock_alerts.items())
        return json.dumps(rows)

    async def _load_stock_alerts(self, db: AsyncSession) -> None:
        """Read the notified set saved by the last run, once per process.

        A missing or unreadable row is an empty set: the worst that does is one
        repeat of what a restart used to cause every time.
        """
        raw = (await db.execute(select(Settings).where(Settings.key == _STOCK_ALERTS_SETTING_KEY))).scalar_one_or_none()
        loaded: dict[stock_forecast.SkuKey, tuple[str, frozenset[str]]] = {}
        if raw and raw.value:
            try:
                for key, kind, events in json.loads(raw.value):
                    if len(key) == 4 and kind in ("reorder", "break"):
                        loaded[tuple(str(part) for part in key)] = (kind, frozenset(str(e) for e in events))
            except (ValueError, TypeError):
                logger.warning("Ignoring unreadable %s setting", _STOCK_ALERTS_SETTING_KEY)
                loaded = {}
        self._notified_stock_alerts = loaded
        self._stock_alerts_persisted = self._serialize_stock_alerts()

    async def _save_stock_alerts(self, db: AsyncSession) -> None:
        """Write the notified set to its settings row if it changed since it was last read or written."""
        serialized = self._serialize_stock_alerts()
        if serialized == self._stock_alerts_persisted:
            return
        from backend.app.core.db_dialect import upsert_setting

        await upsert_setting(db, Settings, _STOCK_ALERTS_SETTING_KEY, serialized)
        await db.commit()
        self._stock_alerts_persisted = serialized

    async def _stock_forecasts(self, db: AsyncSession) -> stock_forecast.ForecastMap | None:
        """Forecast every active SKU in whichever inventory mode is on. None if it cannot be read."""
        from backend.app.models.filament_sku_settings import FilamentSkuSettings

        global_lead_time = max(0, await self._get_int_setting(db, "forecast_global_lead_time_days", default=0))
        sku_rows = (await db.execute(select(FilamentSkuSettings))).scalars().all()
        sku_settings = {
            stock_forecast.sku_key(row.material, row.subtype, row.brand, row.color_name): stock_forecast.SkuSettings(
                lead_time_days=row.lead_time_days,
                safety_margin_value=row.safety_margin_value,
                safety_margin_unit=row.safety_margin_unit,
                alerts_snoozed=bool(row.alerts_snoozed),
            )
            for row in sku_rows
        }

        if await self._get_bool_setting(db, "spoolman_enabled"):
            spools = await self._stock_spools_spoolman()
            if spools is None:
                return None
            # Spoolman owns the usage in this mode and PrintLab's own history
            # table holds nothing for those spools, so the rate is always the
            # delta rate. PrintLab's table is deliberately not consulted: its ids
            # are local spool ids, and a Spoolman id that happens to match one
            # (left over from before Spoolman was switched on) would borrow an
            # unrelated spool's history.
            history: dict[int, list[stock_forecast.UsageRecord]] = {}
        else:
            spools = await self._stock_spools_internal(db)
            history = await self._stock_usage_history(db)

        return stock_forecast.forecast_all(spools, history, sku_settings, global_lead_time, utcnow_naive())

    async def _stock_spools_internal(self, db: AsyncSession) -> list[stock_forecast.StockSpool]:
        from backend.app.models.spool import Spool

        rows = (await db.execute(select(Spool).where(Spool.archived_at.is_(None)))).scalars().all()
        return [
            stock_forecast.StockSpool(
                id=spool.id,
                material=spool.material,
                subtype=spool.subtype,
                brand=spool.brand,
                color_name=spool.color_name,
                label_weight=float(spool.label_weight or 0),
                weight_used=float(spool.weight_used or 0),
                weight_used_baseline=float(spool.weight_used_baseline or 0),
                created_at=spool.created_at,
            )
            for spool in rows
        ]

    async def _stock_usage_history(self, db: AsyncSession) -> dict[int, list[stock_forecast.UsageRecord]]:
        from backend.app.models.spool_usage_history import SpoolUsageHistory

        rows = (
            await db.execute(
                select(SpoolUsageHistory.spool_id, SpoolUsageHistory.created_at, SpoolUsageHistory.weight_used)
                .order_by(SpoolUsageHistory.created_at.desc())
                .limit(_STOCK_FORECAST_HISTORY_LIMIT)
            )
        ).all()
        history: dict[int, list[stock_forecast.UsageRecord]] = {}
        for spool_id, created_at, weight_used in rows:
            if created_at is None:
                continue
            history.setdefault(spool_id, []).append(stock_forecast.UsageRecord(created_at, float(weight_used or 0)))
        return history

    async def _stock_spools_spoolman(self) -> list[stock_forecast.StockSpool] | None:
        """Spoolman's spools in the forecast's shape, or None when Spoolman cannot be reached.

        ``get_all_spools`` leaves archived spools out unless asked, which is the
        exclusion the internal query applies explicitly. ``_map_spoolman_spool``
        is the same mapping the Inventory page (and so the panel) reads.
        """
        from backend.app.api.routes._spoolman_helpers import _map_spoolman_spool
        from backend.app.services.spoolman import SpoolmanUnavailableError, get_spoolman_client

        client = await get_spoolman_client()
        if client is None:
            logger.debug("Stock forecast skipped, no Spoolman client (spoolman_enabled without a URL?)")
            return None
        try:
            raw_spools = await client.get_all_spools()
        except SpoolmanUnavailableError as e:
            logger.debug("Stock forecast skipped, Spoolman unreachable: %s", e)
            return None

        spools: list[stock_forecast.StockSpool] = []
        for raw in raw_spools:
            try:
                mapped = _map_spoolman_spool(raw)
            except ValueError:
                continue
            created_at = None
            if mapped.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(str(mapped["created_at"]).replace("Z", "+00:00"))
                except ValueError:
                    created_at = None
            spools.append(
                stock_forecast.StockSpool(
                    id=mapped["id"],
                    material=mapped["material"],
                    subtype=mapped.get("subtype"),
                    brand=mapped.get("brand"),
                    color_name=mapped.get("color_name"),
                    label_weight=float(mapped.get("label_weight") or 0),
                    weight_used=float(mapped.get("weight_used") or 0),
                    weight_used_baseline=float(mapped.get("weight_used_baseline") or 0),
                    created_at=created_at,
                    color_name_is_synthesized=bool(mapped.get("color_name_is_synthesized")),
                )
            )
        return spools

    async def _emit_stock_alerts(
        self,
        db: AsyncSession,
        forecasts: stock_forecast.ForecastMap,
        wanted: dict[str, bool],
    ) -> None:
        """Send the notifications for each SKU that has moved into a stock alert condition.

        A SKU in break has also reached its reorder point, so both events apply to
        it: the break event goes to providers that have it on, and the reorder event
        to the providers that have only that one on. A provider with both on gets the
        break and no second message.

        What is remembered per SKU is the condition and which events had a
        subscriber when it was sent. An event with no subscriber is forgotten, so
        switching it on later reports the SKUs already in that condition.
        """
        active_events = {event for event, on in wanted.items() if on}
        for key, (forecast, spool) in forecasts.items():
            kind: str | None = None
            if not forecast.snoozed:
                if forecast.stock_break_alert:
                    kind = "break"
                elif forecast.reorder_alert:
                    kind = "reorder"
            applicable = {"break": {"break", "reorder"}, "reorder": {"reorder"}}.get(kind or "", set())
            events = applicable & active_events
            if not events:
                self._notified_stock_alerts.pop(key, None)
                continue

            previous = self._notified_stock_alerts.get(key)
            told = (previous[1] & active_events) if previous else frozenset()
            # Trimmed to the events this condition can send. That is what makes easing from
            # break back to reorder silent (the reorder event was told with the break) and
            # worsening again news again (the break event is no longer remembered).
            self._notified_stock_alerts[key] = (kind, frozenset((told | events) & applicable))
            # Recorded before sending, for the reason _emit_filament_low gives: a
            # provider that is down should lose this alert, not repeat it every hour.
            to_send = events - told

            # Both flags imply a positive rate and so a day count.
            days_left = forecast.days_remaining if forecast.days_remaining is not None else 0
            rate = forecast.daily_rate_g if forecast.daily_rate_g is not None else 0.0
            color = None if spool.color_name_is_synthesized else spool.color_name
            try:
                if "break" in to_send:
                    await notification_service.on_stock_break_alert(
                        spool.material,
                        spool.brand,
                        forecast.remaining_g,
                        rate,
                        days_left,
                        forecast.effective_lead_time_days,
                        db,
                        subtype=spool.subtype,
                        color=color,
                    )
                if "reorder" in to_send:
                    await notification_service.on_stock_reorder_alert(
                        spool.material,
                        spool.brand,
                        forecast.remaining_g,
                        rate,
                        days_left,
                        db,
                        subtype=spool.subtype,
                        color=color,
                        skip_break_subscribers=kind == "break",
                    )
            except Exception as e:
                logger.warning("Stock %s notification failed for %s: %s", kind, key, e)

        # A SKU with no spools left is no longer alerting.
        for key in [k for k in self._notified_stock_alerts if k not in forecasts]:
            del self._notified_stock_alerts[key]

    # Scheduled manual drying (#2638) -----------------------------------

    SCHEDULED_DRYING_GRACE_SECONDS = 120  # firmware needs time to report dry_time
    SCHEDULED_DRYING_COMPLETE_FRACTION = 0.9  # dry_time==0 earlier than this = interrupted

    async def _get_smart_plugs(self, db: AsyncSession, printer_id: int) -> list[SmartPlug]:
        """Get all smart plugs associated with a printer."""
        result = await db.execute(select(SmartPlug).where(SmartPlug.printer_id == printer_id))
        return list(result.scalars().all())

    @staticmethod
    def _pick_power_plug(auto_on_plugs: list[SmartPlug]) -> SmartPlug:
        """Pick the plug to power-cycle a printer back online with (#2629).

        Only a plug flagged ``controls_printer_power`` can actually bring the
        printer back; waiting for a boot on an accessory (filter fan, lights)
        just burns the power-on timeout and fails the dispatch. Falls back to
        the first plug when none is flagged, which is the pre-#2629 behaviour.
        Callers must pass a non-empty list.
        """
        for plug in auto_on_plugs:
            if plug.controls_printer_power:
                return plug
        return auto_on_plugs[0]

    # Bundled defaults for preheat_filament_targets (#1468). Values are the
    # chamber-temperature recommendations BambuStudio ships for the matching
    # filament profile; users can override via Settings → Workflow → Preheat
    # card. "default" applies when a loaded tray's normalised type isn't in
    # the map (rare — Bambu RFID-tagged spools always carry a known type).
    DEFAULT_PREHEAT_FILAMENT_TARGETS: dict[str, int] = {
        "PLA": 0,
        "PETG": 0,
        "PETG-CF": 40,
        "ABS": 45,
        "ASA": 45,
        "PA": 50,
        "PA-CF": 55,
        "PC": 50,
        "PC-FR": 50,
        "TPU": 0,
        "PVA": 0,
        "default": 0,
    }

    def notify_dispatch_cancelled(self, item_id: int) -> None:
        """Tell an in-flight dispatch that its item no longer wants to print.

        Called by the queue's cancel and delete routes. Those only write to the
        database, which a dispatch coroutine parked in ``asyncio.sleep`` cannot
        observe — so preheat would keep heating for the rest of max_wait + soak
        (45 minutes at the defaults) and keep the printer in ``busy_printers``,
        blocking every other queued item behind a print that is not happening.

        Signalling in memory rather than re-reading the row keeps this off the
        database entirely: no second session, no transaction held across a long
        sleep, and no snapshot staleness deciding whether a print goes ahead.
        PrintLab serves from a single uvicorn process with one scheduler task,
        so the route and the dispatch always share this object. The flag is
        advisory — dropping it (e.g. after a restart) only costs a wasted
        preheat, never a wrongly-abandoned print.

        Only ids with a dispatch actually in flight are recorded, so the set
        stays bounded by the upload pool rather than growing once per cancelled
        item for the life of the process. Skipping the rest loses nothing: an
        item that is not in flight cannot start heating later either, because
        ``_claim_for_dispatch`` only claims rows that are still ``pending`` and
        the caller has already committed a terminal status (or deleted the row)
        before calling this.
        """
        if item_id in self._inflight:
            self._cancelled_dispatches.add(item_id)

    async def _power_on_and_wait(self, plug: SmartPlug, printer_id: int, db: AsyncSession) -> bool:
        """Turn on smart plug and wait for printer to connect.

        Returns True if printer connected successfully within timeout.
        """
        # Get the appropriate service for the plug type (Tasmota or Home Assistant)
        service = await smart_plug_manager.get_service_for_plug(plug, db)

        # Check current plug state
        status = await service.get_status(plug)
        if not status.get("reachable"):
            logger.warning("Smart plug '%s' is not reachable", plug.name)
            return False

        # Turn on if not already on
        if status.get("state") != "ON":
            success = await service.turn_on(plug)
            if not success:
                logger.warning("Failed to turn on smart plug '%s'", plug.name)
                return False
            logger.info("Powered on smart plug '%s' for printer %s", plug.name, printer_id)

        # Get printer from database for connection
        result = await db.execute(select(Printer).where(Printer.id == printer_id))
        printer = result.scalar_one_or_none()
        if not printer:
            logger.error("Printer %s not found in database", printer_id)
            return False

        # Wait for printer to boot (give it some time before trying to connect)
        logger.info("Waiting 30s for printer %s to boot...", printer_id)
        await asyncio.sleep(30)

        # Try to connect to the printer periodically
        elapsed = 30  # Already waited 30s
        while elapsed < self._power_on_wait_time:
            # Try to connect
            logger.info("Attempting to connect to printer %s...", printer_id)
            try:
                connected = await printer_manager.connect_printer(printer)
                if connected:
                    logger.info("Printer %s connected after %ss", printer_id, elapsed)
                    # Give it a moment to stabilize and get status
                    await asyncio.sleep(5)
                    return True
            except Exception as e:
                logger.debug("Connection attempt failed: %s", e)

            await asyncio.sleep(self._power_on_check_interval)
            elapsed += self._power_on_check_interval
            logger.debug("Waiting for printer %s to connect... (%ss)", printer_id, elapsed)

        logger.warning("Printer %s did not connect within %ss after power on", printer_id, self._power_on_wait_time)
        return False

    async def _check_previous_success(self, db: AsyncSession, item: PrintQueueItem) -> bool:
        """Check if the previous print on this printer succeeded.

        A user-cancelled predecessor is treated as neutral — `cancelled` is a
        deliberate action, not a failure, so subsequent items should still
        dispatch (#1667). `skipped` is excluded from the lookback entirely:
        a skip isn't an actual print attempt, so it must not gate downstream
        items — counting it as a failed predecessor was the cascade bug that
        let a single cancellation block 18 items over 3 days for the reporter.
        Only `failed` and `aborted` — real print-attempt failures — block.

        Failures with `gate_acknowledged=True` (set by the per-printer Resume
        action — #1818) are also excluded from the lookback so the user can
        clear the gate after fixing the physical issue without having to
        re-queue every downstream job.
        """
        result = await db.execute(
            select(PrintQueueItem)
            .where(PrintQueueItem.printer_id == item.printer_id)
            .where(PrintQueueItem.id != item.id)
            .where(PrintQueueItem.status.in_(["completed", "failed", "cancelled", "aborted"]))
            .where(PrintQueueItem.gate_acknowledged == False)  # noqa: E712
            .order_by(PrintQueueItem.completed_at.desc())
            .limit(1)
        )
        prev_item = result.scalar_one_or_none()

        # If no previous item, assume success (first in queue)
        if not prev_item:
            return True

        return prev_item.status in ("completed", "cancelled")

    async def _repoint_siblings_at_archive(
        self,
        db: AsyncSession,
        *,
        consumed_library_file_id: int,
        archive_id: int,
        dispatched_item_id: int,
    ) -> int:
        """Move the other queue items off a library row that is about to be deleted (#2819).

        ``cleanup_library_after_dispatch`` consumes the library row: the printer-card
        upload-and-print flow uploads a transient file, prints it, and deletes it.
        Queue creation happily puts that flag on every copy of a ``quantity > 1``
        request, and ``_clone_queue_item`` copies ``library_file_id`` onto batch
        clones, so the first dispatch could pull the file out from under rows that
        had not run yet. What those rows did next depended on the database, and
        neither answer was right: SQLite ships with ``PRAGMA foreign_keys`` off, so
        the ``ON DELETE CASCADE`` on ``print_queue.library_file_id`` never fired and
        they were left pointing at a row that no longer existed, failing with
        "Library file not found" whenever someone started them -- or sitting
        ``pending`` forever under ``manual_start``. PostgreSQL enforces the same
        constraint, so there the rows were deleted outright and the queued copies
        simply vanished, with no error and no history.

        The archive holds its own copy of the 3MF, so the remaining copies can print
        from it instead. Two things happen here, and both must happen *before* the
        delete -- afterwards there is nothing left to repair on PostgreSQL:

        * every row still naming the file has ``library_file_id`` cleared, which is
          what takes it out of the cascade's reach. That covers rows this cannot
          re-point as well -- a copy already printing from its own archive, and the
          finished ones, which are not spare parts but the record a batch order
          counts its progress from.
        * the rows that still need something to print are pointed at the archive.

        Returns how many items were re-pointed.
        """
        variant_item_ids = (
            (
                await db.execute(
                    select(PrintQueueVariant.queue_item_id).where(
                        PrintQueueVariant.library_file_id == consumed_library_file_id
                    )
                )
            )
            .scalars()
            .all()
        )
        # Candidate rows naming the consumed file have to go rather than be
        # cleared: `library_file_id` is NOT NULL there, so there is no way to keep
        # one out of the cascade. This is what PostgreSQL already does, and
        # _candidates_for skips such a variant on SQLite anyway, so no selection
        # outcome changes -- the two backends simply stop disagreeing about
        # whether the row is still there.
        #
        # It also has to happen before the re-point below: a cross-model item
        # (#671) picks a variant every pass and folds it onto the row, and
        # _resolve_variant clears archive_id as it does so, which would undo the
        # re-point on the very next lap.
        await db.execute(delete(PrintQueueVariant).where(PrintQueueVariant.library_file_id == consumed_library_file_id))

        # An item left with other candidates still has somewhere to go, and those
        # carry their own target model -- pointing it at this archive would print a
        # file the matcher never chose. It is excluded from the re-point and simply
        # re-resolves against what is left.
        surviving_variant_item_ids = set(
            (
                await db.execute(
                    select(PrintQueueVariant.queue_item_id).where(
                        PrintQueueVariant.queue_item_id.in_(variant_item_ids) if variant_item_ids else false()
                    )
                )
            )
            .scalars()
            .all()
        )
        repoint_ids = set(
            (
                await db.execute(
                    select(PrintQueueItem.id)
                    .where(PrintQueueItem.id != dispatched_item_id)
                    .where(PrintQueueItem.archive_id.is_(None))
                    # "skipped" belongs here with the two live states: it is not
                    # terminal. Clearing a printer's previous-success gate puts
                    # every item skipped by it back to "pending"
                    # (resume_after_failure), and one restored onto a deleted
                    # file is the same orphan by a slower route. "failed",
                    # "cancelled", "aborted" and "completed" never return.
                    .where(PrintQueueItem.status.in_(("pending", "printing", "skipped")))
                    .where(
                        PrintQueueItem.id.notin_(surviving_variant_item_ids) if surviving_variant_item_ids else true()
                    )
                    .where(
                        or_(
                            PrintQueueItem.library_file_id == consumed_library_file_id,
                            PrintQueueItem.id.in_(variant_item_ids) if variant_item_ids else false(),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        if repoint_ids:
            await db.execute(
                update(PrintQueueItem)
                .where(PrintQueueItem.id.in_(repoint_ids))
                .values(
                    archive_id=archive_id,
                    library_file_id=None,
                    # The file this flag named is already consumed. Leaving it set
                    # would arm every re-pointed copy to delete whatever library
                    # row it is next given.
                    cleanup_library_after_dispatch=False,
                )
            )
            logger.info(
                "Queue items %s: re-pointed at archive %s -- library file %s was consumed by item %s",
                sorted(repoint_ids),
                archive_id,
                consumed_library_file_id,
                dispatched_item_id,
            )

        # Everything else that still names the file: taken out of the cascade's
        # reach without touching what it prints. The file is gone either way; what
        # this preserves is the row.
        await db.execute(
            update(PrintQueueItem)
            .where(PrintQueueItem.id != dispatched_item_id)
            .where(PrintQueueItem.library_file_id == consumed_library_file_id)
            .values(library_file_id=None)
        )
        return len(repoint_ids)

    async def _power_off_if_needed(self, db: AsyncSession, item: PrintQueueItem):
        """Schedule power-off if the queue item enabled auto_off_after.

        Delegates to the smart-plug manager so the off honours each plug's
        configured strategy (time delay or temperature threshold), is cancelled
        if the printer starts printing again, and never cuts power on a loaded
        print (#1890). Previously this hardcoded a 50°C / 600s cooldown wait and
        powered off on the timeout regardless of print state.
        """
        if not item.auto_off_after:
            return
        try:
            await smart_plug_manager.schedule_off_after_queue_job(item.printer_id, db)
        except Exception as e:
            logger.warning("Auto-off: Failed to schedule power-off for printer %s: %s", item.printer_id, e)

    async def _get_job_name(self, db: AsyncSession, item: PrintQueueItem) -> str:
        """Get a human-readable name for a queue item."""
        if item.archive_id:
            result = await db.execute(select(PrintArchive).where(PrintArchive.id == item.archive_id))
            archive = result.scalar_one_or_none()
            if archive:
                return archive.filename.replace(".gcode.3mf", "").replace(".3mf", "")
        if item.library_file_id:
            result = await db.execute(LibraryFile.active().where(LibraryFile.id == item.library_file_id))
            library_file = result.scalar_one_or_none()
            if library_file:
                return library_file.filename.replace(".gcode.3mf", "").replace(".3mf", "")
        # A cross-model item (#671) holds no file of its own until a printer is
        # picked, so name it after its first candidate — otherwise every waiting
        # notification for one reads "Job #12". Queried rather than read off
        # item.variants because callers outside the selection loop have not
        # eager-loaded them, and a lazy load raises in async.
        first_variant_name = (
            await db.execute(
                select(LibraryFile.filename)
                .join(PrintQueueVariant, PrintQueueVariant.library_file_id == LibraryFile.id)
                .where(PrintQueueVariant.queue_item_id == item.id)
                .order_by(PrintQueueVariant.position, PrintQueueVariant.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if first_variant_name:
            return first_variant_name.replace(".gcode.3mf", "").replace(".3mf", "")
        return f"Job #{item.id}"

    async def _get_printer(self, db: AsyncSession, printer_id: int) -> Printer | None:
        """Get printer by ID."""
        result = await db.execute(select(Printer).where(Printer.id == printer_id))
        return result.scalar_one_or_none()

    async def _notify_dispatch_gave_up(
        self,
        queue_item_id: int,
        printer_id: int,
        created_by_id: int | None,
        reason: str = "Printer accepted the file but never started printing",
    ) -> None:
        """Tell the user the queue item was failed after exhausting its dispatch retries.

        Called from the watchdog, which is a background task with no session of
        its own — hence the fresh one here. Best-effort throughout: the row is
        already marked failed and that is the load-bearing part; a notification
        provider being down must not resurrect the retry loop we just stopped.

        ``reason`` defaults to the exhausted-retries wording. The command-rejected
        path passes its own, because "accepted the file but never started" is the
        opposite of what happened there — the printer refused it outright (#2732).
        """
        try:
            async with async_session() as db:
                item = await db.get(PrintQueueItem, queue_item_id)
                if not item:
                    return
                job_name = await self._get_job_name(db, item)
                printer = await self._get_printer(db, printer_id)
                await notification_service.on_queue_job_failed(
                    job_name=job_name,
                    printer_id=printer_id,
                    printer_name=printer.name if printer else "Unknown",
                    reason=reason,
                    db=db,
                )
        except Exception as e:
            logger.warning("Queue item %s: give-up notification failed: %s", queue_item_id, e)

        try:
            await ws_manager.send_queue_item_failed(
                user_id=created_by_id,
                queue_item_id=queue_item_id,
                printer_id=printer_id,
                reason="never_started",
            )
        except Exception:
            pass  # toast is best-effort

    async def _block_on_filament_deficit(
        self,
        db: AsyncSession,
        item: PrintQueueItem,
    ) -> bool:
        """Promote the item to manual_start when the assigned spool is short (#1496).

        Returns True when this dispatch attempt was blocked, False when the
        item is clear to start. A previously-flagged item whose spool has
        since been swapped to one with enough material clears the flag here
        so the next scheduler tick dispatches it.
        """
        # User has explicitly acknowledged the deficit ("Print Anyway") —
        # don't re-flag, don't even compute. Without this short-circuit the
        # scheduler bounces between "user said anyway" (route clears
        # manual_start) and "scheduler re-blocked" (this method re-flags it
        # on identical spool state) (#1698-followup).
        if item.skip_filament_check:
            # #1762 diagnostic: surface the short-circuit at INFO so a
            # future "Print Anyway didn't work" report (e.g. issue #1762
            # comment 3) has actionable evidence in the support bundle
            # without needing DEBUG enabled.
            logger.info(
                "Queue item %s honouring user's Print Anyway acknowledgement — skipping deficit check",
                item.id,
            )
            return False

        try:
            deficit = await compute_deficit_for_queue_item(db, item)
        except Exception as e:
            # Never let a flaky deficit check wedge the queue — log and let
            # dispatch proceed. The PrintModal-side check still runs on the
            # manual paths.
            logger.warning("Filament deficit check failed for item %s: %s", item.id, e)
            return False

        if deficit:
            item.filament_short = True
            item.manual_start = True
            await db.commit()
            job_name = await self._get_job_name(db, item)
            printer = await self._get_printer(db, item.printer_id) if item.printer_id else None
            logger.info(
                "Queue item %s blocked on filament deficit (%d slot(s)) — promoted to manual_start",
                item.id,
                len(deficit),
            )
            try:
                await notification_service.on_queue_job_waiting(
                    job_name=job_name,
                    target_model=(printer.model if printer else "") or "",
                    waiting_reason="filament_short",
                    db=db,
                )
            except Exception as e:
                logger.debug("filament_short notification failed for item %s: %s", item.id, e)
            return True

        # No deficit — clear any stale flag from a previous tick.
        if item.filament_short:
            item.filament_short = False
            await db.commit()
        return False

    async def _propagate_owner_to_printer_manager(self, db: AsyncSession, item: PrintQueueItem) -> None:
        """Hand the queue item's owner to printer_manager so the
        print-complete callback can credit the user in PrintLogEntry (#1670).

        No-ops when the item has no `created_by_id` or the referenced user
        row is missing (e.g. user deleted between queue-add and dispatch —
        in that case the print log row falls back to the existing un-credited
        behaviour rather than crashing the dispatch).
        """
        if not item.created_by_id:
            return
        from backend.app.models.user import User

        owner = await db.get(User, item.created_by_id)
        if owner:
            printer_manager.set_current_print_user(item.printer_id, owner.id, owner.username)

    async def _start_print(self, db: AsyncSession, item: PrintQueueItem):
        """Upload file and start print for a queue item.

        Supports two sources:
        - archive_id: Print from an existing archive
        - library_file_id: Print from a library file (file manager)
        """
        logger.info("Starting queue item %s", item.id)

        # Also covers a reservation left active by a process interruption
        # during an earlier attempt. `_dispatch_one` releases this marker on
        # every exit unless start_print() confirms that the command was sent.
        self._unconfirmed_budget_reservations.add(item.id)
        try:
            from backend.app.models.user import User

            queue_user = await db.get(User, item.created_by_id) if item.created_by_id is not None else None
            # Recompute at the final authorization boundary as well as enqueue
            # time. This covers rows created before the server-side estimate
            # migration and prevents any alternate write path from weakening
            # the budget reservation.
            archive = await db.get(PrintArchive, item.archive_id) if item.archive_id is not None else None
            library_file = await db.get(LibraryFile, item.library_file_id) if item.library_file_id is not None else None
            item.estimated_cost = await estimate_queue_source_cost(
                db,
                archive=archive,
                library_file=library_file,
                plate_id=item.plate_id,
                ams_mapping=item.ams_mapping,
                printer_id=item.printer_id,
            )
            await validate_print_budget(
                db,
                cost_center_id=item.cost_center_id,
                estimated_cost=item.estimated_cost,
                current_user=queue_user,
                exclude_queue_item_id=item.id,
                exclude_reservation_source_type="print_queue",
                exclude_reservation_source_id=item.id,
            )
            budget_reservation = await create_budget_reservation(
                db,
                cost_center_id=item.cost_center_id,
                estimated_cost=item.estimated_cost,
                current_user=queue_user,
                source_type="print_queue",
                source_id=item.id,
                print_archive_id=item.archive_id,
                exclude_queue_item_id=item.id,
            )
            await db.commit()
        except HTTPException as exc:
            item.status = "failed"
            item.error_message = str(exc.detail)
            item.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error("Queue item %s: Budget check failed: %s", item.id, item.error_message)
            await self._power_off_if_needed(db, item)
            return

        # Get printer first (needed for both paths)
        result = await db.execute(select(Printer).where(Printer.id == item.printer_id))
        printer = result.scalar_one_or_none()
        if not printer:
            item.status = "failed"
            item.error_message = "Printer not found"
            item.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error("Queue item %s: Printer %s not found", item.id, item.printer_id)
            await self._power_off_if_needed(db, item)
            return

        # Check printer is connected
        if not printer_manager.is_connected(item.printer_id):
            item.status = "failed"
            item.error_message = "Printer not connected"
            item.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error("Queue item %s: Printer %s not connected", item.id, item.printer_id)
            await self._power_off_if_needed(db, item)
            return

        # Cancel-while-dispatching race (#1853): the scheduler's snapshot of
        # `items` was taken at the top of check_queue, but the user can /cancel
        # any pending row in the gap before we reach this point. Re-read the
        # row and bail out cleanly instead of starting an FTP upload for a row
        # that's already cancelled. The atomic CAS at the pending→printing
        # transition (below, before start_print) is the load-bearing guard;
        # this is the early-exit optimisation that avoids wasted FTP I/O.
        await db.refresh(item)
        if item.status != "pending":
            logger.info(
                "Queue item %s no longer pending (status=%s) — aborting dispatch",
                item.id,
                item.status,
            )
            return

        # Busy-printer guard (#2598). check_queue gates dispatch on
        # _is_printer_idle(), but that treats FINISH as idle and a printer can
        # keep reporting FINISH for tens of seconds *after* it accepted a
        # project_file (see the watchdog's phase-B note). A watchdog revert
        # (#2555) also releases the dispatch hold, so a re-selected item can
        # reach here while its printer has actually started printing. Uploading
        # and dispatching then collides with the live job — the firmware answers
        # 0500_4004 and, on an A1 mini, cancels the running print. Re-check the
        # live state right before the expensive FTP upload: if the printer is
        # busy, leave the item pending and let a later tick dispatch it once the
        # printer is genuinely idle. No wasted upload, no collision.
        pre_dispatch_state = getattr(printer_manager.get_status(item.printer_id), "state", None)
        if pre_dispatch_state in _ACTIVE_PRINT_STATES:
            logger.info(
                "Queue item %s: printer %s is busy (state=%s) — deferring dispatch, "
                "leaving item pending for a later tick (#2598)",
                item.id,
                item.printer_id,
                pre_dispatch_state,
            )
            return

        # Determine source: archive or library file
        archive = None
        library_file = None
        file_path = None
        filename = None
        cleanup_disk_paths: list[Path] = []
        # Set when a dispatch consumes its library file, so the photos can be
        # carried over after the commit that removes the row (#3077).
        consumed_library_file_id: int | None = None
        consumed_photos: list[str] = []

        if item.archive_id:
            # Print from archive
            result = await db.execute(select(PrintArchive).where(PrintArchive.id == item.archive_id))
            archive = result.scalar_one_or_none()
            if not archive:
                item.status = "failed"
                item.error_message = "Archive not found"
                item.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.error("Queue item %s: Archive %s not found", item.id, item.archive_id)
                await self._power_off_if_needed(db, item)
                return

            # Persist the queue item's selected plate onto the archive so Print
            # History can show the actual plate after cancel/fail/complete (#2603).
            # Only when the archive doesn't already carry one, so a reprint of a
            # plate-specific archive isn't relabelled by a differently-plated
            # queue row.
            if archive.plate_id is None and item.plate_id is not None:
                archive.plate_id = item.plate_id

            # Ask-for-outcome opt-in rides from the queue item to the archive
            # the same way (#1898); never cleared here so a reprint of an
            # archive that already asked keeps asking.
            if item.confirm_outcome:
                archive.confirm_requested = True

            file_path = settings.base_dir / archive.file_path
            filename = archive.filename

        elif item.library_file_id:
            # Print from library file (file manager)
            result = await db.execute(LibraryFile.active().where(LibraryFile.id == item.library_file_id))
            library_file = result.scalar_one_or_none()
            if not library_file:
                # "Not found" covers two different situations and only one of
                # them is recoverable, so say which. A trashed file is still
                # there and restoring it makes a re-queued job work; a file that
                # is really gone needs a different one. Neither is knowable from
                # the queue, which is the whole complaint about this message.
                trashed = (
                    await db.execute(select(LibraryFile.filename).where(LibraryFile.id == item.library_file_id))
                ).scalar_one_or_none()
                item.status = "failed"
                item.error_message = (
                    f"'{trashed}' is in the library trash — restore it and queue the print again"
                    if trashed
                    else "Library file not found — it was deleted after this job was queued"
                )
                item.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.error(
                    "Queue item %s: library file %s is %s",
                    item.id,
                    item.library_file_id,
                    "in the trash" if trashed else "gone",
                )
                await self._power_off_if_needed(db, item)
                return
            # Library files store absolute paths
            lib_path = Path(library_file.file_path)
            file_path = lib_path if lib_path.is_absolute() else settings.base_dir / library_file.file_path
            filename = library_file.filename

            # Create archive from library file so usage tracking has access to the 3MF
            queue_item_id = item.id
            # Held separately: a cleanup dispatch clears item.library_file_id
            # below, and the log line at the end of this block reported that
            # cleared field -- so every consumed print logged "from library
            # file None", which is the one case worth being able to trace.
            source_library_file_id = item.library_file_id
            try:
                from backend.app.services.archive import ArchiveService

                archive_service = ArchiveService(db)
                archive = await archive_service.archive_print(
                    printer_id=item.printer_id,
                    source_file=file_path,
                    original_filename=filename,
                    created_by_id=item.created_by_id,
                    project_id=item.project_id,
                    cost_center_id=item.cost_center_id,
                    library_file_id=item.library_file_id,  # per-file project progress (#1897)
                    plate_id=item.plate_id,  # selected plate → Print History (#2603)
                )
                if archive:
                    item.archive_id = archive.id
                    if item.confirm_outcome:
                        archive.confirm_requested = True  # ask-for-outcome opt-in (#1898)
                    if budget_reservation is not None:
                        budget_reservation.print_archive_id = archive.id
                    if item.cleanup_library_after_dispatch and not library_file.is_external:
                        consumed_library_file_id = library_file.id
                        item.library_file_id = None
                        cleanup_disk_paths.append(file_path)
                        if library_file.thumbnail_path:
                            thumb_path = Path(library_file.thumbnail_path)
                            if not thumb_path.is_absolute():
                                thumb_path = settings.base_dir / library_file.thumbnail_path
                            cleanup_disk_paths.append(thumb_path)
                        # Before the delete, not after: on PostgreSQL the FK
                        # cascade would already have taken these rows (#2819).
                        await self._repoint_siblings_at_archive(
                            db,
                            consumed_library_file_id=consumed_library_file_id,
                            archive_id=archive.id,
                            dispatched_item_id=item.id,
                        )
                        # Read while the row is still here; the photos move
                        # below, once the delete has actually committed.
                        consumed_photos = list(library_file.photos or [])
                        await db.delete(library_file)
                        file_path = settings.base_dir / archive.file_path
                        filename = archive.filename
                    # Commit, not flush — flush opens the SQLite write
                    # transaction (item.archive_id update + library_file
                    # delete) and would hold the WAL writer lock through the
                    # FTP upload below, causing "database is locked" cascades
                    # for sensor history + concurrent cancels (#1853).
                    await db.commit()
                    logger.info(
                        "Queue item %s: Created archive %s from library file %s",
                        item.id,
                        archive.id,
                        source_library_file_id,
                    )
            except Exception as e:
                logger.warning(
                    "Queue item %s: Failed to create archive from library file: %s",
                    queue_item_id,
                    e,
                    exc_info=True,
                )
                await db.rollback()
                item = await db.get(PrintQueueItem, queue_item_id)
                if item:
                    item.status = "failed"
                    item.error_message = "Failed to create archive from library file"
                    item.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    await self._power_off_if_needed(db, item)
                return

            if not archive:
                item.status = "failed"
                item.error_message = "Failed to create archive from library file"
                item.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.error("Queue item %s: Archive creation from library file returned no archive", item.id)
                await self._power_off_if_needed(db, item)
                return

            # The photos follow the file into the archive that replaces it, for
            # the same reason the siblings do (#3077). After the commit above,
            # never before it: that commit can fail ("database is locked",
            # #1853) and roll the library row back, and photos already moved
            # would leave it naming a directory that no longer exists. The
            # file and thumbnail unlinks are deferred for the same reason.
            if consumed_library_file_id is not None and consumed_photos:
                # Held as a plain int, read here while the session is still
                # healthy, because the handler below may not touch an ORM
                # instance at all. The commit it exists for fails inside the
                # FLUSH, not at COMMIT: SQLite takes the write lock at the
                # first DML statement, so a busy writer surfaces as "database
                # is locked" on the UPDATE (#1853). SQLAlchemy rolls that back
                # internally through safe_reraise before re-raising, which
                # expires every loaded instance and leaves the session in
                # pending-rollback state -- so `archive.id` inside the except
                # would itself raise PendingRollbackError and the rollback
                # below would never be reached.
                archive_id = archive.id
                try:
                    carried_photos = move_library_photos(
                        consumed_library_file_id,
                        consumed_photos,
                        archive_photos_dir(archive),
                    )
                    if carried_photos:
                        archive.photos = list(archive.photos or []) + carried_photos
                        await db.commit()
                except Exception as e:
                    # The archive and the delete are already committed; the
                    # print goes ahead either way. Worst case the pictures sit
                    # unnamed in the archive's own directory.
                    #
                    # Ints only until the rollback has run, per the note above,
                    # which is why this logs queue_item_id and not item.id --
                    # the sibling handler forty lines up does the same.
                    logger.warning(
                        "Queue item %s: failed to carry library photos into archive %s: %s",
                        queue_item_id,
                        archive_id,
                        e,
                    )
                    await db.rollback()
                    # rollback() expires every loaded instance, and in async
                    # SQLAlchemy the next plain attribute read is lazy IO
                    # outside the greenlet -- MissingGreenlet, which would turn
                    # this cosmetic failure into a dispatch crash in exactly the
                    # "database is locked" case the block exists for (#1853).
                    # The nozzle guard, the upload and the start all keep
                    # reading item, archive and printer, so all three go back
                    # into the session before falling through.
                    item = await db.get(PrintQueueItem, queue_item_id)
                    archive = await db.get(PrintArchive, archive_id)
                    printer = await db.get(Printer, item.printer_id) if item else None
                    if not item or not archive or not printer:
                        logger.error(
                            "Queue item %s: item, archive %s or printer gone after the photo rollback",
                            queue_item_id,
                            archive_id,
                        )
                        return

        else:
            # Neither archive nor library file specified
            item.status = "failed"
            item.error_message = "No source file specified"
            item.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error("Queue item %s: No archive_id or library_file_id specified", item.id)
            await self._power_off_if_needed(db, item)
            return

        # Check file exists on disk
        if not file_path.exists():
            item.status = "failed"
            item.error_message = "Source file not found on disk"
            item.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error("Queue item %s: File not found: %s", item.id, file_path)
            await self._power_off_if_needed(db, item)
            return

        # Nozzle-diameter mismatch guard (#1899). A file sliced for one nozzle
        # size dispatched to a printer with a different nozzle installed is
        # rejected by the firmware with a cryptic HMS ("Failed to get AMS mapping
        # table" 0700_8012, or "nozzle diameter … not consistent" 0500_4038) that
        # gives the user no idea what went wrong. Catch it here, before we spend
        # time preheating and uploading, and fail with an actionable message.
        # Fail-safe by construction: only a POSITIVE mismatch blocks — when the
        # slice carries no nozzle diameter (archive.nozzle_diameter is None) or
        # the printer hasn't reported its nozzles yet, we fall through and let the
        # print proceed exactly as before. On dual-nozzle printers (H2D) a match
        # against EITHER installed nozzle passes, so a 0.6 slice is fine as long
        # as one of the two hotends is a 0.6.
        #
        # On a tool-changer model (H2C) the nozzles parked in the rack count too
        # (#2885): the printer fetches one as part of starting the print, so the
        # set to test against is "reachable", not "currently mounted". This runs
        # well before the rack picker at the bottom of this method, so without
        # the rack in scope here that picker never got the chance to run.
        sliced_nozzle = archive.nozzle_diameter if archive else None
        if sliced_nozzle:
            nozzle_status = printer_manager.get_status(item.printer_id)
            installed = _installed_nozzle_diameters(nozzle_status)
            rack = _rack_nozzle_diameters(nozzle_status)
            mismatch_msg = _nozzle_mismatch_message(sliced_nozzle, installed, rack)
            if mismatch_msg:
                item.status = "failed"
                item.error_message = mismatch_msg
                item.completed_at = datetime.now(timezone.utc)
                await db.commit()
                logger.warning("Queue item %s: nozzle mismatch — %s", item.id, mismatch_msg)
                await notification_service.on_queue_job_failed(
                    job_name=filename.replace(".gcode.3mf", "").replace(".3mf", ""),
                    printer_id=printer.id,
                    printer_name=printer.name,
                    reason=mismatch_msg,
                    db=db,
                )
                try:
                    await ws_manager.send_queue_item_failed(
                        user_id=item.created_by_id,
                        queue_item_id=item.id,
                        printer_id=item.printer_id,
                        reason="nozzle_mismatch",
                    )
                except Exception:
                    pass
                await self._power_off_if_needed(db, item)
                return

        # Preheat / heat-soak (#1468) — fires before upload so the printer's
        # bed (and chamber, if applicable) is at temperature when the firmware
        # starts the actual print routine. Best-effort: any failure logs and
        # falls through to the normal upload+start path rather than turning a
        # configuration issue into a failed queue item.
        # Returns False only when the item was cancelled or deleted while the
        # stage was holding at temperature. Uploading and starting it anyway
        # would print a job the user has already called off, so abandon the
        # dispatch here; `_dispatch_one`'s finally clause unwinds the heaters.
        if not await self._preheat_and_soak(db, item, printer, archive):
            logger.info("Queue item %s: dispatch abandoned — cancelled during preheat", item.id)
            return

        # See `_effective_plate_id` for why this is resolved once here rather
        # than each site below repeating `item.plate_id or 1`.
        effective_plate_id = _effective_plate_id(item.plate_id, file_path)

        # G-code injection for auto-print systems (#422)
        injected_path = None
        # #2547: tracked separately from `injected_path`, which is also set when
        # only a START snippet was injected. Only an END snippet changes what the
        # camera sees at print completion.
        end_gcode_injected = False
        if item.gcode_injection:
            try:
                snippets_raw = await self._get_setting(db, "gcode_snippets")
                if snippets_raw:
                    snippets = json.loads(snippets_raw)
                    model_snippets = snippets.get(printer.model, {})
                    start_gc = (model_snippets.get("start_gcode") or "").strip()
                    end_gc = (model_snippets.get("end_gcode") or "").strip()
                    if start_gc or end_gc:
                        from backend.app.utils.threemf_tools import inject_gcode_into_3mf

                        injected_path = inject_gcode_into_3mf(
                            file_path, effective_plate_id, start_gc or None, end_gc or None
                        )
                        if injected_path:
                            file_path = injected_path
                            end_gcode_injected = bool(end_gc)
                            logger.info("Queue item %s: G-code injected for model %s", item.id, printer.model)
                        else:
                            logger.warning(
                                "Queue item %s: G-code injection returned no result, using original", item.id
                            )
            except Exception as e:
                logger.warning("Queue item %s: G-code injection failed, using original: %s", item.id, e)

        # #2547: the finish-photo path can't learn from telemetry that this print
        # ends with user End G-code — which means the plate may be gone by the
        # time FINISH arrives (#1867). Flag it here; `on_print_start` binds it to
        # the print once the printer confirms it running.
        if end_gcode_injected:
            print_dispatch_context.mark_pending(printer.id)

        # Release the pooled DB connection before the FTP delete/upload (#2572).
        # Every read this method needs (printer, archive/library, preheat) is
        # done, and the library-file branch already committed its archive
        # creation. Without this the transaction opened by the first SELECT above
        # stays "idle in transaction" for the entire upload — multiple seconds
        # for a large 3MF — pinning one pooled connection per in-flight dispatch;
        # a farm dispatching many jobs at once then exhausts the pool. This was
        # correlated to an exact idle-in-transaction session on a 93-printer farm
        # (reporter @Jostxxl). expire_on_commit=False keeps item/printer/archive
        # readable; the status writes below (upload-failure path and the
        # pending->printing CAS) transparently open a fresh transaction.
        await db.commit()

        # Löschen, Toast, Wiederholung und Fehlertext liegen in
        # ``scheduler/upload.py``; was daraus für den Auftrag folgt, entscheidet
        # der Planer hier.
        toast_uid = item.created_by_id
        upload = await deliver_file(
            printer=printer,
            queue_item_id=item.id,
            user_id=toast_uid,
            file_path=file_path,
            filename=filename,
        )
        remote_filename = upload.remote_filename
        remote_path = upload.remote_path

        # Der eingefügte G-code lebt nur für diese Übertragung.
        if injected_path and injected_path.exists():
            injected_path.unlink(missing_ok=True)

        if not upload.uploaded:
            error_msg = upload.error_message
            if upload.refused:
                await self._requeue_after_upload_refused(db, item, printer, error_msg, toast_uid)
                return
            item.status = "failed"
            item.error_message = error_msg
            item.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error(
                f"Queue item {item.id}: FTP upload failed - printer={printer.name}, model={printer.model}, "
                f"ip={printer.ip_address}. Check logs above for storage diagnostics and specific error codes."
            )

            # Send failure notification
            await notification_service.on_queue_job_failed(
                job_name=filename.replace(".gcode.3mf", "").replace(".3mf", ""),
                printer_id=printer.id,
                printer_name=printer.name,
                # The same sentence the queue shows. A push notification saying
                # something different from the UI is its own small bug (#2899).
                reason=error_msg,
                db=db,
            )
            try:
                await ws_manager.send_queue_item_failed(
                    user_id=toast_uid,
                    queue_item_id=item.id,
                    printer_id=item.printer_id,
                    reason="upload_failed",
                )
            except Exception:
                pass
            await self._power_off_if_needed(db, item)
            return

        # The printer took a file, so any run of refused uploads is over: the
        # next refusal starts again at the shortest backoff, and notifies (#3210).
        self._upload_refusals.pop(printer.id, None)
        self._upload_refusal_notified.discard(printer.id)

        # Parse AMS mapping if stored
        ams_mapping = None
        if item.ams_mapping:
            try:
                ams_mapping = json.loads(item.ams_mapping)
            except json.JSONDecodeError:
                logger.warning("Queue item %s: Invalid AMS mapping JSON, ignoring", item.id)

        # Register as expected print so we don't create a duplicate archive
        # Only applicable for archive-based prints
        if archive:
            from backend.app.main import register_expected_print

            register_expected_print(
                item.printer_id,
                remote_filename,
                archive.id,
                ams_mapping=ams_mapping,
                created_by_id=item.created_by_id,
                cost_center_id=item.cost_center_id,
                # The plate actually dispatched, not the queue item's raw
                # column: on None, `register_expected_print` stores nothing,
                # and `extract_filament_usage_from_3mf` then books every
                # filament in the file rather than the one plate that printed.
                plate_id=effective_plate_id,
            )
            # Registration happens before the print command by necessity (the
            # printer can report the print before the send returns), so record
            # what to undo if we never get as far as sending. `_dispatch_one`
            # rolls back anything still pending here on every exit — exception,
            # early return, or cancel winning the CAS below.
            self._unconfirmed_expected_print[item.id] = (item.printer_id, remote_filename, archive.id)

        # Propagate the queue item's owner into printer_manager so the
        # print-complete callback can credit the user in the PrintLogEntry
        # (#1670). `created_by_id` is set either at queue-add time (UI-added
        # items) or when the user clicks the manual-start button.
        await self._propagate_owner_to_printer_manager(db, item)

        # IMPORTANT: Set status to "printing" BEFORE sending the print command.
        # This prevents phantom reprints if the backend crashes/restarts after the
        # print command is sent but before the status update is committed.
        # If we crash after this commit but before start_print(), the item will be
        # in "printing" status without actually printing - but that's safer than
        # accidentally reprinting the same file hours later.
        #
        # Atomic CAS (#1853): a user pressing /cancel mid-dispatch (between the
        # initial pending read at the top of check_queue and this point) flips
        # the row to "cancelled" in a separate session. Without the WHERE
        # status='pending' clause, the unconditional update here would silently
        # overwrite that cancellation and we'd ship the MQTT start_print below
        # — printer obeys, user sees "I pressed cancel and the print started".
        # rowcount==0 means the user won the race; bail out, best-effort delete
        # the file we just uploaded, do NOT send start_print.
        now_utc = datetime.now(timezone.utc)
        billing_run_id = str(uuid.uuid4())
        cas = await db.execute(
            update(PrintQueueItem)
            .where(PrintQueueItem.id == item.id)
            .where(PrintQueueItem.status == "pending")
            .values(status="printing", started_at=now_utc, billing_run_id=billing_run_id)
        )
        await db.commit()
        if cas.rowcount == 0:
            logger.info(
                "Queue item %s no longer pending at print-command time "
                "(cancelled or removed mid-dispatch) — aborting before MQTT send (#1853)",
                item.id,
            )
            try:
                await delete_file_async(
                    printer.ip_address,
                    printer.access_code,
                    remote_path,
                    socket_timeout=upload.ftp_timeout,
                    printer_model=printer.model,
                )
            except Exception as cleanup_err:
                logger.debug(
                    "Queue item %s: best-effort cleanup of uploaded file failed: %s",
                    item.id,
                    cleanup_err,
                )
            try:
                await ws_manager.send_queue_item_failed(
                    user_id=toast_uid,
                    queue_item_id=item.id,
                    printer_id=item.printer_id,
                    reason="cancelled_mid_dispatch",
                )
            except Exception:
                pass
            return
        # Sync the in-memory item so subsequent code that reads item.status /
        # item.started_at sees the values we just persisted.
        item.status = "printing"
        item.started_at = now_utc
        item.billing_run_id = billing_run_id
        if archive is not None:
            archive.billing_run_id = billing_run_id
            # Legacy transaction deletion used an archive-wide skip flag.
            # A newly dispatched run has its own UUID/tombstone, so it must be
            # billable independently of any older deleted run on this archive.
            archive.wallet_charge_skipped = False
            # Persist before MQTT send so completion and restart recovery can
            # always recover the internal billing identity.
            await db.commit()

        for cleanup_path in cleanup_disk_paths:
            try:
                if cleanup_path.exists():
                    cleanup_path.unlink()
            except OSError as cleanup_err:
                logger.warning(
                    "TRANSIENT_LIBRARY_FILE_ORPHAN %s",
                    json.dumps(
                        {
                            "queue_item_id": item.id,
                            "path": str(cleanup_path),
                            "error": str(cleanup_err),
                        },
                        sort_keys=True,
                    ),
                )

        # Clear the awaiting-plate-clear flag now that we're starting a new print
        printer_manager.set_awaiting_plate_clear(item.printer_id, False)

        # #1898: with the opt-in default-good setting, moving on to the next
        # print resolves the previous print's unanswered outcome prompt as
        # "good" — this path also covers the camera-based plate detection,
        # which releases the gate by allowing dispatch rather than by an
        # explicit acknowledgment. Rides on the dispatch transaction.
        if await self._get_bool_setting(db, "confirm_default_good_on_plate_clear", default=False):
            from backend.app.services.print_confirmation import resolve_pending_confirmation_as_good

            await resolve_pending_confirmation_as_good(db, item.printer_id)
        logger.info("Queue item %s: Status set to 'printing', sending print command...", item.id)

        # Plan und Zustand davor kommen aus ``scheduler/delivery.py``. Eine
        # zurückgewiesene Platte (Rack-Position passt nicht mehr) ist ein Fehler
        # vor dem Absetzen: beim Drucker ist noch nichts angekommen, also reichen
        # Fehlerstatus, Meldung und das Aufräumen der schon übertragenen Datei.
        plan = prepare_start(
            item=item,
            printer=printer,
            file_path=file_path,
            plate_id=effective_plate_id,
            ams_mapping=ams_mapping,
            remote_filename=remote_filename,
        )
        if isinstance(plan, StartRefusal):
            item.status = "failed"
            item.error_message = plan.message
            item.completed_at = datetime.now(timezone.utc)
            await db.commit()
            await notification_service.on_queue_job_failed(
                job_name=filename.replace(".gcode.3mf", "").replace(".3mf", ""),
                printer_id=printer.id,
                printer_name=printer.name,
                reason=plan.message,
                db=db,
            )
            try:
                await ws_manager.send_queue_item_failed(
                    user_id=toast_uid,
                    queue_item_id=item.id,
                    printer_id=item.printer_id,
                    reason="nozzle_rack_pick_stale",
                )
            except Exception:
                pass  # Best-effort — don't fail the error handler
            # The file is already on the SD card by this point, and a 3MF left
            # there is a phantom print waiting to be started from the touchscreen.
            # Same cleanup the start_print failure path below does, same reason.
            try:
                await delete_file_async(
                    printer.ip_address,
                    printer.access_code,
                    remote_path,
                    printer_model=printer.model,
                )
            except Exception:
                pass  # Best-effort — don't fail the error handler
            return

        # A slot that lost its K-profile selection (a power cycle resets every
        # slot to the default K) would print on the default. The idle check in
        # the status handler normally restores it first, but nothing guarantees
        # it ran before this dispatch (#3219). Unthrottled: once per job.
        # Never allowed to stop the print it is protecting.
        try:
            await kprofile_drift.reapply_lost_kprofiles(item.printer_id, _used_global_tray_ids(item), throttle=False)
        except Exception:
            logger.exception("Queue item %s: K-profile check before dispatch failed", item.id)

        # Was der Watchdog nach dem Absetzen braucht, kommt aus dem Plan.
        pre_state = plan.pre_state
        pre_subtask_id = plan.pre_subtask_id
        pre_gcode_file = plan.pre_gcode_file

        started = printer_manager.start_print(
            item.printer_id,
            remote_filename,
            **plan.print_kwargs(),
        )

        if started:
            # The command is away, so the expectation is now legitimate and must
            # survive. Anything still in this dict when _dispatch_one exits gets
            # rolled back.
            self._unconfirmed_expected_print.pop(item.id, None)
            self._unconfirmed_budget_reservations.discard(item.id)
            # Handoff to the print's own gcode: keep whatever preheat set (bed
            # target, chamber target, airduct heating) — the gcode owns
            # heater/flap control from here. Clearing the pin prevents
            # `_dispatch_one`'s finally from unwinding a live print.
            self._preheat_pin.pop(item.printer_id, None)
            self._preheat_pin_bed.pop(item.printer_id, None)
            logger.info("Queue item %s: Print started successfully - %s", item.id, filename)
            # No dispatch-toast event here: the legacy bg-dispatch path kept
            # status='processing' from upload start until the printer acked
            # (or timed out). The frontend derives "Awaiting printer…" purely
            # from upload_progress_pct >= 99.9; an explicit 'dispatched' WS
            # event would push the status chip out of 'PROCESSING' prematurely
            # — which is exactly what the screenshot at #1625-followup
            # complained about.

            # Register the local 3MF in the cover-cache so /cover skips FTP
            # (#1166 follow-up). file_path was resolved earlier from either the
            # archive or the library file row.
            if file_path is not None:
                cache_3mf_download(item.printer_id, remote_filename, file_path)

            # Hold the printer against further dispatches until the watchdog
            # confirms the printer transitioned (or until the hard timeout).
            # Prevents multi-plate batches from triple-dispatching onto the
            # same H2D Pro while it digests the first project_file (#1157).
            self._mark_printer_dispatched(item.printer_id, pre_state, pre_subtask_id)

            # Watchdog: if the printer never transitions out of pre_state AND
            # never advances subtask_id, the MQTT publish was accepted locally but
            # didn't reach the printer (half-broken session — same shape as
            # #887/#936). Revert the queue item so the next dispatch can pick it
            # up instead of leaving it stuck in "printing" (#967). subtask_id
            # check avoids false reverts on slow H2D FINISH→PREPARE transitions
            # that would otherwise cause the item to re-dispatch as a reprint
            # of the just-finished job (#1078).
            if pre_state:
                spawn_background_task(
                    self._watchdog_print_start(
                        item.id,
                        item.printer_id,
                        pre_state,
                        pre_subtask_id,
                        pre_gcode_file,
                        created_by_id=toast_uid,
                    ),
                    name=f"watchdog-print-start-{item.id}",
                )

            # Get estimated time for notification.
            #
            # This used to fall back to `library_file.print_time_seconds`, a column
            # LibraryFile does not have — the print time it knows about lives in
            # `file_metadata`. So a library print whose archive carried no parseable
            # print time (a plain .gcode, or a 3MF the parser could not read) raised
            # AttributeError right here, *after* the printer had already been sent
            # the job: the started-notification never fired, and the exception
            # unwound the whole queue pass, so every other printer still waiting to
            # be dispatched on that tick silently missed its turn.
            #
            # The queue item caches the print time at creation ("Cached from
            # archive/library"), which is the value this was reaching for.
            estimated_time = None
            if archive and archive.print_time_seconds:
                estimated_time = archive.print_time_seconds
            elif item.print_time_seconds:
                estimated_time = item.print_time_seconds

            # Send job started notification
            await notification_service.on_queue_job_started(
                job_name=filename.replace(".gcode.3mf", "").replace(".3mf", ""),
                printer_id=printer.id,
                printer_name=printer.name,
                db=db,
                estimated_time=estimated_time,
            )

            # MQTT relay - publish queue job started
            try:
                from backend.app.services.mqtt_relay import mqtt_relay

                await mqtt_relay.on_queue_job_started(
                    job_id=item.id,
                    filename=filename,
                    printer_id=printer.id,
                    printer_name=printer.name,
                    printer_serial=printer.serial_number,
                )
            except Exception:
                pass  # Don't fail if MQTT fails
        else:
            # Clean up uploaded file from SD card to prevent phantom prints
            try:
                await delete_file_async(
                    printer.ip_address,
                    printer.access_code,
                    remote_path,
                    printer_model=printer.model,
                )
            except Exception:
                pass  # Best-effort — don't fail the error handler

            # Busy-refusal is a deferral, not a failure (#2598). The printer's
            # state can flip from idle to active in the window between the
            # pre-dispatch check above and this publish (the FTP upload takes
            # seconds); start_print() then refuses to send project_file to the
            # now-busy printer and returns False. Failing the item here would be
            # wrong — the printer is fine, it is simply busy — so revert to
            # pending and let a later tick dispatch it once the printer is idle,
            # exactly like the pre-dispatch guard. Only a start_print() False on
            # an idle/unknown printer is a genuine command failure.
            post_dispatch_state = getattr(printer_manager.get_status(item.printer_id), "state", None)
            if post_dispatch_state in _ACTIVE_PRINT_STATES:
                logger.info(
                    "Queue item %s: printer %s became busy (state=%s) before the start "
                    "command was sent — deferring, reverting item to pending (#2598)",
                    item.id,
                    item.printer_id,
                    post_dispatch_state,
                )
                item.status = "pending"
                item.started_at = None
                await db.commit()
                return

            # Print command failed - revert status
            item.status = "failed"
            item.error_message = "Failed to send print command to printer"
            item.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.error(
                f"Queue item {item.id}: Failed to start print on {printer.name} ({printer.model}) - "
                f"printer_manager.start_print() returned False. "
                f"This may indicate: printer not connected, MQTT error, unsupported model configuration, or firmware issue. "
                f"Check printer status and backend logs for details."
            )

            # Send failure notification
            await notification_service.on_queue_job_failed(
                job_name=filename.replace(".gcode.3mf", "").replace(".3mf", ""),
                printer_id=printer.id,
                printer_name=printer.name,
                reason="Failed to send print command to printer - check printer connection and status",
                db=db,
            )
            try:
                await ws_manager.send_queue_item_failed(
                    user_id=toast_uid,
                    queue_item_id=item.id,
                    printer_id=item.printer_id,
                    reason="start_command_failed",
                )
            except Exception:
                pass

            await self._power_off_if_needed(db, item)

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
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval)
            status = printer_manager.get_status(printer_id)
            if not status:
                # Printer disconnected — don't mess with the DB. Drop the
                # in-memory dispatch hold too so a fresh dispatch can retry
                # once the printer comes back; the hard timeout would
                # otherwise hold the printer unnecessarily.
                scheduler._release_dispatch_hold(printer_id)
                return
            last_status = status
            if status.state in _ACTIVE_PRINT_STATES:
                # Printer is actively processing the job — release the
                # post-dispatch hold so the next pending item for this printer
                # can be evaluated normally. We do NOT accept arbitrary state
                # transitions: a printer going FINISH -> IDLE (user dismissed
                # the post-print prompt without accepting our project_file)
                # would otherwise look like "command landed" and leave the
                # queue item stuck in 'printing' forever (#1370).
                scheduler._release_dispatch_hold(printer_id)
                try:
                    await ws_manager.send_queue_item_acked(
                        user_id=created_by_id,
                        queue_item_id=queue_item_id,
                        printer_id=printer_id,
                    )
                except Exception:
                    pass
                return
            drying_ams_ids = drying_ams_ids or _drying_ams_ids(status)
            # Checked only after the active-state exit above: a stale HMS left
            # over from an earlier job must never abort a print that is visibly
            # running. An actually-refused command leaves the printer idle, so
            # this ordering costs the detection nothing.
            if _mqtt_commands_rejected(status):
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
            phase_b_deadline = time.monotonic() + phase_b_timeout
            while time.monotonic() < phase_b_deadline:
                await asyncio.sleep(poll_interval)
                status = printer_manager.get_status(printer_id)
                if not status:
                    scheduler._release_dispatch_hold(printer_id)
                    return
                last_status = status
                if status.state in _ACTIVE_PRINT_STATES:
                    scheduler._release_dispatch_hold(printer_id)
                    try:
                        await ws_manager.send_queue_item_acked(
                            user_id=created_by_id,
                            queue_item_id=queue_item_id,
                            printer_id=printer_id,
                        )
                    except Exception:
                        pass
                    return
                drying_ams_ids = drying_ams_ids or _drying_ams_ids(status)
                # Same ordering rule as Phase A: a running print wins over a
                # lingering HMS.
                if _mqtt_commands_rejected(status):
                    command_rejected = True
                    break

        # No active-state transition. Revert the item so the scheduler can retry.
        # Drop the in-memory hold so the retry isn't blocked by it.
        scheduler._release_dispatch_hold(printer_id)

        # Logged on every failed dispatch window, not just the last one, so a
        # support bundle shows the correlation from the first attempt rather than
        # only after the retry budget is spent (#2758).
        if drying_ams_ids:
            logger.info(
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
                item.completed_at = datetime.now(timezone.utc)
                await db.commit()
                return "command_rejected"
            if item.dispatch_attempts >= DISPATCH_MAX_ATTEMPTS:
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
                item.completed_at = datetime.now(timezone.utc)
                await release_budget_reservation(
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
            revert_outcome = await run_with_retry(_do_revert, label=f"watchdog revert item={queue_item_id}")
        except Exception as e:
            logger.warning(
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
            logger.error(
                "Queue item %s: printer %d reported HMS %s (MQTT command verification "
                "failed) — the print command was rejected, not lost. Failing the item "
                "without retrying; enable Developer Mode on the printer and restart it (#2732)",
                queue_item_id,
                printer_id,
                HMS_MQTT_VERIFY_FAILED,
            )
            await scheduler._notify_dispatch_gave_up(
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
            logger.error(
                "Queue item %s: printer %d never started the print after %d dispatch "
                "attempts (last one waited %.0fs) — marking the item failed instead of "
                "re-uploading it again (#2555)",
                queue_item_id,
                printer_id,
                DISPATCH_MAX_ATTEMPTS,
                total_timeout,
            )
            await scheduler._notify_dispatch_gave_up(queue_item_id, printer_id, created_by_id)
        elif revert_outcome == "reverted":
            if landed_on_subtask:
                logger.warning(
                    "Queue item %s: printer %d accepted project_file (subtask_id "
                    "advanced) but never transitioned to an active state within "
                    "%.0fs — printer wedged post-acceptance; reverted to 'pending' "
                    "for retry (#1678)",
                    queue_item_id,
                    printer_id,
                    total_timeout,
                )
            else:
                logger.warning(
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
        client = printer_manager.get_client(printer_id)
        current_gcode_file = getattr(last_status, "gcode_file", None) if last_status else None
        publish_landed = current_gcode_file is not None and current_gcode_file != pre_gcode_file
        if publish_landed:
            logger.warning(
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


# Global scheduler instance
scheduler = PrintScheduler()
