"""Erwartete Drucke: Registrierung, Widerruf und TTL-Aufraeumen.

Aus ``backend/app/main.py`` ausgelagert: die Modul-Zustaende hinter den
Prints, die neu gestartet werden, bevor der Drucker sie meldet (Wiederholung,
geplant, Druckwarteschlange) — die Registrierung schreibt mehrere
Dateinamen-Varianten, der Widerruf macht sie rueckgaengig (#1853), der
TTL-Aufraeumer raeumt auf, was niemals gestartet wurde. Die Namen bleiben
ueber Re-Export im ``main``-Namensraum; ``time`` und ``asyncio`` ueber
:func:`_rt`, weil Tests dort setzen. Aufrufer und Tests sehen keinen
Unterschied.
"""

import asyncio  # noqa: F401 — Annotationen und CancelledError brauchen die echte Klasse
import logging

# Der Logger-Name bleibt der der alten Heimat, damit Protokollzeilen in den
# Support-Bundles unverändert unter ``backend.app.main`` auftauchen.
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen."""
    import importlib

    return importlib.import_module("backend.app.main")


# Track expected prints from reprint/scheduled (skip auto-archiving for these)
# {(printer_id, filename): archive_id}
_expected_prints: dict[tuple[int, str], int] = {}

# Track AMS mapping for prints: {archive_id: [global_tray_id_per_slot]}
# Used by usage tracker to map 3MF slots to physical AMS trays
_print_ams_mappings: dict[int, list[int]] = {}

# Track cost center selection for the current print run: {archive_id: cost_center_id}
_print_cost_center_ids: dict[int, int] = {}

# Track plate_id for prints from multi-plate 3MFs: {archive_id: plate_id}
# Used by usage tracker to scope 3MF parsing to the dispatched plate (#1697).
# Populated by direct-Print and queue dispatch paths; queue prints also have a
# redundant queue-item lookup in on_print_start so this dict isn't load-bearing
# for the queue path. Cleared on print completion or TTL eviction.
_print_plate_ids: dict[int, int] = {}

# Track created_by_id for expected prints so the user email can be sent even when
# the archive itself doesn't have created_by_id set (e.g. library-file-based prints).
# {(printer_id, filename): created_by_id}
_expected_print_creators: dict[tuple[int, str], int] = {}

# TTL for expected-print entries: evict registrations older than this to prevent
# unbounded growth when a print is registered but never starts (e.g. printer
# disconnect, app restart, print started from the printer panel).
_EXPECTED_PRINT_TTL_SECONDS: int = 2 * 60 * 60  # 2 hours

# Registration timestamps used for TTL eviction: {(printer_id, filename): monotonic_time}
_expected_print_registered_at: dict[tuple[int, str], float] = {}

# Cleanup loop interval
_EXPECTED_PRINT_CLEANUP_INTERVAL: int = 15 * 60  # 15 minutes
_expected_prints_cleanup_task: asyncio.Task | None = None


def register_expected_print(
    printer_id: int,
    filename: str,
    archive_id: int,
    ams_mapping: list[int] | None = None,
    created_by_id: int | None = None,
    cost_center_id: int | None = None,
    plate_id: int | None = None,
):
    """Register an expected print from reprint/scheduled so we don't create duplicate archives."""
    # Store with multiple filename variations to catch different naming patterns
    _expected_prints[(printer_id, filename)] = archive_id
    # Also store without .3mf extension if present
    if filename.endswith(".3mf"):
        base = filename[:-4]
        _expected_prints[(printer_id, base)] = archive_id
        _expected_prints[(printer_id, f"{base}.gcode")] = archive_id
    # Store AMS mapping for usage tracking at print completion
    if ams_mapping is not None:
        _print_ams_mappings[archive_id] = ams_mapping
    if cost_center_id is not None:
        _print_cost_center_ids[archive_id] = cost_center_id
    # Store plate_id for usage tracking when this is a single-plate dispatch from
    # a multi-plate 3MF — without this, the direct-Print path attributes the whole
    # file's filament total to the spool instead of just the printed plate (#1697).
    if plate_id is not None:
        _print_plate_ids[archive_id] = plate_id
    # Store created_by_id so the user start email can be sent even when the archive
    # itself has no created_by_id (e.g. library-file-based queue prints)
    if created_by_id is not None:
        _expected_print_creators[(printer_id, filename)] = created_by_id
        if filename.endswith(".3mf"):
            base = filename[:-4]
            _expected_print_creators[(printer_id, base)] = created_by_id
            _expected_print_creators[(printer_id, f"{base}.gcode")] = created_by_id
    # Record registration time for TTL-based eviction
    _registered_at = _rt().time.monotonic()
    _expected_print_registered_at[(printer_id, filename)] = _registered_at
    if filename.endswith(".3mf"):
        base = filename[:-4]
        _expected_print_registered_at[(printer_id, base)] = _registered_at
        _expected_print_registered_at[(printer_id, f"{base}.gcode")] = _registered_at
    logger.info(
        f"Registered expected print: printer={printer_id}, file={filename}, archive={archive_id}, ams_mapping={ams_mapping}, plate_id={plate_id}"
    )


def unregister_expected_print(printer_id: int, filename: str, archive_id: int) -> None:
    """Undo :func:`register_expected_print` when the print never went out.

    Registration has to happen *before* the MQTT print command, because the
    printer can report the print before the line after the send executes. So
    every path that registers and then fails to send — a cancel winning the
    #1853 CAS race, a ``start_print()`` that returns False, or any exception in
    between — leaves an expectation for a print that will never arrive.

    The TTL sweep evicts those after two hours, which is far longer than it
    takes a user to react to a failed dispatch by pressing print again: that
    reprint would be folded into the *old* archive and take the stale
    ``ams_mapping`` / ``plate_id`` with it. Hence the explicit inverse.

    Mirrors the sweep's rules, including the one that is easy to get wrong:
    ``_print_ams_mappings`` / ``_print_plate_ids`` are keyed by archive, not by
    file, so they may only be dropped once no live key still points at that
    archive.
    """
    keys = [(printer_id, filename)]
    if filename.endswith(".3mf"):
        base = filename[:-4]
        keys.append((printer_id, base))
        keys.append((printer_id, f"{base}.gcode"))

    removed = False
    for key in keys:
        if _expected_prints.pop(key, None) is not None:
            removed = True
        _expected_print_creators.pop(key, None)
        _expected_print_registered_at.pop(key, None)

    if archive_id not in set(_expected_prints.values()):
        _print_ams_mappings.pop(archive_id, None)
        _print_plate_ids.pop(archive_id, None)

    if removed:
        logger.info(
            "Unregistered expected print: printer=%s, file=%s, archive=%s (print was never sent)",
            printer_id,
            filename,
            archive_id,
        )


def _evict_stale_expected_prints() -> None:
    """Remove entries from _expected_prints / _expected_print_creators that are
    older than _EXPECTED_PRINT_TTL_SECONDS.

    This prevents unbounded growth when a print is registered (via
    register_expected_print) but on_print_start never fires — e.g. because the
    printer disconnects, the app restarts, or the print is started directly from
    the printer panel without going through the queue.
    """
    # Use monotonic time so the TTL is unaffected by system clock adjustments
    # (e.g. NTP sync, DST changes).
    cutoff = _rt().time.monotonic() - _EXPECTED_PRINT_TTL_SECONDS
    stale_keys = [k for k, t in _expected_print_registered_at.items() if t < cutoff]
    if not stale_keys:
        return

    evicted_archive_ids: set[int] = set()
    for key in stale_keys:
        archive_id = _expected_prints.pop(key, None)
        if archive_id is not None:
            evicted_archive_ids.add(archive_id)
        _expected_print_creators.pop(key, None)
        _expected_print_registered_at.pop(key, None)

    # Also clean up _print_ams_mappings and _print_plate_ids for archive_ids
    # that have no remaining live keys in _expected_prints (all variants
    # were just evicted).
    live_archive_ids = set(_expected_prints.values())
    for archive_id in evicted_archive_ids:
        if archive_id not in live_archive_ids:
            _print_ams_mappings.pop(archive_id, None)
            _print_cost_center_ids.pop(archive_id, None)
            _print_plate_ids.pop(archive_id, None)

    logger.info("Evicted %d stale expected-print entries (TTL=%ds)", len(stale_keys), _EXPECTED_PRINT_TTL_SECONDS)


async def _expected_prints_cleanup_loop() -> None:
    """Background task: periodically evict stale expected-print entries."""
    while True:
        try:
            _evict_stale_expected_prints()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Expected prints cleanup failed: %s", e)
        await _rt().asyncio.sleep(_EXPECTED_PRINT_CLEANUP_INTERVAL)


def start_expected_prints_cleanup() -> None:
    global _expected_prints_cleanup_task
    if _expected_prints_cleanup_task is None:
        _expected_prints_cleanup_task = _rt().asyncio.create_task(_expected_prints_cleanup_loop())
        logger.info("Expected prints cleanup started")


def stop_expected_prints_cleanup() -> None:
    global _expected_prints_cleanup_task
    if _expected_prints_cleanup_task:
        _expected_prints_cleanup_task.cancel()
        _expected_prints_cleanup_task = None
        logger.info("Expected prints cleanup stopped")
