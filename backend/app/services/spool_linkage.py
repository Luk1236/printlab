"""Spool-Verknuepfung zum AMS: Automatisches Entknuepfen und Nachziehen.

Aus ``backend/app/main.py`` ausgelagert: das Entknuepfen fester Inventar-
Zuweisungen, deren Slot den Spool nicht mehr haelt, das Ablaufenlassen
gehaltener Spoolman-Slots und die Nachpruefung gehaltener Entfernungen
(#3186), plus die Registrierung der Nachpruefung bei ``slot_unlink_grace``.
Patchbare Namen greifen weiterhin im Modul ``main`` — das Modul liest sie
ueber :func:`_rt`. Aufrufer und Tests sehen keinen Unterschied.
"""

import logging

from sqlalchemy import delete, select

from backend.app.services import slot_unlink_grace
from backend.app.utils.filament_types import printer_filament_type

# Der Logger-Name bleibt der der alten Heimat, damit Protokollzeilen in den
# Support-Bundles unverändert unter ``backend.app.main`` auftauchen.
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen."""
    import importlib

    return importlib.import_module("backend.app.main")


def _is_bambu_uuid(tray_uuid: str) -> bool:
    """Check if a tray UUID looks like a valid Bambu Lab RFID UUID (non-empty, non-zero)."""
    return bool(tray_uuid) and tray_uuid not in ("", "0" * len(tray_uuid))


async def _unlink_stale_assignments(printer_id: int, ams_data: list, printing_now: bool) -> None:
    """Unlink built-in inventory assignments whose slot no longer holds their spool.

    Runs from ``on_ams_change`` and, for removals held by ``slot_unlink_grace``,
    from the delayed re-check -- which is why it takes the AMS data and print
    state as arguments instead of reading them from the push (#3186).
    """

    from backend.app.utils.color_utils import colors_similar as _colors_similar

    # Auto-unlink spool assignments with stale fingerprints. Under the
    # per-printer assignment lock since #3186: the held-removal re-check runs
    # this outside any MQTT push, so it can now overlap one.
    try:
        async with _rt()._get_ams_assignment_lock(printer_id), _rt().async_session() as db:
            from sqlalchemy.orm import selectinload

            from backend.app.api.routes.inventory import _find_tray_in_ams_data
            from backend.app.models.spool import Spool as _Spool
            from backend.app.models.spool_assignment import SpoolAssignment as SA
            from backend.app.services.ams_slot_presence import spool_present
            from backend.app.services.inventory_mode import spoolman_owns_assignments

            # Built-in assignments only. Since #2812 they survive a switch to
            # Spoolman mode rather than being deleted by it, and this pass ends
            # in ``db.delete`` — left ungated it would unlink them one slot at a
            # time as the AMS contents changed under the other mode, undoing the
            # preservation more slowly but just as completely.
            assignments = []
            if not await spoolman_owns_assignments(db):
                result = await db.execute(
                    select(SA)
                    .where(SA.printer_id == printer_id)
                    .options(selectinload(SA.spool).selectinload(_Spool.k_profiles))
                )
                assignments = result.scalars().all()
            # ``printing_now`` (top of this function) keeps a runout from
            # unlinking the spool that fed the print — the next idle-time pass
            # unlinks it if the user really did take it out.
            stale = []
            # Removals this pass is holding rather than unlinking (#3186).
            held: set[tuple] = set()
            for assignment in assignments:
                # External spool assignments (ams_id=255) live in vt_tray, not AMS data
                if assignment.ams_id == 255:
                    ps = _rt().printer_manager.get_status(printer_id)
                    vt_tray_raw = ps.raw_data.get("vt_tray", []) if ps else []
                    ext_id = assignment.tray_id + 254  # 0→254, 1→255
                    current_tray = None
                    for vt in vt_tray_raw:
                        if isinstance(vt, dict) and int(vt.get("id", 254)) == ext_id:
                            current_tray = vt
                            break
                    if not current_tray:
                        # vt_tray data may not have arrived yet — keep assignment
                        continue
                else:
                    current_tray = _find_tray_in_ams_data(ams_data, assignment.ams_id, assignment.tray_id)
                if not current_tray:
                    if printing_now:
                        logger.info(
                            "Auto-unlink skipped: spool %d AMS%d-T%d — slot empty during a running print (runout?)",
                            assignment.spool_id,
                            assignment.ams_id,
                            assignment.tray_id,
                        )
                        continue
                    # A whole AMS unit can drop out of one push and come back in
                    # the next; only a slot that stays gone is a removal (#3186).
                    hold_key = ("inventory", assignment.ams_id, assignment.tray_id, assignment.spool_id)
                    if not slot_unlink_grace.removal_confirmed(printer_id, hold_key):
                        held.add(hold_key)
                        logger.info(
                            "Auto-unlink held: spool %d AMS%d-T%d — tray not found in AMS data; "
                            "unlinking if it is still gone in %ds",
                            assignment.spool_id,
                            assignment.ams_id,
                            assignment.tray_id,
                            int(slot_unlink_grace.GRACE_SECONDS),
                        )
                        continue
                    logger.info(
                        "Auto-unlink: spool %d AMS%d-T%d — tray not found in AMS data (slot empty?)",
                        assignment.spool_id,
                        assignment.ams_id,
                        assignment.tray_id,
                    )
                    stale.append(assignment)  # Slot empty
                elif _is_bambu_uuid(current_tray.get("tray_uuid", "")):
                    # A Bambu Lab spool is in this slot — check if it's the same spool
                    # that's currently assigned. If yes, keep the assignment (avoids
                    # unnecessary unlink/re-assign/ams_filament_setting cycle that clears
                    # the printer's filament preset on every startup).
                    tray_uuid = current_tray.get("tray_uuid", "")
                    tag_uid = current_tray.get("tag_uid", "")
                    spool = assignment.spool
                    spool_matches = False
                    if spool:
                        if (spool.tray_uuid and spool.tray_uuid.upper() == tray_uuid.upper()) or (
                            spool.tag_uid
                            and tag_uid
                            and tag_uid != "0000000000000000"
                            and spool.tag_uid.upper() == tag_uid.upper()
                        ):
                            spool_matches = True
                    if spool_matches:
                        # Same BL spool still in slot — keep assignment, update fingerprint if needed
                        cur_color = current_tray.get("tray_color", "")
                        cur_type = current_tray.get("tray_type", "")
                        fp_color = assignment.fingerprint_color or ""
                        fp_type = assignment.fingerprint_type or ""
                        if cur_color.upper() != fp_color.upper() or cur_type.upper() != fp_type.upper():
                            assignment.fingerprint_color = cur_color
                            assignment.fingerprint_type = cur_type
                            logger.debug(
                                "Auto-unlink: spool %d AMS%d-T%d — same BL spool, updated fingerprint",
                                assignment.spool_id,
                                assignment.ams_id,
                                assignment.tray_id,
                            )
                        continue
                    # Different BL spool or unrecognized — unlink so auto-assign can match
                    logger.info(
                        "Auto-unlink: spool %d AMS%d-T%d — different Bambu Lab spool detected (uuid=%s)",
                        assignment.spool_id,
                        assignment.ams_id,
                        assignment.tray_id,
                        tray_uuid,
                    )
                    stale.append(assignment)
                else:
                    cur_color = current_tray.get("tray_color", "")
                    cur_type = current_tray.get("tray_type", "")
                    cur_state = current_tray.get("state")
                    fp_color = assignment.fingerprint_color or ""
                    fp_type = assignment.fingerprint_type or ""

                    # SpoolBuddy pre-config replay: fingerprint_type empty means
                    # the slot was empty when the user pre-assigned via SpoolBuddy
                    # (the firmware drops ams_filament_setting on empty slots, so
                    # MQTT was deferred). The moment any filament gets inserted
                    # — Bambu RFID, 3rd-party, or even an existing-but-now-
                    # reconfigured spool — fire the deferred configuration.
                    # The "loaded" signal is state == 11 (Bambu's "filament fed to
                    # extruder" code) OR, on firmwares that don't use the state
                    # enum meaningfully, a non-empty tray_type when state is
                    # NOT one of the firmware's explicit empty signals (9, 10).
                    # state-only was wrong for firmwares that never set 11 — A1
                    # Mini BMCU 01.07.02.00 and P1S Standard AMS 00.00.06.75 both
                    # always report state=3 — so the replay never fired for them
                    # (#1322). The state ∉ {9,10} guard keeps the firmware's
                    # explicit "empty" signals authoritative over any stale
                    # tray_type that might survive the relay's auto-clearing.
                    #
                    # tray_exist_bits comes first because that guard cannot tell
                    # a firmware "empty" from PrintLab's own: apply_tray_exist_bits
                    # writes state=9 when the bit is 0 and leaves it there when the
                    # bit returns. A non-RFID spool inserted into a pre-assigned
                    # slot brings no tray_type with it, so the stale 9 made this
                    # expression false forever and the deferred config never fired
                    # — the deadlock #1322 removed from the assign path, still in
                    # place here (#3084, #3100).
                    loaded = spool_present(current_tray) is True or (
                        cur_state == 11 or (cur_state not in (9, 10) and cur_type.strip())
                    )
                    if not fp_type.strip() and loaded and assignment.spool:
                        try:
                            from backend.app.api.routes.inventory import (
                                apply_spool_to_slot_via_mqtt,
                            )

                            await apply_spool_to_slot_via_mqtt(
                                db=db,
                                current_user=None,
                                spool=assignment.spool,
                                printer_id=printer_id,
                                ams_id=assignment.ams_id,
                                tray_id=assignment.tray_id,
                                current_tray_info_idx=current_tray.get("tray_info_idx", ""),
                                current_tray_type=cur_type,
                            )
                            logger.info(
                                "SpoolBuddy pre-config applied on insert: spool %d → printer %d AMS%d-T%d",
                                assignment.spool_id,
                                printer_id,
                                assignment.ams_id,
                                assignment.tray_id,
                            )
                        except Exception:
                            logger.exception(
                                "Pre-config apply failed for spool %d on printer %d AMS%d-T%d",
                                assignment.spool_id,
                                printer_id,
                                assignment.ams_id,
                                assignment.tray_id,
                            )
                        assignment.fingerprint_color = cur_color
                        assignment.fingerprint_type = cur_type
                        continue

                    if not _colors_similar(cur_color, fp_color) or cur_type.upper() != fp_type.upper():
                        # Blank tray data mid-print is a runout, not a swap: the
                        # firmware clears colour and type when it unloads a spool
                        # it just emptied. Unlinking here would erase the record
                        # of which spool fed the print so far.
                        if printing_now and not cur_color.strip() and not cur_type.strip():
                            logger.info(
                                "Auto-unlink skipped: spool %d AMS%d-T%d — tray data cleared during a running print "
                                "(runout?)",
                                assignment.spool_id,
                                assignment.ams_id,
                                assignment.tray_id,
                            )
                            continue
                        # Same reasoning off the print, on firmware's own say-so:
                        # a blank tray report from a slot whose tray_exist_bits
                        # bit is set describes a spool the AMS cannot identify —
                        # a non-RFID one, or one whose slot was reset — not a
                        # spool that was taken out. Deleting the assignment there
                        # threw away the identity the user had supplied, which is
                        # the only place it existed (#3100). A slot the bit calls
                        # empty, or one that carries no bit at all, still unlinks.
                        #
                        # Unless the slot was reported empty first: a removal
                        # already held means a spool came out and another went
                        # in, so the blank report keeps the hold running below
                        # rather than cancelling it (#3186).
                        if (
                            spool_present(current_tray) is True
                            and not cur_color.strip()
                            and not cur_type.strip()
                            and not slot_unlink_grace.is_held(
                                printer_id,
                                ("inventory", assignment.ams_id, assignment.tray_id, assignment.spool_id),
                            )
                        ):
                            logger.info(
                                "Auto-unlink skipped: spool %d AMS%d-T%d — slot still occupied, "
                                "tray reports no filament data yet",
                                assignment.spool_id,
                                assignment.ams_id,
                                assignment.tray_id,
                            )
                            continue
                        # A blank report the presence bit does not vouch for is
                        # still only one push. An idle X1C cleared a whole AMS
                        # unit's bits, colour and type for a moment and lost
                        # four saved assignments that way (#3186); unlink only
                        # if the slot is still blank after the grace period.
                        if not cur_color.strip() and not cur_type.strip():
                            hold_key = ("inventory", assignment.ams_id, assignment.tray_id, assignment.spool_id)
                            if not slot_unlink_grace.removal_confirmed(printer_id, hold_key):
                                held.add(hold_key)
                                logger.info(
                                    "Auto-unlink held: spool %d AMS%d-T%d — tray reports no filament data; "
                                    "unlinking if it is still blank in %ds",
                                    assignment.spool_id,
                                    assignment.ams_id,
                                    assignment.tray_id,
                                    int(slot_unlink_grace.GRACE_SECONDS),
                                )
                                continue
                        # Fingerprint mismatch — but check if tray now matches the
                        # assigned spool (e.g. auto-configure changed the tray).
                        # Both sides are reduced to the type the slot can carry
                        # before comparing: the assign path writes that rather
                        # than the spool's raw material (#2902), so a spool whose
                        # material is a product line — "PLA+", "HTPLA" — reports
                        # back as "PLA" and would otherwise fail this check and
                        # be auto-unlinked from the slot it was just assigned to.
                        # Reducing the printer's side too keeps slots configured
                        # by an older PrintLab, still reporting "PLA+", matching.
                        spool = assignment.spool
                        if spool:
                            spool_color = (spool.rgba or "FFFFFFFF").upper()
                            # Two ways the assign path can have arrived at the
                            # slot's type, so both count as "we wrote this".
                            # The material column is one; the spool's preset is
                            # the other, and it outranks the material when the
                            # spool has one -- a spool whose material says PLA
                            # and whose preset is "Bambu PLA Aero" puts
                            # PLA-AERO in the slot (#2902). Read from the stored
                            # preset name rather than resolving the preset,
                            # because this runs on every AMS push and a cloud
                            # lookup here would be both slow and unavailable on
                            # the unauthenticated replay path.
                            spool_types = {printer_filament_type(spool.material).upper()}
                            if spool.slicer_filament_name:
                                spool_types.add(printer_filament_type(spool.slicer_filament_name).upper())
                            # An imported local preset stores its type outright,
                            # which is what the assign path used -- and the name
                            # above may be unset. One keyed read, and only on a
                            # mismatch, which is rare.
                            #
                            # slicer_filament is free text up to fifty characters,
                            # so the digits have to be checked against the range
                            # of the integer primary key they are about to be
                            # compared with. Postgres raises on an out-of-range
                            # integer rather than simply not matching, and that
                            # would poison this session and abandon the rest of
                            # the cleanup pass.
                            lp_ref = (spool.slicer_filament or "").strip()
                            if lp_ref.isdigit() and int(lp_ref) <= 2147483647:
                                from backend.app.models.local_preset import LocalPreset as _LP

                                lp_type = await db.scalar(select(_LP.filament_type).where(_LP.id == int(lp_ref)))
                                if lp_type:
                                    spool_types.add(printer_filament_type(lp_type).upper())
                            if (
                                _colors_similar(cur_color, spool_color)
                                and printer_filament_type(cur_type).upper() in spool_types
                            ):
                                logger.info(
                                    "Auto-unlink: spool %d AMS%d-T%d — fingerprint mismatch but tray matches spool, updating fp",
                                    assignment.spool_id,
                                    assignment.ams_id,
                                    assignment.tray_id,
                                )
                                assignment.fingerprint_color = cur_color
                                assignment.fingerprint_type = cur_type
                                continue
                        logger.info(
                            "Auto-unlink: spool %d AMS%d-T%d — fingerprint mismatch (cur=%s/%s fp=%s/%s spool=%s/%s)",
                            assignment.spool_id,
                            assignment.ams_id,
                            assignment.tray_id,
                            cur_color,
                            cur_type,
                            fp_color,
                            fp_type,
                            spool.rgba if spool else "?",
                            spool.material if spool else "?",
                        )
                        stale.append(assignment)  # Spool changed
            slot_unlink_grace.settle(printer_id, "inventory", held)
            # Snapshot slots before delete — ORM attribute access after the
            # commit would refresh against a deleted row.
            unlinked_slots = [(a.ams_id, a.tray_id) for a in stale]
            for a in stale:
                await db.delete(a)
            if stale:
                logger.info("Auto-unlinked %d stale spool assignments for printer %d", len(stale), printer_id)
            # Commit any changes (stale deletions and/or fingerprint updates)
            await db.commit()
            # Tell open browsers the assignment is gone (#2575). Only the manual
            # REST assign/unassign endpoints broadcast this event; without it the
            # frontend's spool-assignments cache keeps rendering the unlinked
            # spool on the slot until an unrelated refetch — which reads exactly
            # like "the fix didn't work" (reporter verified: a browser refresh
            # after the swap showed the correct state all along).
            for ams_id, tray_id in unlinked_slots:
                await _rt().ws_manager.broadcast(
                    {
                        "type": "spool_assignment_changed",
                        "printer_id": printer_id,
                        "ams_id": ams_id,
                        "tray_id": tray_id,
                    }
                )
    except Exception as e:
        logger.warning("Spool assignment cleanup failed: %s", e, exc_info=True)


async def _expire_spoolman_empty_slots(printer_id: int, ams_data: list, printing_now: bool) -> None:
    """Delete Spoolman slot rows whose held removal has run its grace period.

    The Spoolman half of the #3186 re-check. The full sync in ``on_ams_change``
    talks to Spoolman for every tray; this only needs the local rows, so it
    repeats that pass's empty-slot decision -- a tray with no type or no colour
    (``parse_ams_tray`` returns None for exactly those), not during a print, and
    not in a slot the presence bit calls occupied -- and nothing else.
    """
    try:
        async with _rt().async_session() as db:
            from backend.app.api.routes.settings import get_setting
            from backend.app.models.spoolman_slot_assignment import SpoolmanSlotAssignment
            from backend.app.services.ams_slot_presence import spool_present

            enabled = await get_setting(db, "spoolman_enabled")
            if not enabled or enabled.lower() != "true":
                return
            sync_mode = await get_setting(db, "spoolman_sync_mode")
            if sync_mode and sync_mode != "auto":
                return

            trays: dict[tuple[int, int], dict] = {}
            for ams_unit in ams_data or []:
                if not isinstance(ams_unit, dict):
                    continue
                for tray in ams_unit.get("tray", []):
                    if isinstance(tray, dict):
                        trays[(int(ams_unit.get("id", 0)), int(tray.get("id", 0)))] = tray

            rows = (
                (
                    await db.execute(
                        select(SpoolmanSlotAssignment).where(SpoolmanSlotAssignment.printer_id == printer_id)
                    )
                )
                .scalars()
                .all()
            )
            held: set[tuple] = set()
            expired: list[tuple[int, int]] = []
            for row in rows:
                tray = trays.get((row.ams_id, row.tray_id))
                if tray is None or printing_now:
                    continue
                if (tray.get("tray_type") or "").strip() and (tray.get("tray_color") or "").strip():
                    continue
                hold_key = ("spoolman", row.ams_id, row.tray_id, row.spoolman_spool_id)
                if spool_present(tray) is True and not slot_unlink_grace.is_held(printer_id, hold_key):
                    continue
                if slot_unlink_grace.removal_confirmed(printer_id, hold_key):
                    expired.append((row.ams_id, row.tray_id))
                else:
                    held.add(hold_key)
            slot_unlink_grace.settle(printer_id, "spoolman", held)
            if not expired:
                return
            # A statement rather than ORM deletes, like the sync pass: the two
            # can overlap, and a row the other already removed must not fail
            # this commit.
            for ams_id, tray_id in expired:
                await db.execute(
                    delete(SpoolmanSlotAssignment).where(
                        SpoolmanSlotAssignment.printer_id == printer_id,
                        SpoolmanSlotAssignment.ams_id == ams_id,
                        SpoolmanSlotAssignment.tray_id == tray_id,
                    )
                )
            await db.commit()
            logger.info("Unlinked %d Spoolman slot(s) that stayed empty for printer %d", len(expired), printer_id)
            for ams_id, tray_id in expired:
                await _rt().ws_manager.broadcast(
                    {
                        "type": "spool_assignment_changed",
                        "printer_id": printer_id,
                        "ams_id": ams_id,
                        "tray_id": tray_id,
                    }
                )
    except Exception as e:
        logger.warning("Spoolman slot re-check failed for printer %s: %s", printer_id, e, exc_info=True)


async def _recheck_held_unlinks(printer_id: int) -> None:
    """Re-run just the slot cleanup against the printer's current AMS state.

    Scheduled by ``slot_unlink_grace`` when it holds a removal. The unlink
    passes otherwise run only when the AMS hash changes, and a slot that went
    empty and stayed empty may never change it again.
    """
    status = _rt().printer_manager.get_status(printer_id)
    # A disconnected printer's state is its last report, not a new one: acting
    # on it would "confirm" a removal nobody has seen for the whole grace
    # period. Leave the holds; the first push after reconnecting decides.
    if status is None or not status.connected:
        return
    ams_raw = status.raw_data.get("ams")
    ams_data = ams_raw.get("ams", []) if isinstance(ams_raw, dict) else ams_raw if isinstance(ams_raw, list) else []
    printing_now = (getattr(status, "state", "") or "").upper() in ("RUNNING", "PAUSE")
    await _rt()._unlink_stale_assignments(printer_id, ams_data, printing_now)
    await _rt()._expire_spoolman_empty_slots(printer_id, ams_data, printing_now)


slot_unlink_grace.set_recheck(_recheck_held_unlinks)
