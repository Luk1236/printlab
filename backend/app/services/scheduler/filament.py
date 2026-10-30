"""Filament- und AMS-Abgleich des Druckplaners.

Kandidatenwahl je Auftrag, Filament-Grenzen, Tray-Zuordnung und die
Trocknungs-Erkennung. Aus ``print_scheduler.py`` ausgelagert, damit die
Datei wieder Platz für Änderungen hat; die Namen werden dort weiterhin
importiert, Aufrufer und Tests arbeiten unverändert über
``backend.app.services.print_scheduler``.
"""

import json
from dataclasses import dataclass

from backend.app.models.print_queue import PrintQueueItem, PrintQueueVariant
from backend.app.services.bambu_mqtt import HMS_MQTT_VERIFY_FAILED
from backend.app.services.spool_assignment_notifications import (
    _global_tray_from_assignment,
    _slot_label_from_global_tray,
)
from backend.app.utils.printer_models import is_dual_nozzle_model, normalize_printer_model


def _ams_slot_label(ams_id: int, tray_id: int) -> str:
    """Human slot name for an assignment tuple, in the spelling already in use.

    Composed from the notification side's own pair rather than spelled out again
    here. The hand-rolled version this replaces got three real slot kinds wrong:
    ams_id 254 fell into its ``>= 128`` branch and came out as ``HT-`` plus
    ``chr(191)``; both externals collapsed to one label, because an external
    assignment stores ams_id 255 with tray_id picking left or right
    (inventory.py:1771, ``ext_id = data.tray_id + 254``); and an A2L AMS-Lite,
    normalised to unit 6, read as ``AMS-G`` instead of ``Lite-``.

    Naming the same slot two ways is its own defect once an alert and the
    Inventory page are meant to be talking about the same tray, so this defers
    rather than adding a fifth spelling.
    """
    return _slot_label_from_global_tray(_global_tray_from_assignment(ams_id, tray_id))


def _remaining_percent(label_weight: int | float | None, weight_used: float | None) -> float | None:
    """Remaining filament as a percentage of the label weight.

    The same arithmetic the Inventory page's Low Stock count uses, and it works
    unchanged in both inventory modes: internal spools store ``weight_used``
    directly, and ``_map_spoolman_spool`` derives it from Spoolman's
    ``remaining_weight`` so the shape matches. Returns None when there is no
    label weight to be a percentage of -- a spool that cannot say how full it
    started cannot say how empty it is.
    """
    if not label_weight or label_weight <= 0:
        return None
    remaining = max(0.0, float(label_weight) - float(weight_used or 0.0))
    return remaining / float(label_weight) * 100.0


@dataclass(slots=True)
class _ModelCandidate:
    """One (file, printer model) pair the model-based matcher may try.

    Model-based assignment used to have exactly one of these per item, held
    directly in the item's own columns. Cross-model queue items (#671) have
    several, held in ``print_queue_variants``. Both shapes are normalised into
    this so the matching, the cross-model gate and the waiting-reason handling
    are written once and an item without variants provably takes the same path
    it took before variants existed.

    ``variant`` is None for the item's own columns and set for a real variant
    row, which is what :meth:`PrintScheduler._resolve_variant` writes onto the
    item once that candidate wins.
    """

    target_model: str | None
    sliced_for: str | None
    required_filament_types: str | None
    filament_overrides: str | None
    variant: "PrintQueueVariant | None" = None


def _sliced_for_model(archive, library_file) -> str | None:
    """Model a 3MF declares it was sliced for, from whichever source holds it."""
    if archive is not None:
        return archive.sliced_for_model
    if library_file is not None and library_file.file_metadata:
        return library_file.file_metadata.get("sliced_for_model")
    return None


def _filament_constraints(candidate: _ModelCandidate) -> tuple[list[str] | None, list[dict] | None]:
    """The filament a candidate needs, as ``(types, overrides)``.

    Both columns are JSON text written by the slicer step. Malformed content is
    treated as no constraint rather than as an error: a job whose overrides
    cannot be parsed still prints, it just gets no filament-based narrowing.

    Overrides carry their own types, so the returned type list is the union of
    the two — an override on one slot must not drop the requirements of the
    slots it says nothing about.

    Shared by the matcher and by the smart-plug wake step so both ask a printer
    for the same filament (#2876). Waking a printer the matcher would then
    reject on colour is the bug this exists to prevent.
    """
    required_types = None
    if candidate.required_filament_types:
        try:
            required_types = json.loads(candidate.required_filament_types)
        except json.JSONDecodeError:
            pass

    filament_overrides = None
    if candidate.filament_overrides:
        try:
            filament_overrides = json.loads(candidate.filament_overrides)
        except json.JSONDecodeError:
            pass

    effective_types = required_types
    if filament_overrides:
        override_types = sorted({o["type"] for o in filament_overrides if "type" in o})
        if override_types:
            effective_types = sorted(set(required_types or []) | set(override_types))

    return effective_types, filament_overrides


def _could_take_printer(item: PrintQueueItem, printer_id: int, printer_model: str | None) -> bool:
    """Whether ``item`` was competing for the printer another item just took.

    The SJF starvation guard marks a job as jumped when a shorter one lower in
    the queue takes a printer it wanted. A pinned job and an "Any <model>" job
    compete for the same printer, so the guard has to look across both lanes
    (#3200); looking only inside the dispatched item's own lane let a stream of
    short model-based jobs hold a longer pinned job back indefinitely.

    Location filters are not checked: over-marking only lifts an item that was
    going to wait anyway, while under-marking is the starvation this prevents.
    """
    if item.printer_id is not None:
        return item.printer_id == printer_id
    if not printer_model:
        return False
    wanted = (normalize_printer_model(printer_model) or printer_model).lower()
    models = [v.target_model for v in item.variants] if item.variants else [item.target_model]
    return any(m and (normalize_printer_model(m) or m).lower() == wanted for m in models)


def _candidates_for(item: PrintQueueItem) -> list[_ModelCandidate]:
    """Candidate files for ``item``, best first.

    An item with no variant rows yields exactly one candidate built from its own
    columns — the pre-#671 behaviour, unchanged.

    Variants come back least-attempted first, ties broken by the user's
    ``position``. On the first pass every count is zero, so this is purely the
    user's priority order. After a start-watchdog bounce the printer that failed
    drops behind, so the next lap tries the other machine rather than spending the
    item's whole retry budget on the one that is wedged. Once every candidate has
    been tried equally often they cycle again, which keeps the item-level
    ``DISPATCH_MAX_ATTEMPTS`` bound from #2555 intact — a job with alternatives
    still gives up, it just does not give up without trying them.
    """
    if not item.variants:
        if not item.archive_id and not item.library_file_id:
            # Nothing to print at all. Dispatching would fail deep in the upload
            # on "No archive_id or library_file_id"; the caller holds the item
            # with an explanation instead.
            return []
        return [
            _ModelCandidate(
                target_model=item.target_model,
                sliced_for=_sliced_for_model(item.archive, item.library_file),
                required_filament_types=item.required_filament_types,
                filament_overrides=item.filament_overrides,
            )
        ]

    # Drop candidates whose file is gone or in the trash. Both are reachable and
    # neither is covered by the schema: library deletes are soft (the row lives
    # on with ``deleted_at`` set, which no foreign key can express), and SQLite
    # ships with ``PRAGMA foreign_keys`` off, so the ON DELETE CASCADE never
    # fires there and a hard delete leaves the variant row pointing at nothing.
    usable = [v for v in item.variants if v.library_file is not None and v.library_file.deleted_at is None]

    ordered = sorted(usable, key=lambda v: (v.attempt_count or 0, v.position, v.id))
    return [
        _ModelCandidate(
            target_model=v.target_model,
            sliced_for=_sliced_for_model(None, v.library_file),
            required_filament_types=v.required_filament_types,
            filament_overrides=v.filament_overrides,
            variant=v,
        )
        for v in ordered
    ]


def _is_busy_only(waiting_reason: str) -> bool:
    """Whether the waiting reason only names busy printers.

    A job waiting on busy printers starts by itself once one finishes, so the
    queue does not notify the user for it.
    """
    parts = [p.strip() for p in waiting_reason.split(" | ")]
    return all(p.startswith("Busy:") for p in parts)


def _collapse_waiting_reasons(per_model: list[tuple[str | None, str]]) -> str | None:
    """Fold one waiting reason per candidate into a single line for the item.

    A cross-model item produces a reason per candidate, and pasting them
    together unlabelled reads as gibberish ("No idle printer; PETG not loaded"
    — on which machine?). Each reason is prefixed with its model, except in the
    single-candidate case where the item already displays its target model and
    the prefix would be noise.

    Identical reasons collapse rather than repeat, so three idle-less models
    read as one clause.

    When *every* candidate is merely busy the parts are joined with the ``" | "``
    separator :meth:`PrintScheduler._is_busy_only` already parses, and left
    unprefixed. That case must keep testing busy-only: a fleet that is simply
    printing needs no user action, and labelling the clauses would turn each pass
    over a two-model item into a "job waiting" notification.
    """
    reasons = [(model, reason) for model, reason in per_model if reason]
    if not reasons:
        return None
    if len(reasons) == 1:
        return reasons[0][1]

    distinct = list(dict.fromkeys(reason for _model, reason in reasons))
    if len(distinct) == 1:
        return distinct[0]

    if all(_is_busy_only(reason) for _model, reason in reasons):
        return " | ".join(distinct)

    return "; ".join(f"{model or 'unassigned'}: {reason}" for model, reason in reasons)


def _candidate_model_label(candidates: list[_ModelCandidate]) -> str | None:
    """Human label for the models an item is waiting on ("H2S or H2C").

    Notifications take a single target model. For a cross-model item the item's
    own ``target_model`` is whichever variant happens to be first, which reads as
    a lie once it is the H2C that actually runs — so name all of them.
    """
    models = list(dict.fromkeys(c.target_model for c in candidates if c.target_model))
    if not models:
        return None
    return " or ".join(models)


def _mapping_is_all_unresolved(mapping: list | None) -> bool:
    """True if ``mapping`` is a non-empty list whose every entry is the
    unresolved sentinel (-1 / None) — i.e. no required slot ever matched a tray.

    Such a mapping is a bug artifact: a frontend status-load race can serialize
    ``[-1]`` before the printer's AMS trays are known (#2589). It must be
    recomputed from live status at dispatch rather than trusted, otherwise it
    reaches the print command and is silently downgraded to external-spool mode.

    A partially-resolved mapping (``[-1, -1, 5]`` where slot 3 matched, or a
    padding ``-1`` for a slot this plate does not print) is NOT unresolved. An
    explicit external selection (``>= 254``) is NOT unresolved either — those
    keep their meaning.
    """
    if not isinstance(mapping, list) or not mapping:
        return False
    return all(t is None or (isinstance(t, int) and t < 0) for t in mapping)


# Global tray ids at or above this are the external spool(s), not an AMS slot:
# 254 is the deputy feed and 255 the main one. Mirrors the sentinel documented
# on `_mapping_is_all_unresolved`.
_EXTERNAL_TRAY_ID_MIN = 254


def _consumed_mapping_entries(mapping: list | None, required: list[dict] | None) -> list | None:
    """The ``mapping`` entries for the slots this plate actually prints.

    ``required`` comes from ``extract_filament_requirements``, which drops any
    filament with ``used_g <= 0`` — so a slot_id present there is one the plate
    consumes, and one absent from it is padding. That distinction is why this
    decision lives here and not in the MQTT command builder: a ``-1`` in the
    mapping means either "this plate does not print filament N" or "we never
    worked out which tray", and only the plate's own filament list separates
    them. The builder sees both as the same byte, which is how a plate whose one
    printed filament sat on the external spool went out as `use_ams=true` with a
    mapping of nothing but -1 and stalled at preheat until the firmware gave up
    with 07FF_8012 (#3087).

    Returns None whenever the two cannot be lined up — no mapping, no parsed
    requirements, or a requirement the mapping is too short to cover — so every
    caller falls back to existing behaviour rather than acting on a guess.
    """
    if not isinstance(mapping, list) or not mapping or not required:
        return None
    entries = []
    for filament in required:
        slot_id = filament.get("slot_id")
        if not isinstance(slot_id, int) or not 1 <= slot_id <= len(mapping):
            # The mapping and the requirements disagree about how many filaments
            # the file has. They came from different reads, so judge nothing.
            return None
        entries.append(mapping[slot_id - 1])
    return entries or None


def _is_external_tray(tray_id) -> bool:
    """True for an explicit external-spool selection (254/255), not for an
    unresolved slot and not for an AMS tray."""
    if tray_id is None:
        return False
    try:
        return int(tray_id) >= _EXTERNAL_TRAY_ID_MIN
    except (TypeError, ValueError):
        return False


def _might_be_dual_nozzle(printer_model: str | None, status) -> bool:
    """Whether this printer could have two extruders, judged generously.

    On a dual-nozzle printer ``use_ams`` is nozzle routing rather than an
    AMS on/off flag — H2D Pro firmware reads it as an extruder index — which is
    why the MQTT command builder skips its own use_ams reconcile there. Anything
    that might be dual-nozzle therefore keeps whatever ``use_ams`` it arrived
    with, external spools or not.

    Deliberately over-eager: a wrong "yes" only means this printer keeps the
    behaviour it has always had, while a wrong "no" would rewrite a field that
    steers which nozzle prints. The model name is the first answer (it is what
    the command builder falls back to as well), then the same live evidence the
    dispatcher's extruder annotation uses — a second nozzle reporting a
    diameter, a populated ``ams_extruder_map``, or more than one external feed,
    since a single-nozzle printer has exactly one.
    """
    if is_dual_nozzle_model(printer_model):
        return True
    nozzles = getattr(status, "nozzles", None) or []
    if len(nozzles) > 1 and getattr(nozzles[1], "nozzle_diameter", ""):
        return True
    raw = getattr(status, "raw_data", None) or {}
    if raw.get("ams_extruder_map"):
        return True
    vt_trays = raw.get("vt_tray") or []
    return isinstance(vt_trays, list) and len(vt_trays) > 1


def _int_or(value, default: int) -> int:
    """``int(value)``, or ``default`` when the field is missing or junk.

    AMS telemetry types its ids inconsistently — `"0"` in one firmware, `0` in
    the next — and a tray id that fails to parse must not take the whole
    derivation down with it.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _global_tray_id(ams_id: int, tray_id: int) -> int:
    """Bambu's flat tray addressing: ``ams_id * 4 + tray_id`` for a four-slot
    unit, and the bare unit id for an AMS-HT (ids from 128, one tray each).

    Mirrors the calculation in ``_build_loaded_filaments``, which is what
    produces the ids stored in ``PrintQueueItem.ams_mapping`` — the two must
    agree or a mapping cannot be read back against live tray telemetry.
    """
    return ams_id if ams_id >= 128 else ams_id * 4 + tray_id


def _used_global_tray_ids(item: PrintQueueItem | None) -> set[int] | None:
    """The global tray ids ``item`` actually prints from, or None if unknown.

    ``ams_mapping`` is the array the print command carries: position = filament
    slot, value = global tray id, ``-1`` / ``None`` for a slot this plate does
    not use. None means "no usable statement" — no mapping, unparseable JSON,
    an all-unresolved mapping (the artifact ``_mapping_is_all_unresolved``
    documents), or one that resolves to no tray at all. Callers must treat None
    as "consider every loaded tray" rather than "consider none": narrowing on
    an absent mapping would silently drop requirements the print really has.
    """
    raw = getattr(item, "ams_mapping", None)
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            mapping = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    else:
        mapping = raw
    if not isinstance(mapping, list) or _mapping_is_all_unresolved(mapping):
        return None
    used = {t for t in mapping if isinstance(t, int) and not isinstance(t, bool) and t >= 0}
    return used or None


def _mqtt_commands_rejected(status) -> bool:
    """True when the printer is currently reporting that it refused a command.

    ``HMS_MQTT_VERIFY_FAILED`` means the firmware's authorization check rejected
    a control command it could not verify. Queries still answer, so the printer
    looks connected and idle while project_file, gcode_line and
    ams_change_filament are all dropped — no amount of waiting or re-uploading
    changes that (#2732).

    Tolerates a missing status and errors without a ``full_code`` (the 8-char
    ``print_error`` path builds HMSError differently), so this is safe to call on
    every watchdog poll.
    """
    for err in getattr(status, "hms_errors", None) or []:
        if getattr(err, "full_code", "") == HMS_MQTT_VERIFY_FAILED:
            return True
    return False


def _drying_ams_ids(status) -> list[int]:
    """AMS unit ids currently running a drying cycle, per firmware telemetry.

    ``dry_time`` is minutes remaining, so >0 is the firmware's own statement that
    a cycle is active. Used by the dispatch watchdog to say *why* a print never
    started (#2758) — it is a diagnostic, not a gate.

    Deliberately not used to block or stop drying before dispatch. This printer
    class supports drying concurrently with an active print
    (``supports_drying_while_printing``), so drying is not incompatible with
    printing in general; what #2758 shows is one X2D refusing to *begin* a print
    while two AMS units were drying, one of them without its external PSU. Until
    it is known whether the blocker is drying itself or the power budget
    (``dry_sf_reason`` 1 / 8), acting on this would tear down drying that the
    hardware is perfectly happy to continue.
    """
    ids: list[int] = []
    for unit in (getattr(status, "raw_data", None) or {}).get("ams") or []:
        if not isinstance(unit, dict):
            continue
        try:
            if int(unit.get("dry_time") or 0) > 0:
                ids.append(int(unit.get("id", 0)))
        except (TypeError, ValueError):
            continue
    return ids
