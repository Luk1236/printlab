"""Bambu Lab AMS and Rack mapping utilities.

Extracted from bambu_mqtt.py for modularity and file size budget compliance.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("backend.app.services.bambu_mqtt")

def parse_ams_filament_backup_from_cfg(cfg_raw: object) -> bool | None:
    """Extract AMS Filament Backup state from a Bambu push_status ``print.cfg`` value.

    OrcaSlicer reads bit 18 of the hex string via
    ``get_flag_bits(cfg, 18)`` (DeviceManager.cpp:4961). Old-protocol families
    (A1 / A1 Mini) omit ``cfg`` entirely; this returns ``None`` for any input
    that doesn't yield a clean integer so downstream consumers preserve today's
    behaviour rather than treating "absent" as "OFF".
    """
    if not isinstance(cfg_raw, str) or not cfg_raw:
        return None
    try:
        return bool((int(cfg_raw, 16) >> 18) & 1)
    except ValueError:
        return None


def is_printer_status_frame(print_data: dict) -> bool:
    """True when a ``print`` payload is the printer reporting its own state.

    Bambu firmware echoes a command's fields back in its acknowledgement, so a
    `project_file` ack carries whatever PrintLab put on the wire — including
    the `cfg` bitmask and the per-job `timelapse` flag. Ingesting those as
    telemetry means reading our own request back as the printer's state
    (#3040). Only `push_status` (and the odd firmware that omits `command`
    entirely on a status frame) describes the printer.
    """
    command = print_data.get("command")
    return command is None or command == "push_status"


# ── A2L "AMS Lite" unit-id normalisation (issue capture 2026-07-20) ──────────
# The A2L reports its 4-slot AMS Lite as physical unit **id 16**, but the
# firmware is internally inconsistent about it:
#   - its tray bitmasks (tray_exist_bits etc.) sit at **bit base 24**, i.e. the
#     position for id 6 (6*4), NOT id 16 (which would be bit 64);
#   - it reports `tray_now` as a **local** 0-3 slot, not a global id;
#   - `ams_mapping2` and per-unit commands use the **physical** id 16.
# So we normalise 16 -> 6 at the MQTT ingest boundary. Global tray ids then land
# at 24-27, which every `ams_id*4+slot` consumer handles unchanged, collides with
# nothing (regular AMS 0-15, AMS-HT 128-135, external 254/255) and passes the
# `ams_id <= 7` DB constraint. We translate 6 -> 16 (and the local slot) back to
# the physical form ONLY on the outbound wire. See memory a2l-am-unit-16.
A2L_LITE_PHYSICAL_AMS_ID = 16
A2L_LITE_NORMALIZED_AMS_ID = 6
A2L_LITE_GLOBAL_BASE = A2L_LITE_NORMALIZED_AMS_ID * 4  # 24


def normalize_am_unit_id(ams_id: int) -> int:
    """Map the A2L AMS-Lite's physical unit id (16) to its normalised id (6).

    Self-scoping: only id 16 is remapped, and no other Bambu device reports an
    AMS unit at id 16 (regular AMS 0-3, AMS-HT 128-135). All other ids pass
    through untouched.
    """
    return A2L_LITE_NORMALIZED_AMS_ID if ams_id == A2L_LITE_PHYSICAL_AMS_ID else ams_id


def wire_tray_color(tray_color: str | None) -> str:
    """Normalise a colour to the form AMS firmware actually parses: UPPERCASE hex.

    P1S firmware 01.10.00.00 parses every lowercase hex letter in ``tray_color``
    as a zero, and does it silently: the command response echoes the value you
    sent and reports ``result: "success"``, so only the next AMS push shows what
    was really stored. Measured on the reporter's machine (#2987), where the
    spool's own ``rgba`` is stored lowercase and went out verbatim:

        sent 09ff00ff  ->  AMS reports 09000000
        sent ff5100ff  ->  AMS reports 00510000
        sent 090000FF  ->  AMS reports 090000FF

    A mangled colour is not merely cosmetic. The auto-unlink sweep compares the
    tray against the spool it is assigned to, so the tray PrintLab just wrote no
    longer matches the spool that asked for it and the assignment is deleted
    seconds after being made -- and re-assigning through the slot modal writes
    the mangled colour back, because the modal seeds itself from the tray.

    Applied here, at the one place the command is built, rather than in each of
    the four callers: a caller that forgets is exactly how this arrived.

    A leading ``#`` is stripped -- the wire format carries bare hex -- and a
    blank stays blank, which is how a slot is cleared.
    """
    return (tray_color or "").strip().lstrip("#").upper()


def a2l_lite_wire_ids(ams_id: int, tray_id: int) -> tuple[int, int, int] | None:
    """Translate a normalised A2L slot back to the physical wire form.

    Returns ``(wire_ams_id, wire_slot_id, wire_global_tray)`` for the AMS-Lite
    (normalised id 6), else ``None`` for every other unit.

    CONFIRMED from the firmware's own `ams_mapping2` ({ams_id:16, slot_id:0-3}):
    the wire uses the physical unit id 16 with a **local** 0-3 slot. NOT yet
    confirmed by capture: the physical **global** tray value some commands put on
    the wire (load `target`, extrusion_cali `tray_id`) — we extrapolate it as
    16*4+slot = 64-67 to stay consistent with the physical unit id. This is the
    single unverified encoding; a BambuStudio->A2L capture of a load or cali
    command would settle it, and it lives only here.
    """
    if ams_id != A2L_LITE_NORMALIZED_AMS_ID:
        return None
    local_slot = tray_id % 4
    return (
        A2L_LITE_PHYSICAL_AMS_ID,
        local_slot,
        A2L_LITE_PHYSICAL_AMS_ID * 4 + local_slot,
    )


def resolve_external_spools_in_mapping(ams_mapping: object, ams_mapping2: object, is_dual_nozzle: bool) -> object:
    """Put the external spool back into a captured flat ``ams_mapping`` (#3166).

    The firmware rejects 254/255 in the flat list, so BambuStudio and our own
    dispatch both write an external spool there as -1 -- the same value as a
    slot that isn't fed at all -- and carry the real target only in
    ``ams_mapping2`` as ``{ams_id: 254|255, slot_id: 0}``. Capturing the flat
    list alone turns "printed from the external spool" into "unmapped", and
    usage then lands on whatever tray the fallback guesses.

    Each -1 whose ``ams_mapping2`` entry names an external spool becomes the
    global tray the rest of PrintLab uses: the ams_id itself on dual-nozzle
    printers (254 = left/deputy, 255 = right/main), 254 on single-nozzle
    printers, which have one external spool that the wire always calls 255.
    ``{255, 255}`` is the unmapped marker and stays -1. Every other entry is
    left exactly as captured. Without a usable ``ams_mapping2`` the input is
    returned unchanged.
    """
    if not isinstance(ams_mapping, list) or not isinstance(ams_mapping2, list):
        return ams_mapping
    if len(ams_mapping2) != len(ams_mapping):
        return ams_mapping
    resolved = list(ams_mapping)
    for i, (flat, detail) in enumerate(zip(ams_mapping, ams_mapping2, strict=True)):
        if flat != -1 or not isinstance(detail, dict):
            continue
        ams_id = detail.get("ams_id")
        slot_id = detail.get("slot_id")
        if ams_id not in (254, 255) or slot_id == 255:
            continue
        resolved[i] = ams_id if is_dual_nozzle else 254
    return resolved


def apply_tray_exist_bits(
    units: list,
    tray_exist_bits_str: str | int | None,
    *,
    power_on_flag: bool = True,
    log_label: str | None = None,
    annotate_exists: bool = False,
) -> int:
    """Wipe stale per-tray filament fields on slots whose `tray_exist_bits` bit is 0.

    `tray_exist_bits` is firmware's canonical "which slots have a spool" bitmask
    (BambuStudio uses it too). For every slot whose bit is 0, promote the tray
    `state` to 9 (firmware's "no spool" code) and clear `tray_type` / `tray_color`
    / `tray_info_idx` / `tag_uid` / `tray_uuid` / `remain` etc so downstream
    readers (PrintLab's AMS card, the VP slicer-facing cache, inventory short-
    circuits keyed on `state in {9, 10}`) all see one canonical empty-slot signal
    instead of guessing from payload shape (#1322, #147).

    Two callers share this helper to keep their views consistent:

    1. ``_handle_ams_data`` for PrintLab's internal AMS state (printer card).
    2. ``virtual_printer.mqtt_bridge._on_printer_raw`` for the cached slicer-
       facing push_status (#1726 — without this the VP would forward stale
       per-tray fields for empty slots, and BambuStudio's Sync would render
       phantom loaded slots).

    Skipped only on the printer-shutdown pattern: all-zero bits paired with
    ``power_on_flag=False`` (#765). Non-zero bits with ``power_on_flag=False``
    is valid idle-printer state (#1365 — X1C between prints) and MUST be applied
    so spool removal is detected without requiring a manual reconnect.

    AMS-HT units (``id`` 128-135) are single-tray dry boxes whose presence bit
    is packed as ONE consecutive bit starting at 16 (``16 + (ams_id - 128)``),
    NOT ``ams_id * 4`` (which would overflow to bit 512+). This is the firmware's
    authoritative empty signal for the HT — the only working clear path, since
    the HT keeps echoing stale ``tray_type`` and its ``state`` is firmware-variant
    (#2670). Verified against OrcaSlicer ``DevFilaSystem.cpp``
    (``is_exists = tray_exist_bits >> (16 + (ams_id-128))``) and a live H2D
    capture (HT-A → bit 16). The A2L-Lite lands at bits 24-27 via the regular
    ``ams_id * 4`` formula, matching OrcaSlicer's ``AMS_LITE_MIXED`` offset; the
    unit id is folded through ``normalize_am_unit_id`` first so callers holding
    the raw physical id 16 get the same bit base as callers holding the
    normalised 6 (#2697).

    `tray_exist_bits_str` is expected as a hex string (firmware sends it that
    way). Ints are tolerated for defensive symmetry but typically not seen
    on the wire. ``None`` / empty / unparseable → no-op.

    ``annotate_exists`` writes a per-tray ``exists`` bool (from the bitmask) on
    every processed slot. This is firmware's authoritative "spool physically
    present" signal — the same one BambuStudio uses to draw a ``?`` for a
    non-RFID spool in an otherwise-unidentified slot. PrintLab's AMS card keys
    empty-vs-unknown off it so a non-Bambu spool shows ``?`` instead of "Empty"
    (#2527). Only the internal (printer-card) caller sets this; the VP bridge
    leaves it False so the ``exists`` key never reaches the slicer wire format.

    Mutates ``units`` in place. Returns the number of slots cleared.
    """
    if not tray_exist_bits_str:
        return 0
    try:
        if isinstance(tray_exist_bits_str, int):
            tray_exist_bits = tray_exist_bits_str
        else:
            tray_exist_bits = int(tray_exist_bits_str, 16)
    except (ValueError, TypeError):
        return 0
    if tray_exist_bits == 0 and not power_on_flag:
        return 0
    if not isinstance(units, list):
        return 0

    cleared = 0
    for ams_unit in units:
        if not isinstance(ams_unit, dict):
            continue
        ams_id_raw = ams_unit.get("id")
        if ams_id_raw is None:
            continue
        try:
            ams_id = int(ams_id_raw) if isinstance(ams_id_raw, str) else ams_id_raw
        except (ValueError, TypeError):
            continue
        if not isinstance(ams_id, int):
            continue
        # The A2L AMS-Lite reaches this helper under either id: `_handle_ams_data`
        # normalises 16 -> 6 before calling, but the VP bridge parses the raw
        # printer payload itself (`mqtt_bridge._on_printer_raw`) and still holds
        # the physical 16. Both mean bit base 24, so fold them together here
        # rather than relying on every caller to normalise first — reading 16 as
        # 16*4 = bit 64 finds nothing set and wipes every A2L slot (#2697).
        ams_id = normalize_am_unit_id(ams_id)
        # AMS-HT (n3s, id 128-135): single tray, presence bit at 16+(ams_id-128).
        # Regular AMS (and the A2L-Lite normalised to id 6): ams_id*4 + tray_id.
        # Anything outside those ranges has no known bit layout — don't guess it.
        is_ht = 128 <= ams_id <= 135
        if not is_ht and not (0 <= ams_id <= 15):
            continue
        for tray in ams_unit.get("tray", []):
            if not isinstance(tray, dict):
                continue
            tray_id_raw = tray.get("id")
            if tray_id_raw is None:
                continue
            try:
                tray_id = int(tray_id_raw) if isinstance(tray_id_raw, str) else tray_id_raw
            except (ValueError, TypeError):
                continue
            if not isinstance(tray_id, int):
                continue
            global_bit = (16 + (ams_id - 128)) if is_ht else (ams_id * 4 + tray_id)
            slot_exists = (tray_exist_bits >> global_bit) & 1
            if annotate_exists:
                tray["exists"] = bool(slot_exists)
            if slot_exists:
                continue
            tray["state"] = 9
            if tray.get("tray_type"):
                if log_label:
                    logger.debug(
                        f"[{log_label}] Clearing empty slot: AMS {ams_id} slot {tray_id} "
                        f"(tray_exist_bits bit {global_bit} = 0)"
                    )
                tray["tray_type"] = ""
                tray["tray_sub_brands"] = ""
                tray["tray_color"] = ""
                tray["tray_id_name"] = ""
                tray["tag_uid"] = "0000000000000000"
                tray["tray_uuid"] = "00000000000000000000000000000000"
                tray["tray_info_idx"] = ""
                tray["remain"] = 0
                cleared += 1
    return cleared


# --- H2C nozzle-rack dispatch mapping (#2800) -------------------------------
#
# Physical nozzle IDs the H2C reports for its six rack slots, verified on
# hardware. They sit well clear of the fixed hotend's own physical ID, so a
# rack position is never mistakable for the nozzle on the other carriage.
#
# Extruder indices are a different namespace that happens to overlap these
# low numbers -- index 1 means the rack, physical ID 1 means the fixed hotend.
# Nothing below may pass a value from one namespace to the other untranslated;
# doing exactly that is what #2800 was.
_RACK_NOZZLE_IDS = frozenset(range(16, 22))

# BambuStudio dispatches a fixed-length nozzle_mapping on rack models: one
# physical nozzle ID per filament slot, -1 for slots the plate does not print.
#
# Briefly changed to the plate's own slot count on the strength of a single
# 3-entry capture, then changed back: Studio's dispatch of a real 3-filament
# project print on the maintainer's H2C is 32 entries ([16, 1, 18, -1 x29],
# captured 2026-08-13 17:20, and that print completed). The 3-entry capture was
# a calibration job, so the length varies with whatever Studio is doing rather
# than with the filament count -- which makes it the wrong thing to derive.
_RACK_WIRE_SLOTS = 32

# The two carriages, as extruder indices in the form the queue stores (already
# translated through the file's physical_extruder_map).
#
# Measured on the maintainer's H2C 2026-08-14, from three sources that agree:
#
#   - telemetry: ``ams_extruder_map {'0': 1, '1': 0, '2': 0}`` -- AMS 0 feeds
#     extruder 1, AMS 1 and 2 feed extruder 0;
#   - BambuStudio's own dispatch of a plate using all three units sent AMS 0's
#     filament to physical nozzle 1 and AMS 1's to rack positions 16 and 18,
#     and that print completed. So extruder 1 is the fixed hotend and extruder
#     0 is the rack;
#   - our own constants were internally inconsistent about it: physical nozzle
#     id N sits on extruder N (see the L/R split in PrintersPage), and
#     ``_FIXED_NOZZLE_ID`` is 1, which cannot be reconciled with a fixed
#     extruder index of 0.
#
# These were the other way round until then, which is what dispatched a plate
# to the carriage that had not been levelled and printed its first layer in
# mid-air. That value came from #2800, where dispatching [17, -1, -1, 1] printed
# in mid-air and [1, -1, -1, 17] printed correctly -- but that A/B measured
# which *wire* worked, and the extruder indices were only inferred from it by
# pairing with a slot_extruders list the then-buggy 3MF reader had produced. The
# wire result stands; the inference from it did not.
_FIXED_EXTRUDER_ID = 1
_RACK_EXTRUDER_ID = 0

# The fixed hotend's physical ID, which is *not* its extruder index. The same
# hardware A/B ruled the index out: [0, -1, -1, 17] was rejected by the printer
# outright, which would not start the job at all. Native BambuStudio captures
# of a mixed plate agree -- [1, 17, ...], and [17, 1, ...] once the filament
# slot order is swapped, so the fixed side is 1 whichever slot it lands in.
_FIXED_NOZZLE_ID = 1


def resolve_rack_nozzle_mapping(
    slot_extruders: list[int],
    rack_nozzle_id: int | None,
) -> list[int] | None:
    """Expand a per-slot extruder mapping into an H2C physical nozzle_mapping.

    ``slot_extruders`` is the compact form stored on the queue item: MQTT
    extruder index per filament slot (index 0 = slot 1), -1 for a slot the
    plate does not print. ``rack_nozzle_id`` is the rack position the printer
    reports as live.

    Returns a ``_RACK_WIRE_SLOTS``-long list of physical nozzle IDs, or None
    when the mapping cannot be resolved with confidence -- in which case the
    caller omits the field entirely and the firmware falls back to its own
    nozzle pick, exactly as it did before this translation existed. Omitting
    is deliberately the failure mode: a *wrong* physical ID makes the printer
    level with one nozzle and print with another several millimetres off the
    bed, which is far worse than letting the firmware choose.

    Returns None specifically when:

    - a slot needs the rack but the printer has not reported a live rack
      position (mid-swap, or a stale connection);
    - no slot needs the rack at all. BambuStudio omits nozzle_mapping entirely
      for a plate sliced for the fixed hotend only (#2800 capture), so this
      matches it rather than naming a nozzle it does not have to name;
    - a slot names a carriage that is neither of the two an H2C has, which
      means the file was mapped for a machine this translation does not model;
    - the plate needs more slots than the wire format carries;
    - the input is not a list of whole numbers.

    Total by construction: it raises nothing, because the only caller is
    building an MQTT print command with no exception handler above it and the
    queue item has already been committed as `printing` by then. An
    unparseable input has to degrade to "let the firmware pick", not to a job
    wedged in a state no print will ever leave.
    """
    if not isinstance(slot_extruders, list) or not slot_extruders:
        return None
    if len(slot_extruders) > _RACK_WIRE_SLOTS:
        return None
    if not isinstance(rack_nozzle_id, int) or isinstance(rack_nozzle_id, bool):
        return None
    if rack_nozzle_id not in _RACK_NOZZLE_IDS:
        return None

    # Normalise first so the checks below, and the values that reach the wire,
    # are known ints. bool is an int subclass and would otherwise serialise as
    # a JSON `true`; None means "slot not printed" and is folded into -1.
    normalised: list[int] = []
    for extruder in slot_extruders:
        if extruder is None:
            normalised.append(-1)
        elif isinstance(extruder, int) and not isinstance(extruder, bool):
            normalised.append(extruder)
        else:
            return None

    if _RACK_EXTRUDER_ID not in normalised:
        return None

    wire = [-1] * _RACK_WIRE_SLOTS
    for index, extruder in enumerate(normalised):
        if extruder < 0:
            continue
        if extruder == _RACK_EXTRUDER_ID:
            wire[index] = rack_nozzle_id
        elif extruder == _FIXED_EXTRUDER_ID:
            wire[index] = _FIXED_NOZZLE_ID
        else:
            # An H2C has these two carriages and no others. A third index is a
            # file mapped for something else, and forwarding it raw would name
            # a physical nozzle by an index that does not identify one.
            return None
    return wire


# A rack position as the operator counts it (and as the printer card and
# BambuStudio both label it) is 1-based; the physical nozzle id is 15 higher.
# Measured 2026-08-14: a plate dispatched with the operator picking R1 and R2
# sent 16 and 17, and the same plate picking R1 and R3 sent 16 and 18.
_RACK_POSITION_BASE = 15
RACK_POSITIONS = tuple(range(1, len(_RACK_NOZZLE_IDS) + 1))


def rack_position_to_nozzle_id(position: int) -> int | None:
    """Physical nozzle id for a 1-based rack position, or None if out of range."""
    if not isinstance(position, int) or isinstance(position, bool):
        return None
    if position not in RACK_POSITIONS:
        return None
    return _RACK_POSITION_BASE + position


def _rack_slot_is_eligible(slot: dict, diameter: str, volume_type: str) -> bool:
    """Whether a live rack slot can print a group wanting this nozzle.

    Mirrors the filter BambuStudio applies in its own picker: the position has
    to hold a nozzle at all, and that nozzle has to match the slice's diameter
    and flow type. A mismatch here is not cosmetic -- it is the printer being
    asked to lay down a 0.4 extrusion through a 0.2 orifice.
    """
    if not isinstance(slot, dict):
        return False
    slot_diameter = str(slot.get("diameter") or "").strip()
    slot_type = str(slot.get("type") or "").strip()
    if not slot_diameter and not slot_type:
        return False  # empty position

    # "0.40" and "0.4" are the same nozzle spelled two ways -- the 3MF pads,
    # the printer does not.
    try:
        if round(float(slot_diameter), 2) != round(float(diameter), 2):
            return False
    except (TypeError, ValueError):
        return False

    # Flow type: the printer reports a code ("HS", "HH01"), the slice reports a
    # name ("Standard", "High Flow"). Compared only when both are stated, so a
    # printer that omits the code is not thereby ruled ineligible.
    wanted = volume_type.strip().lower()
    if wanted and slot_type:
        is_high_flow = slot_type.upper().startswith("HH")
        if wanted.startswith("high flow") != is_high_flow:
            return False
    return True


# The nozzle currently picked up onto the rack carriage. Physical id 1 is the
# fixed hotend (``_FIXED_NOZZLE_ID``), so the other carriage entry is 0.
_RACK_CARRIAGE_NOZZLE_ID = 0


def _rack_by_position(rack_slots: list[dict]) -> dict[int, dict]:
    """Live rack contents keyed by 1-based position, mounted nozzle included.

    The firmware omits a rack id entirely while that nozzle is picked up onto
    the carriage (#943) -- it does not send an empty placeholder. Taking the
    omission at face value would rule the nozzle ineligible for the very print
    that wants it, and it is the single most likely position to be picked,
    because it is the one the last print left mounted.

    The absent id is recoverable only when exactly one is missing: rack ids are
    fixed at 16..21, so a single gap alongside a loaded carriage is that
    carriage's nozzle. Two or more gaps are genuinely ambiguous -- an operator
    with four nozzles in six positions looks the same -- so those stay absent
    and the caller treats them as empty.

    Measured 2026-08-14 09:02 on the maintainer's H2C: ``IDs: [16, 1, 21, 19,
    18, 0, 20]`` -- both carriages present, rack id 17 the lone gap.
    """
    by_position: dict[int, dict] = {}
    carriage: dict | None = None
    for slot in rack_slots or []:
        if not isinstance(slot, dict) or not isinstance(slot.get("id"), int):
            continue
        if slot["id"] == _RACK_CARRIAGE_NOZZLE_ID:
            carriage = slot
            continue
        position = slot["id"] - _RACK_POSITION_BASE
        if position in RACK_POSITIONS:
            by_position[position] = slot

    missing = [position for position in RACK_POSITIONS if position not in by_position]
    if len(missing) == 1 and carriage is not None and (carriage.get("diameter") or carriage.get("type")):
        by_position[missing[0]] = carriage
    return by_position


def resolve_rack_plan_mapping(
    slot_groups: list[int],
    groups: dict[int, dict],
    choice: dict[int, int],
    rack_slots: list[dict],
) -> tuple[list[int] | None, str | None]:
    """Build a physical ``nozzle_mapping`` from a rack plan and a position pick.

    This is the multi-hotend counterpart to :func:`resolve_rack_nozzle_mapping`.
    That one can only name the single live rack position, so a plate wanting a
    different hotend per group is unresolvable to it. Here each group carries
    its own position, which is the operator's choice (#1784) -- the 3MF states
    it nowhere, proven by dispatching one plate twice with different picks and
    diffing the two files down to float noise.

    ``choice`` may be partial or empty; groups it does not name are assigned
    from the live rack, preferring a position already loaded with the group's
    own filament colour and otherwise taking the lowest eligible one.

    Returns ``(wire, None)`` on success, or ``(None, reason)`` where *reason*
    is a sentence naming what could not be satisfied. The caller decides what
    to do with a failure, and the two cases differ: a stale *explicit* pick
    should stop the print, while a failed auto-assignment should degrade to
    letting the firmware choose, exactly as before this existed.
    """
    if not isinstance(slot_groups, list) or not slot_groups:
        return None, "the plate lists no filament slots"
    if len(slot_groups) > _RACK_WIRE_SLOTS:
        return None, f"the plate needs {len(slot_groups)} filament slots and the printer takes {_RACK_WIRE_SLOTS}"

    by_position = _rack_by_position(rack_slots)

    # Assign every rack-bound group a position before building the wire, so a
    # group can never be handed one an earlier group already took. Explicit
    # picks are placed first: an auto-assignment must yield to them rather than
    # claim a position the operator asked for.
    assigned: dict[int, int] = {}
    rack_group_ids = sorted(gid for gid, g in groups.items() if g.get("on_rack"))

    for group_id in rack_group_ids:
        position = choice.get(group_id)
        if position is None:
            continue
        group = groups[group_id]
        if rack_position_to_nozzle_id(position) is None:
            return None, f"rack position {position} does not exist"
        if position in assigned.values():
            return None, f"rack position {position} is picked for more than one filament group"
        slot = by_position.get(position)
        if slot is None:
            return None, f"the printer reports nothing at rack position {position}"
        if not _rack_slot_is_eligible(slot, group.get("nozzle_diameter", ""), group.get("volume_type", "")):
            return None, (
                f"rack position {position} holds a "
                f"{slot.get('diameter') or 'missing'} {slot.get('type') or ''} nozzle, "
                f"and the plate needs {group.get('nozzle_diameter')} {group.get('volume_type')}".replace("  ", " ")
            )
        assigned[group_id] = position

    for group_id in rack_group_ids:
        if group_id in assigned:
            continue
        group = groups[group_id]
        eligible = [
            position
            for position in RACK_POSITIONS
            if position not in assigned.values()
            and position in by_position
            and _rack_slot_is_eligible(
                by_position[position], group.get("nozzle_diameter", ""), group.get("volume_type", "")
            )
        ]
        if not eligible:
            return None, (
                f"no free rack position holds a {group.get('nozzle_diameter')} "
                f"{group.get('volume_type')} nozzle for filament group {group_id}"
            )
        # Prefer a position already carrying this group's colour: picking it
        # means the operator does not have to move filament to make the print
        # match what they asked for.
        wanted_colour = str(group.get("filament_color") or "").strip().lstrip("#").upper()[:6]
        assigned[group_id] = next(
            (
                position
                for position in eligible
                if wanted_colour
                and str(by_position[position].get("filament_color") or "").strip().lstrip("#").upper()[:6]
                == wanted_colour
            ),
            eligible[0],
        )

    wire = [-1] * _RACK_WIRE_SLOTS
    for index, group_id in enumerate(slot_groups):
        if not isinstance(group_id, int) or isinstance(group_id, bool) or group_id < 0:
            continue  # slot this plate does not print
        group = groups.get(group_id)
        if group is None:
            return None, f"filament slot {index + 1} names group {group_id}, which the plate does not describe"
        if not group.get("on_rack"):
            wire[index] = _FIXED_NOZZLE_ID
            continue
        nozzle_id = rack_position_to_nozzle_id(assigned[group_id])
        if nozzle_id is None:  # pragma: no cover - assigned only ever holds valid positions
            return None, f"filament group {group_id} resolved to no rack position"
        wire[index] = nozzle_id

    if all(value == -1 for value in wire):
        return None, "the plate assigns no filament to a nozzle"
    return wire, None

