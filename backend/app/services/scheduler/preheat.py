"""Vorheizen, Warmhalten und Kammer-Abkühlung des Druckplaners.

Aus ``print_scheduler.py`` ausgelagert: die Methoden hängen an der Kammer-
temperatur und am Bett, nicht an der Warteschlange. ``PrintScheduler``
erbt sie über :class:`PreheatMixin`; Aufrufer sehen keinen Unterschied.
"""

import asyncio
import importlib
import json
import logging
from collections import deque

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.services.printer_manager import (
    supports_airduct,
    supports_chamber_heater,
    supports_chamber_temp,
)
from backend.app.services.scheduler.chamber import (
    _AIRDUCT_MODE_COOLING,
    _AIRDUCT_MODE_HEATING,
    _CHAMBER_DIP_GRACE_SECONDS,
    _CHAMBER_SAMPLE_MAX_GAP_SECONDS,
    _KEEP_WARM_MAX_MINUTES_DEFAULT,
    _PREHEAT_CANCEL_CHECK_SECONDS,
    _KeepWarmEntry,
)
from backend.app.services.scheduler.filament import (
    _EXTERNAL_TRAY_ID_MIN,
    _global_tray_id,
    _int_or,
    _used_global_tray_ids,
)

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen.

    Die Methoden sind hierher gewandert, die Tests patchen aber weiterhin die
    Namen im Modul ``print_scheduler`` (etwa ``printer_manager`` oder ``time``).
    Über das Modul aufgelöst statt über eigene Importe gilt beides zugleich:
    der austauschbare Name aus dem Test und der Produktionspfad.
    """
    return importlib.import_module("backend.app.services.print_scheduler")


class PreheatMixin:
    """Methoden für Vorheizen, Warmhalten und Kammer-Abkühlung."""

    @classmethod
    def _bundled_preheat_targets(cls) -> dict[str, int]:
        """The bundled map under the same key casing a parsed one gets.

        The constant is declared with a lowercase ``default`` because that is
        the key the Settings editor writes and displays. Every read of the map
        happens after ``str(key).upper()``, so handing the constant back as
        declared broke the contract the parser documents: an install that had
        never touched the setting returned a dict with no ``DEFAULT`` in it,
        and the resolution loop's fallback silently found nothing. It read the
        right number only because the bundled default happens to be 0 -- change
        that constant and every unconfigured install would keep preheating to
        zero with no way to tell why.
        """
        return {key.upper(): value for key, value in cls.DEFAULT_PREHEAT_FILAMENT_TARGETS.items()}

    async def _get_preheat_filament_targets(self, db: AsyncSession) -> dict[str, int]:
        """Parse the user-configured filament→chamber-target map, falling back
        to DEFAULT_PREHEAT_FILAMENT_TARGETS on missing / malformed JSON. Keys
        are uppercased and the 'default' fallback is always present in the
        returned dict so the resolution loop can index it unconditionally."""
        raw = await self._get_setting(db, "preheat_filament_targets")
        if not raw:
            return self._bundled_preheat_targets()
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("not an object")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("preheat_filament_targets unparseable, using defaults: %s", exc)
            return self._bundled_preheat_targets()
        # Coerce values to int; drop unparseable rows so a stray string
        # doesn't crash the loop.
        out: dict[str, int] = {}
        for key, value in parsed.items():
            try:
                out[str(key).upper()] = int(value)
            except (TypeError, ValueError):
                continue
        if "DEFAULT" not in out:
            out["DEFAULT"] = self.DEFAULT_PREHEAT_FILAMENT_TARGETS["default"]
        return out

    @staticmethod
    def _normalize_filament_type(tray_type: str) -> str:
        """Reduce the printer's tray_type to a preset-lookup key. Mirrors the
        existing drying-preset normalisation (split-at-space, upper-case) so
        the two maps share vocabulary — "PLA Basic" → "PLA", "PA-CF" stays
        "PA-CF" (no space to split on).

        This is the first stage of ``_resolve_filament_key``, which goes on to
        drop the suffix and consult the alias map; on its own it only decides
        what the tray is called, not which row answers for it.

        Indexing the split rather than testing the input: a tray_type of spaces
        is truthy and splits to nothing, so the old ``if tray_type`` guard let
        it through to an IndexError.
        """
        words = (tray_type or "").split()
        return words[0].upper() if words else ""

    def _target_for_tray_type(self, tray_type: str | None, targets: dict[str, int]) -> int:
        """Per-filament chamber target for one tray's reported type, or 0 when
        the tray is empty / RFID-less and reports no type at all.

        A filled or foamed variant wants its base material's chamber when the
        map has no row of its own: ASA-GF is ASA and needs ASA's 45 degrees,
        not the 0 an unknown type falls to. The specific type is still tried
        first, so PETG-CF and PA-CF keep the hotter rows they are listed with
        (#2902).

        That lookup is now the shared one, which adds the polyamide aliases on
        top of the suffix it already dropped -- so PA6-CF reaches PA's row here
        too, rather than the catch-all it was landing on (#3067).
        """
        if not self._normalize_filament_type(tray_type or ""):
            return 0
        key = self._resolve_filament_key(tray_type, targets)
        if key is not None:
            return targets[key]
        # A type the map does not list at all, which is not the same as a tray
        # with nothing in it -- that already returned 0 above.
        return targets.get("DEFAULT", 0)

    def _derive_chamber_target(
        self,
        printer: Printer,
        targets: dict[str, int],
        item: PrintQueueItem | None = None,
    ) -> int:
        """Chamber target for the trays this print actually loads: the max of
        their per-filament targets. Returns 0 when there is nothing to read (no
        status, no AMS telemetry — e.g. external-spool prints) or when every
        tray considered maps to 0, and the chamber phase then short-circuits in
        the main loop.

        ``item`` narrows the scan to the trays named in its ``ams_mapping``.
        Scanning the whole unit instead meant one ASA spool parked in the AMS
        forced a 45°C chamber onto every PLA job sharing it — the full max-wait
        plus soak burned ahead of each upload, on a printer whose chamber never
        reaches the target anyway (#2886). An item with no usable mapping falls
        back to scanning every loaded tray: that is the only signal left, and
        narrowing to nothing would skip preheat on prints that genuinely need
        it.

        Reads from `_rt().printer_manager.get_status(...).raw_data['ams']`, which is
        the same source the dispatcher uses for AMS slot mapping. Empty / RFID-
        less slots have empty `tray_type` and contribute nothing. The external
        spool is consulted only when the mapping names it (>= 254); it stays
        out of the unnarrowed scan, so an item without a mapping derives from
        the AMS alone exactly as before.
        """
        state = _rt().printer_manager.get_status(printer.id)
        if state is None:
            return 0
        raw_data = state.raw_data or {}
        used = _used_global_tray_ids(item)
        ams_list = raw_data.get("ams")
        # Older Bambu firmware nests AMS as {"ams": {"ams": [...]}} — try both.
        if isinstance(ams_list, dict):
            ams_list = ams_list.get("ams") or []
        if not isinstance(ams_list, list):
            ams_list = []
        best = 0
        for ams in ams_list:
            if not isinstance(ams, dict):
                continue
            ams_id = _int_or(ams.get("id"), 0)
            for tray in ams.get("tray") or []:
                # A non-dict entry has never been seen from real firmware, but
                # `.get` on one raises, and nothing between here and
                # `_dispatch_one`'s try/finally catches it — the item would be
                # left holding its dispatch claim. Preheat is best-effort by
                # contract, so step over it instead.
                if not isinstance(tray, dict):
                    continue
                if used is not None and _global_tray_id(ams_id, _int_or(tray.get("id"), 0)) not in used:
                    continue
                best = max(best, self._target_for_tray_type(tray.get("tray_type"), targets))
        if used is not None and any(t >= _EXTERNAL_TRAY_ID_MIN for t in used):
            for vt in raw_data.get("vt_tray") or []:
                if not isinstance(vt, dict):
                    continue
                # `_build_loaded_filaments` addresses external feeds by the id
                # the firmware reports — 255 main, 254 deputy — defaulting to
                # 254 when the field is absent. Same expression here so the two
                # agree on which entry a mapping's 254/255 refers to.
                if _int_or(vt.get("id"), _EXTERNAL_TRAY_ID_MIN) not in used:
                    continue
                best = max(best, self._target_for_tray_type(vt.get("tray_type"), targets))
        return best

    def _release_keep_warm(self, pid: int) -> None:
        """Release keep-warm on a printer that left the candidate set.

        Publishes ``set_bed_temperature(0)`` once — but only if firmware still
        reports the target we set (``entry.held_target``), so a user or
        subsequent print that changed the bed target since is not clobbered.
        Best-effort, never raises.

        The entry is kept, not dropped, when the printer cannot be reached
        right now: a printer that is briefly offline still has a hot bed, and
        holding the entry is what keeps the max-duration timeout applying and
        lets a later tick retry the release. Only a printer that has left the
        manager entirely gives up on that, in ``_sample_chamber_temps``.
        """
        entry = self._keep_warm.get(pid)
        if entry is None:
            return
        state = _rt().printer_manager.get_status(pid)
        client = _rt().printer_manager.get_client(pid)
        if state is None or client is None:
            logger.debug(
                "Queue: keep-warm release for printer %d deferred — printer unreachable, entry kept",
                pid,
            )
            return
        cur_bed_target = float((state.temperatures or {}).get("bed_target", 0) or 0)
        if int(cur_bed_target) != entry.held_target:
            # Someone else owns the bed now, so there is nothing of ours to
            # undo and nothing left to track.
            logger.info(
                "Queue: keep-warm release for printer %d skipped bed-off (firmware target %d != held %d)",
                pid,
                int(cur_bed_target),
                entry.held_target,
            )
            self._keep_warm.pop(pid, None)
            return
        try:
            client.set_bed_temperature(0)
            logger.info("Queue: keep-warm released for printer %d (bed → 0)", pid)
            self._keep_warm.pop(pid, None)
        except Exception as exc:
            # Keep the entry so the next tick tries again rather than leaving
            # the bed hot with nothing tracking it.
            logger.warning("Queue: keep-warm release for printer %d failed: %s", pid, exc)

    def _sweep_keep_warm(self, active_candidates: set[int], dispatched: set[int]) -> None:
        """Release printers that dropped out of the keep-warm candidate set.

        Called from ``_apply_keep_warm`` on every tick (with the current
        candidate set), and from ``check_queue``'s no-pending-items early
        return (with an empty candidate set) so orphaned holds still get
        released when the queue empties. Also called with an empty candidate
        set when any of the three gate settings toggles off, so a printer
        whose feature was disabled mid-hold gets its bed released.

        Printers being dispatched this tick are excluded from the bed-off
        publish: ``_preheat_and_soak`` owns the bed from that tick on, so a
        transient 0 in between would just churn against preheat. Ownership of
        the hot bed transfers to the preheat rollback pin instead — if the
        dispatch aborts before the print starts (failed upload, cancelled
        item), `_rollback_preheat_pin` turns the bed off; if preheat itself
        skips (e.g. the item has no bed_temperature metadata) the pin entry
        is the ONLY thing standing between an aborted dispatch and a bed
        left hot with no owner. A successful print start clears the pin and
        the print's own gcode takes over, as usual.
        """
        for _pid in list(self._keep_warm):
            if _pid in active_candidates:
                continue
            if _pid in dispatched:
                handed_over = self._keep_warm.pop(_pid, None)
                self._preheat_pin.setdefault(_pid, set()).add("bed")
                if handed_over is not None:
                    self._preheat_pin_bed[_pid] = handed_over.held_target
                continue
            self._release_keep_warm(_pid)

    async def _apply_keep_warm(
        self,
        db: AsyncSession,
        items: list[PrintQueueItem],
        dispatch_ids: list[int] | set[int],
        busy_printers: set[int],
        require_plate_clear: bool,
    ) -> None:
        """Hold the bed warm on FINISH printers whose next queued item needs chamber heat.

        When a printer just finished a job (FINISH state) and the next queued
        item needs chamber heating, hold the bed hot so the chamber stays warm
        during the bed-clearing window. The bed is the chamber's heating
        element here, not a print surface — nothing is printing during the
        hold and the dispatched print's own preheat/gcode re-targets the bed —
        so the hold temperature is ``queue_keep_warm_bed_temp`` (default 90°C,
        chosen to sustain chamber warmth and to satisfy bed-threshold-linked
        aftermarket chamber heaters), raised to the item's own parsed
        bed_temperature when that is higher. Items whose archive metadata has
        no bed temperature (e.g. OrcaSlicer gcode.3mf exports) therefore still
        get a hold — chamber need is what gates the feature, not metadata.
        Skips entirely for filaments that map to a 0°C chamber target
        (PLA, PETG, etc.) — read off the trays the next item's ``ams_mapping``
        names, so a hot-chamber spool it never touches does not hold the bed of
        a PLA job (#2886). An item still awaiting its mapping is judged on the
        whole unit, as every item was before. Printers being dispatched this
        cycle are excluded:
        ``_preheat_and_soak`` already handles their bed temperature.

        Bounded by ``queue_keep_warm_max_minutes`` — on timeout the bed is
        released to 0 and the entry is latched ``expired=True`` so
        subsequent ticks neither re-engage nor re-seed the clock. Idempotent
        MQTT: publish is skipped when firmware already has the target.

        The release sweep runs BEFORE the engagement gate so a printer that
        was owned by keep-warm still gets its bed released when any of the
        three gate settings is toggled off mid-hold. The
        ``check_queue`` early-return-when-no-items path also calls
        ``_sweep_keep_warm`` directly to release orphaned holds.
        """
        dispatch_set = set(dispatch_ids)
        dispatched_printers = {it.printer_id for it in items if it.id in dispatch_set and it.printer_id}
        pending_printer_ids = {it.printer_id for it in items if it.printer_id}
        warm_candidates = (pending_printer_ids & busy_printers) - dispatched_printers

        keep_warm_enabled = await self._get_bool_setting(db, "queue_keep_bed_warm", default=False)
        preheat_on = await self._get_bool_setting(db, "preheat_enabled", default=False)
        gate_open = keep_warm_enabled and require_plate_clear and preheat_on

        # Release sweep first — must run even when gate_open is False so a
        # printer owned by keep-warm when a gate toggles off gets released.
        self._sweep_keep_warm(
            active_candidates=warm_candidates if gate_open else set(),
            dispatched=dispatched_printers,
        )

        if not gate_open:
            return

        hold_temp = await self._get_int_setting(db, "queue_keep_warm_bed_temp", default=90)
        max_hold_seconds = (
            await self._get_int_setting(db, "queue_keep_warm_max_minutes", default=_KEEP_WARM_MAX_MINUTES_DEFAULT) * 60
        )
        now_mono = _rt().time.monotonic()
        filament_targets: dict[str, int] | None = None
        for pid in warm_candidates:
            entry = self._keep_warm.get(pid)
            # Latched-expired: max-duration timeout already fired for this
            # printer. Skip until the release sweep drops the entry (i.e.
            # until the printer leaves the candidate set).
            if entry is not None and entry.expired:
                continue
            # These two guards sit ahead of the max-duration check below, so an
            # engaged hold only ages out while its printer is still reachable
            # and still in FINISH. That is deliberate rather than a hole: with
            # no status or no client there is no M140 to send anyway, and the
            # elapsed check runs off `entry.started` so it fires on the first
            # tick after the printer comes back. Leaving FINISH means the plate
            # was cleared, which drops the printer out of `warm_candidates` and
            # hands it to `_release_keep_warm` instead. The invariant worth
            # preserving if this is ever reordered: every path out of an
            # engaged hold ends in a bed-off, whether by timeout or release.
            state = _rt().printer_manager.get_status(pid)
            if state is None or state.state != "FINISH":
                continue
            client = _rt().printer_manager.get_client(pid)
            if client is None:
                continue
            next_item = next((it for it in items if it.printer_id == pid), None)
            if next_item is None:
                continue
            # Hold temperature: the configured keep-warm temp, raised to the
            # item's own bed temp when the metadata reports a higher one. A
            # missing bed_temperature (Orca gcode.3mf exports parse without
            # one) does NOT skip the hold — chamber need gates the feature.
            archive = next_item.archive
            item_bed = int(archive.bed_temperature) if archive and archive.bed_temperature else 0
            bed_target = max(item_bed, hold_temp)
            if bed_target <= 0:
                continue
            explicit = getattr(next_item, "preheat_chamber_target_override", None)
            if explicit is not None:
                chamber_needed = int(explicit) > 0
            else:
                if filament_targets is None:
                    filament_targets = await self._get_preheat_filament_targets(db)
                printer_obj = await self._get_printer(db, pid)
                chamber_needed = (
                    printer_obj is not None
                    and self._derive_chamber_target(printer_obj, filament_targets, next_item) > 0
                )
            if not chamber_needed:
                continue

            # Seed the timer on first engagement; keep it on subsequent ticks
            # (never re-seed — that would defeat the max-duration cap).
            if entry is None:
                entry = _KeepWarmEntry(started=now_mono, held_target=bed_target)
                self._keep_warm[pid] = entry

            elapsed = now_mono - entry.started
            if elapsed > max_hold_seconds:
                # Timeout: publish bed → 0 once (if firmware still holds our
                # target) and latch expired. The entry stays until the release
                # sweep drops it, preventing the next tick from re-seeding.
                logger.warning(
                    "Queue: keep-warm timeout for printer %d (held for %.0fs) — publishing bed → 0",
                    pid,
                    elapsed,
                )
                cur_bed_target = float((state.temperatures or {}).get("bed_target", 0) or 0)
                if int(cur_bed_target) == entry.held_target:
                    try:
                        client.set_bed_temperature(0)
                    except Exception as exc:
                        logger.warning(
                            "Queue: keep-warm timeout bed-off failed for printer %d: %s",
                            pid,
                            exc,
                        )
                else:
                    logger.info(
                        "Queue: keep-warm timeout for printer %d skipped bed-off (firmware target %d != held %d)",
                        pid,
                        int(cur_bed_target),
                        entry.held_target,
                    )
                entry.expired = True
                continue

            # Idempotence: skip publish when firmware already has our target.
            cur_bed_target = float((state.temperatures or {}).get("bed_target", 0) or 0)
            if int(cur_bed_target) == bed_target:
                entry.held_target = bed_target
                continue
            try:
                client.set_bed_temperature(bed_target)
                entry.held_target = bed_target
                logger.info(
                    "Queue: keeping bed warm at %d°C for printer %d (FINISH, next item needs chamber heat)",
                    bed_target,
                    pid,
                )
            except Exception as exc:
                logger.warning("Queue: keep-warm bed command failed for printer %d: %s", pid, exc)

    def _sample_chamber_temps(self) -> None:
        """Record a chamber temperature sample for every connected printer.

        Called once per scheduler tick (every 3–30 s). Entries older than
        _chamber_history_ttl are pruned on each write so the deques stay bounded.
        Also evicts per-printer state whose printer_id is no longer registered
        (e.g. deleted from the DB), so nothing accumulates for gone printers.
        """
        now = _rt().time.monotonic()
        cutoff = now - self._chamber_history_ttl
        statuses = _rt().printer_manager.get_all_statuses()
        known_pids = set(statuses.keys())
        for pid, status in statuses.items():
            if status is None or not status.connected:
                continue
            temps = status.temperatures or {}
            chamber = temps.get("chamber")
            if chamber is None:
                continue
            hist = self._chamber_history.setdefault(pid, deque())
            hist.append((now, float(chamber)))
            while hist and hist[0][0] < cutoff:
                hist.popleft()
        # Evict state for printers that are no longer registered with the manager.
        # This is the one place a keep-warm entry is dropped without releasing
        # the bed: the printer is gone from the manager, so there is no client
        # left to send M140 to. `_release_keep_warm` deliberately keeps entries
        # for printers that are merely unreachable, which is what makes this
        # the terminal case rather than a silent leak.
        for pid in list(self._chamber_history):
            if pid not in known_pids:
                self._chamber_history.pop(pid, None)
        for pid in list(self._keep_warm):
            if pid not in known_pids:
                logger.info(
                    "Queue: dropping keep-warm state for printer %d — no longer registered",
                    pid,
                )
                self._keep_warm.pop(pid, None)
        for pid in list(self._preheat_pin):
            if pid not in known_pids:
                self._preheat_pin.pop(pid, None)
                self._preheat_pin_bed.pop(pid, None)

    def _chamber_soak_remaining(
        self,
        printer_id: int,
        chamber_target: float,
        soak_seconds: int,
        tolerance: float = 2.0,
    ) -> int:
        """Return how many seconds of soak time are still needed.

        Credits the time the chamber has already spent at temperature against
        the configured soak. The credit may not start earlier than any of:

        * **The newest sample.** Nothing recent means the printer stopped
          reporting mid-observation and the chamber may have cooled unseen, so
          the full soak is required. (A 2 h history whose last reading is half
          an hour old is not evidence of anything — the measured cooling rate
          is fast enough to cross the threshold in that time.)
        * **The most recent contiguous run of samples.** A gap wider than
          ``_CHAMBER_SAMPLE_MAX_GAP_SECONDS`` is a disconnect, and time on its
          far side is not evidence of temperature.
        * **The end of the most recent real dip below the threshold.**

        A dip only counts as real once it lasts ``_CHAMBER_DIP_GRACE_SECONDS``
        — see that constant for the thermal reasoning. A stray low reading is
        an artifact, and treating it as cooling would discard a soak that
        actually happened.

        Returns ``soak_seconds`` when nothing can be credited (no history,
        stale history, or the chamber is below the threshold right now) and 0
        once the credited time covers the whole soak.
        """
        hist = self._chamber_history.get(printer_id)
        if not hist:
            return soak_seconds

        now = _rt().time.monotonic()
        newest_ts, newest_temp = hist[-1]
        if now - newest_ts > _CHAMBER_SAMPLE_MAX_GAP_SECONDS:
            return soak_seconds  # stale — no fresh evidence to credit

        threshold = chamber_target - tolerance
        if newest_temp < threshold:
            return soak_seconds  # below target right now; nothing is soaked

        samples = list(hist)

        # Earliest point we have unbroken observations for.
        credit_from = samples[-1][0]
        for i in range(len(samples) - 1, 0, -1):
            if samples[i][0] - samples[i - 1][0] > _CHAMBER_SAMPLE_MAX_GAP_SECONDS:
                break
            credit_from = samples[i - 1][0]

        # Pull the credit forward to the end of the last significant dip. Each
        # excursion is measured between the in-range readings that bracket it,
        # so a lone stray sample is charged one sampling interval rather than
        # zero, and the comparison errs towards calling a dip real.
        i = 0
        while i < len(samples):
            if samples[i][1] >= threshold:
                i += 1
                continue
            j = i
            while j < len(samples) and samples[j][1] < threshold:
                j += 1
            # `newest_temp >= threshold` was checked above, so j is in range.
            opened_at = samples[i - 1][0] if i > 0 else samples[i][0]
            if samples[j][0] - opened_at >= _CHAMBER_DIP_GRACE_SECONDS:
                # Credit resumes at the last below-threshold sample rather than
                # the first good one after it, so a recovered dip over-credits
                # by up to one sampling interval — the opposite lean to the
                # bracketing above. Both are bounded by the sample cadence and
                # dwarfed by the grace period, so neither is worth the extra
                # arithmetic to remove.
                credit_from = max(credit_from, samples[j - 1][0])
            i = j

        return max(0, soak_seconds - int(now - credit_from))

    async def _preheat_sleep(self, item_id: int, seconds: float) -> bool:
        """Sleep in slices, returning False as soon as the item stops wanting preheat.

        A single long ``asyncio.sleep`` cannot notice a cancellation that lands
        while it is parked, so the wait is chopped into
        ``_PREHEAT_CANCEL_CHECK_SECONDS`` slices with a check after each.
        """
        remaining = float(seconds)
        while remaining > 0:
            slice_secs = min(_PREHEAT_CANCEL_CHECK_SECONDS, remaining)
            await asyncio.sleep(slice_secs)
            remaining -= slice_secs
            if item_id in self._cancelled_dispatches:
                return False
        return True

    def _preheat_flap_to_cooling(self, item_id: int, printer: Printer) -> None:
        """Put the airduct flap back to cooling for a print that wants no chamber heat.

        The full preheat stage does this as part of its own dispatch: an H2D
        left in heating mode by the ABS job before it would otherwise cook the
        PLA that follows. The skip path never reaches that code, so it calls
        this instead -- one idempotent MQTT command, no waiting, and nothing to
        add to the rollback pin, because a flap set to cooling for a print that
        needs no heat is where it should have been either way.

        Best-effort like everything else in the stage: a refused command logs
        and the dispatch carries on.
        """
        model = printer.model or ""
        if not supports_airduct(model):
            return
        state = _rt().printer_manager.get_status(printer.id)
        current = getattr(state, "airduct_mode", None) if state else None
        if current == _AIRDUCT_MODE_COOLING:
            return
        client = _rt().printer_manager.get_client(printer.id)
        if client is None:
            return
        try:
            client.set_airduct_mode("cooling")
        except Exception as exc:
            logger.warning("Queue item %s: preheat-skip airduct cooling failed: %s", item_id, exc)

    async def _preheat_and_soak(
        self,
        db: AsyncSession,
        item: PrintQueueItem,
        printer: Printer,
        archive: PrintArchive | None,
    ) -> bool:
        """Run the per-printer preheat + heat-soak stage before FTP upload (#1468).

        Returns True when the dispatch should carry on to the upload — including
        every case where preheat is skipped, since a skipped preheat is not a
        reason to abandon the print. Returns False only when the item stopped
        wanting to be printed while the stage was waiting (cancelled or
        deleted); the caller must then abandon the dispatch, and
        ``_dispatch_one``'s rollback shuts the heaters off on the way out.

        Resolution order:
          1. `item.preheat_override` — 'off' skips entirely; 'inherit' falls back
             to the global `preheat_enabled` setting; 'on' forces the stage on
             even if the global is off.
          2. Chamber target — `item.preheat_chamber_target_override` if non-null;
             else max of `preheat_filament_targets[normalize(t.tray_type)]`
             across the trays `item.ams_mapping` names (every loaded slot when
             it names none).
          3. A target of 0 off the filament map skips the whole stage: the
             materials this print loads want no chamber, so there is nothing to
             soak for and the bed phase would only delay the upload (#3041).
             An explicit 0 typed into the per-item override, or a per-item
             'on', still runs the bed phase and the soak — both are the user
             asking for a warm bed in so many words.
          4. Three hardware tiers branch the wait loop:
             - Chamber heater (H2C/H2D/H2DPro/H2S/X2D/X1E via supports_chamber_heater):
               send M141 to the resolved target, then wait for the chamber sensor
               to reach it (or the max-wait timeout to elapse).
             - Chamber sensor only (X1C/P2S via supports_chamber_temp ∧ ¬supports_chamber_heater):
               no M141; the bed is the only heat source, so we wait for the chamber
               sensor to rise via bed radiation OR fall through on timeout.
             - No chamber sensor (P1S/P1P/A1/A1 Mini): no way to verify chamber
               temperature; the function just heats the bed and holds for the
               configured soak duration.

        The bed target comes from the archive's parsed metadata
        (`bed_temperature`); if missing the preheat stage logs and returns
        without dispatching anything, rather than guessing at a default that
        might wreck filament setup.

        Failures are logged but never re-raised — preheat is best-effort. A
        printer that goes offline mid-soak, a refused gcode command, or a
        missing temperature reading must not turn into a failed queue item; the
        normal upload + start path runs immediately after this method returns.
        """
        override = (getattr(item, "preheat_override", None) or "inherit").lower()
        if override == "off":
            return True
        if override == "inherit":
            enabled = await self._get_bool_setting(db, "preheat_enabled", default=False)
            if not enabled:
                return True
        # override == "on" forces the stage on regardless of the global setting.

        max_wait = await self._get_int_setting(db, "preheat_max_wait_seconds", default=900)
        soak_seconds = await self._get_int_setting(db, "preheat_soak_seconds", default=300)

        # Chamber target resolution:
        #   1. Explicit per-item override beats everything (user knows best).
        #   2. Otherwise derive from the filament types this print loads, via
        #      the per-filament target map. A PLA-only print derives 0 and the
        #      block below skips the stage without the user touching anything,
        #      even when an ASA spool is sitting in another slot of the same
        #      AMS (#2886).
        explicit_target = getattr(item, "preheat_chamber_target_override", None)
        if explicit_target is not None and explicit_target > 0:
            chamber_target = int(explicit_target)
            chamber_source = "item-override"
        elif explicit_target == 0:
            chamber_target = 0  # explicit 0 means "no chamber, even if filament wants it"
            chamber_source = "item-override-zero"
        else:
            targets = await self._get_preheat_filament_targets(db)
            chamber_target = self._derive_chamber_target(printer, targets, item)
            chamber_source = "filament-map"

        # Nothing to preheat *for*. A zero that came out of the filament map is
        # the map saying this print's materials want no chamber conditioning --
        # PLA, PETG, TPU and PVA all sit at 0 by default. Running the stage
        # anyway heated the bed and then held it for the full soak, which
        # delayed every PLA dispatch by minutes and bought nothing: the print's
        # own G-code sets the bed the moment it starts, so preheating it here
        # only moves that heating ahead of the upload instead of overlapping
        # with it, and the soak has no chamber to condition (#3041).
        #
        # An explicit statement from the user still runs the stage. Forcing the
        # per-item override to 'on', or typing a chamber target of exactly 0,
        # both mean "preheat the bed for this print" -- the second is
        # documented as doing precisely that. Only the automatic path, the
        # global toggle plus the filament map, short-circuits here.
        if chamber_target <= 0 and chamber_source == "filament-map" and override != "on":
            logger.info(
                "Queue item %s: preheat skipped -- the loaded filaments derive no chamber "
                "target, so there is nothing to soak for (override=%s model=%s)",
                item.id,
                override,
                printer.model or "",
            )
            self._preheat_flap_to_cooling(item.id, printer)
            return True

        bed_target = int(archive.bed_temperature) if archive and archive.bed_temperature else 0
        if bed_target <= 0:
            # No bed temperature in the slicer metadata. When the print needs a
            # hot chamber the bed is simply how we heat it, so fall back to the
            # configured chamber-heating bed temperature rather than skipping
            # the whole stage — otherwise the print starts with a cold chamber,
            # which is exactly what preheat exists to prevent. Without a chamber
            # requirement there is nothing to preheat *for*, so skip as before
            # rather than guess a bed temperature for the print itself.
            if chamber_target <= 0:
                logger.info(
                    "Queue item %s: preheat skipped — archive has no bed_temperature metadata and no chamber target",
                    item.id,
                )
                return True
            bed_target = await self._get_int_setting(db, "queue_keep_warm_bed_temp", default=90)
            logger.info(
                "Queue item %s: archive has no bed_temperature metadata — heating the bed to "
                "%d°C to drive the chamber to %d°C",
                item.id,
                bed_target,
                chamber_target,
            )

        client = _rt().printer_manager.get_client(printer.id)
        if client is None:
            logger.warning("Queue item %s: preheat skipped — printer client unavailable", item.id)
            return True

        model = printer.model or ""
        has_heater = supports_chamber_heater(model)
        has_sensor = supports_chamber_temp(model)
        do_chamber = chamber_target > 0 and (has_heater or has_sensor)

        # Fast path: if the chamber has been continuously above target for at
        # least soak_seconds and the bed is already at temperature, skip the
        # entire preheat stage. Typical case: keep-warm held the bed between
        # consecutive same-material prints and the chamber never dropped.
        if do_chamber and has_sensor and soak_seconds > 0:
            remaining = self._chamber_soak_remaining(printer.id, float(chamber_target), soak_seconds)
            if remaining == 0:
                cur = _rt().printer_manager.get_status(printer.id)
                if cur:
                    cur_temps = cur.temperatures or {}
                    if (
                        float(cur_temps.get("bed", 0) or 0) >= bed_target - 2.0
                        and float(cur_temps.get("chamber", 0) or 0) >= chamber_target - 2.0
                    ):
                        logger.info(
                            "Queue item %s: preheat skipped — chamber has been above %d°C for ≥%ds "
                            "and bed is already at temperature (chamber history fast-path)",
                            item.id,
                            chamber_target,
                            soak_seconds,
                        )
                        # Still set targets to prevent cooling during the 3MF upload window.
                        # Register each successful set in the preheat pin so `_dispatch_one`
                        # unwinds them on any non-success exit.
                        pin = self._preheat_pin.setdefault(printer.id, set())
                        try:
                            client.set_bed_temperature(bed_target)
                            pin.add("bed")
                            self._preheat_pin_bed[printer.id] = bed_target
                        except Exception as exc:
                            logger.warning("Queue item %s: fast-path bed M140 failed: %s", item.id, exc)
                        if supports_airduct(model):
                            cur_airduct = getattr(cur, "airduct_mode", None)
                            if cur_airduct != _AIRDUCT_MODE_HEATING:
                                try:
                                    client.set_airduct_mode("heating")
                                    # Only undo what we can see we replaced. `None`
                                    # means no mode has been observed yet, and
                                    # rolling that back to cooling would assert a
                                    # state the printer never reported.
                                    if cur_airduct == _AIRDUCT_MODE_COOLING:
                                        pin.add("airduct")
                                except Exception as exc:
                                    logger.warning("Queue item %s: fast-path airduct failed: %s", item.id, exc)
                        if has_heater:
                            try:
                                client.set_chamber_temperature(chamber_target)
                                pin.add("chamber")
                            except Exception as exc:
                                logger.warning("Queue item %s: fast-path chamber M141 failed: %s", item.id, exc)
                        return True

        logger.info(
            "Queue item %s: preheat starting — bed=%d°C chamber_target=%d°C (source=%s override=%s "
            "model=%s has_heater=%s has_sensor=%s) max_wait=%ds soak=%ds",
            item.id,
            bed_target,
            chamber_target if do_chamber else 0,
            chamber_source,
            override,
            model,
            has_heater,
            has_sensor,
            max_wait,
            soak_seconds,
        )

        # Preheat rollback registry: everything we set below is recorded here so
        # `_dispatch_one`'s finally clause can unwind the whole heating regime
        # (bed off, chamber off, airduct back to cooling) on any non-success
        # exit. Populated as each command succeeds; consumed and cleared by
        # `_dispatch_one`.
        pin = self._preheat_pin.setdefault(printer.id, set())

        # Dispatch heaters. set_bed_temperature / set_chamber_temperature already
        # cache the target locally so the polling reads below see consistent
        # state (firmware MQTT echoes lag by ~1s).
        try:
            client.set_bed_temperature(bed_target)
            pin.add("bed")
            self._preheat_pin_bed[printer.id] = bed_target
        except Exception as exc:
            logger.warning("Queue item %s: preheat bed M140 failed: %s", item.id, exc)
            return True

        # Airduct mode (#1468 follow-up). Models with the cooling/heating flap
        # (H2C/H2D/H2D Pro/H2S/X2D/P2S) keep the flap whatever the user last
        # left it on, regardless of M141. Default cooling actively vents the
        # chamber, so a `chamber_target > 0` print with the flap stuck in
        # cooling never converges — the heater fights the open exhaust. We
        # flip the flap BEFORE M141 to "heating" when the preheat wants
        # chamber heat, and back to "cooling" when it doesn't (PLA-only print
        # on an H2D that was previously running ABS would otherwise stay in
        # heating mode and overheat PLA). The current-state read keeps the
        # command idempotent — no MQTT chatter when the flap is already where
        # we want it.
        if supports_airduct(model):
            desired_airduct = "heating" if chamber_target > 0 else "cooling"
            desired_id = _AIRDUCT_MODE_HEATING if desired_airduct == "heating" else _AIRDUCT_MODE_COOLING
            current_state = _rt().printer_manager.get_status(printer.id)
            current_airduct = getattr(current_state, "airduct_mode", None) if current_state else None
            if current_airduct != desired_id:
                try:
                    client.set_airduct_mode(desired_airduct)
                    # As in the fast path: only pin a rollback for a flap we
                    # saw in cooling. `current_airduct` of None means no mode
                    # has been observed, so there is nothing to restore to.
                    if desired_airduct == "heating" and current_airduct == _AIRDUCT_MODE_COOLING:
                        pin.add("airduct")
                except Exception as exc:
                    logger.warning(
                        "Queue item %s: preheat airduct %s mode failed: %s",
                        item.id,
                        desired_airduct,
                        exc,
                    )

        if do_chamber and has_heater:
            try:
                client.set_chamber_temperature(chamber_target)
                pin.add("chamber")
            except Exception as exc:
                logger.warning("Queue item %s: preheat chamber M141 failed: %s", item.id, exc)

        # Release the pooled DB connection before the (potentially many-minute)
        # heat-soak wait below (#2572). Every setting this method needs is read
        # above; the wait/soak loop only polls printer_manager state and sleeps —
        # it never touches the DB. Without this the caller's transaction sat
        # "idle in transaction" for the whole soak, pinning one pooled connection
        # per preheating printer. expire_on_commit=False keeps item/printer
        # readable afterwards; there are no pending writes to lose here.
        await db.commit()

        # Wait for convergence. Bed warm-up is fast (~5 min from cold); chamber
        # via M141 takes a few minutes; chamber via bed radiation can take 20+.
        # Poll every 3s — frequent enough for responsive logging without
        # spamming the MQTT state stream. The "converged" predicate is:
        #   bed reached target (within 2°C tolerance for floating-point + heater hysteresis),
        #   AND
        #   chamber phase satisfied (no chamber phase, no sensor, or sensor reached target).
        BED_TOLERANCE = 2.0
        CHAMBER_TOLERANCE = 2.0
        POLL_INTERVAL = 3.0
        deadline = asyncio.get_event_loop().time() + max_wait

        while True:
            state = _rt().printer_manager.get_status(printer.id)
            if state is None:
                logger.warning("Queue item %s: preheat lost state during wait", item.id)
                break

            temps = state.temperatures or {}
            bed_now = float(temps.get("bed", 0) or 0)
            chamber_now = float(temps.get("chamber", 0) or 0)
            bed_ok = bed_now >= bed_target - BED_TOLERANCE

            if not do_chamber:
                chamber_ok = True  # phase disabled or model has neither sensor nor heater
            elif not has_sensor:
                chamber_ok = True  # P1S etc — can't read, rely on soak timer only
            else:
                chamber_ok = chamber_now >= chamber_target - CHAMBER_TOLERANCE

            if bed_ok and chamber_ok:
                logger.info(
                    "Queue item %s: preheat target reached (bed=%.1f chamber=%.1f) — entering soak",
                    item.id,
                    bed_now,
                    chamber_now,
                )
                break

            if asyncio.get_event_loop().time() >= deadline:
                logger.info(
                    "Queue item %s: preheat max_wait reached (bed=%.1f/%d chamber=%.1f/%d) — falling through to soak",
                    item.id,
                    bed_now,
                    bed_target,
                    chamber_now,
                    chamber_target if do_chamber else 0,
                )
                break

            if not await self._preheat_sleep(item.id, POLL_INTERVAL):
                logger.info(
                    "Queue item %s: preheat aborted — item cancelled or deleted while waiting for temperature",
                    item.id,
                )
                return False

        if soak_seconds > 0:
            if do_chamber and has_sensor:
                remaining = self._chamber_soak_remaining(printer.id, float(chamber_target), soak_seconds)
            else:
                remaining = soak_seconds  # no sensor — can't verify history, run full soak
            if remaining > 0:
                logger.info(
                    "Queue item %s: preheat soak — holding for %ds (of %ds configured; chamber "
                    "has been above target for ~%ds already)",
                    item.id,
                    remaining,
                    soak_seconds,
                    soak_seconds - remaining,
                )
                if not await self._preheat_sleep(item.id, remaining):
                    logger.info(
                        "Queue item %s: preheat aborted — item cancelled or deleted during soak",
                        item.id,
                    )
                    return False
            else:
                logger.info(
                    "Queue item %s: preheat soak skipped — chamber has been above %d°C for ≥%ds",
                    item.id,
                    chamber_target,
                    soak_seconds,
                )

        logger.info("Queue item %s: preheat complete — proceeding to upload", item.id)
        return True
