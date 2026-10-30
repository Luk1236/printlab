"""Automatische und geplante Trocknung des Druckplaners.

Aus ``print_scheduler.py`` ausgelagert: alles, was Trocknung anstößt,
überwacht und beendet. ``PrintScheduler`` erbt die Methoden über
:class:`DryingMixin`; Aufrufer und Tests sehen keinen Unterschied.
"""

import importlib
import json
import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.scheduled_drying import ScheduledDrying
from backend.app.models.settings import Settings
from backend.app.services import drying_preflight
from backend.app.services.printer_manager import supports_drying_while_printing
from backend.app.services.scheduler.chamber import (
    AUTO_DRY_MAX_UNPRODUCTIVE_CYCLES,
    AUTO_DRY_REARM_COOLDOWN_SECONDS,
    AUTO_DRY_SUSTAINED_GAP_FLOOR_SECONDS,
    SCHEDULED_DRYING_PRUNE_INTERVAL_SECONDS,
    SCHEDULED_DRYING_RETENTION_DAYS,
)
from backend.app.services.scheduler.dispatch import _ACTIVE_PRINT_STATES
from backend.app.utils.ams_drying import is_countdown_parked
from backend.app.utils.ams_humidity import ams_humidity_percent
from backend.app.utils.local_time import utcnow_naive

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen.

    Die Methoden sind hierher gewandert, gepatcht wird aber weiterhin im
    Modul ``print_scheduler`` (``printer_manager``, ``time``, ``datetime``,
    ``notification_service``, ``supports_drying``). Der Zugriff über das
    Modul hält beides zusammen: Test-Attrappe und Produktionspfad.
    """
    return importlib.import_module("backend.app.services.print_scheduler")


class DryingMixin:
    """Methoden für automatische und geplante Trocknung."""

    async def _get_drying_presets(self, db: AsyncSession) -> dict[str, dict[str, int]]:
        """Get drying presets (user-configured or built-in defaults)."""
        result = await db.execute(select(Settings).where(Settings.key == "drying_presets"))
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            try:
                presets = json.loads(setting.value)
                if isinstance(presets, dict) and presets:
                    return presets
            except json.JSONDecodeError:
                pass
        return self.DEFAULT_DRYING_PRESETS

    async def _get_humidity_thresholds(self, db: AsyncSession) -> dict[str, int]:
        """Per-filament humidity thresholds (#1605).

        Returns the user-configured overrides map keyed by normalized filament
        type (uppercase base, e.g. ``PLA``, ``ASA``) plus a ``default`` key for
        unknown / unmapped types. Empty / unset → empty dict, in which case
        callers fall back to ``ams_humidity_fair``.
        """
        result = await db.execute(select(Settings).where(Settings.key == "ams_humidity_thresholds"))
        setting = result.scalar_one_or_none()
        if not setting or not setting.value:
            return {}
        try:
            data = json.loads(setting.value)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, int] = {}
        for key, value in data.items():
            try:
                out[str(key).upper() if key != "default" else "default"] = int(value)
            except (TypeError, ValueError):
                continue
        return out

    @staticmethod
    def resolve_humidity_threshold(trays: list[dict], thresholds: dict[str, int], fallback: int) -> int:
        """Resolve the effective humidity threshold for an AMS unit (#1605).

        For mixed filament types loaded into one AMS, returns the most
        restrictive (lowest) threshold across all loaded tray types — matches
        the conservative-params strategy already used for drying temp/hours.
        Empty / unloaded trays contribute no constraint. Unknown types use the
        ``default`` key, falling through to ``fallback`` (= ``ams_humidity_fair``)
        when no per-type map is configured at all.
        """
        default = thresholds.get("default", fallback)
        if not thresholds:
            return fallback
        candidates: list[int] = []
        for tray in trays:
            tray_type = str(tray.get("tray_type") or "").strip()
            if not tray_type:
                continue
            # A composite carries its base material's threshold when it has no
            # row of its own, the same way it takes its drying preset (#3067).
            key = _rt().PrintScheduler._resolve_filament_key(tray_type, thresholds)
            candidates.append(thresholds[key] if key is not None else default)
        if not candidates:
            return default
        return min(candidates)

    def _get_conservative_drying_params(
        self, trays: list[dict], module_type: str, presets: dict[str, dict[str, int]]
    ) -> tuple[int, int, str] | None:
        """Get the most conservative drying params for mixed filament types in an AMS unit.

        Returns (temp, duration_hours, filament_type) or None if no drying-eligible filaments.
        """
        temp_key = module_type if module_type in ("n3f", "n3s") else "n3f"
        hours_key = f"{temp_key}_hours"

        min_temp = None
        max_hours = None
        filament_type = ""

        for tray in trays:
            tray_type = tray.get("tray_type", "")
            if not tray_type:
                continue
            # "PLA Basic" -> PLA, and "PA6-CF" -> PA rather than nothing at all,
            # which is what stopped auto-drying on every composite spool (#3067).
            base_type = self._resolve_filament_key(tray_type, presets)
            if base_type is None:
                continue
            # The table is user-editable JSON with no per-row validation, so a
            # row can be present and empty. That has always meant "skip this
            # material", and it has to keep meaning it: the reads below fall
            # back to 55C/12h per missing field, which is a temperature nobody
            # chose and would deform a PLA spool.
            preset = presets[base_type]
            if not preset:
                continue

            temp = preset.get(temp_key, 55)
            hours = preset.get(hours_key, 12)

            # Conservative: lowest temp, longest duration
            if min_temp is None or temp < min_temp:
                min_temp = temp
            if max_hours is None or hours > max_hours:
                max_hours = hours
            if not filament_type:
                filament_type = base_type

        if min_temp is None:
            return None
        return (min_temp, max_hours or 12, filament_type)

    async def _check_auto_drying(
        self,
        db: AsyncSession,
        queue_items: list[PrintQueueItem],
        dispatching_printers: set[int],
    ):
        """Start drying on idle printers based on humidity.

        Three modes (can all be enabled independently):
        - queue_drying_enabled: Dry between scheduled queue prints
        - ambient_drying_enabled: Dry any idle printer when humidity is high, regardless of queue
        - print_drying_enabled: Also evaluate printers that are currently printing,
          when model+firmware supports "Print While Drying" (gated by
          supports_drying_while_printing). Drying temperature is capped at
          max(40, preset_temp - 5) to protect spools mid-print.
        """
        queue_drying_enabled = await self._get_bool_setting(db, "queue_drying_enabled")
        ambient_drying_enabled = await self._get_bool_setting(db, "ambient_drying_enabled")
        print_drying_enabled = await self._get_bool_setting(db, "print_drying_enabled")
        sustained_minutes = await self._get_int_setting(db, "ambient_drying_sustained_minutes", default=0)
        # The wait belongs to ambient drying: the settings UI only shows it while
        # ambient drying is on, so a value left behind when ambient is turned off
        # must not keep delaying the one path that still reaches the wait gate
        # without it (a mid-print start under print_drying).
        sustained_wait_active = sustained_minutes > 0 and ambient_drying_enabled
        # Clear every streak as soon as the wait is inactive. An early return (or
        # an already-drying unit) may otherwise skip the per-unit cleanup and let
        # a quick toggle-on inherit an old streak.
        if not sustained_wait_active:
            self._auto_dry_above.clear()
        if not queue_drying_enabled and not ambient_drying_enabled:
            # Stop active drying on all printers if both features disabled
            if self._drying_in_progress:
                for pid in list(self._drying_in_progress):
                    if pid in self._scheduled_drying_printer_ids:
                        continue
                    logger.info("Auto-drying: printer %d — stopping, auto-drying disabled", pid)
                    await self._stop_drying(pid)
            return

        # Update drying state from printer status (handles backend restart)
        self._sync_drying_state()

        # Find printers with scheduled items (for queue drying mode)
        printers_with_scheduled: set[int] = set()
        printers_with_items: set[int] = set()
        for item in queue_items:
            if item.printer_id:
                printers_with_items.add(item.printer_id)
                if item.scheduled_time and not item.manual_start:
                    printers_with_scheduled.add(item.printer_id)

        # If only queue mode is on and no printers have scheduled items, stop drying
        # (but skip this short-circuit when print_drying_enabled is on — busy printers
        # may still be eligible for mid-print drying regardless of queue state).
        if not ambient_drying_enabled and not printers_with_scheduled and not print_drying_enabled:
            for pid in list(self._drying_in_progress):
                if pid in self._scheduled_drying_printer_ids:
                    continue
                logger.info("Auto-drying: printer %d — stopping, no scheduled prints in queue", pid)
                await self._stop_drying(pid)
            return

        # Get humidity threshold (global fallback)
        result = await db.execute(select(Settings).where(Settings.key == "ams_humidity_fair"))
        setting = result.scalar_one_or_none()
        global_humidity_threshold = int(setting.value) if setting else 60

        # Per-filament humidity threshold overrides (#1605). Empty → fall back
        # to the global threshold for every AMS unit.
        per_type_thresholds = await self._get_humidity_thresholds(db)

        # Get drying presets
        presets = await self._get_drying_presets(db)

        # Determine if drying should be skipped for printers with pending items
        block_for_drying = await self._get_bool_setting(db, "queue_drying_block")

        # Get all active printers
        all_printers = await db.execute(select(Printer).where(Printer.is_active.is_(True)))
        for printer in all_printers.scalars():
            pid = printer.id

            # Resolve model+firmware up front — needed to decide whether this printer
            # qualifies for mid-print drying (busy printer on capable hardware).
            state = _rt().printer_manager.get_status(pid)
            if not state:
                logger.debug("Auto-drying: printer %d skipped — no state", pid)
                continue
            model = _rt().printer_manager.get_model(pid)
            firmware = state.firmware_version

            # "Mid-print" has to mean the printer is actually printing (#2801).
            # It used to be inferred from the dispatch set, which also holds
            # printers that merely could not be dispatched to -- so a printer
            # sitting in FINISH behind an unacknowledged plate was treated as
            # printing, had its drying temperature capped by the mid-print
            # spool protection, and was logged as (mid-print) while idle.
            is_printing = state.state in _ACTIVE_PRINT_STATES
            mid_print = is_printing and print_drying_enabled and supports_drying_while_printing(model, firmware)

            # A printer whose print is running or imminent is left alone unless
            # it can dry through it. `dispatching_printers` is deliberately the
            # narrow set: running, held post-dispatch, or mid-upload.
            if (is_printing or pid in dispatching_printers) and not mid_print:
                logger.debug("Auto-drying: printer %d skipped — printing or about to", pid)
                continue

            if not mid_print:
                # In queue-only mode, only dry printers that have scheduled prints
                if not ambient_drying_enabled and pid not in printers_with_scheduled:
                    if self._drying_in_progress.get(pid) and pid not in self._scheduled_drying_printer_ids:
                        logger.info("Auto-drying: printer %d — stopping, no scheduled prints for this printer", pid)
                        await self._stop_drying(pid)
                    logger.debug("Auto-drying: printer %d skipped — no scheduled prints", pid)
                    continue
                # When block mode is on, don't START new drying on printers with pending items.
                # But allow already-drying printers through so humidity auto-stop logic still runs.
                if block_for_drying and pid in printers_with_items and not self._drying_in_progress.get(pid):
                    logger.debug("Auto-drying: printer %d skipped — has pending items (block mode)", pid)
                    continue
            if not _rt().printer_manager.is_connected(pid):
                logger.debug("Auto-drying: printer %d skipped — not connected", pid)
                continue
            # Plate-clear is deliberately ignored here (#2801). It answers
            # "is the bed ready for the next job", which says nothing about
            # whether the AMS may heat -- and the gap between a finished print
            # and the acknowledgment is exactly when drying is most useful,
            # because the printer is free and nobody is waiting on it. Leaving
            # the plate unacknowledged is also how people hold the queue by
            # hand, and that hold should not cost them their drying.
            if not mid_print and not self._is_printer_idle(pid, require_plate_clear=False):
                logger.debug("Auto-drying: printer %d skipped — not idle", pid)
                continue

            # Check drying capability. For mid-print path, supports_drying_while_printing
            # was already verified when computing mid_print above.
            if not mid_print and not _rt().supports_drying(model, firmware):
                logger.debug("Auto-drying: printer %d skipped — model %s does not support drying", pid, model)
                continue

            # Check each AMS unit from raw_data
            ams_list = state.raw_data.get("ams", [])
            logger.debug("Auto-drying: printer %d — checking %d AMS units", pid, len(ams_list))
            for ams_data in ams_list:
                module_type = str(ams_data.get("module_type") or "")
                ams_id = int(ams_data.get("id", 0))
                # Only n3f/n3s support drying
                if module_type not in ("n3f", "n3s"):
                    logger.debug("Auto-drying: printer %d AMS %d skipped — module_type=%s", pid, ams_id, module_type)
                    continue

                # Resolve per-filament humidity threshold for this AMS unit (#1605).
                # Most-restrictive of all loaded tray types; falls back to the
                # global threshold when no overrides are configured.
                trays = ams_data.get("tray", []) or []
                humidity_threshold = self.resolve_humidity_threshold(
                    trays, per_type_thresholds, global_humidity_threshold
                )

                dry_time = int(ams_data.get("dry_time") or 0)

                # Read humidity as a percentage. The 1-5 index is never
                # substituted: it is inverted, and being unable to exceed any
                # threshold it would read as "dry" forever (#3140). ``None``
                # already means "skip this unit" everywhere below.
                humidity_pct = ams_humidity_percent(ams_data)
                humidity = int(round(humidity_pct)) if humidity_pct is not None else None
                unit_key = (pid, ams_id)
                unit_state = self._auto_dry_units.get(unit_key)

                # Already drying — let it run to its configured duration (#1892).
                #
                # We deliberately do NOT stop drying from a humidity re-check here.
                # Relative humidity drops steeply in heated air, so the AMS sensor
                # reads ~15-20% within minutes of the dryer starting even while the
                # filament is still saturated. A humidity-based early-stop therefore
                # always fires at the minimum-time floor, truncating both user-started
                # manual cycles and PrintLab's own preset-duration dries to ~30 min.
                # The firmware stops when the configured duration elapses; scheduling
                # stops (print takes priority, queue no longer needs drying) are
                # handled separately via _stop_drying().
                if dry_time > 0:
                    if pid not in self._drying_in_progress:
                        # Drying we didn't start (manual or from before restart) —
                        # track it so scheduling stops still apply; never auto-stop it.
                        self._drying_in_progress[pid] = _rt().time.monotonic()
                    if unit_state is not None:
                        unit_state["running"] = True
                    logger.debug(
                        "Auto-drying: printer %d AMS %d — drying (%dm left, humidity %s%%), letting it run",
                        pid,
                        ams_id,
                        dry_time,
                        humidity,
                    )
                    continue

                # Nothing is drying. Close out a cycle we armed ourselves and
                # judge whether it achieved anything (#2770).
                #
                # "Achieved anything" is measured against the LOWEST reading any
                # cycle on this unit has ended at, not against the threshold and
                # not against the previous cycle. A spool that is genuinely wet
                # in a humid room comes down slowly — 40, 37, 35 — and must be
                # allowed to keep going for as long as it is still coming down,
                # however far it still is from the threshold. What must not
                # continue is a cycle that ends exactly where the last one did,
                # which is the reporter's signature: 15, 15, 16, 15, forever.
                # Comparing against the running minimum rather than the previous
                # end is what stops a sensor oscillating by one point between two
                # values from reading as progress every other cycle.
                if unit_state is not None and unit_state.pop("running", False):
                    unit_state["ended_at"] = _rt().time.monotonic()
                    # The streak that armed this cycle is spent; the next one
                    # starts fresh (and accumulates through the re-arm cooldown
                    # below, so the wait overlaps the cooldown, never stacks on
                    # top of it).
                    self._auto_dry_above.pop(unit_key, None)
                    if humidity is not None and humidity > humidity_threshold:
                        best = unit_state.get("best_end_humidity")
                        if isinstance(best, int) and humidity < best:
                            # Still coming down. Keep going, however far the
                            # threshold still is.
                            unproductive = 0
                        else:
                            unproductive = int(unit_state.get("unproductive", 0)) + 1
                        if not isinstance(best, int) or humidity < best:
                            unit_state["best_end_humidity"] = humidity
                        unit_state["unproductive"] = unproductive
                        logger.info(
                            "Auto-drying: printer %d AMS %d — cycle ended with humidity still %d%% > "
                            "threshold %d%% (best so far %s%%, %d unproductive in a row)",
                            pid,
                            ams_id,
                            humidity,
                            humidity_threshold,
                            unit_state.get("best_end_humidity"),
                            unproductive,
                        )
                    # A cycle that ended at or below the threshold needs no
                    # counter reset here: the branch below drops the whole entry.

                # Humidity below threshold — no need to start drying. This is
                # also the only thing that lifts a suspension: the reading we
                # gave up on has come down, so auto-drying works again and the
                # unit goes back to having no history at all.
                if humidity is None or humidity <= humidity_threshold:
                    if unit_state is not None and unit_state.get("suspended"):
                        logger.info(
                            "Auto-drying: printer %d AMS %d — humidity %s%% is back at or below the %d%% "
                            "threshold, resuming automatic drying",
                            pid,
                            ams_id,
                            humidity,
                            humidity_threshold,
                        )
                    # Clear the judgement, keep the clock (#2801). Dropping the
                    # whole entry also dropped `ended_at`, and with it the
                    # 30-minute cooldown -- so a reading that dips to the
                    # threshold as the AMS cools and comes back above it once
                    # warm wiped its own history and re-armed immediately. That
                    # oscillation is the very thing #2770's cooldown exists to
                    # ride out, and it is worst at exactly the margin that makes
                    # a unit dry repeatedly: a point or two above the threshold.
                    if unit_state is not None:
                        unit_state.pop("suspended", None)
                        unit_state.pop("unproductive", None)
                        unit_state.pop("best_end_humidity", None)
                    # A real below-threshold reading ends any sustained-wait
                    # streak (#2518) -- "continuously above" means exactly that.
                    # An absent reading (humidity is None) is no-information and
                    # leaves the streak alone; the observation-gap guard handles
                    # a prolonged sensor silence.
                    if humidity is not None:
                        _above = self._auto_dry_above.pop(unit_key, None)
                        if _above is not None and sustained_wait_active:
                            logger.info(
                                "Auto-drying: printer %d AMS %d — humidity fell back to %s%% after "
                                "%.0fs of the required %dm above the %d%% threshold; not drying",
                                pid,
                                ams_id,
                                humidity,
                                _rt().time.monotonic() - _above["since"],
                                sustained_minutes,
                                humidity_threshold,
                            )
                    logger.debug(
                        "Auto-drying: printer %d AMS %d skipped — humidity %s <= threshold %d",
                        pid,
                        ams_id,
                        humidity,
                        humidity_threshold,
                    )
                    continue

                # Sustained-humidity streak (#2518): updated on every pass that
                # observes the reading above the threshold, BEFORE the
                # suspension/cooldown gates below -- a suspended or cooling-down
                # unit still accumulates streak _rt().time, so the wait overlaps those
                # gates instead of stacking after them. Inert when the feature
                # is off: no entries are written, and an entry left over from a
                # toggle-off is dropped so it cannot seed a stale streak later.
                if sustained_wait_active:
                    _now = _rt().time.monotonic()
                    # Four missed scheduler passes, floored: a single slow pass
                    # must not void a streak, but the ceiling has to scale with
                    # the cadence or a slow loop silently restarts every streak.
                    _gap_ceiling = max(4 * self._check_interval, AUTO_DRY_SUSTAINED_GAP_FLOOR_SECONDS)
                    _above = self._auto_dry_above.get(unit_key)
                    if _above is None:
                        self._auto_dry_above[unit_key] = {"since": _now, "last": _now}
                    elif _now - _above["last"] > _gap_ceiling:
                        # Restart, and say so at the same level as the dip
                        # reset: a silent restart voids the streak invisibly,
                        # and a user who set a long wait and never gets a dry
                        # has no way to see why.
                        logger.info(
                            "Auto-drying: printer %d AMS %d — sustained-humidity streak restarted after a "
                            "%.0fs observation gap (ceiling %ds); the %dm wait starts over",
                            pid,
                            ams_id,
                            _now - _above["last"],
                            _gap_ceiling,
                            sustained_minutes,
                        )
                        self._auto_dry_above[unit_key] = {"since": _now, "last": _now}
                    else:
                        _above["last"] = _now
                else:
                    self._auto_dry_above.pop(unit_key, None)

                if unit_state is not None:
                    if unit_state.get("suspended"):
                        logger.debug(
                            "Auto-drying: printer %d AMS %d skipped — suspended, %d cycles left humidity "
                            "above the %d%% threshold",
                            pid,
                            ams_id,
                            int(unit_state.get("unproductive", 0)),
                            humidity_threshold,
                        )
                        continue

                    if int(unit_state.get("unproductive", 0)) >= AUTO_DRY_MAX_UNPRODUCTIVE_CYCLES:
                        unit_state["suspended"] = True
                        logger.warning(
                            "Auto-drying: printer %d AMS %d — suspending automatic drying. %d cycles in a "
                            "row ended with humidity at %d%%, still above the %d%% threshold. The AMS reads "
                            "higher while it is warm, so a threshold in that range can never be reached and "
                            "re-arming would loop. Raise the threshold or dry the spools off the printer.",
                            pid,
                            ams_id,
                            int(unit_state.get("unproductive", 0)),
                            humidity,
                            humidity_threshold,
                        )
                        await self._notify_auto_drying_suspended(
                            db, printer, ams_id, humidity, humidity_threshold, int(unit_state.get("unproductive", 0))
                        )
                        continue

                    ended_at = unit_state.get("ended_at")
                    if (
                        isinstance(ended_at, float)
                        and _rt().time.monotonic() - ended_at < AUTO_DRY_REARM_COOLDOWN_SECONDS
                    ):
                        logger.debug(
                            "Auto-drying: printer %d AMS %d skipped — cooling off for %ds after the last "
                            "cycle before the humidity reading is worth acting on",
                            pid,
                            ams_id,
                            AUTO_DRY_REARM_COOLDOWN_SECONDS,
                        )
                        continue

                # Check cannot-dry reasons (power constraints etc.). Sits
                # ahead of the sustained wait so a unit the firmware refuses
                # to dry never logs a wait it was never going to cash in.
                sf_reasons = ams_data.get("dry_sf_reason", [])
                if sf_reasons:
                    logger.debug(
                        "Auto-drying: printer %d AMS %d skipped — cannot dry reasons: %s",
                        pid,
                        ams_id,
                        sf_reasons,
                    )
                    continue

                # Sustained-humidity wait (#2518): ambient-triggered starts
                # wait; only a printer with a scheduled queue item pending
                # keeps the instant behavior, because that drying has a real
                # deadline. Mid-print is deliberately NOT exempt while ambient
                # drying is on: a humidity start on a printer that happens to be
                # printing is as vulnerable to a lid-open spike as one on an idle
                # printer (proven live: a 2-point threshold crossing mid-print
                # bought a parked 12h command). Inactive when ambient drying is
                # off: print_drying then still starts mid-print cycles on its own
                # (#1816, "regardless of queue state"), and those stay instant.
                if sustained_wait_active and pid not in printers_with_scheduled:
                    _above = self._auto_dry_above.get(unit_key)
                    _waited = _rt().time.monotonic() - _above["since"] if _above else 0.0
                    if _waited < sustained_minutes * 60:
                        logger.debug(
                            "Auto-drying: printer %d AMS %d waiting — humidity %s%% above the %d%% "
                            "threshold for %.0fs of the required %dm",
                            pid,
                            ams_id,
                            humidity,
                            humidity_threshold,
                            _waited,
                            sustained_minutes,
                        )
                        continue

                # Get conservative drying params for mixed filaments
                params = self._get_conservative_drying_params(trays, module_type, presets)
                if not params:
                    logger.debug(
                        "Auto-drying: printer %d AMS %d skipped — no drying-eligible filaments in trays", pid, ams_id
                    )
                    continue

                temp, duration_hours, filament_type = params

                # Mid-print drying: cap drying temperature to protect spools (Bambu warns
                # "drying temperature must not exceed the filament's softening temperature"
                # for Print While Drying). Floor at 40 degC — below that the dryer is
                # ineffective and firmware will reject anyway.
                if mid_print:
                    temp = max(40, temp - 5)

                # Start drying
                logger.info(
                    "Auto-drying: printer %d AMS %d — humidity %d%% > threshold %d%%, "
                    "starting %s drying at %d°C for %dh%s",
                    pid,
                    ams_id,
                    humidity,
                    humidity_threshold,
                    filament_type,
                    temp,
                    duration_hours,
                    " (mid-print)" if mid_print else "",
                )
                success = _rt().printer_manager.send_drying_command(
                    pid, ams_id, temp, duration_hours, mode=1, filament=filament_type
                )
                if success:
                    self._drying_in_progress[pid] = _rt().time.monotonic()
                    armed = self._auto_dry_units.setdefault(
                        unit_key, {"unproductive": 0, "suspended": False, "ended_at": None}
                    )
                    armed["running"] = True

    async def _notify_auto_drying_suspended(
        self,
        db: AsyncSession,
        printer: Printer,
        ams_id: int,
        humidity: int,
        threshold: int,
        cycles: int,
    ) -> None:
        """Tell the user auto-drying has given up on one AMS unit (#2770).

        Fires once per suspension — the caller sets ``suspended`` before calling
        and every later pass short-circuits on it — because the whole point is
        that PrintLab has stopped acting. Somebody whose printer sits in another
        building needs that to reach them, and the hourly humidity alarm they
        are already getting says the opposite of what happened here.

        Never raises: a notification provider being down must not stop the
        suspension itself from taking effect.
        """
        ams_label = f"HT-{chr(65 + (ams_id - 128))}" if ams_id >= 128 else f"AMS-{chr(65 + ams_id)}"
        try:
            await _rt().notification_service.on_ams_drying_suspended(
                printer.id,
                printer.name,
                ams_label,
                float(humidity),
                float(threshold),
                cycles,
                db,
            )
        except Exception as e:
            logger.warning("Failed to send auto-drying suspended notification: %s", e)

    def forget_auto_dry_cycle(self, printer_id: int, ams_id: int) -> None:
        """Stop judging the drying cycle currently on this AMS unit (#2770).

        The unproductive-cycle counter exists to notice that *drying* is not
        moving the humidity reading. A cycle that ended because somebody sent a
        stop says nothing about that — it was cut short before it had a chance —
        so counting it would suspend auto-drying for a reason that has nothing to
        do with the loop the counter is there to break.

        Two callers, both of them a stop PrintLab is responsible for: the
        print-takes-priority stop below, and the manual Stop button. Left
        uncalled, an install that dries between queue jobs would suspend its own
        auto-drying after two prints interrupted a dry — exactly the install
        queue-drying exists for.

        The rest of the unit's history is kept: the cooldown before re-arming
        still applies, and an earlier count still stands.
        """
        state = self._auto_dry_units.get((printer_id, ams_id))
        if state is not None:
            state.pop("running", None)
            state["ended_at"] = _rt().time.monotonic()
        # A stopped cycle spends the streak that armed it, same as a completed
        # one (#2518).
        self._auto_dry_above.pop((printer_id, ams_id), None)

    def _sync_drying_state(self):
        """Drop printers from ``_drying_in_progress`` that are no longer drying.

        One direction only: it prunes, it never adds. A printer drying without an
        entry here — because the user started the cycle from Studio, the printer's
        screen or PrintLab's own manual Dry button, or because PrintLab restarted
        mid-cycle — stays unknown to the scheduler, so the "print takes priority"
        stop at ``check_queue`` only ever applies to cycles PrintLab itself began.

        That is deliberate for now rather than an oversight: populating this from
        telemetry would hand the scheduler authority to stop drying a user started
        by hand. It also means the backend-restart case this used to claim to
        handle is not handled.
        """
        to_remove = []
        for pid in self._drying_in_progress:
            state = _rt().printer_manager.get_status(pid)
            if not state:
                to_remove.append(pid)
                continue
            # Check if any AMS unit is still drying
            ams_list = state.raw_data.get("ams", [])
            any_drying = any(int(a.get("dry_time") or 0) > 0 for a in ams_list)
            if not any_drying:
                to_remove.append(pid)
        for pid in to_remove:
            self._drying_in_progress.pop(pid, None)

        # A printer that has gone away entirely takes its per-AMS auto-drying
        # history with it (#2770), so a printer deleted and re-added does not
        # inherit a suspension it never earned.
        for key in [k for k in self._auto_dry_units if _rt().printer_manager.get_status(k[0]) is None]:
            self._auto_dry_units.pop(key, None)
        # Same for sustained-wait streaks (#2518): a deleted-and-re-added
        # printer starts a fresh wait, and vanished printers do not leak
        # entries.
        for key in [k for k in self._auto_dry_above if _rt().printer_manager.get_status(k[0]) is None]:
            self._auto_dry_above.pop(key, None)

    @staticmethod
    def _drying_is_only_parked(printer_id: int) -> bool:
        """True when every AMS unit with a drying timer on this printer is parked.

        A parked timer (#2896: the command was taken but the countdown never
        runs) does not end on its own, so nothing may wait on it. False when no
        unit reports a timer yet -- a command just sent that the firmware has not
        reported back is real drying about to begin.
        """
        state = _rt().printer_manager.get_status(printer_id)
        units = [a for a in ((state.raw_data or {}).get("ams") or [] if state else []) if isinstance(a, dict)]
        timed = []
        for unit in units:
            try:
                if int(unit.get("dry_time") or 0) > 0:
                    timed.append(unit)
            except (TypeError, ValueError):
                continue
        return bool(timed) and all(is_countdown_parked(unit) for unit in timed)

    async def _drying_may_continue_through_print(self, db: AsyncSession, printer_id: int) -> bool:
        """True when a running cycle can be left alone while the next print runs.

        Some hardware dries happily through a print and #2758 settled that we
        should not tear those cycles down: the X2D there was refusing to
        *start* a job, which is a different problem, and stopping drying before
        every dispatch would throw away cycles the printer was content to run.
        Where the model cannot do it, or the user has not enabled it, the print
        takes priority and the cycle stops -- which is what the queue_drying_block
        setting has always promised in its off position.
        """
        if not await self._get_bool_setting(db, "print_drying_enabled"):
            return False
        status = _rt().printer_manager.get_status(printer_id)
        return supports_drying_while_printing(
            _rt().printer_manager.get_model(printer_id),
            status.firmware_version if status else None,
        )

    async def _stop_drying(self, printer_id: int):
        """Stop drying cycles PrintLab armed on a printer (print takes priority).

        Scoped to units in ``_auto_dry_units``. It used to send a stop to every
        AMS reporting ``dry_time > 0``, which meant one auto-dried unit was
        enough to kill a cycle the user had started by hand on a *different*
        unit of the same printer (#2801). That contradicted the contract
        ``_sync_drying_state`` already documents -- the entry gate deliberately
        only knows about cycles PrintLab began, so the action must not reach
        past them either.
        """
        state = _rt().printer_manager.get_status(printer_id)
        if not state:
            self._drying_in_progress.pop(printer_id, None)
            return

        ams_list = state.raw_data.get("ams", [])
        for ams_data in ams_list:
            dry_time = int(ams_data.get("dry_time") or 0)
            if dry_time > 0:
                ams_id = int(ams_data.get("id", 0))
                if (printer_id, ams_id) not in self._auto_dry_units:
                    logger.debug(
                        "Auto-drying: leaving printer %d AMS %d alone — not a cycle PrintLab started",
                        printer_id,
                        ams_id,
                    )
                    continue
                logger.info(
                    "Auto-drying: stopping drying on printer %d AMS %d — print takes priority",
                    printer_id,
                    ams_id,
                )
                _rt().printer_manager.send_drying_command(printer_id, ams_id, 0, 0, mode=0)
                self.forget_auto_dry_cycle(printer_id, ams_id)
        self._drying_in_progress.pop(printer_id, None)

    async def _check_scheduled_dryings(self, db: AsyncSession):
        """Dispatch due scheduled drying runs and track running ones."""
        now = utcnow_naive()

        # Hourly, not every pass: see SCHEDULED_DRYING_PRUNE_INTERVAL_SECONDS.
        # Monotonic, so a clock adjustment cannot park the prune for hours.
        since_prune = _rt().time.monotonic()
        if (
            self._last_scheduled_drying_prune is None
            or since_prune - self._last_scheduled_drying_prune >= SCHEDULED_DRYING_PRUNE_INTERVAL_SECONDS
        ):
            self._last_scheduled_drying_prune = since_prune
            await db.execute(
                delete(ScheduledDrying).where(
                    ScheduledDrying.status.in_(("completed", "cancelled", "failed")),
                    ScheduledDrying.completed_at.is_not(None),
                    ScheduledDrying.completed_at < now - timedelta(days=SCHEDULED_DRYING_RETENTION_DAYS),
                )
            )

        # Same order as the list route: with two rows due on one printer the
        # earliest scheduled wins rather than whatever the DB hands back first.
        result = await db.execute(
            select(ScheduledDrying)
            .where(ScheduledDrying.status.in_(("pending", "running")))
            .order_by(ScheduledDrying.start_after.asc().nullsfirst(), ScheduledDrying.id.asc())
        )
        rows = list(result.scalars().all())

        # Rebuild from the DB every tick so route-side cancels and completions
        # show up. Auto-drying's stop-all branches check this set before
        # stopping anything (#2638).
        # Kept from the previous pass so a run that ended between passes — a
        # cancel through the route, say — can still be released below.
        previously_running = self._scheduled_drying_printer_ids
        self._scheduled_drying_printer_ids = {row.printer_id for row in rows if row.status == "running"}
        running_printer_ids = set(self._scheduled_drying_printer_ids)

        # Model and firmware come from the printer row, not the live state.
        printer_ids = {row.printer_id for row in rows}
        printers_by_id: dict[int, Printer] = {}
        if printer_ids:
            printer_rows = await db.execute(select(Printer).where(Printer.id.in_(printer_ids)))
            printers_by_id = {p.id: p for p in printer_rows.scalars()}

        for row in rows:
            if row.status == "running":
                self._update_running_scheduled_drying(row, now)
                continue

            if row.start_after is not None and row.start_after > now:
                continue

            state = _rt().printer_manager.get_status(row.printer_id)
            if not state:
                row.waiting_reason = "printer_offline"
                continue

            # Same preflight the immediate endpoint runs. Without it the publish
            # succeeds, the row goes to running, the printer ignores the command
            # and the run silently cancels itself after the grace window.
            printer = printers_by_id.get(row.printer_id)
            unsupported = drying_preflight.check_drying_supported(
                printer.model if printer else None, state.firmware_version
            )
            if unsupported:
                row.status = "failed"
                row.error_message = unsupported
                row.error_code = drying_preflight.DETAIL_CODES.get(unsupported)
                row.completed_at = now
                logger.warning("Scheduled drying %d: %s", row.id, unsupported)
                continue

            if (
                self._drying_in_progress.get(row.printer_id) and not self._drying_is_only_parked(row.printer_id)
            ) or row.printer_id in running_printer_ids:
                row.waiting_reason = "already_drying"
                continue
            if not self._is_printer_idle(row.printer_id, require_plate_clear=False):
                row.waiting_reason = "printer_busy"
                continue

            target = drying_preflight.find_ams_unit(state, row.ams_id)
            if target is None:
                row.waiting_reason = "ams_not_found"
                continue
            blocking = drying_preflight.blocking_reason_codes(target)
            if blocking:
                # Keep the power case distinct; it needs the user to act, so the
                # card can say so instead of waiting silently.
                row.waiting_reason = drying_preflight.waiting_reason_for_codes(blocking)
                continue

            filament = drying_preflight.resolve_filament(target, row.filament)
            logger.info(
                "Scheduled drying %d: starting on printer %d AMS %d at %d°C for %dh",
                row.id,
                row.printer_id,
                row.ams_id,
                row.temp,
                row.duration_hours,
            )
            success = _rt().printer_manager.send_drying_command(
                row.printer_id,
                row.ams_id,
                row.temp,
                row.duration_hours,
                mode=1,
                filament=filament,
                rotate_tray=row.rotate_tray,
            )
            if success:
                row.status = "running"
                row.started_at = now
                row.waiting_reason = None
                row.filament = filament
                self._drying_in_progress[row.printer_id] = _rt().time.monotonic()
                self._scheduled_drying_printer_ids.add(row.printer_id)
                running_printer_ids.add(row.printer_id)
            else:
                row.waiting_reason = "printer_offline"

        # Release the printers whose run has ended. `_drying_in_progress` is
        # shared with auto-drying, which prunes it in `_sync_drying_state()` —
        # but that call sits behind the auto-drying enabled check, and this
        # method is the one writer that runs whether auto-drying is on or not.
        # With it off, nothing would ever drop the entry short of a print being
        # dispatched to the same printer, so the next scheduled run would wait
        # on "already_drying" forever and `queue_drying_block` would hold the
        # printer's prints too. Covers a run that ended during this pass and one
        # cancelled through the route between passes.
        self._scheduled_drying_printer_ids = {row.printer_id for row in rows if row.status == "running"}
        for printer_id in (previously_running | running_printer_ids) - self._scheduled_drying_printer_ids:
            self._drying_in_progress.pop(printer_id, None)

        await db.commit()

    def _update_running_scheduled_drying(self, row: ScheduledDrying, now: _rt().datetime):
        """Detect completion or interruption of a running scheduled drying.

        The firmware reports remaining minutes in ams.dry_time; 0 means not
        drying. Within the grace window after start we ignore dry_time==0
        (the status lags the command). After that, dry_time==0 near the end
        of the configured duration means completed. Much earlier means the
        run was stopped: re-queue it if a print preempted the dryer, but a
        stop while the printer is idle was deliberate, so cancel the row
        rather than restart drying the user just stopped.
        """
        if row.started_at is None:
            row.started_at = now
            return
        elapsed = (now - row.started_at).total_seconds()
        if elapsed < self.SCHEDULED_DRYING_GRACE_SECONDS:
            return

        state = _rt().printer_manager.get_status(row.printer_id)
        if not state:
            return  # offline mid-dry; resolve when it reconnects

        # find_ams_unit, not a local lookup: this runs inside check_queue, so a
        # throw on a malformed id would cost the whole pass including print
        # dispatch, every tick.
        target = drying_preflight.find_ams_unit(state, row.ams_id)
        try:
            dry_time = int(target.get("dry_time") or 0) if target else 0
        except (TypeError, ValueError):
            dry_time = 0
        if dry_time > 0 and is_countdown_parked(target):
            # The printer took the command but the countdown is not running
            # (#2896) and will never reach 0, so the run would stay "running"
            # forever. A print in progress is the likely cause (the power budget
            # is spent), so re-queue it like any interruption; the next start
            # waits for the printer to be idle. Parked on an idle printer is a
            # refusal, not something a retry fixes. The timer itself is left on
            # the printer: it may yet start once power frees up.
            if not self._is_printer_idle(row.printer_id, require_plate_clear=False):
                logger.info(
                    "Scheduled drying %d: AMS %d countdown is not running during a print; re-queued",
                    row.id,
                    row.ams_id,
                )
                row.status = "pending"
                row.started_at = None
                row.waiting_reason = "interrupted"
            else:
                logger.warning(
                    "Scheduled drying %d: printer accepted the command but AMS %d never started drying",
                    row.id,
                    row.ams_id,
                )
                row.status = "failed"
                row.error_message = drying_preflight.DID_NOT_START_DETAIL
                row.error_code = drying_preflight.DETAIL_CODES[drying_preflight.DID_NOT_START_DETAIL]
                row.completed_at = now
            return
        if dry_time > 0:
            return

        if elapsed >= row.duration_hours * 3600 * self.SCHEDULED_DRYING_COMPLETE_FRACTION:
            row.status = "completed"
            row.completed_at = now
        elif not self._is_printer_idle(row.printer_id, require_plate_clear=False):
            row.status = "pending"
            row.started_at = None
            row.waiting_reason = "interrupted"
        else:
            row.status = "cancelled"
            row.completed_at = now
