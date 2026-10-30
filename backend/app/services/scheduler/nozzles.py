"""Düsen-Bestückung und Filament-Meldungen des Druckplaners.

Liest den Düsenbestand aus dem Druckerstatus und formuliert die Meldungen,
wenn Filament oder Düse nicht zum Auftrag passen. Aus ``print_scheduler.py``
ausgelagert; die Namen werden dort weiterhin importiert.
"""

from backend.app.services.bambu_mqtt import _RACK_NOZZLE_IDS


def _parse_diameter(raw) -> float | None:
    """``"0.4"`` → ``0.4``; anything unparseable or non-positive → None."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _nozzle_info_by_id(status) -> dict[int, dict]:
    """Index ``PrinterState.nozzle_rack`` by nozzle id.

    The field name is historical: on the H2 series ``nozzle_info`` carries an
    entry for *every* nozzle the printer knows about — the L/R hotends under
    ids 0/1 and, on a rack model, the dock positions under ids 16-21. Only the
    latter are the rack proper; :func:`_rack_nozzle_diameters` and
    :func:`_installed_nozzle_diameters` each take the half they need.
    """
    by_id: dict[int, dict] = {}
    for entry in getattr(status, "nozzle_rack", None) or []:
        if not isinstance(entry, dict):
            continue
        try:
            by_id[int(entry.get("id"))] = entry
        except (TypeError, ValueError):
            continue
    return by_id


# What the firmware puts in a nozzle's serial number when the carriage or dock
# is empty. Measured on an H2C at idle, where the rack-side hotend had parked
# its nozzle back in the rack (#2885).
_EMPTY_NOZZLE_SERIAL = "N/A"


def _nozzle_is_mounted(entry: dict | None) -> bool:
    """Whether a ``nozzle_info`` entry describes hardware that is actually there.

    A hotend entry is reported whether or not a nozzle is mounted, and an empty
    carriage keeps the *last* nozzle's diameter — measured on an H2C at idle,
    where id 1 read ``diameter "0.4"`` with ``max_temp 0``, ``serial_number
    "N/A"`` and ``wear 0`` because that hotend had parked its nozzle back in
    the dock. So the diameter is not a presence signal (#2885).

    Emptiness has to be stated, not merely unstated. The serial must be the
    firmware's explicit ``"N/A"`` marker *and* the temperature rating must be
    absent — an empty serial only means the printer didn't say, and a firmware
    that reports neither field normalises to exactly that. Treating "didn't
    say" as "empty" would silently switch the #1899 guard off on any such
    machine, so everything we cannot positively call empty counts as mounted.
    """
    if entry is None:
        return True
    serial = str(entry.get("serial_number") or "").strip().upper()
    if serial != _EMPTY_NOZZLE_SERIAL:
        return True
    try:
        max_temp = float(entry.get("max_temp") or 0)
    except (TypeError, ValueError):
        return True
    return max_temp > 0


def _installed_nozzle_diameters(status) -> list[float]:
    """Parse the mounted nozzle diameters from a PrinterState (#1899).

    Returns the diameters the printer actually reports (e.g. [0.4] single-nozzle,
    [0.4, 0.6] dual-nozzle), skipping the empty-string defaults that populate a
    NozzleInfo before MQTT fills it in. An empty list means "the printer hasn't
    told us its nozzle hardware" — callers must treat that as unknown, not as a
    mismatch, so we never block a print on missing data.

    A hotend whose ``nozzle_info`` entry says nothing is mounted is skipped even
    though ``nozzles`` still carries a diameter for it: that value is stale, and
    counting it would let a slice match a nozzle the machine does not have
    (#2885). Printers that report no ``nozzle_info`` at all are unaffected.
    """
    info = _nozzle_info_by_id(status)
    diameters: list[float] = []
    for index, nozzle in enumerate(getattr(status, "nozzles", None) or []):
        raw = getattr(nozzle, "nozzle_diameter", "") or ""
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0 and _nozzle_is_mounted(info.get(index)):
            diameters.append(value)
    return diameters


def _rack_nozzle_diameters(status) -> list[float]:
    """Diameters sitting in the tool-changer rack, nearest dock first (#2885).

    Keyed off the nozzle ids themselves rather than the printer model: only a
    rack machine ever reports ids 16-21, so there is no model registry to keep
    in sync. An empty dock is simply absent from the payload — measured on an
    H2C whose R2 (id 17) was empty and unlisted while R1/R3/R4/R5/R6 were all
    present — so appearing here already means "a nozzle is in that dock".

    ``stat`` is deliberately not interpreted: its values aren't known, and
    reading it wrongly could hide a nozzle the printer would happily fetch.
    """
    diameters: list[float] = []
    for nozzle_id, entry in sorted(_nozzle_info_by_id(status).items()):
        if nozzle_id not in _RACK_NOZZLE_IDS:
            continue
        # PrinterState spells it "diameter"; the REST schema renames it to
        # "nozzle_diameter". Accept either so a caller holding the serialised
        # shape gets the same answer.
        value = _parse_diameter(entry.get("diameter") or entry.get("nozzle_diameter"))
        if value is not None:
            diameters.append(value)
    return diameters


def _format_diameters(diameters: list[float]) -> str:
    """``[0.4, 0.4, 0.6]`` → ``"0.4mm / 0.6mm"``, in first-seen order.

    Deduplicated because a loaded rack holds several nozzles of the same size,
    and "0.4mm / 0.4mm / 0.4mm / 0.6mm / 0.2mm" tells the reader nothing the
    short form doesn't. Matching still runs over the full list.
    """
    return " / ".join(f"{d:g}mm" for d in dict.fromkeys(diameters))


def _nozzle_mismatch_message(
    sliced_nozzle: float | None,
    installed: list[float],
    rack: list[float] | None = None,
) -> str | None:
    """Return an actionable error message when the sliced nozzle can't be
    printed on any nozzle the machine can reach, else None (#1899).

    Fail-safe: returns None whenever we lack the data to judge — no sliced
    diameter, or the printer reported no nozzles — so a print is only ever
    blocked on a POSITIVE mismatch. On dual-nozzle printers a match against
    EITHER installed nozzle passes (a 0.6 slice is fine if one hotend is 0.6).
    The 0.05 tolerance absorbs float noise while staying well inside the 0.2
    gap between adjacent nozzle sizes (0.2/0.4/0.6/0.8).

    *rack* holds the diameters parked in a tool-changer dock (H2C). Those count
    as reachable: the printer fetches one as part of starting the print, so a
    slice that matches a docked nozzle is not a mismatch. Without this the
    guard blocked every job whose nozzle happened not to be on a hotend at
    dispatch time — on a rack loaded with 0.2/0.4/0.6 that meant only the
    diameter already mounted could ever print, and the user had to fetch the
    nozzle by hand on the printer's own UI first (#2885).
    """
    reachable = [*installed, *(rack or [])]
    if not sliced_nozzle or not reachable:
        return None
    if any(abs(d - sliced_nozzle) < 0.05 for d in reachable):
        return None
    where = f"{_format_diameters(installed)} installed" if installed else "no nozzle mounted"
    if rack:
        where += f" and {_format_diameters(rack)} in the nozzle rack"
    return (
        f"File sliced for a {sliced_nozzle:g}mm nozzle, but the printer has "
        f"{where}. Re-slice for an available nozzle, or fit the matching "
        f"nozzle before printing."
    )


def _describe_filament(entry: dict, nozzle_key: str) -> str:
    """One-line "PETG #000000 (left nozzle)" for an error message (#2771).

    Shared by the required and loaded sides, which name their extruder
    differently: a 3MF requirement carries ``nozzle_id``, a loaded tray carries
    ``extruder_id``. Both are MQTT extruder ids — 0 is the right/main nozzle,
    1 the left/deputy — and both are absent on single-nozzle printers, where
    naming a nozzle would be noise.
    """
    parts = [(entry.get("type") or "filament").upper()]
    if entry.get("color"):
        parts.append(str(entry["color"]))
    nozzle = entry.get(nozzle_key)
    if nozzle == 0:
        parts.append("(right nozzle)")
    elif nozzle == 1:
        parts.append("(left nozzle)")
    return " ".join(parts)


def _unmatched_filament_message(required: list[dict], loaded: list[dict]) -> str:
    """Explain that nothing loaded matches what the file needs (#2771).

    Only ever built for a printer with no AMS, where the loaded list is short
    enough to quote in full and there is no "load another spool and hit Resume"
    recovery — the external spool holder is all there is, so the user needs to
    be told which filament to put on it.
    """
    want = ", ".join(_describe_filament(r, "nozzle_id") for r in required)
    have = ", ".join(_describe_filament(f, "extruder_id") for f in loaded)
    return (
        f"No filament loaded on this printer matches the file. It needs {want}; "
        f"the printer has {have} and no AMS. Load the required filament on the "
        f"external spool holder, or send this job to a printer that has it."
    )
