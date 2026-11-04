"""Verfügbarkeit und Aufwecken von Druckern für die Warteschlange.

Aus ``print_scheduler.py`` ausgelagert: die Modell-Suche mit Filament-Matching,
das Aufwecken über Smart Plugs, die Idle-Prüfung samt Haltegrund, die Prüfung
des vorherigen Auftrags und die Blockade bei Filament-Knappheit.
``PrintScheduler`` erbt die Methoden über :class:`AvailabilityMixin`; Aufrufer
und Tests sehen keinen Unterschied.
"""

import asyncio
import importlib
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.smart_plug import SmartPlug
from backend.app.services.queue_priority import printer_usage_seconds
from backend.app.services.scheduler.filament import (
    _filament_constraints,
    _ModelCandidate,
)
from backend.app.services.smart_plug_manager import smart_plug_manager
from backend.app.utils.printer_models import normalize_printer_model

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen.

    Die Methoden sind hierher gewandert, gepatcht wird aber weiterhin im
    Modul ``print_scheduler`` (``printer_manager``, ``time``, ``datetime``,
    ``notification_service``, ``compute_deficit_for_queue_item``). Der Zugriff
    über das Modul hält beides zusammen: Test-Attrappe und Produktionspfad.
    """
    return importlib.import_module("backend.app.services.print_scheduler")


class AvailabilityMixin:
    """Methoden der Verfügbarkeits- und Aufweck-Schritte des Druckplaners."""

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
        if _rt().time.monotonic() >= deadline:
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
                if _rt().printer_manager.is_connected(printer.id):
                    continue
                if self._wake_recently_failed(printer.id):
                    # Its plug did not bring it back a moment ago. Move on to a
                    # sibling instead of spending this pass — and every pass —
                    # on the same printer.
                    continue
                if require_plate_clear and _rt().printer_manager.is_awaiting_plate_clear(printer.id):
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
                    self._wake_failures[printer.id] = _rt().time.monotonic() + self._wake_failure_cooloff
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

            is_connected = _rt().printer_manager.is_connected(printer.id)
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

    def _is_printer_idle(self, printer_id: int, require_plate_clear: bool = True) -> bool:
        """Check if a printer is connected and idle."""
        if not _rt().printer_manager.is_connected(printer_id):
            logger.debug("Printer %d: not connected", printer_id)
            return False

        state = _rt().printer_manager.get_status(printer_id)
        if not state:
            logger.debug("Printer %d: no status available", printer_id)
            return False

        # Plate-clear gate: if the printer finished/failed a previous print and the user
        # hasn't acknowledged the plate was cleared, the queue must not dispatch the next
        # job — even if the printer currently reports IDLE. After Auto Off cycles the
        # printer, it boots back into IDLE with no memory of the previous finish; without
        # the persisted awaiting flag we'd bypass the confirmation prompt (#961).
        if require_plate_clear and _rt().printer_manager.is_awaiting_plate_clear(printer_id):
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
        if require_plate_clear and _rt().printer_manager.is_awaiting_plate_clear(printer_id):
            return f"Waiting for plate confirmation: {printer_name}"
        return f"Busy: {printer_name}"

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
                connected = await _rt().printer_manager.connect_printer(printer)
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
            deficit = await _rt().compute_deficit_for_queue_item(db, item)
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
                await _rt().notification_service.on_queue_job_waiting(
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
