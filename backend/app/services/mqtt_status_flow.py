"""MQTT-Status- und AMS-Abfluss von main.py ausgelagert.

Enthalten: ``on_printer_status_change`` (WebSocket-Stauvermeidung, Erkenntnis-
Kanten der Vermittlung, Meldungen bei Milestones und HMS-Fehlern, Kill-Schalter),
``on_fts_inlet_change`` (K-Profile auf den neuen Düsen-Slot umlenken) und
``on_ams_change`` (Spool-Synchronisation für Inventar und Spoolman samt
Auto-Zuweisung) samt ihren eigenen Zuständen und Helfern.

Namen, die die Wartungs-Tests im Modul ``main`` umlenken — Drucks
``printer_manager``, ``ws_manager``, ``mqtt_relay``, ``notification_service``,
``async_session``, ``time``, ``spawn_background_task``, ``printer_state_to_dict``,
``get_spoolman_client``, die Kill-Schalter-Helfer, die Übergrenz-Helfer
(reconcile/prime) und die K-Tabellen-Werkzeuge — greift dieses Modul über
:func:`_rt` ab. Die echten Dienst-Singletons (``kprofile_drift``,
``slot_unlink_grace``) und die Werkzeuge kommen direkt, denn niemand patcht sie
dort. ``except asyncio.CancelledError`` braucht die echte Klasse — die bleibt
importiert.
"""

import asyncio  # noqa: F401 — Annotationen und CancelledError brauchen die echte Klasse
import logging

from sqlalchemy import delete, select, text  # noqa: F401 — select bleibt in den Funktionskörpern

from backend.app.services import kprofile_drift, slot_unlink_grace
from backend.app.services.bambu_mqtt import PrinterState
from backend.app.services.slot_nozzle import (
    nozzle_diameter_for_extruder,
    nozzle_flow_for_extruder,
    resolve_slot_nozzle,
)
from backend.app.services.spool_filament_preset import printer_safe_filament_id
from backend.app.services.spool_linkage import _unlink_stale_assignments
from backend.app.services.spoolman import init_spoolman_client
from backend.app.utils.fts_routing import extruder_for_inlet

# Der Logger-Name bleibt der der alten Heimat, damit Protokollzeilen in den
# Support-Bundles unverändert unter ``backend.app.main`` auftauchen.
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen."""
    import importlib

    return importlib.import_module("backend.app.main")


# Connected-Edge-Vermittlung: einmal je Verbindung, plus die K-Primierung.
_printer_reconciled_since_connect: dict[int, bool] = {}
_printer_kprofiles_primed_since_connect: dict[int, bool] = {}

# Milestones der Meldungen (#3211) und die erste Schicht (#2702).
_last_progress_milestone: dict[int, int] = {}
_first_layer_notified: dict[int, bool] = {}

# Drucke, deren Stopp der Kill-Schalter schon losgeschickt hat.
_unauthorized_print_kill_sent: set[int] = set()

# HMS-Verfolgung (#1840, #2728): welche Fehler schon gemeldet sind und wie
# lange einer weg bleiben muss, bevor die Verfolgung vergisst.
_notified_hms_errors: dict[int, set[str]] = {}
_hms_last_seen: dict[int, float] = {}
_HMS_CLEAR_GRACE_SECONDS = 30.0

# Offline-Meldung (#1752): Rand, Auflauf und Meldungsaufgänge je Drucker.
_printer_last_connected: dict[int, bool] = {}
_printer_offline_notify_tasks: dict[int, asyncio.Task] = {}
_PRINTER_OFFLINE_NOTIFY_DEBOUNCE_SECONDS = 5

# Per-printer lock that serialises the spool-assignment side of on_ams_change
# (auto-unlink stale + auto-assign new) when MQTT bursts deliver multiple AMS
# updates for the same printer in quick succession (~30 ms apart, observed in
# the wild on H2D + dual AMS).
#
# Without this serialisation, two concurrent on_ams_change callbacks each read
# "no assignment for (printer, ams, tray)", each call auto_assign_spool, and
# the second commit hits
#   IntegrityError: duplicate key value violates unique constraint
#                   "spool_assignment_printer_id_ams_id_tray_id_key"
# SQLite's WAL serialises writes so the bug stayed latent there until optional
# Postgres support landed (asyncpg allows true concurrent transactions and
# surfaces the constraint violation).
#
# Scope is intentionally narrow: only the two DB-mutating blocks (unlink +
# assign) are inside the lock. The Spoolman sync block further down stays
# concurrent because it's network-bound and idempotent.
_ams_assignment_locks: dict[int, asyncio.Lock] = {}


def _get_ams_assignment_lock(printer_id: int) -> asyncio.Lock:
    """Return the per-printer assignment lock, creating it on first use."""
    lock = _ams_assignment_locks.get(printer_id)
    if lock is None:
        lock = asyncio.Lock()
        _ams_assignment_locks[printer_id] = lock
    return lock


# Per-printer dedup for unknown_tag WS broadcasts. Keyed by
# (ams_id, tray_id) -> (tag_uid, tray_uuid); we only re-broadcast when the
# tag tuple changes for the slot. Cleared when the slot is reported empty
# so remove + reinsert reliably re-prompts the UI.
_unknown_tag_last_broadcast: dict[int, dict[tuple[int, int], tuple[str, str]]] = {}


async def _broadcast_unknown_tag(
    *,
    printer_id: int,
    ams_id: int,
    tray_id: int,
    tag_uid: str,
    tray_uuid: str,
    tray_type: str | None = None,
    tray_color: str | None = None,
    tray_sub_brands: str | None = None,
    tray_count: int | None = None,
) -> None:
    """Broadcast unknown_tag, deduped so repeated MQTT pushes for the same slot+tag don't spam the UI."""
    slot_key = (ams_id, tray_id)
    tag_key = (tag_uid or "", tray_uuid or "")
    per_printer = _unknown_tag_last_broadcast.setdefault(printer_id, {})
    if per_printer.get(slot_key) == tag_key:
        logger.debug(
            "unknown_tag deduped for printer=%d AMS=%d slot=%d tag=%s",
            printer_id,
            ams_id,
            tray_id,
            tag_key[0][:8] or tag_key[1][:8] or "(none)",
        )
        return
    logger.info(
        "unknown_tag broadcast: printer=%d AMS=%d slot=%d type=%r color=%r tag=%s",
        printer_id,
        ams_id,
        tray_id,
        tray_type,
        tray_color,
        tag_key[0][:8] or tag_key[1][:8] or "(none)",
    )
    # Broadcast first; only commit the dedup if the WS write succeeds.
    # If broadcast raises, the next MQTT push retries instead of being
    # permanently silenced by a poisoned dedup entry.
    await _rt().ws_manager.broadcast(
        {
            "type": "unknown_tag",
            "printer_id": printer_id,
            "ams_id": ams_id,
            "tray_id": tray_id,
            "tag_uid": tag_uid,
            "tray_uuid": tray_uuid,
            "tray_type": tray_type,
            "tray_color": tray_color,
            "tray_sub_brands": tray_sub_brands,
            "tray_count": tray_count,
        }
    )
    per_printer[slot_key] = tag_key


def _clear_unknown_tag_dedup(printer_id: int, ams_id: int, tray_id: int) -> None:
    """Drop the cached last-broadcast tag for a slot (called when slot reports empty or gets matched)."""
    per_printer = _unknown_tag_last_broadcast.get(printer_id)
    if per_printer is None:
        return
    per_printer.pop((ams_id, tray_id), None)


# Active-print states as the MQTT status handler sees them.
_ACTIVE_PRINT_STATES: set[str] = {"RUNNING", "PRINTING", "PAUSE"}


# Broadcast-Dedupe und Druckerzähler des Status-Abflusses.
_last_status_broadcast: dict[int, str] = {}
# Track printers where we've updated nozzle_count
_nozzle_count_updated: set[int] = set()


async def _maybe_notify_printer_offline(printer_id: int) -> None:
    """Wait the debounce window then fire `on_printer_offline` if the printer
    is still offline.

    Scheduled by `on_printer_status_change` on the connected → disconnected
    edge (#1752). Cancelled by the same handler if the printer reconnects
    before the window elapses, so a single MQTT blip + recovery doesn't
    notify. Both the staleness-detector path (`bambu_mqtt.py::check_staleness`)
    and the smart-plug power-off path (`printer_manager.mark_printer_offline`)
    route through the same status-change callback, so this covers both.
    """
    try:
        await _rt().asyncio.sleep(_PRINTER_OFFLINE_NOTIFY_DEBOUNCE_SECONDS)
        still_offline = not _rt().printer_manager.is_connected(printer_id)
        logger.info(
            "[#1752] Printer %s offline debounce elapsed: still_offline=%s",
            printer_id,
            still_offline,
        )
        if not still_offline:
            return
        async with _rt().async_session() as db:
            from backend.app.models.printer import Printer

            result = await db.execute(select(Printer).where(Printer.id == printer_id))
            printer = result.scalar_one_or_none()
            if not printer:
                logger.warning(
                    "[#1752] Printer %s missing from DB at offline-notify time; skipping",
                    printer_id,
                )
                return
            logger.info(
                "[#1752] Dispatching on_printer_offline for printer %s (%s)",
                printer_id,
                printer.name,
            )
            await _rt().notification_service.on_printer_offline(printer_id, printer.name, db)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("Printer offline notification failed for printer %s: %s", printer_id, e)
    finally:
        _printer_offline_notify_tasks.pop(printer_id, None)


def _hms_notify_key(error) -> str:
    """What identifies a fault for notification de-duplication.

    The full code, which is unique per fault. ``attr`` alone used to be the key:
    unique for a ``print_error``, but for an ``hms[]`` fault it is only the
    module and part, so two faults on one part (#1840's H2C held 0500-0600-0002-0005
    and -0006 together) shared a key and only the first was ever notified. An
    entry without a full code falls back to attr and code together.
    """
    full_code = getattr(error, "full_code", "") or ""
    if full_code:
        return full_code.upper()
    return f"{error.attr:08X}:{error.code}"


def _hms_fault_counts(error) -> bool:
    """Whether a fault counts as a problem: the same rule the frontend's
    ``filterKnownHMSErrors`` applies to the printer card, badge and camera wall.

    It counts when Bambu publishes text for it or it offers action buttons, and
    its level is a real one. An ``hms[]`` fault at level 3 (notification) with
    no actions does not count: those are things like "the top cover is open" or
    "the chamber is hot, fan speed increased", which a printer can hold through
    a whole print. A ``print_error`` at the same level (0xCxxx) still counts, as
    it always has; those are prompts such as "unable to start drying" (#2728).
    """
    if error.severity < 1:
        return False
    has_actions = bool(getattr(error, "actions", None))
    is_hms_notice = len(getattr(error, "full_code", "") or "") == 16 and error.severity == 3
    return has_actions or (bool(getattr(error, "description", None)) and not is_hms_notice)


def _hms_errors_to_notify(errors: list, new_error_codes: set[str]) -> list:
    """The new faults that count (see ``_hms_fault_counts``).

    These go to the MQTT relay; the caller also needs a description before it
    sends a notification. Level 0, Bambu's "invalid" level, never counts. This
    used to read ``severity >= 2`` when severity held the part byte; on the real
    level that would drop the task-stopping errors (#2728).
    """
    return [e for e in errors if _hms_notify_key(e) in new_error_codes and _hms_fault_counts(e)]


def _take_new_hms_faults(printer_id: int, errors: list) -> list:
    """The faults on this printer not notified yet, and record them as notified.

    Tracking is updated before anything is sent, so concurrent status callbacks
    cannot notify the same fault twice. The set is replaced, not extended: a
    fault that clears and later returns is notified again, and the grace period
    in the caller keeps a fault that flickers off for a moment from doing that.
    """
    current = {_hms_notify_key(e) for e in errors}
    new = current - _notified_hms_errors.get(printer_id, set())
    _notified_hms_errors[printer_id] = current
    _hms_last_seen[printer_id] = _rt().time.time()
    return _hms_errors_to_notify(errors, new)


# `stg_cur` values that mean the printer is not in a preparation stage: 0 is
# "Printing", -1 and 255 are "no stage" (#3211).
_NO_PREPARATION_STAGES = frozenset({0, -1, 255})


def _progress_milestone_to_notify(printer_id: int, state: PrinterState) -> int | None:
    """The milestone (25, 50 or 75) this status update reaches for the first time, if any.

    Records it as notified. Called only for a printing state with progress above 0.

    Progress before the first layer is not progress through the print (#3211).
    An A1 mini reports ``mc_percent`` 85 in the first frame of a print, while
    still preheating the bed at layer 0, then 3, 7, 40 and 44 through its
    calibration, and starts layer 1 at 45. Read as progress, that 85 sent the
    75% notification together with Print Started, and since 75 was then on
    record, 25 and 50 could never fire. So nothing counts while the printer
    reports a layer count but has not started layer 1.

    Without a layer count -- a print whose first frame carried no
    ``total_layer_num``, until the pushall that asks for it is answered
    (#2702) -- the preparation stage says the same thing: before layer 1 the
    A1 mini reported ``stg_cur`` 2, 4, 14 and 1 (bed preheating, calibration,
    homing), and 0 from layer 1 on. -1 and 255 are "no stage". A printer that
    reports neither keeps the old behaviour rather than never notifying.
    """
    if (state.layer_num or 0) < 1:
        if (state.total_layers or 0) > 0:
            return None
        if state.stg_cur not in _NO_PREPARATION_STAGES:
            return None

    progress = state.progress or 0
    current_milestone = 0
    if progress >= 75:
        current_milestone = 75
    elif progress >= 50:
        current_milestone = 50
    elif progress >= 25:
        current_milestone = 25

    if current_milestone > _last_progress_milestone.get(printer_id, 0):
        _last_progress_milestone[printer_id] = current_milestone
        return current_milestone
    return None


async def on_printer_status_change(printer_id: int, state: PrinterState):
    """Handle printer status changes - broadcast via WebSocket."""
    # Connected-edge reconciliation (#1542 follow-up). When the printer
    # transitions disconnected → connected — which covers both PrintLab
    # startup (no prior connection) and a mid-session MQTT reconnect — fire
    # `reconcile_stale_active_prints` exactly once for this connection so
    # any archive still in `status="printing"` that can't actually be
    # running anymore (printer IDLE / different subtask / empty subtask)
    # gets a synthesised PRINT COMPLETE. Without this, a print that
    # finished during a disconnect window + a smart-plug power cycle
    # leaves the .3mf on the SD card and the firmware ghost-replays it on
    # next boot. Reconciliation runs concurrently — it must not block the
    # WebSocket dedup / broadcast logic below, and the connected edge is
    # marked True BEFORE the await so concurrent status updates inside
    # the same connection don't re-trigger reconciliation.
    #
    # Wait for a real push_status before reconciling (#1679): MQTT
    # `_on_connect` broadcasts `state` IMMEDIATELY after the broker accepts
    # the connection, BEFORE `_request_push_all` round-trips. At that
    # instant the `PrinterState` is still on construction defaults — most
    # importantly `state.state == "unknown"` and `state.subtask_name == ""`.
    # If reconcile spawns here, every in-flight archive falls through to
    # the empty-subtask_name trigger and gets synthesised `aborted`, which
    # creates a duplicate archive on the real PRINT COMPLETE and
    # double-counts filament. Gating on `state.state ∉ ("", "unknown")`
    # keeps the #1542 mechanism intact: once the first real push_status
    # updates `state.state` (RUNNING / IDLE / FINISH / …), this handler
    # fires again with the flag still False — reconcile then runs against
    # actual evidence.
    state_known = bool(state.state) and state.state.upper() not in ("", "UNKNOWN")
    if state.connected and state_known and not _printer_reconciled_since_connect.get(printer_id, False):
        _printer_reconciled_since_connect[printer_id] = True
        _rt().spawn_background_task(
            _rt().reconcile_stale_active_prints(printer_id),
            name=f"reconcile-stale-prints-{printer_id}",
        )
    elif not state.connected and _printer_reconciled_since_connect.get(printer_id, False):
        # Re-arm so the next reconnect triggers reconciliation again.
        _printer_reconciled_since_connect[printer_id] = False

    # Same edge, for the calibration table the AMS card reads its K values from.
    #
    # Also gated on knowing a nozzle diameter, which is what decides *which*
    # tables to ask for. A `state_known` gate alone is not enough: the first
    # real push_status is what makes the state known, and the nozzle fields do
    # not always arrive in it. Latching there would spend this connection's one
    # attempt on a printer that could not yet say what was fitted.
    nozzle_known = any(n.nozzle_diameter for n in (state.nozzles or []))
    if (
        state.connected
        and state_known
        and nozzle_known
        and not _printer_kprofiles_primed_since_connect.get(printer_id, False)
    ):
        _printer_kprofiles_primed_since_connect[printer_id] = True
        _rt().spawn_background_task(
            _rt().prime_kprofile_table(printer_id),
            name=f"prime-kprofiles-{printer_id}",
        )
    elif not state.connected and _printer_kprofiles_primed_since_connect.get(printer_id, False):
        _printer_kprofiles_primed_since_connect[printer_id] = False

    # A slot can lose its K-profile selection (cali_idx back to -1) with nothing
    # else in the AMS report changing -- a power cycle does it to every slot --
    # and on_ams_change never hears of it (#3219). Checked here, on every push
    # while the printer is idle; needs_check is cheap and throttled per slot.
    # Guarded: nothing here may stop the status broadcast below.
    try:
        if not state.connected:
            kprofile_drift.forget_printer(printer_id)
        elif kprofile_drift.needs_check(printer_id, state):
            _rt().spawn_background_task(
                kprofile_drift.reapply_lost_kprofiles(printer_id),
                name=f"reapply-kprofiles-{printer_id}",
            )
    except Exception:
        logger.exception("[Printer %s] K-profile check failed", printer_id)

    # Offline-notification edge (#1752): schedule `on_printer_offline` on
    # connected → disconnected. The "back online" channel is already covered
    # by the print-failure notification (firmware reports gcode_state=FAILED
    # on reconnect of an interrupted print), so we don't add a symmetric
    # online event here.
    prev_connected = _printer_last_connected.get(printer_id)
    _printer_last_connected[printer_id] = state.connected
    if prev_connected is True and not state.connected:
        existing = _printer_offline_notify_tasks.get(printer_id)
        if existing is None or existing.done():
            logger.info(
                "[#1752] Printer %s connected→disconnected edge; scheduling offline notification in %.0fs",
                printer_id,
                _PRINTER_OFFLINE_NOTIFY_DEBOUNCE_SECONDS,
            )
            _printer_offline_notify_tasks[printer_id] = _rt().asyncio.create_task(
                _maybe_notify_printer_offline(printer_id),
                name=f"printer-offline-notify-{printer_id}",
            )
    elif state.connected:
        pending = _printer_offline_notify_tasks.pop(printer_id, None)
        if pending is not None and not pending.done():
            logger.info(
                "[#1752] Printer %s reconnected before debounce; cancelling pending offline notification",
                printer_id,
            )
            pending.cancel()

    # Only broadcast if something meaningful changed (reduce WebSocket spam)
    # Include rounded temperatures to detect meaningful temp changes (within 1 degree)
    temps = state.temperatures or {}
    nozzle_temp = round(temps.get("nozzle", 0))
    bed_temp = round(temps.get("bed", 0))
    nozzle_2_temp = round(temps.get("nozzle_2", 0)) if "nozzle_2" in temps else ""
    chamber_temp = round(temps.get("chamber", 0)) if "chamber" in temps else ""

    # Auto-detect dual-nozzle printers from MQTT temperature data
    if "nozzle_2" in temps and printer_id not in _nozzle_count_updated:
        _nozzle_count_updated.add(printer_id)
        # Update nozzle_count in database
        async with _rt().async_session() as db:
            from backend.app.models.printer import Printer

            result = await db.execute(select(Printer).where(Printer.id == printer_id))
            printer = result.scalar_one_or_none()
            if printer and printer.nozzle_count != 2:
                printer.nozzle_count = 2
                await db.commit()
                logger.info(f"Auto-detected dual-nozzle printer {printer_id}, updated nozzle_count=2")

    # Include target temps for heating phase detection
    bed_target = round(temps.get("bed_target", 0))
    nozzle_target = round(temps.get("nozzle_target", 0))

    # Include tray_now and vt_tray hash so external spool changes trigger broadcasts
    vt_tray_key = hash(str(state.raw_data.get("vt_tray", []))) if state.raw_data else 0
    # Include AMS dry_time and tray state values so drying/slot changes trigger broadcasts.
    #
    # dry_countdown_stalled rides along because it is the one drying signal the
    # countdown itself cannot carry: the MQTT layer raises it precisely BECAUSE
    # dry_time stopped moving, so on the frame that flips it every other member
    # of this key is identical and the push would be deduplicated away. Mid-print
    # a temperature would eventually break the tie, but a parked command on an
    # idle machine changes nothing else at all — AMS temp and humidity are not in
    # the key — so the badge could sit unreachable indefinitely. The flag flips at
    # most once per drying cycle, so it costs no mid-print broadcast traffic.
    ams_dry_key = (
        tuple((a.get("dry_time", 0), bool(a.get("dry_countdown_stalled"))) for a in (state.raw_data.get("ams") or []))
        if state.raw_data
        else ()
    )
    # Include tray states so load/unload transitions (state 11→10) trigger broadcasts (#784)
    #
    # The filament identity fields are here because Configure Slot writes
    # exactly those and nothing else. Re-configuring a slot from PLA to another
    # brand or colour of PLA leaves id/tray_type/state identical, so the key
    # matched, this function returned before broadcasting, and the card kept
    # showing the old filament until the 30s fallback poll or a page reload —
    # even though the configure route asks the printer for a fresh pushall and
    # that push does carry the new values. Reset always worked, because it
    # clears tray_type.
    #
    # These fields only change when someone configures a slot or swaps a spool,
    # so unlike temperature or progress they add no broadcast traffic mid-print.
    ams_tray_key = (
        tuple(
            (
                t.get("id"),
                t.get("tray_type", ""),
                t.get("state"),
                t.get("tray_color", ""),
                t.get("tray_info_idx", ""),
                t.get("tray_sub_brands", ""),
                t.get("cali_idx"),
            )
            for a in (state.raw_data.get("ams") or [])
            for t in a.get("tray", [])
        )
        if state.raw_data
        else ()
    )
    # Filament Track Switch: which inlet each AMS is bound to, and whether the
    # accessory is fitted at all. Neither is in ams_tray_key (it is per-tray) nor
    # in the AMS change-hash (tray fields only, and widening that would fire
    # spurious Spoolman syncs), so without them a "Join IN-B" on the printer
    # screen changed no key at all and the card's inlet badges sat stale until a
    # reload. Like the filament-backup flag, these only move when someone
    # reconfigures the machine, so they add no mid-print broadcast traffic.
    fts_key = (
        state.fila_switch.installed if state.fila_switch else False,
        tuple(sorted(state.ams_switch_inlet.items())),
        # Which hotend holds which slot. Unlike the two above this does move
        # mid-print, on every filament change — but only between discrete slots,
        # so it adds a push per toolchange, not a stream. The AMS slot menu needs
        # it live: it decides which hotend the Load dialog may offer and whether
        # Unload has anything to act on.
        tuple(
            sorted(
                ((ext, slot.ams_id, slot.slot_id, slot.has_filament) for ext, slot in state.extruder_slots.items()),
                # Sort on the extruder id alone: the other members are nullable
                # and comparing None with an int raises.
                key=lambda entry: entry[0],
            )
        ),
    )
    status_key = (
        f"{state.connected}:{state.state}:{state.progress}:{state.layer_num}:"
        f"{nozzle_temp}:{bed_temp}:{nozzle_2_temp}:{chamber_temp}:"
        f"{state.stg_cur}:{bed_target}:{nozzle_target}:"
        f"{state.cooling_fan_speed}:{state.big_fan1_speed}:{state.big_fan2_speed}:"
        f"{state.chamber_light}:{state.active_extruder}:{state.tray_now}:{vt_tray_key}:"
        f"{ams_dry_key}:{ams_tray_key}:{state.door_open}:{state.ams_filament_backup}:{fts_key}"
    )

    is_active_print = state.state in _ACTIVE_PRINT_STATES
    if not is_active_print:
        _unauthorized_print_kill_sent.discard(printer_id)
    elif printer_id in _unauthorized_print_kill_sent:
        # stop_print() was already sent for this print; avoid all further
        # ownership and settings work until the printer leaves an active state.
        pass
    elif _rt()._is_printlab_authorized_print_in_memory(printer_id, state):
        # Normal PrintLab-started prints stay entirely on the in-memory path.
        _unauthorized_print_kill_sent.discard(printer_id)
    else:
        kill_switch_enabled = False
        authorization: bool | None = None
        status_logger = logger
        try:
            kill_switch_enabled = await _rt()._is_printer_kill_switch_enabled_cached()
            if kill_switch_enabled:
                async with _rt().async_session() as db:
                    authorization = await _rt()._is_printlab_authorized_print(printer_id, state, db)
        except Exception as e:
            # Fail safe: a database/reconciliation error must never turn into an
            # irreversible stop of a print whose ownership is still unknown.
            authorization = None
            status_logger.warning(
                "[KILL SWITCH] Failed to reconcile print authorization for printer %s: %s", printer_id, e
            )

        if not kill_switch_enabled or authorization is True:
            _unauthorized_print_kill_sent.discard(printer_id)
        elif authorization is None:
            _unauthorized_print_kill_sent.discard(printer_id)
            status_logger.debug(
                "[KILL SWITCH] Deferring authorization for printer %s until archive state is reconciled",
                printer_id,
            )
        else:
            try:
                stopped = _rt().printer_manager.stop_print(printer_id)
                if stopped:
                    _unauthorized_print_kill_sent.add(printer_id)
                    printer_info = _rt().printer_manager.get_printer(printer_id)
                    printer_name = printer_info.name if printer_info else f"Printer {printer_id}"
                    filename = state.subtask_name or state.gcode_file or state.current_print or "Unknown"
                    notification_data = {
                        "status": "stopped",
                        "filename": state.gcode_file or state.current_print or "",
                        "subtask_name": state.subtask_name or "",
                        "progress": state.progress,
                        "reason": "unauthorized_print",
                    }
                    status_logger.warning(
                        "[KILL SWITCH] Stopped unauthorized print on printer %s (state=%s)",
                        printer_id,
                        state.state,
                    )
                    try:
                        await _rt().ws_manager.broadcast(
                            {
                                "type": "kill_switch_triggered",
                                "printer_id": printer_id,
                                "printer_name": printer_name,
                                "filename": filename,
                                "reason": "unauthorized_print",
                            }
                        )
                    except Exception as e:
                        status_logger.warning(
                            "[KILL SWITCH] WebSocket notification failed for printer %s: %s", printer_id, e
                        )

                    previous_task = _rt()._kill_switch_notification_tasks.pop(printer_id, None)
                    if previous_task is not None and not previous_task.done():
                        previous_task.cancel()
                    _rt()._kill_switch_notification_tasks[printer_id] = _rt().spawn_background_task(
                        _rt()._send_kill_switch_provider_notification(printer_id, printer_name, notification_data),
                        name=f"kill-switch-notification-{printer_id}",
                    )
                else:
                    status_logger.warning(
                        "[KILL SWITCH] Could not stop unauthorized print on printer %s (state=%s)",
                        printer_id,
                        state.state,
                    )
            except Exception as e:
                status_logger.warning(
                    "[KILL SWITCH] Failed to stop unauthorized print on printer %s: %s", printer_id, e
                )

    # MQTT relay - publish status (before dedup check - always publish to MQTT)
    try:
        printer_info = _rt().printer_manager.get_printer(printer_id)
        if printer_info:
            await _rt().mqtt_relay.on_printer_status(
                printer_id,
                state,
                printer_info.name,
                printer_info.serial_number,
                _rt().printer_manager.is_awaiting_plate_clear(printer_id),
            )
    except Exception:
        pass  # Don't fail status callback if MQTT fails

    if _last_status_broadcast.get(printer_id) == status_key:
        return  # No change, skip WebSocket broadcast

    _last_status_broadcast[printer_id] = status_key

    # Check for progress milestone notifications (25%, 50%, 75%)
    progress = state.progress or 0
    is_printing = state.state in ("RUNNING", "PRINTING")

    if is_printing and progress > 0:
        current_milestone = _progress_milestone_to_notify(printer_id, state)
        if current_milestone is not None:
            try:
                from backend.app.models.printer import Printer

                # Read the printer in a short session and release the connection
                # BEFORE the ~15s camera snapshot below — holding it across the grab
                # pinned a pooled connection per milestone, per printer (issue #2572).
                async with _rt().async_session() as db:
                    result = await db.execute(select(Printer).where(Printer.id == printer_id))
                    printer = result.scalar_one_or_none()

                printer_name = printer.name if printer else f"Printer {printer_id}"
                filename = state.subtask_name or state.gcode_file or "Unknown"
                # remaining_time is in minutes, convert to seconds for notification
                remaining_time_seconds = state.remaining_time * 60 if state.remaining_time else None

                # Capture camera snapshot for notification image attachment (no DB held).
                image_data = await _rt()._capture_snapshot_for_notification(printer_id, printer, logger)

                # Notification send needs a session (provider/template lookups).
                async with _rt().async_session() as db:
                    await _rt().notification_service.on_print_progress(
                        printer_id,
                        printer_name,
                        filename,
                        current_milestone,
                        db,
                        remaining_time_seconds,
                        image_data=image_data,
                    )
            except Exception as e:
                logger.warning(f"Progress milestone notification failed: {e}")
    elif progress < 5:
        # Reset milestone tracking when print restarts or new print begins
        _last_progress_milestone[printer_id] = 0
        _first_layer_notified[printer_id] = False

    # HMS error codes that should not trigger notifications even though they
    # have known descriptions (e.g. user-initiated actions, not real errors).
    _HMS_NOTIFICATION_SUPPRESS = {
        "0500_400E",  # Printing was cancelled (user action, not an error)
    }

    # Check for new HMS errors and send notifications
    current_hms_errors = getattr(state, "hms_errors", []) or []
    if current_hms_errors:
        new_errors = _take_new_hms_faults(printer_id, current_hms_errors)

        if new_errors:
            try:
                from backend.app.models.printer import Printer

                # Read the printer in a short session and release the connection
                # BEFORE the ~15s camera snapshot below (issue #2572).
                async with _rt().async_session() as db:
                    result = await db.execute(select(Printer).where(Printer.id == printer_id))
                    printer = result.scalar_one_or_none()

                printer_name = printer.name if printer else f"Printer {printer_id}"

                # Format error details for notification
                # Module 0x07 = AMS/Filament, 0x05 = Nozzle, 0x0C = Motion Controller, etc.
                module_names = {
                    0x03: "Print/Task",
                    0x05: "Nozzle/Extruder",
                    0x07: "AMS/Filament",
                    0x0C: "Motion Controller",
                    0x12: "Chamber",
                }

                # Capture camera snapshot once for all error notifications (no DB held).
                error_image_data = await _rt()._capture_snapshot_for_notification(printer_id, printer, logger)

                # Notification sends need a session (provider/template lookups).
                async with _rt().async_session() as db:
                    sent_count = 0
                    for error in new_errors:
                        module_name = module_names.get(error.module, f"Module 0x{error.module:02X}")
                        # Build short code like "0700_8010"
                        # Mask to 16 bits to handle printers that send larger values
                        error_code_int = int(error.code.replace("0x", ""), 16) if error.code else 0
                        error_code_masked = error_code_int & 0xFFFF
                        short_code = f"{(error.attr >> 16) & 0xFFFF:04X}_{error_code_masked:04X}"

                        # Only notify for errors Bambu publishes text for — printers
                        # send undocumented codes that aren't real errors, and Bambu
                        # lists some with empty text. Resolved at parse time (#2926);
                        # short_code is still needed for the suppression set below.
                        description = error.description
                        if not description or short_code in _HMS_NOTIFICATION_SUPPRESS:
                            continue

                        error_type = f"{module_name} Error"
                        error_detail = description

                        await _rt().notification_service.on_printer_error(
                            printer_id, printer_name, error_type, db, error_detail, image_data=error_image_data
                        )
                        sent_count += 1

                    if sent_count:
                        logger.info(f"[HMS] Sent notification for {sent_count} error(s) on printer {printer_id}")

                # Also publish to MQTT relay (no DB): every new fault that
                # counts, with or without text, the same set the UI counts.
                printer_info = _rt().printer_manager.get_printer(printer_id)
                if printer_info:
                    errors_data = [
                        {
                            "code": e.code,
                            "attr": e.attr,
                            "module": e.module,
                            "severity": e.severity,
                        }
                        for e in new_errors
                    ]
                    await _rt().mqtt_relay.on_printer_error(
                        printer_id, printer_info.name, printer_info.serial_number, errors_data
                    )

            except Exception as e:
                logger.warning(f"HMS error notification failed: {e}")

    else:
        # No HMS errors — only clear tracking after a grace period to prevent
        # flapping errors (brief hms:[] gaps) from re-triggering notifications.
        # Some HMS codes (e.g. chamber temp regulation during PETG prints) toggle
        # on/off every few seconds as conditions fluctuate around thresholds.
        if printer_id in _notified_hms_errors:
            last_seen = _hms_last_seen.get(printer_id, 0)
            if _rt().time.time() - last_seen >= _HMS_CLEAR_GRACE_SECONDS:
                _notified_hms_errors.pop(printer_id, None)
                _hms_last_seen.pop(printer_id, None)

    await _rt().ws_manager.send_printer_status(
        printer_id,
        _rt().printer_state_to_dict(
            state,
            printer_id,
            _rt().printer_manager.get_model(printer_id),
            _rt().printer_manager.get_drying_targets(printer_id),
        ),
    )


async def on_fts_inlet_change(printer_id: int, ams_id: int, inlet: str):
    """Re-point a moved AMS's K-profiles at the nozzle it now feeds.

    K-profiles are per-nozzle and the printer's calibration table is numbered
    per-nozzle, but a tray holds exactly one ``cali_idx``. Moving an AMS to the
    switch's other inlet therefore silently invalidates every configured slot in
    it: the index stays put and now resolves against the other nozzle's table.
    Measured on the maintainer's H2C — one spool calibrated 0.018 on the left
    and 0.020 on the right kept the left profile after the move, and a manual
    RFID re-read only re-asserted the same wrong one.

    Configuring a slot is a deliberate preparation step, so this re-selects
    rather than re-configures: only the calibration binding moves, and only for
    slots whose spool already has a stored profile for the new nozzle. A slot
    PrintLab knows nothing about is left exactly as the operator left it.
    """
    target_extruder = extruder_for_inlet(inlet)
    if target_extruder is None:
        return

    client = _rt().printer_manager.get_client(printer_id)
    state = _rt().printer_manager.get_status(printer_id)
    if not client or not state or not state.raw_data:
        return

    # The nozzle the AMS now feeds -- the diameter of the TARGET extruder, not
    # of nozzle 0. On a machine with two sizes fitted, moving the inlet changes
    # the nozzle width, which changes both the K profile to select and the
    # preset the slot should carry.
    nozzle_diameter = nozzle_diameter_for_extruder(state, target_extruder, _rt().printer_manager.get_model(printer_id))

    ams_raw = state.raw_data.get("ams")
    ams_list = ams_raw.get("ams", []) if isinstance(ams_raw, dict) else ams_raw if isinstance(ams_raw, list) else []
    unit = next((u for u in ams_list if str(u.get("id")) == str(ams_id)), None)
    if not unit:
        return

    try:
        async with _rt().async_session() as db:
            for tray in unit.get("tray", []):
                tray_id = int(tray.get("id", -1))
                if tray_id < 0 or not tray.get("tray_type"):
                    continue
                current_idx = tray.get("cali_idx")

                profile = await _rt().find_slot_kprofile_for_extruder(
                    db,
                    printer_id,
                    ams_id,
                    tray_id,
                    target_extruder,
                    nozzle_diameter,
                    _rt().printer_manager.get_model(printer_id),
                    nozzle_flow_for_extruder(state, target_extruder, _rt().printer_manager.get_model(printer_id)),
                )
                if profile is None or profile.cali_idx is None:
                    continue
                if current_idx == profile.cali_idx:
                    continue  # Already on the right one.

                logger.info(
                    "[Printer %s] AMS %s slot %s moved to inlet %s (nozzle %s): "
                    "re-selecting K-profile %s (cali_idx %s -> %s, K=%s)",
                    printer_id,
                    ams_id,
                    tray_id,
                    inlet,
                    target_extruder,
                    profile.name,
                    current_idx,
                    profile.cali_idx,
                    profile.k_value,
                )
                client.extrusion_cali_sel(
                    ams_id=ams_id,
                    tray_id=tray_id,
                    cali_idx=profile.cali_idx,
                    filament_id=printer_safe_filament_id(profile.filament_id, tray.get("tray_info_idx", "")),
                    nozzle_diameter=nozzle_diameter,
                )
    except Exception as e:
        logger.warning("[Printer %s] Could not re-apply K-profiles after inlet move: %s", printer_id, e)


async def on_ams_change(printer_id: int, ams_data: list):
    """Handle AMS data changes - sync to Spoolman if enabled and auto mode."""

    # Snapshot BEFORE any await: if a print is active, skip weight sync later.
    # on_print_complete may pop _active_sessions during our awaits (#880).
    from backend.app.services.usage_tracker import _active_sessions

    _print_active = printer_id in _active_sessions

    # A slot that reports empty while a print is running is a filament runout,
    # not a spool swap: the spool is still physically in the AMS, just
    # consumed. Dropping either inventory backend's slot link there loses the
    # only record of which spool fed the print, so the completion path can't
    # charge the runout segment to anything. Both cleanup passes below consult
    # this; computed once, up front, so neither depends on the other having run.
    _unlink_state = _rt().printer_manager.get_status(printer_id)
    printing_now = (getattr(_unlink_state, "state", "") or "").upper() in ("RUNNING", "PAUSE")

    # MQTT relay - publish AMS change
    try:
        printer_info = _rt().printer_manager.get_printer(printer_id)
        if printer_info:
            await _rt().mqtt_relay.on_ams_change(printer_id, printer_info.name, printer_info.serial_number, ams_data)
    except Exception:
        pass  # Don't fail AMS callback if MQTT fails

    # Broadcast AMS change via WebSocket (bypasses status_key deduplication)
    # This ensures frontend gets immediate updates when AMS slots are configured
    try:
        state = _rt().printer_manager.get_status(printer_id)
        if state:
            logger.info("[Printer %s] Broadcasting AMS change via WebSocket", printer_id)
            await _rt().ws_manager.send_printer_status(
                printer_id,
                _rt().printer_state_to_dict(
                    state,
                    printer_id,
                    _rt().printer_manager.get_model(printer_id),
                    _rt().printer_manager.get_drying_targets(printer_id),
                ),
            )
    except Exception as e:
        logger.warning("Failed to broadcast AMS change for printer %s: %s", printer_id, e)

    await _unlink_stale_assignments(printer_id, ams_data, printing_now)

    # Auto-manage inventory spools from AMS tray data (skip if Spoolman manages AMS).
    # Serialised per-printer via _ams_assignment_locks: MQTT bursts can deliver
    # two AMS pushes ~30 ms apart, and without the lock both callbacks read
    # "no existing assignment" for the same (printer, ams, tray) and race to
    # INSERT, hitting the spool_assignment_printer_id_ams_id_tray_id_key
    # unique constraint on Postgres. SQLite's WAL serialises writes so the
    # bug stayed latent there. See _ams_assignment_locks comment for details.
    try:
        async with _get_ams_assignment_lock(printer_id), _rt().async_session() as db:
            from sqlalchemy.orm import selectinload

            from backend.app.api.routes.settings import get_setting
            from backend.app.models.spool import Spool
            from backend.app.models.spool_assignment import SpoolAssignment as SA
            from backend.app.services.spool_tag_matcher import (
                auto_assign_spool,
                create_spool_from_tray,
                find_matching_untagged_spool,
                get_spool_by_tag,
                is_bambu_tag,
                is_valid_tag,
                link_tag_to_inventory_spool,
            )

            _spoolman_on = await get_setting(db, "spoolman_enabled")
            _auto_add_raw = await get_setting(db, "auto_add_unknown_rfid")
            _auto_add_unknown = _auto_add_raw is None or _auto_add_raw.lower() == "true"
            if not _spoolman_on or _spoolman_on.lower() != "true":
                for ams_unit in ams_data:
                    if not isinstance(ams_unit, dict):
                        continue
                    ams_id = int(ams_unit.get("id", 0))
                    for tray in ams_unit.get("tray", []):
                        if not isinstance(tray, dict):
                            continue
                        tray_id = int(tray.get("id", 0))
                        tag_uid = tray.get("tag_uid", "")
                        tray_uuid = tray.get("tray_uuid", "")
                        tray_info_idx = tray.get("tray_info_idx", "")
                        if not tray.get("tray_type"):
                            # Slot reported empty — drop any cached unknown-tag
                            # broadcast so reinserting the same spool re-prompts.
                            _clear_unknown_tag_dedup(printer_id, ams_id, tray_id)
                            continue  # Empty slot
                        # Check if assignment already exists for this slot
                        existing = await db.execute(
                            select(SA)
                            .options(selectinload(SA.spool).selectinload(Spool.k_profiles))
                            .where(SA.printer_id == printer_id, SA.ams_id == ams_id, SA.tray_id == tray_id)
                        )
                        existing_assignment = existing.scalar_one_or_none()
                        if existing_assignment:
                            # Sync spool weight_used from AMS remain — only INCREASE, never decrease.
                            # The AMS remain% is low-resolution (integer %, i.e. 10g steps for 1kg spool)
                            # and must not overwrite precise values from the usage tracker (3MF/G-code).
                            # Skip during active prints: the usage tracker handles deduction
                            # precisely via 3MF data on print completion. Without this guard the
                            # AMS remain% SET and the usage tracker ADD both fire from the same
                            # MQTT message, doubling the deduction (#880).
                            if _print_active:
                                continue
                            remain_raw = tray.get("remain")
                            if (
                                remain_raw is not None
                                and existing_assignment.spool
                                and not existing_assignment.spool.weight_locked
                            ):
                                try:
                                    remain_val = int(remain_raw)
                                except (TypeError, ValueError):
                                    remain_val = -1
                                if 1 <= remain_val <= 100:
                                    lw = existing_assignment.spool.label_weight or 1000
                                    new_used = round(lw * (100 - remain_val) / 100.0, 1)
                                    current_used = existing_assignment.spool.weight_used or 0
                                    if new_used > current_used + 1:
                                        logger.info(
                                            "Weight sync: spool %d weight_used %s -> %s (remain=%d)",
                                            existing_assignment.spool_id,
                                            current_used,
                                            new_used,
                                            remain_val,
                                        )
                                        existing_assignment.spool.weight_used = new_used
                                        await db.commit()

                            # Re-apply stored K-profile when the live tray's
                            # cali_idx drifted from the spool's stored profile.
                            # This catches "reset slot → re-read" and any other
                            # path where the firmware loses the user's K-profile
                            # selection while the SpoolAssignment row persists.
                            # Per the maintainer's rule: any time a spool tag is
                            # identified and matches inventory, the slot must be
                            # configured with the spool's stored settings. Without
                            # this block the existing-assignment branch only ran
                            # weight-sync and let the firmware-default cali_idx win.
                            try:
                                spool = existing_assignment.spool
                                if (
                                    spool is not None
                                    and is_bambu_tag(tag_uid, tray_uuid, tray_info_idx)
                                    and spool.k_profiles
                                ):
                                    state = _rt().printer_manager.get_status(printer_id)
                                    slot_nozzle = resolve_slot_nozzle(
                                        state, ams_id, tray_id, _rt().printer_manager.get_model(printer_id)
                                    )
                                    nozzle_diameter = slot_nozzle.diameter
                                    slot_extruder = slot_nozzle.extruder
                                    # Prefer exact extruder match, fall back to
                                    # extruder-agnostic kp for the same printer +
                                    # nozzle. Avoids hard-skipping when the AMS is
                                    # mapped differently than at calibration time.
                                    matching_kp = None
                                    fallback_kp = None
                                    for kp in spool.k_profiles:
                                        if (
                                            kp.printer_id != printer_id
                                            or kp.nozzle_diameter != nozzle_diameter
                                            or kp.cali_idx is None
                                            or not slot_nozzle.flow_matches(kp.nozzle_type)
                                        ):
                                            continue
                                        if (
                                            slot_extruder is not None
                                            and kp.extruder is not None
                                            and kp.extruder == slot_extruder
                                        ):
                                            matching_kp = kp
                                            break
                                        if fallback_kp is None:
                                            fallback_kp = kp
                                    chosen_kp = matching_kp or fallback_kp
                                    if chosen_kp is not None:
                                        live_cali_idx = tray.get("cali_idx")
                                        # Only fire MQTT when the printer's live
                                        # cali_idx differs from the stored value.
                                        # Avoids spamming the broker on every
                                        # MQTT push during steady-state operation.
                                        if live_cali_idx != chosen_kp.cali_idx:
                                            client = _rt().printer_manager.get_client(printer_id)
                                            if client:
                                                cali_filament_id = spool.slicer_filament or tray_info_idx or ""
                                                client.extrusion_cali_sel(
                                                    ams_id=ams_id,
                                                    tray_id=tray_id,
                                                    cali_idx=chosen_kp.cali_idx,
                                                    filament_id=cali_filament_id,
                                                    nozzle_diameter=nozzle_diameter,
                                                )
                                                logger.info(
                                                    "Re-applied K-profile cali_idx=%d for spool %d "
                                                    "on printer %d AMS%d-T%d (live=%s drift detected)",
                                                    chosen_kp.cali_idx,
                                                    spool.id,
                                                    printer_id,
                                                    ams_id,
                                                    tray_id,
                                                    live_cali_idx,
                                                )
                            except Exception:
                                logger.exception(
                                    "K-profile re-apply failed for printer %d AMS%d-T%d",
                                    printer_id,
                                    ams_id,
                                    tray_id,
                                )
                            continue

                        if is_bambu_tag(tag_uid, tray_uuid, tray_info_idx):
                            # BL spool with RFID tag: auto-match → inventory match → auto-create
                            spool = await get_spool_by_tag(db, tag_uid, tray_uuid)
                            if not spool:
                                # Try matching an untagged inventory spool (same material/color)
                                spool = await find_matching_untagged_spool(db, tray)
                                if spool:
                                    await link_tag_to_inventory_spool(db, spool, tray)
                                elif _auto_add_unknown:
                                    spool = await create_spool_from_tray(db, tray)
                                else:
                                    # Auto-add disabled: surface the slot so the
                                    # user can add it manually via the UI.
                                    await _broadcast_unknown_tag(
                                        printer_id=printer_id,
                                        ams_id=ams_id,
                                        tray_id=tray_id,
                                        tag_uid=tag_uid,
                                        tray_uuid=tray_uuid,
                                        tray_type=tray.get("tray_type"),
                                        tray_color=tray.get("tray_color"),
                                        tray_sub_brands=tray.get("tray_sub_brands"),
                                        tray_count=len(ams_unit.get("tray", [])),
                                    )
                                    continue
                            # Slot matched (existing tag, untagged inventory
                            # match, or freshly auto-created spool) — drop any
                            # stale dedup so a future tag swap re-prompts.
                            _clear_unknown_tag_dedup(printer_id, ams_id, tray_id)
                            await auto_assign_spool(
                                printer_id,
                                ams_id,
                                tray_id,
                                spool,
                                _rt().printer_manager,
                                db,
                                tray_info_idx=tray_info_idx,
                            )
                            await db.commit()
                            await _rt().ws_manager.broadcast(
                                {
                                    "type": "spool_auto_assigned",
                                    "printer_id": printer_id,
                                    "ams_id": ams_id,
                                    "tray_id": tray_id,
                                    "spool_id": spool.id,
                                }
                            )
                            logger.info(
                                "RFID auto-assigned spool %d to printer %d AMS%d-T%d",
                                spool.id,
                                printer_id,
                                ams_id,
                                tray_id,
                            )
                        elif is_valid_tag(tag_uid, tray_uuid):
                            # Non-BL spool with some tag — let user choose
                            await _broadcast_unknown_tag(
                                printer_id=printer_id,
                                ams_id=ams_id,
                                tray_id=tray_id,
                                tag_uid=tag_uid,
                                tray_uuid=tray_uuid,
                                tray_type=tray.get("tray_type"),
                                tray_color=tray.get("tray_color"),
                                tray_sub_brands=tray.get("tray_sub_brands"),
                                tray_count=len(ams_unit.get("tray", [])),
                            )
                        # No-tag slots (generic non-RFID filament) are left alone:
                        # nothing to identify, prompting "+ Add" would just create
                        # ghost spools with empty tags on every confirm.
    except Exception as e:
        logger.warning("RFID spool auto-assign failed: %s", e, exc_info=True)

    try:
        async with _rt().async_session() as db:
            from backend.app.api.routes.settings import get_setting
            from backend.app.models.printer import Printer

            # Check if Spoolman is enabled
            spoolman_enabled = await get_setting(db, "spoolman_enabled")
            if not spoolman_enabled or spoolman_enabled.lower() != "true":
                return

            # Check sync mode
            sync_mode = await get_setting(db, "spoolman_sync_mode")
            if sync_mode and sync_mode != "auto":
                return  # Only sync on auto mode

            _auto_add_raw_sm = await get_setting(db, "auto_add_unknown_rfid")
            auto_add_unknown_rfid = _auto_add_raw_sm is None or _auto_add_raw_sm.lower() == "true"

            # `spoolman_disable_weight_sync` is deprecated (#1119) — weight is now
            # always owned by per-print tracking, never by AMS auto-sync. The
            # setting is still read by the settings UI for backwards compat but
            # has no effect on the sync path here.

            # Get Spoolman URL
            spoolman_url = await get_setting(db, "spoolman_url")
            if not spoolman_url:
                return

            # Get or create Spoolman client
            client = await _rt().get_spoolman_client()
            if not client:
                try:
                    client = await init_spoolman_client(spoolman_url)
                except ValueError as exc:
                    logger.warning("Spoolman URL %r rejected by SSRF guard: %s", spoolman_url, exc)
                    return

            # Check if Spoolman is reachable
            if not await client.health_check():
                logger.warning("Spoolman not reachable at %s", spoolman_url)
                return

            # Get printer name for location
            result = await db.execute(select(Printer).where(Printer.id == printer_id))
            printer = result.scalar_one_or_none()
            printer_name = printer.name if printer else f"Printer {printer_id}"

            # OPTIMIZATION: Fetch all spools once before processing trays
            # This eliminates redundant API calls (one per tray) when syncing multiple trays
            logger.debug("[Printer %s] Fetching spools cache for AMS sync...", printer_id)
            try:
                cached_spools = await client.get_spools()
                logger.debug("[Printer %s] Cached %d spools for batch sync", printer_id, len(cached_spools))
            except Exception as e:
                logger.error(
                    "[Printer %s] Failed to fetch spools cache after retries, aborting AMS sync: %s",
                    printer_id,
                    e,
                )
                return

            # Load inventory weights as fallback (when AMS MQTT data lacks remain values)
            from sqlalchemy.orm import selectinload

            from backend.app.models.spool_assignment import SpoolAssignment
            from backend.app.models.spoolman_slot_assignment import SpoolmanSlotAssignment
            from backend.app.services.ams_slot_presence import spool_present
            from backend.app.services.inventory_mode import spoolman_owns_assignments

            # Built-in remaining weight, used by sync_ams_tray only when the
            # firmware reports an unusable remain%/tray_weight for a slot.
            #
            # Left empty since #2812. This block runs in Spoolman mode only,
            # and until then the built-in table was emptied on the switch, so
            # there was never anything here to read and the fallback was inert.
            # Preserving those rows makes it live again, and it is keyed by slot
            # rather than by spool: after a mode switch the tray may well hold
            # different filament, and ``create_spool`` writes ``remaining_weight``
            # unconditionally, so a stale figure would be seeded into a brand new
            # Spoolman spool. Deliberately kept inert rather than deleted, so the
            # intent survives for whoever revisits the cross-mode fallback.
            inventory_weights: dict[tuple[int, int], float] = {}
            if not await spoolman_owns_assignments(db):
                try:
                    assign_result = await db.execute(
                        select(SpoolAssignment)
                        .options(selectinload(SpoolAssignment.spool))
                        .where(SpoolAssignment.printer_id == printer_id)
                    )
                    for assignment in assign_result.scalars().all():
                        spool = assignment.spool
                        if spool and spool.label_weight > 0:
                            remaining = max(0.0, spool.label_weight - (spool.weight_used or 0))
                            inventory_weights[(assignment.ams_id, assignment.tray_id)] = remaining
                except Exception as e:
                    logger.warning("Could not load inventory weights for printer %s: %s", printer_id, e)

            # Load existing Spoolman slot assignments for the no-RFID fallback path
            spoolman_slot_map: dict[tuple[int, int], int] = {}
            try:
                slot_result = await db.execute(
                    select(SpoolmanSlotAssignment).where(SpoolmanSlotAssignment.printer_id == printer_id)
                )
                for slot in slot_result.scalars().all():
                    spoolman_slot_map[(slot.ams_id, slot.tray_id)] = slot.spoolman_spool_id
            except Exception as e:
                logger.warning("Could not load Spoolman slot assignments for printer %s: %s", printer_id, e)

            # Sync each AMS tray and collect slot changes for DB persistence
            synced = 0
            slot_changes: list[tuple[int, int, int]] = []  # (ams_id, tray_id, spoolman_spool_id) to upsert
            empty_slots: list[tuple[int, int]] = []  # (ams_id, tray_id) whose tray is now empty
            spoolman_held: set[tuple] = set()  # removals held for the grace period (#3186)
            for ams_unit in ams_data:
                if not isinstance(ams_unit, dict):
                    continue
                ams_id = int(ams_unit.get("id", 0))
                trays = ams_unit.get("tray", [])

                for tray_data in trays:
                    if not isinstance(tray_data, dict):
                        continue
                    tray_id_raw = int(tray_data.get("id", 0))
                    tray = client.parse_ams_tray(ams_id, tray_data)
                    if not tray:
                        # Empty tray slot — record for local assignment cleanup
                        # and drop any cached unknown-tag broadcast so a
                        # reinserted spool re-prompts.
                        #
                        # Not during a running print: a slot that empties there
                        # is a filament runout, and the spool is still in the
                        # AMS. `spoolman_slot_assignments` is how a tag-less
                        # spool assigned through the PrintLab UI is resolved at
                        # completion (#1459), so deleting the row mid-print
                        # loses the runout segment's usage — the same failure
                        # the internal inventory's auto-unlink had.
                        #
                        # Nor when firmware's presence bit says the slot is
                        # occupied. parse_ams_tray calls a tray with no type or
                        # no colour empty, and a spool the AMS cannot read has
                        # neither until something configures it — so a tag-less
                        # spool assigned through the UI had its row deleted by
                        # the first idle push after it was inserted. Same
                        # deletion as the internal inventory's in #3100, same
                        # answer, so the two modes stay in step.
                        #
                        # And only once the slot has stayed empty for the grace
                        # period -- the internal inventory's #3186 answer, for
                        # the same one-push blank.
                        linked_spool = spoolman_slot_map.get((ams_id, tray_id_raw))
                        hold_key = ("spoolman", ams_id, tray_id_raw, linked_spool)
                        if not printing_now and (
                            spool_present(tray_data) is not True or slot_unlink_grace.is_held(printer_id, hold_key)
                        ):
                            if linked_spool is None or slot_unlink_grace.removal_confirmed(printer_id, hold_key):
                                empty_slots.append((ams_id, tray_id_raw))
                            else:
                                spoolman_held.add(hold_key)
                                logger.info(
                                    "Spoolman slot unlink held: AMS%d-T%d (spool %d) reports empty; "
                                    "unlinking if it is still empty in %ds",
                                    ams_id,
                                    tray_id_raw,
                                    linked_spool,
                                    int(slot_unlink_grace.GRACE_SECONDS),
                                )
                        _clear_unknown_tag_dedup(printer_id, ams_id, tray_id_raw)
                        continue

                    spool_tag = (
                        tray.tray_uuid
                        if tray.tray_uuid and tray.tray_uuid != "00000000000000000000000000000000"
                        else tray.tag_uid
                    )

                    # Provide the hint only when no RFID is available
                    hint = spoolman_slot_map.get((ams_id, tray.tray_id)) if not spool_tag else None

                    try:
                        inv_remaining = inventory_weights.get((ams_id, tray.tray_id))
                        result = await client.sync_ams_tray(
                            tray,
                            printer_name,
                            db,
                            # Per-print tracking is the only weight writer (#1119).
                            # AMS auto-sync still maintains spool metadata / slot
                            # assignments but no longer touches remaining_weight.
                            disable_weight_sync=True,
                            cached_spools=cached_spools,
                            inventory_remaining=inv_remaining,
                            spoolman_spool_id_hint=hint,
                            auto_add_unknown_rfid=auto_add_unknown_rfid,
                        )
                        if result is None and spool_tag and not auto_add_unknown_rfid:
                            # Spoolman skipped auto-create per user setting — surface
                            # the slot so the UI can offer "+ Add to inventory".
                            await _broadcast_unknown_tag(
                                printer_id=printer_id,
                                ams_id=ams_id,
                                tray_id=tray.tray_id,
                                tag_uid=tray.tag_uid or "",
                                tray_uuid=tray.tray_uuid or "",
                                tray_type=tray.tray_type,
                                tray_color=tray.tray_color,
                                tray_sub_brands=tray.tray_sub_brands,
                                tray_count=len(trays),
                            )
                        elif result:
                            _clear_unknown_tag_dedup(printer_id, ams_id, tray.tray_id)
                        if result:
                            synced += 1
                            if result.get("id"):
                                slot_changes.append((ams_id, tray.tray_id, result["id"]))
                                # If a new spool was created, add it to the cache
                                # so subsequent trays can find it if they reference the same tag
                                spool_exists = any(s.get("id") == result["id"] for s in cached_spools)
                                if not spool_exists:
                                    cached_spools.append(result)
                                    logger.debug(
                                        "[Printer %s] Added newly created spool %s to cache",
                                        printer_id,
                                        result["id"],
                                    )
                                # Reconcile slot_preset_mappings (the same row internal
                                # mode keeps in sync via inventory + spool_tag_matcher).
                                # Without this the slot card surfaces the previous spool's
                                # preset name — same bug shape, different inventory mode.
                                from backend.app.services.slot_preset_writer import (
                                    upsert_slot_preset_for_spoolman_spool,
                                )

                                await upsert_slot_preset_for_spoolman_spool(
                                    db=db,
                                    spoolman_spool=result,
                                    tray_info_idx=tray.tray_info_idx or "",
                                    tray_sub_brands=tray.tray_sub_brands or "",
                                    tray_type=tray.tray_type or "",
                                    printer_id=printer_id,
                                    ams_id=ams_id,
                                    tray_id=tray.tray_id,
                                )
                    except Exception as e:
                        logger.error("Error syncing AMS %s tray %s: %s", ams_id, tray.tray_id, e)

            slot_unlink_grace.settle(printer_id, "spoolman", spoolman_held)

            if synced > 0:
                logger.info("Auto-synced %s AMS trays to Spoolman for printer %s", synced, printer_id)

            # Persist slot assignment changes to the local table
            if slot_changes or empty_slots:
                try:
                    for ams_id, tray_id, spool_id in slot_changes:
                        await db.execute(
                            text(
                                "INSERT INTO spoolman_slot_assignments"
                                " (printer_id, ams_id, tray_id, spoolman_spool_id)"
                                " VALUES (:printer_id, :ams_id, :tray_id, :spool_id)"
                                " ON CONFLICT(printer_id, ams_id, tray_id)"
                                " DO UPDATE SET spoolman_spool_id = excluded.spoolman_spool_id"
                            ),
                            {
                                "printer_id": printer_id,
                                "ams_id": ams_id,
                                "tray_id": tray_id,
                                "spool_id": spool_id,
                            },
                        )
                    for ams_id, tray_id in empty_slots:
                        await db.execute(
                            delete(SpoolmanSlotAssignment).where(
                                SpoolmanSlotAssignment.printer_id == printer_id,
                                SpoolmanSlotAssignment.ams_id == ams_id,
                                SpoolmanSlotAssignment.tray_id == tray_id,
                            )
                        )
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    logger.error("Error persisting Spoolman slot assignments for printer %s: %s", printer_id, e)
                else:
                    # Tell open browsers the slot changed. This loop rewrites
                    # slot_preset_mappings via upsert_slot_preset_for_spoolman_spool
                    # above, and the AMS slot card reads that row ahead of the
                    # live tray_info_idx -- so with no event the card keeps
                    # showing the previous spool's preset name. Internal mode
                    # raises spool_auto_assigned for the same reason; this loop
                    # broadcast nothing at all, which made Spoolman mode the
                    # worse half of the same bug. On the else branch so a
                    # failed commit stays silent and a broadcast failure cannot
                    # roll back rows that are already committed.
                    for ams_id, tray_id, *_ in (*slot_changes, *empty_slots):
                        await _rt().ws_manager.broadcast(
                            {
                                "type": "spool_assignment_changed",
                                "printer_id": printer_id,
                                "ams_id": ams_id,
                                "tray_id": tray_id,
                            }
                        )

    except Exception as e:
        logger.error("Spoolman AMS sync failed for printer %s: %s", printer_id, e)
