import asyncio
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from fastapi import FastAPI
from sqlalchemy import or_, select, text

from backend.app.api.routes import (
    ams_history,
    announcements,
    api_keys,
    archive_purge,
    archives,
    auth,
    bug_report,
    camera,
    camwall,
    cloud,
    connected_apps,
    discovery,
    external_links,
    filaments,
    finance,
    firmware,
    github_backup,
    groups,
    ha_sensors,
    inventory,
    kprofiles,
    labels,
    layer_alerts,
    library,
    library_tags,
    library_trash,
    library_variants,
    local_backup,
    local_presets,
    location_ha_sensors,
    maintenance,
    maintenance_print,
    maintenance_programs,
    makerworld,
    metrics,
    mfa,
    notification_templates,
    notifications,
    obico,
    orca_cloud,
    part_watcher,
    pending_uploads,
    pipeline_runs,
    print_log,
    print_queue,
    printer_sensor_history,
    printers,
    projects,
    scheduled_dryings,
    settings as settings_routes,
    slice_jobs,
    slicer_pipelines,
    slicer_presets,
    smart_plugs,
    spoolbuddy,
    spoolman,
    spoolman_inventory,
    support,
    system,
    updates,
    user_notifications,
    users,
    virtual_printers,
    webhook,
    websocket,
)
from backend.app.api.routes.maintenance import _get_printer_maintenance_internal, ensure_default_types
from backend.app.api.routes.support import init_debug_logging
from backend.app.core.config import APP_VERSION, settings as app_settings
from backend.app.core.database import async_session, engine, init_db
from backend.app.core.tasks import spawn_background_task
from backend.app.core.websocket import ws_manager
from backend.app.services import (  # noqa: F401 — Test-Patch-Ziel (kprofile_drift)
    kprofile_drift,
    print_dispatch_context,
    slot_unlink_grace,
)
from backend.app.services.archive import ArchiveService, peek_plate_index_in_3mf  # noqa: F401 — Test-Patch-Ziel
from backend.app.services.archive_purge import archive_purge_service
from backend.app.services.background_services import (  # noqa: F401 — Namensraum bleibt hier
    _AUTH_CLEANUP_INTERVAL,
    CAMERA_CLEANUP_INTERVAL,
    CONNECTION_WATCHDOG_INTERVAL,
    CONNECTION_WATCHDOG_OFFLINE_GRACE,
    CONNECTION_WATCHDOG_RETRY_INTERVAL,
    SPOOLBUDDY_WATCHDOG_INTERVAL,
    _auth_cleanup_loop,
    _auth_cleanup_task,
    _camera_cleanup_loop,
    _camera_cleanup_task,
    _connection_watchdog_last_attempt,
    _connection_watchdog_loop,
    _connection_watchdog_task,
    _recover_dead_printer_sessions,
    _run_auth_cleanup,
    _spoolbuddy_watchdog_loop,
    _spoolbuddy_watchdog_task,
    start_auth_cleanup,
    start_camera_cleanup,
    start_connection_watchdog,
    start_spoolbuddy_watchdog,
    stop_auth_cleanup,
    stop_camera_cleanup,
    stop_connection_watchdog,
    stop_spoolbuddy_watchdog,
)
from backend.app.services.bambu_ftp import (  # noqa: F401 — Test-Patch-Ziel
    cache_3mf_download,
    clear_3mf_cache,
    download_file_async,
    download_file_try_paths_async,
    ftps_handshake_blocked,
    get_cached_3mf,
    get_ftp_retry_settings,
    with_ftp_retry,
)
from backend.app.services.bambu_mqtt import PrinterState
from backend.app.services.energy_plug import energy_plug_candidates, select_energy_reading
from backend.app.services.expected_prints import (  # noqa: F401 — Namensraum bleibt hier
    _EXPECTED_PRINT_CLEANUP_INTERVAL,
    _EXPECTED_PRINT_TTL_SECONDS,
    _evict_stale_expected_prints,
    _expected_print_creators,
    _expected_print_registered_at,
    _expected_prints,
    _expected_prints_cleanup_loop,
    _expected_prints_cleanup_task,
    _print_ams_mappings,
    _print_cost_center_ids,
    _print_plate_ids,
    register_expected_print,
    start_expected_prints_cleanup,
    stop_expected_prints_cleanup,
    unregister_expected_print,
)
from backend.app.services.github_backup import github_backup_service
from backend.app.services.ha_sensor_manager import ha_sensor_manager
from backend.app.services.history_runtime import (  # noqa: F401 — Namensraum bleibt hier
    _SENSOR_KINDS,
    _SENSOR_TARGET_KEYS,
    AMS_ALARM_COOLDOWN_MINUTES,
    AMS_HISTORY_INTERVAL,
    AMS_HISTORY_RETENTION_DAYS,
    PRINTER_SENSOR_HISTORY_INTERVAL,
    PRINTER_SENSOR_HISTORY_RETENTION_DAYS,
    RUNTIME_TRACKING_INTERVAL,
    _ams_alarm_cooldown,
    _ams_cleanup_counter,
    _ams_has_filament,
    _ams_history_task,
    _ams_index_only_logged,
    _printer_sensor_cleanup_counter,
    _printer_sensor_history_task,
    _resolve_temp_alarm_threshold,
    _runtime_tracking_task,
    record_ams_history,
    record_printer_sensor_history,
    start_ams_history_recording,
    start_printer_sensor_history_recording,
    start_runtime_tracking,
    stop_ams_history_recording,
    stop_printer_sensor_history_recording,
    stop_runtime_tracking,
    track_printer_runtime,
)
from backend.app.services.homeassistant import homeassistant_service
from backend.app.services.library_trash import library_trash_service
from backend.app.services.local_backup import local_backup_service
from backend.app.services.location_ha_sensor_manager import location_ha_sensor_manager
from backend.app.services.mqtt_relay import mqtt_relay
from backend.app.services.mqtt_smart_plug import mqtt_smart_plug_service
from backend.app.services.mqtt_status_flow import (  # noqa: F401 — Namensraum bleibt hier
    _ACTIVE_PRINT_STATES,
    _HMS_CLEAR_GRACE_SECONDS,
    _NO_PREPARATION_STAGES,
    _PRINTER_OFFLINE_NOTIFY_DEBOUNCE_SECONDS,
    _ams_assignment_locks,
    _broadcast_unknown_tag,
    _clear_unknown_tag_dedup,
    _first_layer_notified,
    _get_ams_assignment_lock,
    _hms_errors_to_notify,
    _hms_fault_counts,
    _hms_last_seen,
    _hms_notify_key,
    _last_progress_milestone,
    _last_status_broadcast,
    _maybe_notify_printer_offline,
    _notified_hms_errors,
    _nozzle_count_updated,
    _printer_kprofiles_primed_since_connect,
    _printer_last_connected,
    _printer_offline_notify_tasks,
    _printer_reconciled_since_connect,
    _progress_milestone_to_notify,
    _take_new_hms_faults,
    _unauthorized_print_kill_sent,
    _unknown_tag_last_broadcast,
    on_ams_change,
    on_fts_inlet_change,
    on_printer_status_change,
)
from backend.app.services.notification_service import notification_service
from backend.app.services.obico_detection import obico_detection_service
from backend.app.services.print_cost_estimate import plate_scoped_run_estimate as _plate_scoped_run_estimate
from backend.app.services.print_scheduler import scheduler as print_scheduler
from backend.app.services.print_start_flow import (  # noqa: F401 — Namensraum bleibt hier
    _FALLBACK_3MF_RETRY_DELAYS_SECONDS,
    _FALLBACK_3MF_TRANSFER_RETRY_DELAYS_SECONDS,
    _ask_outcome_for_external_print,
    _extract_filament_data_from_mqtt,
    _get_start_ams_mapping,
    _queue_item_dispatched_name,
    _record_energy_start,
    _recover_fallback_archive,
    _recover_fallback_archive_locked,
    _schedule_fallback_3mf_retry,
    _send_print_start_notification,
    on_print_start,
    try_recover_fallback_archive,
)
from backend.app.services.printer_manager import (  # noqa: F401 — Test-Patch-Ziel
    init_printer_connections,
    parse_plate_id,
    printer_manager,
    printer_state_to_dict,
    resolve_plate_id,
)
from backend.app.services.slot_kprofile import find_slot_kprofile_for_extruder  # noqa: F401 — Test-Patch-Ziel
from backend.app.services.smart_plug_manager import smart_plug_manager
from backend.app.services.spool_linkage import (  # noqa: F401 — Namensraum bleibt hier
    _expire_spoolman_empty_slots,
    _is_bambu_uuid,
    _recheck_held_unlinks,
    _unlink_stale_assignments,
)
from backend.app.services.spoolman import (  # noqa: F401 — Test-Patch-Ziel
    close_spoolman_client,
    get_spoolman_client,
    init_spoolman_client,
)
from backend.app.services.spoolman_tracking import (  # noqa: F401 — Test-Patch-Ziel
    cleanup_tracking as _cleanup_spoolman_tracking,
    report_usage as _report_spoolman_usage,
    store_print_data as _store_spoolman_print_data,
)
from backend.app.services.tasmota import tasmota_service
from backend.app.services.telegram_reactions import telegram_reaction_poller
from backend.app.services.timelapse import (  # noqa: F401 — Namensraum bleibt hier
    _attach_first_unclaimed_timelapse,
    _capture_finish_photo_from_timelapse,
    _capture_timelapse_baseline_at_start,
    _claimed_timelapse_names,
    _list_timelapse_videos,
    _maybe_start_layer_timelapse,
    _scan_for_timelapse_with_retries,
    _timelapse_listing_is_trustworthy,
    _timelapse_scan_max_attempts,
    _upgrade_finish_photo_from_timelapse,
)
from backend.app.utils.print_jobs import is_internal_printer_job


# =============================================================================
# Dependency Check - runs before other imports to give helpful error messages
# =============================================================================
def _start_error_server(missing_packages: list):
    """Start a minimal HTTP server to display dependency errors in browser."""
    import os
    import signal
    from http.server import BaseHTTPRequestHandler, HTTPServer

    packages_html = "".join(f"<li><code>{p}</code></li>" for p in missing_packages)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>PrintLab - Setup Required</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a; color: #e2e8f0;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box;
        }}
        .container {{
            background: #1e293b; border-radius: 12px; padding: 40px;
            max-width: 600px; text-align: center; box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }}
        h1 {{ color: #f87171; margin-bottom: 10px; }}
        h2 {{ color: #94a3b8; font-weight: normal; margin-top: 0; }}
        .packages {{
            background: #0f172a; border-radius: 8px; padding: 20px;
            margin: 20px 0; text-align: left;
        }}
        .packages ul {{ margin: 0; padding-left: 20px; }}
        .packages li {{ color: #fbbf24; margin: 8px 0; }}
        .command {{
            background: #0f172a; border-radius: 8px; padding: 15px 20px;
            margin: 15px 0; font-family: monospace; color: #4ade80;
            text-align: left; overflow-x: auto;
        }}
        .note {{ color: #94a3b8; font-size: 14px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Setup Required</h1>
        <h2>Missing Python packages</h2>
        <div class="packages"><ul>{packages_html}</ul></div>
        <p>To fix, run this command on your server:</p>
        <div class="command">pip install -r requirements.txt</div>
        <p>Or if using a virtual environment:</p>
        <div class="command">./venv/bin/pip install -r requirements.txt</div>
        <p class="note">After installing, restart PrintLab:<br>
        <code>sudo systemctl restart printlab</code></p>
    </div>
</body>
</html>"""

    class ErrorHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

        def log_message(self, format, *args):
            print(f"[Error Server] {args[0]}")

    port = int(os.environ.get("PORT", 8000))
    print(f"\nStarting error server on http://0.0.0.0:{port}")
    print("Visit this URL in your browser to see the error details.\n")

    server = HTTPServer(("0.0.0.0", port), ErrorHandler)  # nosec B104

    def shutdown(signum, frame):
        print("\nShutting down error server...")
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    server.serve_forever()


def check_dependencies():
    """Check that all required packages are installed."""
    missing = []

    # Map of import name -> package name (for pip install)
    required = {
        "jwt": "PyJWT",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "sqlalchemy": "sqlalchemy",
        "aiosqlite": "aiosqlite",
        "pydantic": "pydantic",
        "paho.mqtt": "paho-mqtt",
    }

    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print("\n" + "=" * 60)
        print("ERROR: Missing required Python packages!")
        print("=" * 60)
        print(f"\nMissing packages: {', '.join(missing)}")
        print("\nTo fix, run:")
        print("  pip install -r requirements.txt")
        print("\nOr if using a virtual environment:")
        print("  ./venv/bin/pip install -r requirements.txt")
        print("=" * 60 + "\n")
        _start_error_server(missing)


check_dependencies()
# =============================================================================


# Import settings first for logging configuration

# Configure logging based on settings
# DEBUG=true -> DEBUG level, else use LOG_LEVEL setting
log_level_str = "DEBUG" if app_settings.debug else app_settings.log_level.upper()
log_level = getattr(logging, log_level_str, logging.INFO)
# Trace ID column ([-] when no request scope is active — startup, MQTT
# callbacks, scheduled tasks not chained from a request — so the column
# stays visually aligned and missing values are obvious in grep). See
# backend/app/core/trace.py for the ContextVar that feeds this slot.
log_format = "%(asctime)s %(levelname)s [%(name)s] [%(trace_id)s] %(message)s"

# Create root logger
root_logger = logging.getLogger()
root_logger.setLevel(log_level)

# Trace-ID injection: this filter populates record.trace_id from the
# per-request ContextVar so the format string above can reference it.
# Attached to each HANDLER (not the root logger) because Python's
# logging semantics only invoke a logger's filters on records that
# *originated* at that logger — records propagated up from child
# loggers (every named logger in the app) never trigger root's filter.
# Putting it on the handlers means every record any handler emits gets
# trace_id injected just before the formatter runs, regardless of which
# logger created the record. Without this, the formatter raises
# KeyError on every child-logger record and the record is silently
# dropped — which is exactly the "logs/printlab.log only shows logs
# partially" bug we hit. See backend/app/core/trace.py for the
# ContextVar the filter reads.
from backend.app.core.trace import TraceIDFilter

_trace_id_filter = TraceIDFilter()

# Console handler - always enabled
console_handler = logging.StreamHandler()
console_handler.setLevel(log_level)
console_handler.setFormatter(logging.Formatter(log_format))
console_handler.addFilter(_trace_id_filter)
root_logger.addHandler(console_handler)

# File handler - only in production or if explicitly enabled
if app_settings.log_to_file:
    log_file = app_settings.log_dir / "printlab.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=app_settings.log_max_bytes,
        backupCount=app_settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))
    file_handler.addFilter(_trace_id_filter)
    root_logger.addHandler(file_handler)
    logging.info("Logging to file: %s", log_file)

    # Pipe uvicorn's HTTP access log to printlab.log too. Uvicorn ships its
    # access logger with propagate=False by default, so without this attach
    # there is no on-disk record of which endpoint triggered a server-state
    # change — the rogue stop_print mystery on 2026-04-26 was untraceable
    # for exactly this reason. Filtered to write methods only
    # (POST/PUT/PATCH/DELETE) so the high-volume status-poll GETs from the
    # frontend don't churn the rotation window faster than it's useful.
    from backend.app.core.logging_filters import (
        CancelledPoolNoiseFilter,
        WriteRequestsOnlyFilter,
    )

    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.addHandler(file_handler)
    uvicorn_access_logger.addFilter(WriteRequestsOnlyFilter())
    # Uvicorn's access logger has propagate=False (its own default), so the
    # root-attached TraceIDFilter never sees these records. Attach a
    # second instance directly so HTTP access lines carry the same trace
    # ID column as the application logs they correlate with.
    uvicorn_access_logger.addFilter(TraceIDFilter())

    # Drop SQLAlchemy connection-pool log noise that's caused by Starlette's
    # BaseHTTPMiddleware cancelling the inner task scope on client
    # disconnect (#1112). The cancel-safe `get_db` already prevents the
    # underlying transaction leak; this filter only suppresses the residual
    # log records that pre-existing pools still emit during their cleanup.
    logging.getLogger("sqlalchemy.pool").addFilter(CancelledPoolNoiseFilter())

# Reduce noise from third-party libraries in production
if not app_settings.debug:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("paho.mqtt").setLevel(logging.WARNING)

logging.info("PrintLab starting - debug=%s, log_level=%s", app_settings.debug, log_level_str)


# Track active prints: {(printer_id, filename): archive_id}
_active_prints: dict[tuple[int, str], int] = {}

# #1721: stage-22 pre-captured finish photo bytes per printer. on_finish_photo_moment
# fires when stg_cur enters 22 ("Filament unloading") at end-of-print — toolhead
# parked, bed not yet dropped — and grabs a single camera frame into this cache.
# `_background_finish_photo` (inside on_print_complete) consumes the cached bytes
# instead of running its own grab-now chain when present, so the finish photo
# captures the better-framed pre-bed-drop moment without us having to force
# timelapse on at dispatch (the #1397 mechanism that caused #1721's per-layer
# nozzle parking on slicer profiles with Timelapse Type = Smooth).
#
# #2708: the bytes in here are ALWAYS already rotated by the printer's
# camera_rotation. `on_finish_photo_moment` owns that, because one of its
# sources (the #1867 in-print bank) is rotated before it ever reaches the
# bank and the others are not — so the consumer can't tell them apart and
# must not rotate again.
_stage22_finish_frames: dict[int, bytes] = {}

# #1790: per-printer producer-done event. Set by `on_finish_photo_moment` in its
# `finally` block (whether it captured a frame or not). The consumer in
# `_background_finish_photo` waits on it before reading `_stage22_finish_frames`
# so the FINISH-state fallback path — where moment and completion are dispatched
# back-to-back — doesn't race past the producer with an empty pop, and the
# consumer's RTSP fallback can't collide with the producer's still-in-flight RTSP
# grab (Bambu printers allow only one RTSP client at a time).
_stage22_finish_in_flight: dict[int, asyncio.Event] = {}

# #1867: rolling "last in-print camera frame" per printer. Refreshed on
# layer-change and on print-progress advances (#2547) while the model is still
# printing, then consumed by the FINISH-state finish-photo path when the
# dispatcher recorded that it injected End G-code into this print. Bambu
# reports gcode_state=FINISH AFTER the user End G-code (e.g. SwapMod
# plate-swap) has run, so a live grab there would capture the swapped/empty
# plate.
#
# The load-bearing property: both drivers are print telemetry that stops before
# the End G-code executes — no further layer_num increases, and mc_percent
# freezes — so the last banked frame is always the finished print before the
# swap. Anything added as a third driver must hold that same property.
_inprint_frame_bank: dict[int, bytes] = {}
# Monotonic timestamp of the last banked frame per printer — throttles banking
# so tall prints don't add a camera grab on every layer.
_inprint_frame_bank_ts: dict[int, float] = {}
# Minimum seconds between banked frames, except the final object layer which
# always refreshes for the best framing.
_INPRINT_BANK_MIN_INTERVAL = 25.0

# The MQTT status callback is a hot path. Cache the two-setting kill-switch
# lookup briefly so an unknown active print does not query the database on
# every status frame. A short TTL keeps settings changes responsive.
_KILL_SWITCH_SETTING_CACHE_TTL_SECONDS = 5.0
_kill_switch_setting_cache: tuple[bool, float] | None = None

# Provider notification started when the kill switch stops a print. The later
# MQTT print-complete callback awaits this task and only sends its regular
# provider notification when the immediate attempt failed.
_kill_switch_notification_tasks: dict[int, asyncio.Task[bool]] = {}

# Track timelapse file baselines at print start: {printer_id: set of video filenames}
# Used for snapshot-diff detection at print completion
_timelapse_baselines: dict[int, set[str]] = {}

# Track printers waiting for bed to cool after print completion.
# Event-driven: fires when bed_temper arrives via MQTT below threshold.
# {printer_id: {"threshold": float, "filename": str, "registered_at": float}}
_bed_cool_waiters: dict[int, dict] = {}

# Track printers where the user explicitly stopped the print from the queue UI.
# When on_print_complete fires with status "failed" for these printers we treat it
# as "cancelled" (stopped by user) so the correct notification email is sent.
_user_stopped_printers: set[int] = set()

# HMS short-code → failure_reason key. Used by _dispatch_archive_update
# when status="failed" to label the print's failure_reason in archives.
#
# Earlier code matched on `module` alone (e.g. "any module 0x0C HMS → Layer shift"),
# which is wrong on two counts:
#   1. Real layer-shift codes live in module 0x03 (see Bambu wiki), not 0x0C.
#   2. Module 0x0C is "Motion Controller" — broad category that also covers cameras
#      and visual markers, AND the H2D firmware emits a 0x0C HMS (0C00_001B, not in
#      the public wiki) as part of its user-cancel sequence. Matching on the module
#      alone caused user-cancellations to be archived as "Layer shift" failures.
# We now match by full short code only — anything not in this map leaves
# failure_reason=None rather than guessing.
# Values are the canonical camelCase failure-reason keys, NOT display labels
# (issue #2974). The vocabulary is enforced on writes by
# ``_FAILURE_REASON_KEYS`` in ``api/routes/print_log.py`` and rendered through
# ``t('editArchive.failureReasons.<key>')`` on both the archive editor and the
# Statistics breakdown. Storing a label here instead put a second spelling of
# the same cause into one column: the Failure Analysis widget groups on the raw
# value, so a print the backend classified and an identical one a user
# classified counted as two different reasons, and the label form could never
# be translated because there was no key for ``t()`` to resolve.
_HMS_FAILURE_REASONS: dict[str, str] = {
    # Layer shift / step loss
    "0300_4057": "layerShift",
    "0300_4068": "layerShift",
    "0300_800C": "layerShift",
    # Filament runout (printer-side & per-AMS-slot)
    "0300_8004": "filamentRunout",
    "0700_8011": "filamentRunout",
    "0701_8011": "filamentRunout",
    "0702_8011": "filamentRunout",
    "0703_8011": "filamentRunout",
    "0704_8011": "filamentRunout",
    "0705_8011": "filamentRunout",
    "0706_8011": "filamentRunout",
    "0707_8011": "filamentRunout",
    "07FF_8011": "filamentRunout",
    # Clogged nozzle / extruder
    "0300_4006": "cloggedNozzle",
    "0300_8016": "cloggedNozzle",
    "0300_801C": "cloggedNozzle",
    "0700_8003": "cloggedNozzle",
    "0700_8007": "cloggedNozzle",
    "0700_8013": "cloggedNozzle",
    "0701_8003": "cloggedNozzle",
    "0701_8007": "cloggedNozzle",
    "0701_8013": "cloggedNozzle",
    "0702_8003": "cloggedNozzle",
    # AI print monitoring — spaghetti / the model coming off the plate.
    # `spaghettiDetached` is a key the archive editor already offers for this
    # failure mode, not a new one, so a derived reason opens the dropdown on
    # that option rather than blank — and survives the next save, which clears
    # any value the editor does not recognise.
    #
    # A module-0x0C row is safe here despite the warning above: that warning is
    # about matching on the module alone, and 0C00_8042 is a full short code
    # with a documented meaning ("The AI print monitor has detected a spaghetti
    # defect", hms_errors.py). The H2D cancel echo is 0C00_001B, so the two
    # cannot collide.
    #
    # 0300_8003's own text ends "before continuing your print", but on an X2D
    # it arrives with the print already paused, offering only
    # RESUME_PRINTING_DEFECTS / STOP_PRINTING — a halt waiting on the user.
    #
    # Two neighbours are left out on purpose, so this does not get re-derived:
    #   * 0C00_C004 "Possible spaghetti failure was detected." — "possible"
    #     reads as a warning about a print that is still running, not a halt.
    #   * 0300_800A is AI monitoring too, but it reports a filament pile-up in
    #     the waste chute. That is not the print failing.
    #
    # That line is drawn from the text, not from `severity`, because severity
    # cannot draw it: 0300_8003 reaches us through `print_error`, a bare
    # module/error word with no level in it, and bambu_mqtt.py gives every
    # print_error entry a flat severity=3. Matching on the short code alone is
    # the right shape for derive_failure_reason, not an omission.
    "0300_8003": "spaghettiDetached",
    "0C00_8042": "spaghettiDetached",
}


def _hms_short_code(attr: int, code: int | str) -> str:
    """Build the canonical "MMMM_CCCC" HMS short code from raw attr/code values."""
    if isinstance(code, str):
        code_int = int(code.replace("0x", ""), 16) if code else 0
    else:
        code_int = int(code or 0)
    attr_int = int(attr or 0)
    return f"{(attr_int >> 16) & 0xFFFF:04X}_{code_int & 0xFFFF:04X}"


def derive_failure_reason(status: str, hms_errors: list[dict] | None) -> str | None:
    """Derive the failure_reason key for an archived print.

    Returns "userCancelled" for cancelled/aborted prints; for failed prints,
    returns the first matching key from _HMS_FAILURE_REASONS, or None when
    no HMS code matches (don't guess — null is honest). The keys are the
    archive editor's vocabulary (_FAILURE_REASON_KEYS in print_log.py) and are
    translated at render time.
    """
    if status in ("aborted", "cancelled"):
        return "userCancelled"
    if status != "failed":
        return None
    for err in hms_errors or []:
        short_code = _hms_short_code(err.get("attr", 0), err.get("code", 0))
        if short_code in _HMS_FAILURE_REASONS:
            return _HMS_FAILURE_REASONS[short_code]
    return None


def _build_status_print_keys(printer_id: int, state: PrinterState) -> list[tuple[int, str]]:
    """Build filename keys for matching a printer status update to PrintLab-owned jobs."""

    possible_keys: list[tuple[int, str]] = []
    filename = (state.gcode_file or state.current_print or "").strip()
    subtask_name = (state.subtask_name or "").strip()

    if subtask_name:
        possible_keys.append((printer_id, subtask_name))
        possible_keys.append((printer_id, f"{subtask_name}.3mf"))
        possible_keys.append((printer_id, f"{subtask_name}.gcode.3mf"))

    if filename:
        base_name = filename.rsplit("/", 1)[-1]
        if base_name.endswith(".gcode.3mf"):
            root_name = base_name[: -len(".gcode.3mf")]
            possible_keys.append((printer_id, root_name))
            possible_keys.append((printer_id, base_name))
            possible_keys.append((printer_id, f"{root_name}.gcode"))
            possible_keys.append((printer_id, f"{root_name}.3mf"))
        elif base_name.endswith(".3mf"):
            root_name = base_name[: -len(".3mf")]
            possible_keys.append((printer_id, root_name))
            possible_keys.append((printer_id, base_name))
        elif base_name.endswith(".gcode"):
            root_name = base_name[: -len(".gcode")]
            possible_keys.append((printer_id, root_name))
            possible_keys.append((printer_id, f"{root_name}.3mf"))
            possible_keys.append((printer_id, base_name))
        else:
            possible_keys.append((printer_id, base_name))
            possible_keys.append((printer_id, f"{base_name}.3mf"))

    return possible_keys


def _is_printlab_authorized_print_in_memory(printer_id: int, state: PrinterState) -> bool:
    """Check the cheap, process-local print ownership signals."""

    if printer_manager.get_current_print_user(printer_id):
        return True

    return any(key in _expected_prints or key in _active_prints for key in _build_status_print_keys(printer_id, state))


async def _is_printer_kill_switch_enabled_cached() -> bool:
    """Return the kill-switch setting without querying on every MQTT frame."""

    global _kill_switch_setting_cache

    now = time.monotonic()
    if _kill_switch_setting_cache is not None:
        enabled, expires_at = _kill_switch_setting_cache
        if now < expires_at:
            return enabled

    async with async_session() as db:
        from backend.app.services.finance_budget import is_printer_kill_switch_enabled

        enabled = await is_printer_kill_switch_enabled(db)

    _kill_switch_setting_cache = (enabled, now + _KILL_SWITCH_SETTING_CACHE_TTL_SECONDS)
    return enabled


async def _is_printlab_authorized_print(printer_id: int, state: PrinterState, db) -> bool | None:
    """Resolve whether the current print was started by PrintLab.

    ``None`` means identity is not yet safe to decide. The kill switch must
    defer in that case: stopping a print is irreversible, and the first status
    frames after a restart may arrive before all subtask fields are populated.
    """

    if _is_printlab_authorized_print_in_memory(printer_id, state):
        return True

    possible_keys = _build_status_print_keys(printer_id, state)

    # In-memory ownership is lost on every PrintLab restart, so fall back to what
    # is on disk. subtask_id is minted per print and pins the answer to the job
    # actually running, rather than to an unrelated one that reuses a filename.
    raw_subtask_id = getattr(state, "subtask_id", None)
    subtask_id = str(raw_subtask_id).strip() if raw_subtask_id is not None else ""
    if subtask_id in ("", "0"):
        return None

    from backend.app.models.archive import PrintArchive

    result = await db.execute(
        select(PrintArchive)
        .where(
            PrintArchive.printer_id == printer_id,
            PrintArchive.status == "printing",
            PrintArchive.subtask_id == subtask_id,
        )
        .order_by(PrintArchive.created_at.desc())
        .limit(1)
    )
    archive = result.scalar_one_or_none()

    # An archive row on its own proves nothing: `on_print_start` archives every
    # print it observes, including ones started from Bambu Studio or Handy, and
    # stamps them with the same status and subtask_id. Authorizing on its mere
    # existence would disable the kill switch the moment the 3MF finishes
    # downloading. Only a dispatch marker PrintLab writes itself counts —
    # `billing_run_id` (minted per dispatch in the scheduler) or `created_by_id`
    # (carried over from the queue item that started it).
    if archive is not None and (archive.billing_run_id is not None or archive.created_by_id is not None):
        # Rehydrate the fast in-memory path for subsequent status frames. Include
        # both the archive filename and every normalized key reported by MQTT.
        _active_prints[(printer_id, archive.filename)] = archive.id
        for key in possible_keys:
            _active_prints[key] = archive.id
        return True

    # No dispatch marker. Before calling this someone else's print, check whether
    # PrintLab has a job of its own running on this printer: a library-file
    # dispatch has no archive at send time, and an archive created seconds later
    # by `on_print_start` carries neither marker. The queue row, which the
    # scheduler commits to status="printing" before the MQTT send, is the one
    # durable record every PrintLab print has. It cannot be tied to this
    # subtask_id, so it is grounds to defer, never to authorize — stopping a
    # print is irreversible, and refusing to act costs nothing but a log line.
    from backend.app.models.print_queue import PrintQueueItem

    dispatched_here = await db.scalar(
        select(PrintQueueItem.id)
        .where(
            PrintQueueItem.printer_id == printer_id,
            PrintQueueItem.status == "printing",
        )
        .limit(1)
    )
    if dispatched_here is not None:
        return None

    return False


async def _send_kill_switch_provider_notification(
    printer_id: int,
    printer_name: str,
    data: dict,
) -> bool:
    """Send the immediate print-stopped provider notification.

    Returning a success flag lets the normal MQTT completion path retry when
    this early notification could not be delivered.
    """

    logger = logging.getLogger(__name__)
    try:
        async with async_session() as db:
            await notification_service.on_print_complete(
                printer_id,
                printer_name,
                "stopped",
                data,
                db,
            )
        return True
    except Exception as e:
        logger.warning(
            "[KILL SWITCH] Immediate provider notification failed for printer %s: %s",
            printer_id,
            e,
        )
        return False


async def _kill_switch_notification_already_sent(task: asyncio.Task[bool] | None) -> bool:
    """Wait for an immediate kill-switch notification, if one was scheduled."""

    if task is None:
        return False
    try:
        return await task
    except Exception as e:
        logging.getLogger(__name__).warning("[KILL SWITCH] Notification task failed: %s", e)
        return False


async def _get_plug_energy(plug, db) -> dict | None:
    """Get energy from plug regardless of type (Tasmota, Home Assistant, MQTT, or REST).

    For HA plugs, configures the service with current settings from DB.
    For MQTT plugs, returns data from the subscription service.
    For REST plugs, polls the status URL with JSON path extraction.
    """
    if plug.plug_type == "homeassistant":
        from backend.app.api.routes.settings import get_homeassistant_settings

        ha_settings = await get_homeassistant_settings(db)
        homeassistant_service.configure(ha_settings["ha_url"], ha_settings["ha_token"])
        return await homeassistant_service.get_energy(plug)
    elif plug.plug_type == "mqtt":
        # MQTT plugs report "today" energy, not lifetime total
        # For per-print tracking, we use "today" as the counter (resets at midnight)
        mqtt_data = mqtt_relay.smart_plug_service.get_plug_data(plug.id)
        if mqtt_data:
            return {
                "power": mqtt_data.power,
                "today": mqtt_data.energy,
                "total": mqtt_data.energy,  # Use today as total for per-print calculations
            }
        return None
    elif plug.plug_type == "rest":
        from backend.app.services.rest_smart_plug import rest_smart_plug_service

        return await rest_smart_plug_service.get_energy(plug)
    else:
        return await tasmota_service.get_energy(plug)


def _compute_run_filament_grams(
    status: str,
    archive_filament_used_grams: float | None,
    progress: float | int | None,
    usage_results: list[dict] | None,
) -> float | None:
    """Per-run filament for PrintLogEntry, partial- and tracker-aware (#1378, #1390).

    Priority for every status:
        1. Sum of tracked spool deltas in ``usage_results`` (AMS-measured
           weight delta — same source that drives "Total Consumed" on the
           Inventory page, so Stats and Inventory totals stay aligned).
        2. For ``completed``: the slicer estimate (no tracker available, fall
           back to the canonical "this print used X" value).
        3. For partial statuses: ``estimate * progress%``.
        4. ``None`` if nothing is known.
    """
    tracked_grams = sum(r.get("weight_used") or 0 for r in (usage_results or []))
    if tracked_grams > 0:
        return round(tracked_grams, 1)

    if status == "completed":
        return archive_filament_used_grams

    if archive_filament_used_grams:
        scale = max(0.0, min(((progress or 0) / 100.0), 1.0))
        if scale > 0:
            return round(archive_filament_used_grams * scale, 1)

    return None


def _get_start_plate_id(archive_id: int | None) -> int | None:
    """Resolve plate_id for print start without consuming stored direct-Print state.

    Direct-Print of a single plate from a multi-plate 3MF registers plate_id in
    ``_print_plate_ids`` at dispatch time; this lets the spoolman / usage tracker
    read it back at print-start without popping (the entry is popped on print
    completion or TTL eviction, mirroring ``_print_ams_mappings``).
    """
    if archive_id is None:
        return None
    return _print_plate_ids.get(archive_id)


def _partial_progress_scale(progress: int | float | None) -> float:
    """Clamp ``progress / 100`` into [0.0, 1.0] for partial-print scaling.

    Used by every site that multiplies a "would-have-used" slicer estimate
    down to "actually-used" for failed / cancelled / stopped prints. Centralised
    so the three sites in ``_background_notifications`` (and the per-plate
    override helper) can't drift apart on the coercion shape.
    """
    return max(0.0, min((progress or 0) / 100.0, 1.0))


def _scope_notification_archive_data_to_plate(
    archive_data: dict,
    archive_file_path: str | None,
    plate_id: int | None,
    print_status: str,
    progress: int | float | None,
    base_dir: Path,
) -> dict:
    """Override summed-across-plates totals in ``archive_data`` with the values
    for ``plate_id`` so the completion notification reports what was actually
    printed, not the whole project (#1785).

    The 3MF parser at services/archive.py:200-264 sums ``prediction`` and
    ``weight`` across every plate of a multi-plate file (#1593) — correct for
    the archive card's "whole project" headline, wrong for the completion
    notification of a single-plate print. The queue UI already re-reads the
    3MF per-plate at print_queue.py:272-285; this helper mirrors that for the
    notification payload (filament grams, time estimate, per-slot breakdown).

    No-ops when ``plate_id`` is None, the file is missing, or the 3MF carries
    no per-plate values — in every fail case the original ``archive_data`` is
    returned unchanged so the notification still sends.
    """
    if plate_id is None or not archive_file_path:
        return archive_data

    from backend.app.utils.threemf_tools import (
        extract_filament_usage_from_3mf,
        extract_print_time_from_3mf,
    )

    archive_path = base_dir / archive_file_path
    if not archive_path.exists():
        return archive_data

    plate_slots = extract_filament_usage_from_3mf(archive_path, plate_id)
    plate_grams = sum(f.get("used_g", 0) for f in plate_slots)
    plate_time = extract_print_time_from_3mf(archive_path, plate_id)

    scale = 1.0 if print_status == "completed" else _partial_progress_scale(progress)

    if plate_time:
        archive_data["print_time_seconds"] = plate_time

    # Gate both the grams headline AND the per-slot breakdown on the same
    # `plate_grams > 0` signal: if the 3MF carries per-plate filament rows but
    # they all sum to zero (slicer bug / re-slice without estimate), drop back
    # to the project-level grams the archive columns already provide rather
    # than ship a project-level headline next to an all-zero per-plate
    # breakdown.
    if plate_grams > 0:
        archive_data["actual_filament_grams"] = round(plate_grams * scale, 1)
        archive_data["filament_slots"] = [
            {
                "slot_id": s.get("slot_id"),
                "used_g": round((s.get("used_g") or 0) * scale, 1),
                "type": s.get("type", ""),
                "color": s.get("color", ""),
            }
            for s in plate_slots
        ]

    return archive_data


def _format_hms_error_summary(hms_errors: list[dict]) -> str | None:
    """Build a human-readable failure reason from MQTT hms_errors for PrintQueueItem.error_message.

    Each entry has keys: code ('0x4038'), attr (32-bit int), module, severity, and
    — since #2926 — the description the parser already resolved, which is preferred
    when present so the queue's failure reason reads the same as the status
    response. The short code still produces the bracketed label, and still
    resolves the sentence for a caller whose entries predate the field. An entry
    with a 16-char ``full_code`` is labelled with it instead, since the short code
    of an ``hms[]`` fault is not a code anyone can look up. Falls back to the bare
    label when no description is on file. Returns None for an empty list so
    callers can leave error_message unset.
    """
    if not hms_errors:
        return None
    from backend.app.services.hms_errors import get_error_description

    parts: list[str] = []
    for err in hms_errors:
        try:
            # `_hms_short_code` rather than a local derivation: this one used to
            # format the error without masking it to 16 bits, so an `hms[]` entry
            # whose code carries an alert-level group produced a five-digit label
            # like "0500_3000A" — not a code the user can look up, and never a
            # catalogue key, so the sentence was lost with it.
            short_code = _hms_short_code(err.get("attr", 0), err.get("code", 0))
        except (TypeError, ValueError):
            continue
        description = err.get("description") or get_error_description(short_code)
        # An `hms[]` fault's short code ("0500_000E") drops the part and level
        # groups and is not a code anyone can look up; its full code in the
        # printer screen's four groups is (#2728).
        full_code = str(err.get("full_code") or "")
        label = "-".join(full_code[i : i + 4] for i in range(0, 16, 4)) if len(full_code) == 16 else short_code
        parts.append(f"[{label}] {description}" if description else f"[{label}]")
    return "; ".join(parts) if parts else None


async def _bump_library_file_usage_if_completed(db, item, queue_status: str) -> None:
    """Increment LibraryFile.print_count and stamp last_printed_at when a queued
    print completes successfully. Gated to status=='completed': failed, cancelled
    and aborted prints do not count as usage. Caller is responsible for committing
    the session. No-op when the queue item has no linked library file (e.g. reprints
    from an archive). See #1008."""
    if queue_status != "completed" or item.library_file_id is None:
        return
    from backend.app.models.library import LibraryFile

    lib_file = await db.scalar(select(LibraryFile).where(LibraryFile.id == item.library_file_id))
    if lib_file is None:
        return
    lib_file.print_count = (lib_file.print_count or 0) + 1
    lib_file.last_printed_at = datetime.now(timezone.utc)


def mark_printer_stopped_by_user(printer_id: int) -> None:
    """Mark that the active print on this printer was stopped by the user from the queue UI.

    When on_print_complete fires with status 'failed' for a printer in this set we
    reclassify it as 'cancelled' so the correct 'print stopped' notification is sent
    rather than a 'print failed' notification.
    """
    _user_stopped_printers.add(printer_id)
    logging.getLogger(__name__).info("Marked printer %s as user-stopped from queue", printer_id)


# Largest finish photo attached to a notification; a bigger one is still linked.
_FINISH_PHOTO_ATTACH_MAX_BYTES = 2_500_000


async def _finish_photo_for_notification(
    db, archive, archive_id: int, filename: str
) -> tuple[str | None, bytes | None]:
    """The ``{finish_photo_url}`` link and the bytes to attach, for a print's finish photo.

    With authentication off the link is the archive's own photo route, as it
    always was: it opens without a login and doesn't expire. With
    authentication on that route needs a media token, which nothing tapping a
    link in Telegram, CallMeBot or a Home Assistant notification has, so the
    link only ever answered 401. The photo is then saved as a notification
    photo as well (utils/notification_photos.py) and the link points there: an
    unguessable name that opens this one photo and nothing else, for 3 days.

    The link is relative when no External URL is set. Bytes over
    ``_FINISH_PHOTO_ATTACH_MAX_BYTES`` are linked but not attached. Returns
    ``(None, None)`` when the photo can't be found.
    """
    from backend.app.api.routes.settings import get_setting
    from backend.app.core.auth import is_auth_enabled
    from backend.app.utils.archive_paths import find_archive_photo
    from backend.app.utils.notification_photos import save_notification_photo

    log = logging.getLogger(__name__)
    base = ((await get_setting(db, "external_url")) or "").strip().rstrip("/")
    url: str | None = f"{base}/api/v1/archives/{archive_id}/photos/{filename}"

    photo_bytes: bytes | None = None
    try:
        photo_path = find_archive_photo(archive, filename)
        if photo_path is not None:
            photo_bytes = await asyncio.to_thread(photo_path.read_bytes)
    except Exception as e:
        log.warning("[NOTIFY-BG] Failed to read finish photo bytes: %s", e)

    try:
        auth_on = await is_auth_enabled(db)
    except Exception:
        auth_on = True  # Unknown: the archive link may need a login, so don't rely on it.
    if auth_on:
        url = None
        if photo_bytes:
            try:
                name = await asyncio.to_thread(save_notification_photo, photo_bytes, "print_complete")
                url = f"{base}/api/v1/notifications/photos/{name}"
            except Exception as e:
                log.warning("[NOTIFY-BG] Failed to save finish photo for its link: %s", e)

    if photo_bytes is not None and len(photo_bytes) > _FINISH_PHOTO_ATTACH_MAX_BYTES:
        log.warning("[NOTIFY-BG] Finish photo too large for attachment: %s bytes", len(photo_bytes))
        return url, None
    if photo_bytes:
        log.info("[NOTIFY-BG] Loaded finish photo bytes: %s bytes", len(photo_bytes))
    return url, photo_bytes


async def _capture_snapshot_for_notification(printer_id: int, printer, logger) -> bytes | None:
    """Capture a camera snapshot for notification image attachment.

    Returns JPEG bytes (max 2.5MB) or None if capture fails or is unavailable.
    Uses: external camera > buffered frame > fresh capture.
    """
    if not printer:
        return None

    try:
        from backend.app.api.routes.settings import get_setting

        async with async_session() as db:
            capture_enabled = await get_setting(db, "capture_finish_photo")

        if capture_enabled is not None and capture_enabled.lower() != "true":
            return None

        # Try external camera first
        if printer.external_camera_enabled and printer.external_camera_url:
            logger.info("[SNAPSHOT] Capturing from external camera for printer %s", printer_id)
            from backend.app.api.routes.camera import live_frame_for_capture
            from backend.app.services.external_camera import capture_frame

            # An external camera allows one reader, so capturing while a viewer
            # is attached fails (#2707). A None here falls through to the paths
            # below exactly as a failed capture did.
            defer, buffered = live_frame_for_capture(printer_id)
            if defer:
                frame_data = buffered
            else:
                frame_data = await capture_frame(
                    printer.external_camera_url,
                    printer.external_camera_type or "mjpeg",
                    snapshot_url=printer.external_camera_snapshot_url,
                )
            if frame_data and len(frame_data) <= 2_500_000:
                logger.info("[SNAPSHOT] External camera frame: %s bytes", len(frame_data))
                return _apply_camera_rotation(frame_data, printer, logger)

        # Try buffered frame from active stream
        from backend.app.api.routes.camera import _active_chamber_streams, _active_streams, get_buffered_frame

        active_for_printer = [k for k in _active_streams if k.startswith(f"{printer_id}-")]
        active_chamber = [k for k in _active_chamber_streams if k.startswith(f"{printer_id}-")]
        buffered_frame = get_buffered_frame(printer_id)

        if (active_for_printer or active_chamber) and buffered_frame:
            logger.info("[SNAPSHOT] Using buffered frame for printer %s: %s bytes", printer_id, len(buffered_frame))
            if len(buffered_frame) <= 2_500_000:
                return _apply_camera_rotation(buffered_frame, printer, logger)

        # Fresh capture from printer camera
        logger.info("[SNAPSHOT] Capturing fresh frame for printer %s", printer_id)
        from backend.app.services.camera import capture_camera_frame_bytes

        frame_data = await capture_camera_frame_bytes(
            printer.ip_address, printer.access_code, printer.model, timeout=15
        )
        if frame_data and len(frame_data) <= 2_500_000:
            logger.info("[SNAPSHOT] Fresh camera frame: %s bytes", len(frame_data))
            return _apply_camera_rotation(frame_data, printer, logger)

    except Exception as e:
        logger.warning("[SNAPSHOT] Failed to capture snapshot for printer %s: %s", printer_id, e)

    return None


async def _maybe_bank_inprint_frame(printer_id: int, layer_num: int) -> None:
    """#1867: bank a recent in-print camera frame for the finish photo.

    Called on every layer change and (#2547) on every print-progress advance.
    Grabs one frame (throttled) into ``_inprint_frame_bank`` so the finish-photo
    path has a pre-End-G-code image for prints that end with a plate swap.

    Both drivers are print telemetry that stops the instant printing ends: no
    further layers, and progress freezes before the End G-code (e.g. SwapMod
    plate swap) executes. So the last banked frame is always the finished print,
    never the swapped plate — that property is what the #1867 path relies on and
    it must survive any change to the throttle below.

    Layer changes alone were not enough: they stop when the *final* layer
    begins, which on a three-minute last layer left the bank stale by the whole
    length of that layer (#2547). Progress keeps ticking through it.

    Best-effort: any failure just leaves the previous banked frame.
    """
    logger = logging.getLogger(__name__)
    client = printer_manager.get_client(printer_id)
    state = client.state if client else None
    if not state or state.state != "RUNNING":
        return
    # Only during actual extrusion — firmware ticks layer_num during the
    # pre-print calibration sequence, whose sub-stages are non-zero.
    if state.mc_print_sub_stage not in (None, 0):
        return

    # #2547: throttled uniformly, with no last-layer exemption. The old code
    # bypassed the throttle on the final layer to guarantee a fresh frame there;
    # now that progress advances also drive banking, that exemption would fire a
    # camera grab on every percent tick of the last layer. Bambu printers accept
    # one RTSP client at a time, so each grab contends with the live view.
    now = time.monotonic()
    last = _inprint_frame_bank_ts.get(printer_id, 0.0)
    if (now - last) < _INPRINT_BANK_MIN_INTERVAL:
        return
    total = state.total_layers or 0

    try:
        async with async_session() as db:
            from backend.app.models.printer import Printer

            result = await db.execute(select(Printer).where(Printer.id == printer_id))
            printer = result.scalar_one_or_none()
        if not printer:
            return
        # Reuses the notification snapshot path, which honours the
        # `capture_finish_photo` setting (returns None when disabled) so we
        # don't bank frames the user never asked for.
        frame = await _capture_snapshot_for_notification(printer_id, printer, logger)
        if frame:
            _inprint_frame_bank[printer_id] = frame
            _inprint_frame_bank_ts[printer_id] = now
            logger.debug(
                "[FINISH-PHOTO-BANK] banked in-print frame for printer %s at layer %s/%s (%d bytes)",
                printer_id,
                layer_num,
                total,
                len(frame),
            )
    except Exception as e:
        logger.debug("[FINISH-PHOTO-BANK] bank failed for printer %s: %s", printer_id, e)


def _apply_camera_rotation(image_data: bytes, printer, logger) -> bytes:
    """Apply camera rotation to snapshot image if configured."""
    from backend.app.services.camera import apply_camera_rotation

    return apply_camera_rotation(image_data, getattr(printer, "camera_rotation", 0), logger)


async def _dispatch_user_print_email(
    status: str,
    created_by_id: int | None,
    printer_name: str,
    filename: str,
    db,
    image_data: bytes | None = None,
    finish_photo_url: str | None = None,
) -> None:
    """Send a user-specific print-completion email based on print status.

    Maps the normalised print status to the correct event type and delegates
    to :meth:`NotificationService.send_user_print_email`.  A single helper
    avoids duplicating the ``if status == "completed" / elif "failed" / elif
    "stopped"`` dispatch block at every call site.

    Does nothing if *created_by_id* is ``None``.
    """
    if created_by_id is None:
        return
    if status == "completed":
        event_type = "user_print_complete"
    elif status == "failed":
        event_type = "user_print_failed"
    elif status in ("stopped", "aborted", "cancelled"):
        event_type = "user_print_stopped"
    else:
        return
    await notification_service.send_user_print_email(
        event_type=event_type,
        created_by_id=created_by_id,
        printer_name=printer_name,
        filename=filename,
        db=db,
        image_data=image_data,
        finish_photo_url=finish_photo_url,
    )


def _load_objects_from_archive(archive, printer_id: int, logger) -> None:
    """Extract printable objects from an archive's 3MF file and store in printer state."""
    try:
        from backend.app.services.archive import extract_printable_objects_from_archive

        client = printer_manager.get_client(printer_id)
        if not client:
            return

        # Extract with positions for UI overlay, scoped to the plate that
        # is printing — resolve_plate_id is the same resolver /cover uses,
        # so the object list can't disagree with the thumbnail it is drawn
        # over (#2522).
        printable_objects, bbox_all = extract_printable_objects_from_archive(
            app_settings.base_dir / archive.file_path,
            plate_number=resolve_plate_id(client.state),
        )
        if printable_objects:
            client.state.printable_objects = printable_objects
            client.state.printable_objects_bbox_all = bbox_all
            client.state.skipped_objects = []
            logger.info("Loaded %s printable objects for printer %s", len(printable_objects), printer_id)
    except Exception as e:
        logger.debug("Failed to extract printable objects from archive: %s", e)


async def _restore_printable_objects(printer_id: int, state, db, logger) -> None:
    """Put the skip-objects list back after a restart mid-print.

    ``PrinterState.printable_objects`` is in-memory only, and the only thing
    that fills it is ``_load_objects_from_archive`` on the print-start paths —
    which the #1304 guard suppresses on the first RUNNING push after startup.
    Everything else this hook restores (the archive, the usage-tracking session,
    the timelapse baseline) was already handled; the object list was not, so a
    restart mid-print took skip-objects away for the rest of that print.

    Nothing recovered it either: the printer card gates its Skip button on the
    object count, and the one endpoint that can rebuild the list is reachable
    only from the modal that button opens.

    Anchored on ``subtask_id``, which the firmware mints per print, so a
    leftover ``status="printing"`` row from a completion we never saw cannot
    hand this print someone else's objects. Without one, nothing is loaded
    rather than guessed — the reload path on ``GET /print/objects`` covers that
    case on demand.
    """
    client = printer_manager.get_client(printer_id)
    if client is None or client.state.printable_objects:
        return

    subtask_id = str(getattr(state, "subtask_id", "") or "").strip()
    if subtask_id in ("", "0"):
        return

    from backend.app.models.archive import PrintArchive

    archive = await db.scalar(
        select(PrintArchive)
        .where(
            PrintArchive.printer_id == printer_id,
            PrintArchive.status == "printing",
            PrintArchive.subtask_id == subtask_id,
        )
        .order_by(PrintArchive.created_at.desc())
        .limit(1)
    )
    if archive is not None:
        _load_objects_from_archive(archive, printer_id, logger)


# printer_id -> the in-flight retry task, so print completion can cancel it.
_fallback_3mf_retry_tasks: dict[int, asyncio.Task] = {}

# printer_id -> lock serialising recovery attempts for that printer. Three callers
# can reach one archive at once: the cover endpoint (whose single-flight coalesces
# by view, so two views race), the cool-off retry task, and print completion.
# Without this they each read file_path == "" and each run a full copy, so the row
# ends up pointing at one timestamped directory while the others sit orphaned.
#
# Keyed by printer rather than archive because a printer runs one print at a time,
# which makes the two equally strong here — and it bounds the dict by printer
# count instead of needing a cleanup pass. Popping a per-archive entry cannot be
# done safely: `Lock.locked()` reads False between release and the queued waiter
# resuming, so "no waiters" is not a question this API can answer.
_fallback_recovery_locks: dict[int, asyncio.Lock] = {}


async def _dispatch_outcome_confirmation_safely(
    db,
    printer_id: int,
    printer_name: str,
    data: dict,
    archive_id: int,
    archive_data: dict | None = None,
) -> None:
    """``dispatch_outcome_confirmation`` for a caller that has more to do on ``db``.

    The completion task sends the per-user print email on the same session
    right after the prompt. A failed statement in the prompt leaves that
    session needing a rollback, and without one the email step fails with
    PendingRollbackError; the prompt is the optional part, so it must not be
    the reason the email never goes out.
    """
    try:
        await dispatch_outcome_confirmation(db, printer_id, printer_name, data, archive_id, archive_data)
    except Exception as e:
        logging.getLogger(__name__).error("[NOTIFY-BG] Outcome-confirmation dispatch failed: %s", e, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            logging.getLogger(__name__).debug("Rollback after a failed outcome confirmation failed too", exc_info=True)


async def dispatch_outcome_confirmation(
    db,
    printer_id: int,
    printer_name: str,
    data: dict,
    archive_id: int,
    archive_data: dict | None = None,
) -> bool:
    """Emit the post-print outcome prompt for a completed archive (#1898).

    Gated on the archive itself: ``confirm_requested`` is the opt-in (from the
    queue item, or from ``confirm_outcome_external_prints`` for a print
    PrintLab did not start) and ``user_verdict`` being unset is what makes the
    question still open. Mints the per-archive capability token the one-tap
    verdict links carry.

    Lives here rather than inline in ``on_print_complete``'s notification task
    because that task swallows every exception: extracted, the gate and the two
    emissions can be driven by a test, which is the only thing standing between
    a regression here and a farm that quietly stops asking.

    Returns whether a prompt was sent.
    """
    logger = logging.getLogger(__name__)
    from backend.app.models.archive import PrintArchive

    confirm_archive = (await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))).scalar_one_or_none()
    if not (confirm_archive and confirm_archive.confirm_requested and confirm_archive.user_verdict is None):
        return False

    import secrets as _secrets

    # A spent token stays on the row so the one-tap route can recognise it, so
    # "has a token" no longer means "answerable". A prompt going out now needs a
    # live one: mint a new token whenever the stored one is already spent, or
    # every button in the new message would land on the already-answered page.
    if not confirm_archive.confirm_token or confirm_archive.confirm_token_used_at is not None:
        confirm_archive.confirm_token = _secrets.token_urlsafe(32)
        confirm_archive.confirm_token_used_at = None
        await db.commit()

    from backend.app.api.routes.settings import get_external_base_url, get_setting

    base = await get_external_base_url(db)
    if not await get_setting(db, "external_url"):
        # Both the Telegram inline keyboard and the ntfy action buttons need an
        # absolute URL, so an unconfigured install used to get a message body
        # with two unusable relative paths and no buttons at all. The shared
        # fallback at least produces tappable links; say which setting makes
        # them resolve from a phone.
        logger.warning(
            "[#1898] No external_url configured — the outcome prompt's Good/Reject links point at %s. "
            "Set Settings → External URL so they resolve away from this host.",
            base,
        )
    token = confirm_archive.confirm_token
    good_url = f"{base}/api/v1/archives/confirm/{token}/good"
    reject_url = f"{base}/api/v1/archives/confirm/{token}/reject"
    confirm_url = f"{base}/archives?confirm={archive_id}"

    await ws_manager.send_print_confirm_request(
        printer_id,
        {
            "archive_id": archive_id,
            "print_name": confirm_archive.print_name or confirm_archive.filename,
        },
    )
    await notification_service.on_print_confirm_request(
        printer_id,
        printer_name,
        data,
        db,
        archive_data=archive_data,
        good_url=good_url,
        reject_url=reject_url,
        confirm_url=confirm_url,
        archive_id=archive_id,
    )
    return True


_TIMELAPSE_VIDEO_EXTENSIONS = (".mp4", ".avi")

# Poll schedule for the post-print timelapse scan (#2704). Module-level so
# tests can shrink them without waiting out real delays.
#
# This replaced a fixed [5, 10, 20, 30] retry ladder, i.e. roughly 65 s of
# looking. Across 247 support bundles the attempt that found the video was #1
# 272 times, then 17 / 13 / 13 — a flat tail against the cutoff rather than a
# decaying one, which is the signature of a budget that expires while files are
# still arriving. 457 scans were scheduled and only 262 ever attached. Big
# prints make big videos and the printer writes them after the print ends, so
# the poll now runs for minutes and costs one FTP LIST per round.
_TIMELAPSE_SCAN_FIRST_DELAY_SECONDS: float = 5.0
_TIMELAPSE_SCAN_POLL_INTERVAL_SECONDS: float = 30.0
_TIMELAPSE_SCAN_TIMEOUT_SECONDS: float = 900.0


# Defaults for the finish-photo-from-timelapse polling loop (#1397). These are
# module-level so tests can monkeypatch them down to ~0 without timing out.
_FINISH_PHOTO_TIMELAPSE_POLL_INTERVAL_SECONDS: float = 3.0
_FINISH_PHOTO_TIMELAPSE_POLL_TIMEOUT_SECONDS: float = 60.0

# How long the *background* upgrade keeps waiting after the notification has
# already gone out (#2704 follow-up). The short bound above exists so a slow
# printer can't hold up the print-complete notification; this one exists so the
# archive still ends up with the better frame afterwards.
#
# Measured across 261 attaches in the support bundles, the video lands a median
# 13s after the print ends — but the P1 series writes MJPEG AVI rather than
# H.264 MP4 and serves it slowly, so its p90 is 167s and the worst observed case
# was 546s. Every other model was inside 26s. The long budget is therefore
# almost entirely for P1-series users; on everything else the short wait already
# wins and this task never runs.
_FINISH_PHOTO_UPGRADE_TIMEOUT_SECONDS: float = 900.0


async def _restore_usage_tracking_session(printer_id: int, state, db, logger) -> None:
    """Put the filament-attribution context back after a restart mid-print.

    ``usage_tracker._active_sessions`` and ``PrinterState.tray_change_log``
    both die with the process. The print keeps running, so at completion the
    tracker would fall back to whatever the printer reports *now* — and AMS
    filament backup makes "now" the substitute tray, charging the whole print
    to the spool that only finished it.

    The persisted row is only trusted when its print name still matches what
    the printer says it is running: a row left behind by a completion we never
    saw must not attach itself to the next print.
    """
    try:
        from backend.app.api.routes.settings import get_setting
        from backend.app.services.usage_tracker import (
            clear_persisted_session,
            get_persisted_print_name,
            restore_session,
        )

        persisted_name = await get_persisted_print_name(db, printer_id)
        current_name = (state.subtask_name or "").strip()
        if persisted_name and current_name and persisted_name.strip() != current_name:
            logger.info(
                "[RESTART] Discarding stale print session for printer %s (%r != running %r)",
                printer_id,
                persisted_name,
                current_name,
            )
            await clear_persisted_session(db, printer_id)
            # Fall through to seeding: the print on the printer is real, it just
            # isn't the one the row described.
            persisted_log = None
        else:
            # Spoolman users get the tray-change log back but no in-memory
            # session — see ``on_print_start`` on why that dict is load-bearing
            # for the remain%-sync guard.
            _spoolman_on = await get_setting(db, "spoolman_enabled")
            persisted_log = await restore_session(
                db,
                printer_id,
                register_active=not (bool(_spoolman_on) and _spoolman_on.lower() == "true"),
            )
        if persisted_log:
            restored = [tuple(entry) for entry in persisted_log if isinstance(entry, (list, tuple)) and len(entry) == 2]
            # Anything this process already observed goes after the persisted
            # history — the log is ordered by layer, and a fresh process can
            # only have seen changes from later in the print.
            for entry in state.tray_change_log or []:
                if tuple(entry) not in restored:
                    restored.append(tuple(entry))
            state.tray_change_log = restored

        tray_now = state.tray_now
        if 0 <= tray_now <= 254:
            if not state.tray_change_log:
                # No persisted history — a print that started before this build,
                # or before the row existed. Seed with the tray feeding right
                # now so the remainder of the print is at least attributable to
                # the right spool.
                state.tray_change_log = [(tray_now, state.layer_num)]
                logger.info(
                    "[RESTART] Seeded tray change log for printer %s: tray=%d at layer=%d",
                    printer_id,
                    tray_now,
                    state.layer_num,
                )
            # The tray handler updates ``last_loaded_tray`` on every push
            # regardless of whether it logged a change, so re-align it to avoid
            # a duplicate entry on the next push. Only ever with a real tray:
            # ``last_loaded_tray`` is the "survives the end-of-print retract to
            # 255" fallback, and writing 255 into it would defeat that.
            state.last_loaded_tray = tray_now
    except Exception:
        # Never let attribution recovery cost the caller its timelapse
        # baseline — that capture has to happen before the printer uploads
        # the in-flight MP4 and there is no second chance at it.
        logger.exception("[RESTART] Failed to restore usage-tracking session for printer %s", printer_id)


async def on_print_running_observed(printer_id: int, data: dict):
    """Restart-recovery for a print that started before PrintLab came up.

    bambu_mqtt.py suppresses ``on_print_start`` on the first RUNNING push
    after PrintLab startup (#1304 guard, prevents duplicate archive
    creation). This hook restores the persisted archive into ``_active_prints``
    and captures the timelapse baseline that normally hangs off print start.

    Fires once per session, in lieu of on_print_start when restart-recovery
    kicks in. The printer doesn't upload the timelapse until after PRINT
    COMPLETE, so a baseline captured any time during the print is still
    pre-upload.
    """
    logger = logging.getLogger(__name__)

    async with async_session() as db:
        from backend.app.models.printer import Printer

        state = printer_manager.get_status(printer_id)
        if state is not None:
            authorization = await _is_printlab_authorized_print(printer_id, state, db)
            if authorization is True:
                logger.info("[RESTART] Restored active PrintLab print for printer %s", printer_id)

            await _restore_usage_tracking_session(printer_id, state, db, logger)
            await _restore_printable_objects(printer_id, state, db, logger)

        result = await db.execute(select(Printer).where(Printer.id == printer_id))
        printer = result.scalar_one_or_none()
        if not printer:
            logger.warning(
                "[TIMELAPSE] on_print_running_observed: printer %s not found in DB, skipping baseline",
                printer_id,
            )
            return

    # Avoid double-capture: ownership reconciliation above must still run when
    # a baseline already exists, but the camera work itself is one-shot.
    if printer_id in _timelapse_baselines:
        logger.debug(
            "[TIMELAPSE] on_print_running_observed: baseline already present for printer %s, skipping",
            printer_id,
        )
        return

    await _capture_timelapse_baseline_at_start(printer, printer_id, logger)


def _is_active_archive_stale(archive, state) -> tuple[bool, str]:
    """Return ``(is_stale, reason)`` for an archive in ``status="printing"``
    against the printer's current MQTT state.

    Reconciliation triggers (#1542 follow-up — recovers from missed PRINT
    COMPLETE events, typically a print finishing during an MQTT disconnect
    window followed by a smart-plug power cycle):

      1. Printer state is terminal (IDLE / FINISH / FAILED). The print is
         provably not running anymore — only branch that should fire under
         normal disconnect-then-reconnect timing.
      2. Printer has a different ``subtask_id`` than the archive. Bambu
         firmware mints a fresh ``subtask_id`` for each print, including the
         ghost replay it runs after a power cycle from a leftover SD file —
         so a mismatch unambiguously means the in-DB archive is no longer
         the print on the printer.
      3. Printer is running but ``subtask_name`` is empty. The printer
         doesn't know what it's running; the archive's reference to it is
         already broken.

    Conservative on purpose: PAUSE / PREPARE / SLICING and any RUNNING state
    with matching subtask_id+subtask_name is left alone. The cost of a false
    positive is a duplicate archive on the next real PRINT COMPLETE — the
    reactive handler uses ``_active_prints`` for lookup, which the reconcile
    clears on synthesis, so the real completion creates a fresh row instead
    of overwriting the synthesised one (#1679). The cost of a false negative
    is the ghost-print loop in #1542.

    Pre-push guard (#1679): when ``state.state`` is empty or ``"unknown"``,
    MQTT has connected but the first ``push_status`` response hasn't been
    applied yet — ``PrinterState`` is sitting on its construction defaults.
    The reconcile caller in ``on_printer_status_change`` is already gated
    on a real ``state.state``, so in normal operation this branch is
    unreachable; it's kept as belt-and-braces for future callers and for
    the narrow window where a partial state update could arrive
    (``state.state`` set but ``subtask_name`` not yet populated). Returning
    ``not stale`` on degenerate input is strictly conservative: a real
    stale archive will still be caught by the next push_status arriving
    with terminal state.
    """
    current_state = (state.state or "").upper()
    if current_state in ("", "UNKNOWN"):
        # No real push_status yet — PrinterState defaults are not evidence.
        return False, ""
    if current_state in ("IDLE", "FINISH", "FAILED"):
        return True, f"printer state {current_state}"
    # Below here the printer is in a running / pre-running state (RUNNING /
    # PAUSE / PREPARE / SLICING / etc.) — decide based on subtask identity.
    current_subtask_id = (state.subtask_id or "").strip()
    if archive.subtask_id and current_subtask_id and archive.subtask_id != current_subtask_id:
        return True, f"subtask_id changed ({archive.subtask_id!r} → {current_subtask_id!r})"
    current_subtask_name = (state.subtask_name or "").strip()
    if not current_subtask_name:
        return True, "printer subtask_name empty"
    return False, ""


async def prime_kprofile_table(printer_id: int) -> int:
    """Read the printer's calibration table once per connection.

    The AMS slot card shows a K value per slot (#2854). On the printers whose
    trays carry no ``k`` field of their own -- the whole H2 series, whose trays
    report ``cali_idx`` and nothing else -- that number can only come from
    ``state.kprofiles``, and nothing used to fill it on connect. It arrived by
    luck: someone opening the Profiles page or Configure Slot, a nightly GitHub
    backup, or the printer answering a query BambuStudio made on the report
    topic we share. A PrintLab that nobody visited showed a card with no K
    values at all.

    Only the diameters actually fitted are asked for, which is one request on a
    single-nozzle printer and two on a dual. Probing the four sizes blind is
    what the backup does, and it is both wasteful and the thing that used to
    blank the table.

    Returns the number of nozzles whose table was read.
    """
    client = printer_manager.get_client(printer_id)
    state = printer_manager.get_status(printer_id)
    if client is None or state is None or not state.connected:
        return 0

    # Deduplicated, order preserved: a dual-nozzle printer with two 0.4s should
    # ask once, and both entries are empty until the first push_status lands.
    diameters = list(dict.fromkeys(n.nozzle_diameter for n in (state.nozzles or []) if n.nozzle_diameter))
    if not diameters:
        logging.getLogger(__name__).debug(
            "[Printer %s] No nozzle diameter reported yet; leaving the K-profile table to the next reader",
            printer_id,
        )
        return 0

    primed = 0
    for diameter in diameters:
        try:
            profiles = await client.get_kprofiles(nozzle_diameter=diameter, max_retries=2)
        except Exception as exc:  # noqa: BLE001
            # A printer that won't answer costs the card its K values, nothing
            # more — never the connection this runs on the back of.
            logging.getLogger(__name__).warning(
                "[Printer %s] Could not read the K-profile table for nozzle %s: %s", printer_id, diameter, exc
            )
            continue
        primed += 1
        logging.getLogger(__name__).info(
            "[Printer %s] Primed K-profile table for nozzle %s: %d profiles", printer_id, diameter, len(profiles)
        )
    return primed


async def reconcile_stale_active_prints(printer_id: int) -> int:
    """Synthesise ``on_print_complete`` for archives whose print can't be
    running on the printer anymore.

    Called once per MQTT (re)connection (from on_printer_status_change when
    the connected edge flips False → True) and at PrintLab startup (from
    the FastAPI lifespan). Without this, a print that completes during a
    disconnect window — followed by a smart-plug-driven power cycle — leaves
    the ``.3mf`` on the SD card, the firmware auto-replays it on next boot,
    and PrintLab fires a fresh PRINT START for the ghost rather than the
    SD cleanup that PRINT COMPLETE was supposed to run. Repeats every
    power cycle until the operator notices (#1542 follow-up). Reconciliation
    closes the loop by faking the missed PRINT COMPLETE — the existing
    cleanup chain handles SD-file deletion, status updates, usage tracking,
    and notifications.

    Synthesised ``status="aborted"`` is the conservative label: we have no
    proof the print finished successfully (and no progress evidence to
    promote to ``"completed"``). The real PRINT COMPLETE callback, if it
    fires later, overwrites the status with the correct value.

    Returns the number of archives reconciled.
    """
    state = printer_manager.get_status(printer_id)
    if not state:
        return 0
    # Don't reconcile while disconnected — we'd be making a decision against
    # stale cached state. The connected → reconcile edge handles this.
    if not state.connected:
        return 0

    from backend.app.models.archive import PrintArchive

    reconciled = 0
    async with async_session() as db:
        result = await db.execute(
            select(PrintArchive).where(
                PrintArchive.printer_id == printer_id,
                PrintArchive.status == "printing",
            )
        )
        active = list(result.scalars().all())

    if not active:
        return 0

    logger = logging.getLogger(__name__)
    for archive in active:
        is_stale, reason = _is_active_archive_stale(archive, state)
        if not is_stale:
            continue
        logger.info(
            "[RECONCILE] Printer %s: synthesising missed PRINT COMPLETE for archive %s (%s) — %s",
            printer_id,
            archive.id,
            archive.filename,
            reason,
        )
        # Synthesised payload: minimal fields the on_print_complete chain
        # needs. `_reconciled` marker lets downstream code distinguish this
        # from a real MQTT-driven completion if it ever needs to (e.g. for
        # metrics / debug logging). raw_data is the live printer state so
        # the usage tracker can compare end-of-print remain% against the
        # captured start values.
        try:
            await on_print_complete(
                printer_id,
                {
                    "status": "aborted",
                    "filename": archive.filename,
                    "subtask_name": archive.print_name or "",
                    "subtask_id": archive.subtask_id or "",
                    "raw_data": state.raw_data or {},
                    "_reconciled": True,
                },
            )
            reconciled += 1
        except Exception as e:
            # Catch-all: a reconciliation failure must not block the
            # printer's normal status flow. The archive stays in
            # ``status="printing"`` and the next reconnect retries.
            logger.warning(
                "[RECONCILE] on_print_complete synthesis failed for archive %s: %s",
                archive.id,
                e,
            )

    return reconciled


# #2547: clearance left between the nozzle and the top of the print when the
# plate is commanded back into camera framing. The nozzle is parked away from
# the part by then, so this is belt-and-braces against a max_z_height that
# under-reports (e.g. a slicer that excludes a final Z hop).
_PLATE_RESTORE_CLEARANCE_MM = 10.0
# How far below the restored position to drop the plate again afterwards, so
# the print is as reachable as Bambu's own end G-code leaves it. Matches the
# stock `G1 Z{max_layer_z + 100}`; the firmware clamps it to the travel limit
# on machines with less headroom.
_PLATE_PARK_DROP_MM = 100.0
# Feedrate for both moves. F600 is exactly what Bambu's own end G-code uses on
# this axis, so it is a proven-safe speed for the full travel.
_PLATE_RESTORE_FEEDRATE = 600
# Time allowed for the plate to reach the restored position before the camera
# grab. Sized for the ~100 mm the stock end G-code drops at F600 (10 mm/s).
_PLATE_RESTORE_SETTLE_SECONDS = 12.0
# How long `_background_finish_photo` waits for this producer. Must cover the
# settle window plus a worst-case RTSP grab (15s), and stay below the
# notification path's own photo wait so a slow producer degrades to a
# photo-less notification rather than a missed one.
_FINISH_PHOTO_PRODUCER_WAIT_SECONDS = _PLATE_RESTORE_SETTLE_SECONDS + 23.0


async def _max_z_for_current_print(printer_id: int, data: dict, logger) -> float | None:
    """Height of the print that just finished on ``printer_id``, or None (#2547).

    This number becomes the target of a real Z move, so every step here refuses
    rather than guesses. A height belonging to some *other* print is the one
    failure that could drive the nozzle into the model: 20 mm carried onto a
    200 mm print would command the plate up through the part.

    Two independent things therefore have to agree before a height is returned:

    1. **Identity.** The archive is matched by the finished print's own
       ``subtask_name``, by equality rather than a ``LIKE``, so "Cube" can never
       resolve to "Cube v2". Matching on "most recent archive for this printer"
       is not good enough — ``on_print_complete`` pops the ``_active_prints``
       binding concurrently with us, and a print PrintLab failed to archive
       would silently resolve to its predecessor.
    2. **Corroboration.** The archive's layer count (parsed from the 3MF) has to
       match the layer count the printer itself reported over MQTT for the print
       that just ended. These come from genuinely different sources, so a
       mismatch means the row is not this print, whatever its name says.

    ``completed`` is accepted alongside ``printing`` only because
    ``on_print_complete`` may already have flipped the status by the time we
    run; the identity check above is what actually selects the row.
    """
    subtask_name = (data.get("subtask_name") or "").strip()
    if not subtask_name:
        # Nothing to identify the print by — refuse rather than fall back to
        # "whatever ran last on this printer".
        logger.info("[PLATE-RESTORE] printer %s: print has no name to match on — skipping", printer_id)
        return None

    try:
        from backend.app.models.archive import PrintArchive
        from backend.app.utils.threemf_tools import extract_max_z_height_from_3mf

        async with async_session() as db:
            result = await db.execute(
                select(PrintArchive)
                .where(
                    PrintArchive.printer_id == printer_id,
                    PrintArchive.status.in_(("printing", "completed")),
                    PrintArchive.deleted_at.is_(None),
                    or_(
                        PrintArchive.print_name == subtask_name,
                        PrintArchive.filename == subtask_name,
                        PrintArchive.filename == f"{subtask_name}.3mf",
                        PrintArchive.filename == f"{subtask_name}.gcode.3mf",
                    ),
                )
                .order_by(PrintArchive.id.desc())
                .limit(1)
            )
            archive = result.scalar_one_or_none()
        if archive is None or not archive.file_path:
            logger.info("[PLATE-RESTORE] printer %s: no archive matches %r — skipping", printer_id, subtask_name)
            return None

        client = printer_manager.get_client(printer_id)
        reported_layers = getattr(getattr(client, "state", None), "total_layers", None)
        if reported_layers and archive.total_layers and reported_layers != archive.total_layers:
            logger.warning(
                "[PLATE-RESTORE] printer %s: archive %s says %s layers but the printer reported %s "
                "— refusing to move the plate on a height that may not be this print's",
                printer_id,
                archive.id,
                archive.total_layers,
                reported_layers,
            )
            return None

        path = Path(archive.file_path)
        if not path.is_absolute():
            path = Path(app_settings.data_dir) / path
        return await asyncio.to_thread(extract_max_z_height_from_3mf, path, archive.plate_id or 1)
    except Exception as e:
        logger.debug("[PLATE-RESTORE] printer %s: no usable print height: %s", printer_id, e)
        return None


async def _restore_plate_for_finish_photo(printer_id: int, max_z_height: float, logger) -> bool:
    """Raise the plate back into camera framing before the finish photo (#2547).

    Bambu's end G-code drops the plate ~100 mm as the last thing it does, so by
    the time ``gcode_state`` reaches FINISH the finished print sits far below
    the camera's natural framing — the complaint behind #1145, #1397 and #1565.
    This commands an absolute ``G1 Z`` back to just above the last printed
    layer.

    Absolute, not relative, is the whole safety argument. ``max_z_height +
    clearance`` is a height the toolhead was physically at seconds earlier, so
    it is inside the travel limits by construction and leaves the nozzle above
    the part. It is also unambiguous across model families: Z is the
    nozzle-to-bed gap whether the bed moves (X1/P1/H2) or the toolhead does
    (A1), so unlike the relative bed-jog path (#1334) there is no sign to get
    wrong. ``M211`` is never touched — see the bed-jog docstring for why
    (#2579).

    Returns True if the move was sent and waited out, False if it was skipped.
    """
    client = printer_manager.get_client(printer_id)
    if client is None:
        return False

    # Re-read state immediately before commanding motion. If the queue has
    # already started the next print, the printer is no longer ours to move.
    state = getattr(client, "state", None)
    if state is None or state.state != "FINISH":
        logger.info(
            "[PLATE-RESTORE] printer %s is in state %s, not FINISH — skipping",
            printer_id,
            getattr(state, "state", "unknown"),
        )
        return False

    target_z = max_z_height + _PLATE_RESTORE_CLEARANCE_MM
    if not client.send_gcode(f"G90\nG1 Z{target_z:.2f} F{_PLATE_RESTORE_FEEDRATE}"):
        logger.warning("[PLATE-RESTORE] printer %s: send failed — capturing where it is", printer_id)
        return False

    logger.info(
        "[PLATE-RESTORE] printer %s: plate to Z%.2f (print top %.2f + %.1f clearance), settling %.0fs",
        printer_id,
        target_z,
        max_z_height,
        _PLATE_RESTORE_CLEARANCE_MM,
        _PLATE_RESTORE_SETTLE_SECONDS,
    )
    await asyncio.sleep(_PLATE_RESTORE_SETTLE_SECONDS)
    return True


def _park_plate_after_finish_photo(printer_id: int, max_z_height: float, logger) -> None:
    """Drop the plate again after the finish photo (#2547).

    Without this the user walks up to a finished print sitting just under the
    nozzle, which is exactly the position Bambu's end G-code goes out of its way
    to avoid — awkward to lift the plate out, and easy to knock the toolhead.
    Fire-and-forget: if it doesn't land, the plate is merely high, and the next
    print homes anyway.
    """
    client = printer_manager.get_client(printer_id)
    state = getattr(client, "state", None) if client else None
    if client is None or state is None or state.state != "FINISH":
        return
    client.send_gcode(f"G90\nG1 Z{max_z_height + _PLATE_PARK_DROP_MM:.2f} F{_PLATE_RESTORE_FEEDRATE}")
    logger.debug("[PLATE-RESTORE] printer %s: plate returned to unload height", printer_id)


async def _plate_restore_is_blocked_by_queue(printer_id: int) -> bool:
    """True if a queue item is about to take this printer (#2547).

    The scheduler dispatches the next job the moment a print completes, and a
    plate move interleaved with a print start is not a race worth having. The
    state re-check in ``_restore_plate_for_finish_photo`` closes the tail of
    this window; this closes the head of it.
    """
    try:
        from backend.app.models.print_queue import PrintQueueItem

        async with async_session() as db:
            result = await db.execute(
                select(PrintQueueItem.id)
                .where(
                    PrintQueueItem.printer_id == printer_id,
                    PrintQueueItem.status.in_(("pending", "printing")),
                )
                .limit(1)
            )
            return result.scalar_one_or_none() is not None
    except Exception as e:
        # Fail closed: if we can't tell, don't move the plate.
        logging.getLogger(__name__).debug(
            "[PLATE-RESTORE] queue check failed for printer %s: %s — skipping restore", printer_id, e
        )
        return True


async def on_finish_photo_moment(printer_id: int, data: dict):
    """Pre-capture a finish photo when the printer enters stage 22 / FINISH (#1721).

    Fires either at the stage-22 ("Filament unloading") edge — toolhead
    parked, bed not yet dropped, optimal framing — or as a FINISH-state
    fallback for prints that skip stage 22 (cancel, external-spool-only,
    HMS halt, firmware variants). Grabs one frame via the same
    external-camera / RTSP path the post-completion fallback uses, stores
    the JPEG bytes in ``_stage22_finish_frames[printer_id]``, and lets
    ``_background_finish_photo`` consume the cached bytes when it runs.

    Replaces the #1397 "force timelapse on at dispatch" mechanism, which
    caused per-layer nozzle parking on slicer profiles with Timelapse Type
    set to Smooth (#1721). No force-on now means the user's explicit
    timelapse=off in the slicer send dialog is respected.
    """
    logger = logging.getLogger(__name__)
    trigger = data.get("trigger", "unknown")
    timelapse_was_active = bool(data.get("timelapse_was_active"))
    logger.info(
        "[FINISH-PHOTO-MOMENT] printer=%s trigger=%s timelapse_active=%s",
        printer_id,
        trigger,
        timelapse_was_active,
    )

    # If a timelapse is actively recording, skip the pre-capture — the
    # post-completion path will extract the last frame from the recorded
    # video, which still provides the best framing (toolhead parked,
    # before bed drop) without the per-layer parking side effects.
    if timelapse_was_active:
        logger.info(
            "[FINISH-PHOTO-MOMENT] timelapse active for printer %s — skipping pre-capture (last-frame extraction will run post-completion)",
            printer_id,
        )
        return

    # #1790: register the producer-done event BEFORE the first await so the
    # consumer in `_background_finish_photo` — which is dispatched back-to-back
    # with us on the FINISH-state fallback path — sees it as soon as it polls.
    # The `finally` below guarantees `set()` runs on every exit, including
    # early returns and exceptions, so the consumer's bounded wait can't hang.
    producer_done = asyncio.Event()
    _stage22_finish_in_flight[printer_id] = producer_done

    # #2547: set once the plate has actually been raised, and read by the
    # `finally` below. Declared out here so a failure anywhere after the move —
    # a camera timeout, a DB error — still lowers the plate again.
    restore_max_z: float | None = None

    try:
        async with async_session() as db:
            from backend.app.api.routes.settings import get_setting
            from backend.app.models.printer import Printer

            capture_setting = await get_setting(db, "capture_finish_photo")
            if capture_setting is not None and capture_setting.lower() != "true":
                logger.info("[FINISH-PHOTO-MOMENT] capture_finish_photo disabled — skipping pre-capture")
                return

            restore_setting = await get_setting(db, "finish_photo_restore_plate")
            restore_plate_enabled = restore_setting is None or restore_setting.lower() == "true"

            result = await db.execute(select(Printer).where(Printer.id == printer_id))
            printer = result.scalar_one_or_none()
            if printer is None:
                logger.warning(
                    "[FINISH-PHOTO-MOMENT] printer %s not found in DB",
                    printer_id,
                )
                return

        frame_bytes: bytes | None = None
        # #2708: the banked frame arrives already rotated — it comes from
        # `_capture_snapshot_for_notification`, which rotates before returning.
        # Every other source below is a raw grab. Tracking which lets us store
        # exactly one rotation in `_stage22_finish_frames` either way.
        frame_already_rotated = False

        # On the FINISH-state path the End G-code has already run, and two very
        # different situations arrive here needing opposite answers.
        #
        # #1867: if PrintLab injected End G-code into this print, a SwapMod
        # snippet may have ejected the plate — the scene in front of the camera
        # is no longer the finished print, and no amount of moving the plate
        # brings it back. Use the banked in-print frame instead.
        #
        # #2547: otherwise the print is still sitting there, just ~100 mm lower
        # than the camera frames well, and the toolhead is parked out of the
        # way. That is the *best* moment available on firmware that never emits
        # stage 22 (H2C, A1 Mini) — so capture live, after putting the plate
        # back. Preferring the bank here unconditionally, as this code used to,
        # is what shipped a mid-print photo with the toolhead over the part.
        if trigger == "finish_state" and print_dispatch_context.end_gcode_injected(printer_id):
            banked = _inprint_frame_bank.get(printer_id)
            if banked:
                frame_bytes = banked
                frame_already_rotated = True
                logger.info(
                    "[FINISH-PHOTO-MOMENT] End G-code was injected — using banked in-print "
                    "frame (%d bytes) instead of a post-swap live grab",
                    len(banked),
                )
            else:
                logger.warning(
                    "[FINISH-PHOTO-MOMENT] End G-code was injected for printer %s but the "
                    "in-print bank is empty — falling back to a live grab, which may show a "
                    "swapped or empty plate",
                    printer_id,
                )

        # `restore_max_z` is set only once the plate is actually up, because the
        # `finally` reads it to decide whether it owes a move back down.
        #
        # Never on a print whose End G-code PrintLab injected, even when the bank
        # came up empty above: that machine may have just ejected its plate, and
        # driving Z into whatever a swap mechanism is doing is not a risk worth
        # taking for a photo of a bed we already know may be bare.
        if (
            frame_bytes is None
            and trigger == "finish_state"
            and restore_plate_enabled
            and not print_dispatch_context.end_gcode_injected(printer_id)
        ):
            wants_restore = await _max_z_for_current_print(printer_id, data, logger)
            if wants_restore is None:
                logger.info(
                    "[PLATE-RESTORE] printer %s: print height unknown — capturing without restore",
                    printer_id,
                )
            elif await _plate_restore_is_blocked_by_queue(printer_id):
                logger.info(
                    "[PLATE-RESTORE] printer %s has queued work — skipping plate restore",
                    printer_id,
                )
            elif await _restore_plate_for_finish_photo(printer_id, wants_restore, logger):
                restore_max_z = wants_restore

        if frame_bytes is None and printer.external_camera_enabled and printer.external_camera_url:
            from backend.app.api.routes.camera import live_frame_for_capture
            from backend.app.services.external_camera import capture_frame

            # #2707: this used to collide with the live view and fail, which is
            # how finish-photo notifications went out with no image attached.
            # Leaving frame_bytes None keeps the rest of the fallback chain.
            defer, buffered = live_frame_for_capture(printer_id)
            if defer:
                frame_bytes = buffered
            else:
                frame_bytes = await capture_frame(
                    printer.external_camera_url,
                    printer.external_camera_type or "mjpeg",
                    snapshot_url=printer.external_camera_snapshot_url,
                )
            if frame_bytes:
                logger.info(
                    "[FINISH-PHOTO-MOMENT] captured external-camera frame (%d bytes)",
                    len(frame_bytes),
                )
        elif frame_bytes is None:
            from backend.app.api.routes.camera import get_buffered_frame

            buffered = get_buffered_frame(printer_id)
            if buffered:
                frame_bytes = buffered
                logger.info(
                    "[FINISH-PHOTO-MOMENT] used buffered RTSP frame (%d bytes)",
                    len(frame_bytes),
                )
            else:
                from backend.app.services.camera import capture_camera_frame_bytes

                frame_bytes = await capture_camera_frame_bytes(
                    ip_address=printer.ip_address,
                    access_code=printer.access_code,
                    model=printer.model,
                    timeout=15,
                )
                if frame_bytes:
                    logger.info(
                        "[FINISH-PHOTO-MOMENT] captured RTSP frame (%d bytes)",
                        len(frame_bytes),
                    )

        if frame_bytes:
            if not frame_already_rotated:
                frame_bytes = _apply_camera_rotation(frame_bytes, printer, logger)
            _stage22_finish_frames[printer_id] = frame_bytes
        else:
            logger.warning(
                "[FINISH-PHOTO-MOMENT] no frame captured for printer %s — post-completion fallback will retry",
                printer_id,
            )

    except Exception as e:
        logger.warning(
            "[FINISH-PHOTO-MOMENT] pre-capture failed for printer %s: %s",
            printer_id,
            e,
        )
    finally:
        # #2547: we raised the plate, so we own lowering it — including when the
        # capture above failed or threw partway through.
        if restore_max_z is not None:
            try:
                _park_plate_after_finish_photo(printer_id, restore_max_z, logger)
            except Exception as e:
                logger.warning("[PLATE-RESTORE] printer %s: could not lower plate: %s", printer_id, e)
        # #1790: always unblock the consumer's bounded wait — whether we stored
        # a frame, gave up, or hit an exception. Local ref means cleanup of the
        # dict entry by the consumer doesn't affect signalling.
        producer_done.set()


def _subtask_name_from_filename(filename: str) -> str:
    """Recover the subtask name a print command would have carried for *filename*.

    The dispatcher derives the printer-facing subtask name from the archive's
    file name, so stripping the extensions back off gives the value MQTT echoes
    on completion. Only the two extensions PrintLab actually stores are removed,
    and in the order they nest (``.gcode.3mf``), so a model whose own name
    contains a dot -- ``My.Model.3mf`` -- keeps it.
    """
    name = PurePosixPath(filename).name
    for suffix in (".3mf", ".gcode"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    return name


# How the printer marks a subtask name it had to cut short. Observed on real
# hardware at ~100 characters, but the cut-off is not a fixed character count
# (a name with multibyte characters came back at 98), so match the marker
# rather than a length.
_SUBTASK_TRUNCATION_MARKER = "..."


def _normalise_subtask_name(name: str) -> str:
    """Canonical form for comparing a dispatched name against MQTT's echo.

    The printer does not echo the name back verbatim: it substitutes
    underscores for spaces. ``H2D_Carbon_Filter_(V2)_Body & Solid Lid`` is
    dispatched and ``H2D_Carbon_Filter_(V2)_Body_&_Solid_Lid`` comes back.

    The 3MF lookup in this module has always known that -- it builds
    space-to-underscore variants of every candidate filename, and its
    directory search normalises both sides before comparing. This exists so
    the completion check reads the same rule from the same place instead of
    growing its own, which is exactly how it came to disagree (#2829).
    """
    return name.strip().replace(" ", "_").casefold()


def _subtask_names_match(expected: str, observed: str) -> bool:
    """Whether two subtask names describe the same print.

    Beyond the space/underscore substitution, the printer truncates long names
    and marks the cut with ``...``. A truncated echo has to count as a match or
    every print with a long name strands its queue item the same way.
    """
    expected_n = _normalise_subtask_name(expected)
    observed_n = _normalise_subtask_name(observed)
    if expected_n == observed_n:
        return True

    # Either side can be the truncated one: the printer truncates what it
    # echoes, and an archive whose own filename was recorded from a previous
    # truncated echo carries the marker too.
    for full, cut in ((expected_n, observed_n), (observed_n, expected_n)):
        if cut.endswith(_SUBTASK_TRUNCATION_MARKER) and full.startswith(cut[: -len(_SUBTASK_TRUNCATION_MARKER)]):
            return True
    return False


async def _completion_belongs_to_queue_item(db, item, data: dict) -> bool:
    """Whether this completion event is plausibly about *item*'s print.

    The caller finds its queue row by printer and ``status='printing'`` alone,
    which is all a completion event gives it -- there is no run identifier in
    the MQTT payload to match on. That makes the lookup indiscriminate: any
    completion delivered for this printer closes whichever row happens to be
    printing, however unrelated. Comparing the subtask name against the archive
    the row was dispatched with costs one primary-key load and rules that out.

    Deliberately permissive: it answers False only on a positive disagreement
    between two names we actually have. A row with no archive, an archive with
    no file name, or an event with no subtask name is unverifiable rather than
    wrong, and refusing those would strand the item in ``printing`` and wedge
    the printer's queue -- a worse failure than the one being prevented.
    """
    observed = (data.get("subtask_name") or "").strip()
    if not observed or item.archive_id is None:
        return True

    from backend.app.models.archive import PrintArchive

    archive = await db.get(PrintArchive, item.archive_id)
    if archive is None or not archive.filename:
        return True

    expected = _subtask_name_from_filename(archive.filename)
    if not expected or _subtask_names_match(expected, observed):
        return True

    logging.getLogger(__name__).warning(
        "Ignoring print completion for queue item %s: it was dispatched as %r "
        "(archive %s, %s) but the completion reports subtask %r. Leaving the item "
        "printing rather than closing a run this event is not about.",
        item.id,
        expected,
        archive.id,
        archive.filename,
        observed,
    )
    return False


async def _recover_fallback_from_cache_before_eviction(printer_id: int, data: dict) -> None:
    """Spend the 3MF download cache on a still-empty fallback archive.

    ``on_print_complete`` drops the cache as its first act, which deletes the
    file. If the cover endpoint (or anything else) pulled the 3MF while the
    print ran and the archive never got one, this is the last moment those bytes
    exist (#2957).
    """
    logger = logging.getLogger(__name__)
    names = [
        n
        for n in (data.get("filename"), data.get("subtask_name"), (data.get("raw_data") or {}).get("subtask_name"))
        if n
    ]
    for name in names:
        try:
            cached = get_cached_3mf(printer_id, name)
            if cached and await try_recover_fallback_archive(printer_id, name, cached):
                return
        except Exception as e:
            logger.debug("[RECOVER] Pre-eviction recovery for %s failed: %s", name, e)


async def on_print_complete(printer_id: int, data: dict):
    """Handle print completion - update the archive status."""
    import time

    logger = logging.getLogger(__name__)
    start_time = time.time()

    def log_timing(section: str):
        elapsed = time.time() - start_time
        logger.info("[TIMING] %s: %.3fs elapsed", section, elapsed)

    logger.info("[CALLBACK] on_print_complete started for printer %s", printer_id)

    # A kill-switch stop sends its provider notification immediately. Keep the
    # task so the later notification path can await it and avoid a duplicate;
    # if that immediate attempt failed, the regular completion path retries.
    kill_switch_notification_task = _kill_switch_notification_tasks.pop(printer_id, None)

    # Last chance before the bytes go: if this print's archive is still an empty
    # fallback and something downloaded the 3MF while it ran, fill the archive in
    # now. The cover endpoint's copy lives in exactly this cache, and clearing it
    # below deletes the file (#2957).
    await _recover_fallback_from_cache_before_eviction(printer_id, data)

    # A pending cool-off retry has nothing left to recover for — the cache is
    # about to be dropped and the print is over.
    retry_task = _fallback_3mf_retry_tasks.pop(printer_id, None)
    if retry_task and not retry_task.done():
        retry_task.cancel()

    # Drop the 3MF download cache for this printer (#972). The print is over,
    # nothing else legitimately needs the bytes; keeping them would only risk
    # handing a stale file to the next print if it reuses the same name.
    clear_3mf_cache(printer_id)

    try:
        ws_data = {
            "status": data.get("status"),
            "filename": data.get("filename"),
            "subtask_name": data.get("subtask_name"),
            "timelapse_was_active": data.get("timelapse_was_active"),
        }
        await ws_manager.send_print_complete(printer_id, ws_data)
        log_timing("WebSocket send_print_complete")
    except Exception as e:
        logger.warning("[CALLBACK] WebSocket send_print_complete failed: %s", e)

    # Capture user info before clearing (needed for print log entry)
    _print_user_info = printer_manager.get_current_print_user(printer_id)

    # Clear current print user tracking (Issue #206)
    printer_manager.clear_current_print_user(printer_id)

    # If the user explicitly stopped this print from the queue UI the printer will
    # report "failed" or "aborted" via MQTT.  Override that to "cancelled" so the
    # correct "print stopped" notification/email is sent instead of a failure alert.
    _raw_status = data.get("status", "completed")
    if printer_id in _user_stopped_printers and _raw_status in ("failed", "aborted"):
        logger.info(
            "[CALLBACK] Overriding status '%s' -> 'cancelled' for printer %s (print was stopped from queue by user)",
            _raw_status,
            printer_id,
        )
        data = {**data, "status": "cancelled"}
    _user_stopped_printers.discard(printer_id)

    # Raise the plate-clear gate for queued dispatch (#961). Any terminal status
    # may have left material on the bed: a user can cancel ten hours into a
    # twelve-hour print, a printer can self-abort mid-job after a clog, and a
    # touchscreen-stop reports `aborted` rather than `cancelled` because
    # `_user_stopped_printers` is only populated when the user stops via the
    # PrintLab queue UI. Earlier code raised the flag only for completed/failed,
    # which auto-dispatched the next queued print onto a fouled bed two seconds
    # after a touchscreen-abort (#1171). Persisted to DB so the gate survives
    # Auto Off power cycles and PrintLab restarts.
    _final_status = data.get("status", "completed")
    if _final_status in ("completed", "failed", "aborted", "cancelled"):
        printer_manager.set_awaiting_plate_clear(printer_id, True)

    # Automatischer Plattenwechsel (Monitor-Port P2): nur nach "completed" und
    # nur wenn die Automatik in data/hardware.json eingeschaltet ist. Läuft als
    # eigener Task; ein Fehler meldet sich nur, blockiert aber nie die
    # Aufräum-Schritte weiter unten.
    if _final_status == "completed":
        try:
            from backend.app.services import auto_plate_change

            auto_plate_change.schedule(printer_id, data.get("subtask_name", ""))
        except Exception as e:
            logger.warning("[CALLBACK] auto plate change schedule failed for printer %s: %s", printer_id, e)

    # MQTT relay - publish print complete
    try:
        printer_info = printer_manager.get_printer(printer_id)
        if printer_info:
            await mqtt_relay.on_print_complete(
                printer_id,
                printer_info.name,
                printer_info.serial_number,
                data.get("filename", ""),
                data.get("subtask_name", ""),
                data.get("status", "completed"),
            )
    except Exception:
        pass  # Don't fail print complete callback if MQTT fails

    filename = data.get("filename", "")
    subtask_name = data.get("subtask_name", "")

    if not filename and not subtask_name:
        logger.warning("Print complete without filename or subtask_name")
        return

    logger.info("Print complete - filename: %s, subtask: %s, status: %s", filename, subtask_name, data.get("status"))

    # Build list of possible keys to try (matching how they were registered in on_print_start)
    possible_keys = []

    # Try subtask_name variations first (most reliable for matching)
    if subtask_name:
        possible_keys.append((printer_id, f"{subtask_name}.3mf"))
        possible_keys.append((printer_id, f"{subtask_name}.gcode.3mf"))
        possible_keys.append((printer_id, subtask_name))

    # Try filename variations
    if filename:
        # Extract just the filename if it's a path
        fname = filename.split("/")[-1] if "/" in filename else filename

        if fname.endswith(".3mf"):
            possible_keys.append((printer_id, fname))
        elif fname.endswith(".gcode"):
            base_name = fname.rsplit(".", 1)[0]
            possible_keys.append((printer_id, f"{base_name}.gcode.3mf"))
            possible_keys.append((printer_id, f"{base_name}.3mf"))
            possible_keys.append((printer_id, fname))
        else:
            possible_keys.append((printer_id, f"{fname}.gcode.3mf"))
            possible_keys.append((printer_id, f"{fname}.3mf"))
            possible_keys.append((printer_id, fname))

        # Also try full path versions
        if filename.endswith(".3mf"):
            possible_keys.append((printer_id, filename))
        elif filename.endswith(".gcode"):
            base_name = filename.rsplit(".", 1)[0]
            possible_keys.append((printer_id, f"{base_name}.3mf"))
            possible_keys.append((printer_id, filename))
        else:
            possible_keys.append((printer_id, f"{filename}.3mf"))
            possible_keys.append((printer_id, filename))

    # Find the archive for this print
    logger.info("Looking for archive in _active_prints, keys to try: %s...", possible_keys[:5])
    logger.info("Current _active_prints: %s", list(_active_prints.keys()))
    archive_id = None
    for key in possible_keys:
        archive_id = _active_prints.pop(key, None)
        if archive_id:
            logger.info("Found archive %s with key %s", archive_id, key)
            # Also clean up any other keys pointing to this archive
            keys_to_remove = [k for k, v in _active_prints.items() if v == archive_id]
            for k in keys_to_remove:
                _active_prints.pop(k, None)
            break

    if not archive_id:
        # Try to find by filename or subtask_name if not tracked (for prints started before app)
        async with async_session() as db:
            from backend.app.models.archive import PrintArchive

            # Try matching by subtask_name (stored as print_name) first
            if subtask_name:
                result = await db.execute(
                    select(PrintArchive)
                    .where(PrintArchive.printer_id == printer_id)
                    .where(PrintArchive.status == "printing")
                    .where(
                        or_(
                            PrintArchive.print_name.ilike(f"%{subtask_name}%"),
                            PrintArchive.filename.ilike(f"%{subtask_name}%"),
                        )
                    )
                    .order_by(PrintArchive.created_at.desc())
                    .limit(1)
                )
                archive = result.scalar_one_or_none()
                if archive:
                    archive_id = archive.id
                    logger.info("Found archive %s by subtask_name match: %s", archive_id, subtask_name)

            # Also try by filename
            if not archive_id and filename:
                result = await db.execute(
                    select(PrintArchive)
                    .where(PrintArchive.printer_id == printer_id)
                    .where(PrintArchive.filename == filename)
                    .where(PrintArchive.status == "printing")
                    .order_by(PrintArchive.created_at.desc())
                    .limit(1)
                )
                archive = result.scalar_one_or_none()
                if archive:
                    archive_id = archive.id

    # Cleanup: delete uploaded file from printer SD card to prevent phantom prints (Issue #374, #1542)
    # The print scheduler uploads files to the SD card root (/). Some printers (e.g. P1S, A1)
    # auto-start files found in root on power cycle, causing ghost prints.
    # Must run before the archive_id early-return so it executes even when archiving is disabled.
    try:
        if subtask_name:
            archive_filename: str | None = None
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive
                from backend.app.models.printer import Printer

                result = await db.execute(select(Printer).where(Printer.id == printer_id))
                printer = result.scalar_one_or_none()
                if archive_id:
                    archive_row = await db.execute(select(PrintArchive.filename).where(PrintArchive.id == archive_id))
                    archive_filename = archive_row.scalar_one_or_none()

            if printer:
                from backend.app.services.bambu_ftp import DeleteResult, delete_file_async
                from backend.app.utils.filename import derive_remote_filename

                # Primary candidate: the exact path the dispatcher uploaded to
                # (derived from archive.filename via the same rule as upload).
                # Without it, a library row that ended up with a doubled
                # .gcode.3mf (#1542) leaves the real file behind because the
                # subtask_name + ext fallbacks below don't match what's on the
                # SD card. Fallbacks remain for archive-less prints (subtask
                # never resolved to an archive) and for older naming variants.
                candidate_paths: list[str] = []
                if archive_filename:
                    candidate_paths.append(f"/{derive_remote_filename(archive_filename)}")
                for ext in (".3mf", ".gcode"):
                    fallback = f"/{subtask_name}{ext}"
                    if fallback not in candidate_paths:
                        candidate_paths.append(fallback)

                # Three outcomes track across all candidates so the final log
                # line reflects what actually happened. The A1 in #1721 always
                # ends here with ``any_not_found=True`` and the others False
                # — its firmware auto-cleans the SD card before our cleanup
                # runs, every candidate FTP-DELE returns 550, and the old
                # code burned 3 retries × 2 s × 3 candidates per print
                # logging a misleading "may linger" WARNING on a successful
                # print.
                any_deleted = False
                any_real_failure = False
                any_not_found = False

                for remote_path in candidate_paths:
                    # Retry only the FAILED case — 550 NOT_FOUND will never
                    # recover by waiting, so a "file isn't here" answer
                    # advances immediately to the next candidate without
                    # consuming the retry budget.
                    for attempt in range(1, 4):
                        try:
                            delete_result = await delete_file_async(
                                printer.ip_address,
                                printer.access_code,
                                remote_path,
                                printer_model=printer.model,
                            )
                        except Exception as e:
                            delete_result = DeleteResult.FAILED
                            logger.warning(
                                "SD card cleanup attempt %d/3 raised for %s: %s",
                                attempt,
                                remote_path,
                                e,
                            )

                        if delete_result == DeleteResult.DELETED:
                            any_deleted = True
                            logger.info("Deleted %s from printer %s SD card", remote_path, printer.name)
                            break
                        if delete_result == DeleteResult.NOT_FOUND:
                            any_not_found = True
                            break  # 550 will not recover; try next candidate
                        # FAILED: real error — retry with backoff, then give up
                        if attempt < 3:
                            await asyncio.sleep(2)
                        else:
                            any_real_failure = True
                            logger.warning(
                                "SD card cleanup failed after 3 attempts for %s "
                                "(network/auth/transient error — file may linger on SD card)",
                                remote_path,
                            )

                if not any_deleted and not any_real_failure and any_not_found:
                    # Every candidate said "not here." Either the printer
                    # firmware swept the SD card itself (common on A1) or the
                    # dispatcher's upload path doesn't match our candidate
                    # rule. Either way: nothing to clean up, no warning.
                    logger.debug(
                        "SD card cleanup: nothing to delete on %s — every candidate returned 550 "
                        "(printer likely self-cleaned)",
                        printer.name,
                    )
    except Exception as e:
        logger.warning("SD card file cleanup failed for printer %s: %s", printer_id, e)

    log_timing("SD card cleanup")

    # Update queue item status early — must run before the archive_id early-return
    # so queue items don't get stuck in "printing" when archive lookup fails.
    # Uses run_with_retry to handle SQLite "database is locked" errors (#897).
    queue_item_id = None
    billing_run_id: str | None = None
    billing_user_id: int | None = None
    billing_cost_center_id: int | None = None
    billing_plate_id: int | None = None
    queue_status = None
    queue_auto_off = False
    try:
        from backend.app.core.database import run_with_retry
        from backend.app.models.print_queue import PrintQueueItem

        async def _update_queue_status(db):
            nonlocal billing_run_id, billing_user_id, billing_cost_center_id, billing_plate_id
            nonlocal queue_item_id, queue_status, queue_auto_off
            result = await db.execute(
                select(PrintQueueItem)
                .where(PrintQueueItem.printer_id == printer_id)
                .where(PrintQueueItem.status == "printing")
            )
            printing_items = list(result.scalars().all())
            if len(printing_items) > 1:
                logger.warning(
                    "BUG: Multiple queue items in 'printing' status for printer %s: %s",
                    printer_id,
                    [(i.id, i.archive_id, i.library_file_id) for i in printing_items],
                )
            item = printing_items[0] if printing_items else None
            if item is not None and not await _completion_belongs_to_queue_item(db, item, data):
                return
            if item:
                queue_status = data.get("status", "completed")
                # MQTT sends "aborted" for cancelled prints; normalise to
                # "cancelled" so it matches the queue schema Literal.
                if queue_status == "aborted":
                    queue_status = "cancelled"
                item.status = queue_status
                item.completed_at = datetime.now(timezone.utc)
                if queue_status == "failed" and not item.error_message:
                    item.error_message = _format_hms_error_summary(data.get("hms_errors") or [])

                # Bump usage counters on the source library file so admins can
                # sort by "last printed" and (eventually) auto-purge stale
                # files — #1008.
                await _bump_library_file_usage_if_completed(db, item, queue_status)

                await db.commit()
                queue_item_id = item.id
                billing_run_id = item.billing_run_id
                billing_user_id = item.created_by_id
                billing_cost_center_id = item.cost_center_id
                billing_plate_id = item.plate_id
                queue_auto_off = item.auto_off_after
                logger.info("Updated queue item %s status to %s", item.id, queue_status)

        await run_with_retry(_update_queue_status, label="queue status update")

        # Automatische Umverteilung nach einem echten Fehlschlag (abschaltbar,
        # höchstens einmal je Auftragskette, Ziel: anderes Gerät desselben Modells).
        if queue_item_id is not None and queue_status == "failed":
            try:
                from backend.app.services import auto_requeue

                async with async_session() as requeue_db:
                    await auto_requeue.maybe_requeue(requeue_db, queue_item_id, queue_status)
            except Exception as e:
                logger.warning("Auto-requeue failed for queue item %s: %s", queue_item_id, e)

        # Post-commit side effects (notifications, MQTT relay, auto-off) use
        # their own sessions and have their own error handling — no retry needed.
        if queue_item_id is not None:
            # Batch orders (#342): this run may have been the last one an order
            # owed. Re-evaluate here rather than lazily on read, so a finished
            # order reports itself complete without someone opening the page.
            try:
                from backend.app.services.print_batch import refresh_batch_status_for_item

                async with async_session() as db:
                    await refresh_batch_status_for_item(db, queue_item_id)
                    await db.commit()
            except Exception as e:
                logger.warning("[BATCH] Failed to refresh batch status for queue item %s: %s", queue_item_id, e)

            # MQTT relay - publish queue job completed
            try:
                printer_info = printer_manager.get_printer(printer_id)
                await mqtt_relay.on_queue_job_completed(
                    job_id=queue_item_id,
                    filename=filename or subtask_name,
                    printer_id=printer_id,
                    printer_name=printer_info.name if printer_info else "Unknown",
                    status=queue_status,
                )
            except Exception:
                pass  # Don't fail if MQTT fails

            # Check if queue is now empty and send notification
            try:
                from sqlalchemy import func as sa_func

                async with async_session() as db:
                    count_result = await db.execute(
                        select(sa_func.count(PrintQueueItem.id)).where(PrintQueueItem.status == "pending")
                    )
                    pending_count = count_result.scalar() or 0

                    if pending_count == 0:
                        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                        completed_result = await db.execute(
                            select(sa_func.count(PrintQueueItem.id)).where(
                                PrintQueueItem.status.in_(["completed", "failed", "skipped"]),
                                PrintQueueItem.completed_at >= today_start,
                            )
                        )
                        completed_count = completed_result.scalar() or 1

                        await notification_service.on_queue_completed(
                            completed_count=completed_count,
                            db=db,
                        )
            except Exception:
                pass  # Don't fail if notification fails

            # Handle auto_off_after - power off printer if the queue item opted
            # in. Delegates to the smart-plug manager so the off honours each
            # plug's configured strategy (time delay or temperature threshold),
            # is cancelled if the printer starts printing again, and never cuts
            # power on a loaded print (#1890). Previously an inline block here
            # hardcoded a 50°C / 600s cooldown wait and powered off on the
            # timeout regardless of print state — cutting a touchscreen reprint.
            if queue_auto_off:
                try:
                    async with async_session() as db:
                        await smart_plug_manager.schedule_off_after_queue_job(printer_id, db)
                except Exception as e:
                    logger.warning("Failed to schedule queue auto-off for printer %s: %s", printer_id, e)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Queue item update failed: {e}")

    log_timing("Queue item update")

    # Register bed cooldown waiter (event-driven via on_bed_temp_update callback).
    # Must run before archive_id early-return so it fires for all prints (including
    # prints started from BambuStudio/touchscreen that have no archive).
    if data.get("status") == "completed":
        try:
            from backend.app.api.routes.settings import get_setting

            async with async_session() as db:
                threshold_str = await get_setting(db, "bed_cooled_threshold")
            threshold = float(threshold_str) if threshold_str else 35.0

            # Check if any provider has on_bed_cooled enabled (skip registration if none)
            async with async_session() as db:
                providers = await notification_service._get_providers_for_event(db, "on_bed_cooled", printer_id)
            if providers:
                _bed_cool_waiters[printer_id] = {
                    "threshold": threshold,
                    "filename": filename or subtask_name or "",
                    "registered_at": time.time(),
                }
                logger.info(
                    "[BED-COOL] Registered waiter for printer %s (threshold: %.0f°C)",
                    printer_id,
                    threshold,
                )
            else:
                logger.debug("[BED-COOL] No providers enabled for bed_cooled on printer %s", printer_id)
        except Exception as e:
            logger.warning("[BED-COOL] Failed to register waiter: %s", e)

    # Capture the slicer estimate before usage tracking runs. The tracker may
    # update archive.cost with this run's measured cost; billing partial runs
    # against that already-partial value would discount the charge twice.
    billing_planned_grams: float | None = None
    billing_base_cost: float | None = None
    if archive_id:
        try:
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive

                billing_archive = await db.get(PrintArchive, archive_id)
                if billing_archive:
                    billing_path = (
                        app_settings.base_dir / billing_archive.file_path if billing_archive.file_path else None
                    )  # SEC-PATH-OK: archive.file_path is DB-stored, internally generated
                    billing_planned_grams, billing_base_cost = _plate_scoped_run_estimate(
                        billing_archive,
                        billing_path,
                        billing_plate_id if billing_plate_id is not None else _get_start_plate_id(archive_id),
                    )
        except Exception as e:
            logger.warning("[FINANCE] Failed to capture planned usage for archive %s: %s", archive_id, e)

    # --- Track filament consumption (must run before archive_id early-return so usage
    # is recorded even when auto-archive is disabled) ---
    usage_results: list[dict] = []
    # Prefer ams_mapping captured from MQTT request topic (works for all print sources)
    stored_ams_mapping = data.get("ams_mapping")
    # Fallback to _print_ams_mappings for queue/reprint (set before print starts)
    if not stored_ams_mapping and archive_id:
        stored_ams_mapping = _print_ams_mappings.pop(archive_id, None)

    # Always drain the plate_id register on completion — the session already
    # consumed it at print-start injection; leaving it would leak into the next
    # print on the same archive_id (rare but possible with reprints) (#1697).
    # Capture the popped value so the completion notification can scope the
    # archive-level (summed-across-plates per #1593) filament + time totals
    # down to the single plate that was actually printed (#1785).
    notify_plate_id: int | None = None
    if archive_id:
        notify_plate_id = _print_plate_ids.pop(archive_id, None)

    # Internal inventory: track AMS remain% deltas (skip if Spoolman handles usage)
    try:
        async with async_session() as db:
            from backend.app.api.routes.settings import get_setting

            _spoolman_on = await get_setting(db, "spoolman_enabled")
        if not _spoolman_on or _spoolman_on.lower() != "true":
            from backend.app.services.usage_tracker import on_print_complete as usage_on_print_complete

            async with async_session() as db:
                usage_results = await usage_on_print_complete(
                    printer_id,
                    data,
                    printer_manager,
                    db,
                    archive_id=archive_id,
                    ams_mapping=stored_ams_mapping,
                )
                if usage_results:
                    await ws_manager.broadcast(
                        {
                            "type": "spool_usage_logged",
                            "printer_id": printer_id,
                            "usage": usage_results,
                        }
                    )
                    log_timing("Usage tracker")

    except Exception as e:
        logger.warning("Usage tracker on_print_complete failed: %s", e)

    # Drop the print-start context unconditionally — the Spoolman branch above
    # skips the internal tracker entirely, so nothing else would clear what
    # print start captured, and a row surviving its print would be restored
    # onto the next one after a restart.
    try:
        from backend.app.services.usage_tracker import discard_session

        async with async_session() as db:
            await discard_session(db, printer_id)
    except Exception as e:
        logger.warning("Failed to clear persisted print session for printer %s: %s", printer_id, e)

    # Spoolman: report filament usage (requires archive_id for tracking data lookup)
    if archive_id:
        if data.get("status") == "completed":
            try:
                await _report_spoolman_usage(printer_id, archive_id)
                log_timing("Spoolman usage report")
            except Exception as e:
                logger.warning("Spoolman usage reporting failed: %s", e)
        else:
            # Report partial usage if tracking data exists (only stored when weight sync is disabled)
            try:
                async with async_session() as db:
                    await _cleanup_spoolman_tracking(
                        printer_id,
                        archive_id,
                        db,
                        last_layer_num=data.get("last_layer_num"),
                        last_progress=data.get("last_progress"),
                    )
            except Exception as e:
                logger.debug("[SPOOLMAN] Cleanup failed: %s", e)

    log_timing("Filament usage tracking")

    if not archive_id:
        # The printer's own calibration run has no archive by design, so this
        # arrives here every time one finishes. Returning before the no-archive
        # notification is not just noise control: that path attributes an
        # unmatched completion to any queue item this printer finished in the
        # last five minutes, which for a calibration that runs alongside a real
        # print means emailing its owner that their print is done, twice and
        # early. Everything above this point has already run — the plate-clear
        # gate, the queue reconciliation, the SD-card cleanup — so only the
        # notification is skipped.
        if is_internal_printer_job(filename, subtask_name):
            logger.info(
                "[CALLBACK] Internal printer job completed, no notification: filename=%s, subtask=%s",
                filename,
                subtask_name,
            )
            return

        logger.warning("Could not find archive for print complete: filename=%s, subtask=%s", filename, subtask_name)

        # Still send print-complete/failed/stopped notifications even without an archive.
        # Try to enrich with queue/library-file data so user-specific emails work too.
        async def _notify_no_archive():
            try:
                async with async_session() as db:
                    from backend.app.models.library import LibraryFile
                    from backend.app.models.print_queue import PrintQueueItem
                    from backend.app.models.printer import Printer

                    result = await db.execute(select(Printer).where(Printer.id == printer_id))
                    printer_obj = result.scalar_one_or_none()
                    p_name = printer_obj.name if printer_obj else f"Printer {printer_id}"

                    # Try to find the most-recent queue item for this printer so we can
                    # recover created_by_id and estimated print time.
                    # NOTE: By the time this task runs the queue item status has already
                    # been updated to a terminal state (completed/failed/cancelled), so
                    # we look for recently-completed items (within the last 5 minutes).
                    no_archive_data: dict | None = None
                    try:
                        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
                        q_result = await db.execute(
                            select(PrintQueueItem)
                            .where(PrintQueueItem.printer_id == printer_id)
                            .where(PrintQueueItem.status.in_(["completed", "failed", "cancelled"]))
                            .where(PrintQueueItem.completed_at >= cutoff)
                            .order_by(PrintQueueItem.completed_at.desc())
                            .limit(1)
                        )
                        queue_item = q_result.scalar_one_or_none()
                        if queue_item:
                            no_archive_data = {"created_by_id": queue_item.created_by_id}
                            # Pull estimated time from library file when available
                            if queue_item.library_file_id:
                                lib_result = await db.execute(
                                    select(LibraryFile).where(LibraryFile.id == queue_item.library_file_id)
                                )
                                lib_file = lib_result.scalar_one_or_none()
                                if lib_file and lib_file.print_time_seconds:
                                    no_archive_data["print_time_seconds"] = lib_file.print_time_seconds
                    except Exception as lookup_err:
                        logger.debug(
                            "[NOTIFY-BG] Could not look up queue item for no-archive notification: %s", lookup_err
                        )

                    # Enrich with usage tracker results (captured in enclosing scope)
                    if usage_results:
                        if no_archive_data is None:
                            no_archive_data = {}
                        total_from_usage = sum(r.get("weight_used", 0) for r in usage_results)
                        if total_from_usage > 0:
                            no_archive_data["actual_filament_grams"] = round(total_from_usage, 1)
                        no_archive_data["usage_results"] = usage_results

                    # Try MQTT remaining_time for print duration when no queue/library data
                    if no_archive_data and not no_archive_data.get("print_time_seconds"):
                        mqtt_remaining = data.get("remaining_time")
                        if mqtt_remaining and isinstance(mqtt_remaining, (int, float)) and mqtt_remaining > 0:
                            no_archive_data["print_time_seconds"] = int(mqtt_remaining)

                    ps = data.get("status", "completed")
                    logger.info(
                        "[NOTIFY-BG] Sending notification without archive: printer=%s, status=%s", printer_id, ps
                    )
                    if not await _kill_switch_notification_already_sent(kill_switch_notification_task):
                        await notification_service.on_print_complete(
                            printer_id, p_name, ps, data, db, archive_data=no_archive_data
                        )
                    else:
                        logger.info("[NOTIFY-BG] Skipped duplicate kill-switch provider notification")

                    # Send user-specific email if we have a created_by_id
                    if no_archive_data and no_archive_data.get("created_by_id"):
                        raw_filename = data.get("subtask_name") or data.get("filename", "Unknown")
                        await _dispatch_user_print_email(
                            ps,
                            no_archive_data["created_by_id"],
                            p_name,
                            raw_filename,
                            db,
                        )
                    logger.info("[NOTIFY-BG] Completed (no-archive path)")
            except Exception as e:
                logger.warning("[NOTIFY-BG] Failed to send notification without archive: %s", e, exc_info=True)

        spawn_background_task(_notify_no_archive(), name="notify-no-archive")
        return

    log_timing("Archive lookup")

    # Update archive status
    logger.info("[ARCHIVE] Updating archive %s status...", archive_id)
    try:
        async with async_session() as db:
            service = ArchiveService(db)
            status = data.get("status", "completed")

            hms_errors = data.get("hms_errors", []) if status == "failed" else None
            if hms_errors:
                logger.info("[ARCHIVE] HMS errors at failure: %s", hms_errors)
            failure_reason = derive_failure_reason(status, hms_errors)
            if data.get("_reconciled"):
                # A reconciled completion closes out a stale archive at
                # reconnect — it is not a user action, so don't mislabel it
                # "userCancelled". It shares the stale-cleanup path's key
                # (issue #2974) and records that the real end time is unknown,
                # which is also why its logged duration is 0 (#2592).
                failure_reason = "noStatusUpdate"
            if failure_reason:
                logger.info("[ARCHIVE] failure_reason=%r (status=%s)", failure_reason, status)
            elif status == "failed" and hms_errors:
                logger.info("[ARCHIVE] HMS errors present but none matched a known failure-reason short code")

            await service.update_archive_status(
                archive_id,
                status=status,
                completed_at=(
                    datetime.now(timezone.utc) if status in ("completed", "failed", "aborted", "cancelled") else None
                ),
                failure_reason=failure_reason,
            )
            logger.info(
                "[ARCHIVE] Archive %s status updated to %s, failure_reason=%s", archive_id, status, failure_reason
            )

            await ws_manager.send_archive_updated(
                {
                    "id": archive_id,
                    "status": status,
                }
            )
            logger.info("[ARCHIVE] WebSocket notification sent for archive %s", archive_id)

            # MQTT relay - publish archive updated
            try:
                await mqtt_relay.on_archive_updated(
                    archive_id=archive_id,
                    print_name=filename or subtask_name,
                    status=status,
                )
            except Exception:
                pass  # Don't fail if MQTT fails
    except Exception as e:
        logger.error("[ARCHIVE] Failed to update archive %s status: %s", archive_id, e, exc_info=True)
        # Continue with other operations even if archive update fails

    log_timing("Archive status update")

    # Apply finance wallet charge or release reservations once. For all partial
    # terminal states (failed, aborted at the printer display, or cancelled via
    # PrintLab) use this run's measured spool delta, falling back to the last
    # valid printer progress. PrintArchive.filament_used_grams is the slicer
    # estimate and therefore cannot represent an interrupted run.
    try:
        if data.get("status") in ("completed", "failed", "aborted", "cancelled"):
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive
                from backend.app.services.finance_billing import apply_print_charge_for_archive

                archive = await db.get(PrintArchive, archive_id)
                if archive and billing_run_id is None:
                    billing_run_id = getattr(archive, "billing_run_id", None)
                if archive and archive.created_by_id is None and _print_user_info:
                    archive.created_by_id = _print_user_info.get("user_id")
                    await db.flush()

                run_status = data.get("status", "completed")
                last_progress = data.get("last_progress")
                if last_progress is None:
                    last_progress = data.get("progress")
                actual_run_grams = _compute_run_filament_grams(
                    run_status,
                    billing_planned_grams,
                    last_progress,
                    usage_results,
                )
                filament_usage = (actual_run_grams, billing_planned_grams) if run_status != "completed" else None
                in_memory_cost_center_id = _print_cost_center_ids.pop(archive_id, None)
                charged = await apply_print_charge_for_archive(
                    db,
                    archive_id,
                    charged_user_id=billing_user_id,
                    cost_center_id=(
                        billing_cost_center_id if billing_cost_center_id is not None else in_memory_cost_center_id
                    ),
                    print_queue_id=queue_item_id,
                    print_run_id=billing_run_id,
                    base_cost_override=billing_base_cost,
                    filament_usage=filament_usage,
                )
                await db.commit()
                if charged:
                    logger.info("[FINANCE] Applied print charge for archive %s", archive_id)
    except Exception as e:
        logger.warning("[FINANCE] Failed to apply print charge for archive %s: %s", archive_id, e)
        printer_info = printer_manager.get_printer(printer_id)
        billing_printer_name = printer_info.name if printer_info else f"Printer {printer_id}"
        billing_filename = filename or subtask_name or "Unknown"
        billing_error = str(e)
        try:
            await ws_manager.broadcast(
                {
                    "type": "billing_charge_failed",
                    "printer_id": printer_id,
                    "printer_name": billing_printer_name,
                    "filename": billing_filename,
                    "archive_id": archive_id,
                }
            )
        except Exception as notification_error:
            logger.error(
                "[FINANCE] Failed to broadcast billing error for archive %s: %s",
                archive_id,
                notification_error,
            )

        async def _notify_billing_charge_failed() -> None:
            try:
                async with async_session() as notification_db:
                    await notification_service.on_billing_charge_failed(
                        printer_id,
                        billing_printer_name,
                        billing_filename,
                        archive_id,
                        billing_error,
                        notification_db,
                    )
            except Exception as provider_error:
                logger.error(
                    "[FINANCE] Failed to send provider billing alert for archive %s: %s",
                    archive_id,
                    provider_error,
                    exc_info=True,
                )

        spawn_background_task(
            _notify_billing_charge_failed(),
            name=f"billing-charge-failed-{archive_id}",
        )

    log_timing("Finance charge update")

    # Write independent print log entry (separate table, never touches archives)
    try:
        async with async_session() as db:
            from backend.app.models.archive import PrintArchive
            from backend.app.services.print_log import write_log_entry

            archive = await db.get(PrintArchive, archive_id)
            if archive:
                # Back-fill created_by_id on reprint (#730): reprint reuses the
                # source archive row rather than creating a new one, so an
                # archive that was auto-created from a printer-initiated
                # print (created_by_id=NULL) would otherwise stay unattributed
                # forever. When we have a print-session user AND the archive
                # has no attribution yet, credit the current user. Never
                # overwrite an existing attribution — the original uploader
                # keeps ownership.
                _print_user_id = _print_user_info.get("user_id") if _print_user_info else None
                if archive.created_by_id is None and _print_user_id is not None:
                    archive.created_by_id = _print_user_id
                p_info = printer_manager.get_printer(printer_id)
                # Per-run actuals — written to PrintLogEntry so stats reflect
                # what THIS print actually used, not the source archive's
                # first-run values (#1378). Helper handles the partial-print
                # math (failed / cancelled / stopped get scaled to progress
                # or to tracked spool deltas).
                _run_status = data.get("status", "completed")
                # #2614: scope the per-run estimate to the printed plate. For a
                # multi-plate 3MF dispatched one plate at a time, the archive's
                # filament/cost are the whole-file totals; the PrintLogEntry must
                # reflect only this plate. No effect on single-plate archives (the
                # plate estimate equals the whole-file value) or on the tracker
                # path (measured spool deltas win in _compute_run_filament_grams).
                _est_full_path = (
                    app_settings.base_dir / archive.file_path if archive.file_path else None
                )  # SEC-PATH-OK: archive.file_path is DB-stored, internally generated
                _est_grams, _est_cost = _plate_scoped_run_estimate(archive, _est_full_path)
                _run_grams = _compute_run_filament_grams(
                    _run_status,
                    _est_grams,
                    data.get("last_progress", data.get("progress")),
                    usage_results,
                )

                # Per-run cost — prefer usage_results sum. For partial prints
                # we deliberately skip the topup-to-estimate logic in
                # usage_tracker (which assumes the print completed); the raw
                # tracked-spool sum is closer to what THIS run actually cost.
                _run_cost: float | None = None
                if usage_results:
                    _run_cost = sum(r.get("cost") or 0 for r in usage_results) or None
                if _run_cost is None and _run_status == "completed":
                    _run_cost = _est_cost

                await write_log_entry(
                    db,
                    archive_id=archive.id,
                    # Captured by _update_queue_status above; None for
                    # printer-initiated prints with no queue row. Batch
                    # cost/energy roll-up joins on it (#342).
                    queue_item_id=queue_item_id,
                    status=_run_status,
                    print_name=archive.print_name,
                    printer_name=p_info.name if p_info else None,
                    printer_id=printer_id,
                    started_at=archive.started_at,
                    completed_at=archive.completed_at,
                    filament_type=archive.filament_type,
                    filament_color=archive.filament_color,
                    filament_used_grams=_run_grams,
                    cost=_run_cost,
                    failure_reason=archive.failure_reason,
                    thumbnail_path=archive.thumbnail_path,
                    created_by_id=archive.created_by_id,
                    created_by_username=_print_user_info.get("username") if _print_user_info else None,
                    # Reconciled completions have an unknown real end time —
                    # log 0 duration instead of the whole disconnect gap (#2592).
                    reconciled=bool(data.get("_reconciled")),
                )
                await db.commit()
                logger.info("[PRINT_LOG] Log entry written for archive %s", archive_id)
    except Exception as e:
        logger.warning("[PRINT_LOG] Failed to write log entry for archive %s: %s", archive_id, e)

    log_timing("Print log entry")

    # Run slow operations as background tasks to avoid blocking the event loop
    # These operations can take 5-10+ seconds and would freeze the UI if awaited

    async def _background_energy_calculation():
        """Calculate and save energy usage in background.

        Reads the starting kWh from the archive row (#941: persisted so a mid-print
        backend restart no longer loses per-print energy data).
        """
        try:
            logger.info("[ENERGY-BG] Starting energy calculation for archive %s", archive_id)
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive

                archive = await db.get(PrintArchive, archive_id)
                if archive is None:
                    logger.warning("[ENERGY-BG] Archive %s no longer exists", archive_id)
                    return
                starting_kwh = archive.energy_start_kwh
                if starting_kwh is None:
                    logger.info("[ENERGY-BG] No start kWh recorded for archive %s", archive_id)
                    return

                candidates = await energy_plug_candidates(db, printer_id)
                if not candidates:
                    logger.info("[ENERGY-BG] No smart plug for printer %s", printer_id)
                    return

                # Same ordering as the start reading, so the delta below is
                # against the counter that produced `starting_kwh` (#2859).
                selected = await select_energy_reading(candidates, _get_plug_energy, db)
                if selected is None:
                    logger.warning(
                        "[ENERGY-BG] No plug on printer %s reports a lifetime energy counter (tried: %s)",
                        printer_id,
                        ", ".join(plug.name for plug in candidates),
                    )
                    return
                plug, energy = selected
                logger.info("[ENERGY-BG] Energy response from plug '%s': %s", plug.name, energy)

                energy_used = round(energy["total"] - starting_kwh, 4)
                logger.info("[ENERGY-BG] Per-print energy: %s kWh", energy_used)
                if energy_used < 0:
                    logger.warning(
                        "[ENERGY-BG] Negative energy delta for archive %s (start=%s, end=%s) — counter reset?",
                        archive_id,
                        starting_kwh,
                        energy["total"],
                    )
                    return

                from backend.app.api.routes.settings import get_setting

                energy_cost_per_kwh = await get_setting(db, "energy_cost_per_kwh")
                cost_per_kwh = float(energy_cost_per_kwh) if energy_cost_per_kwh else 0.15
                energy_cost_value = round(energy_used * cost_per_kwh, 3)

                # First-run-only overwrite of archive.energy_kwh / energy_cost so a
                # reprint doesn't visually clobber the source archive's energy data
                # (#1378). Reprint energy lives in the matching PrintLogEntry below.
                from sqlalchemy import func

                from backend.app.models.print_log import PrintLogEntry

                existing_runs = await db.scalar(
                    select(func.count(PrintLogEntry.id)).where(PrintLogEntry.archive_id == archive_id)
                )
                if (existing_runs or 0) <= 1:
                    # 0 = legacy archive that pre-dates per-run logging; 1 = the row
                    # we just wrote for THIS print. Either way it's the first run.
                    archive.energy_kwh = energy_used
                    archive.energy_cost = energy_cost_value

                # Backfill the latest PrintLogEntry for this archive with energy
                # (write_log_entry above ran before this background task completed,
                # so energy fields are still NULL on that row).
                latest_run = await db.execute(
                    select(PrintLogEntry)
                    .where(PrintLogEntry.archive_id == archive_id)
                    .order_by(PrintLogEntry.id.desc())
                    .limit(1)
                )
                run_row = latest_run.scalar_one_or_none()
                if run_row is not None:
                    run_row.energy_kwh = energy_used
                    run_row.energy_cost = energy_cost_value

                await db.commit()
                logger.info("[ENERGY-BG] Saved: %s kWh, cost=%s", energy_used, energy_cost_value)
        except Exception as e:
            logger.warning("[ENERGY-BG] Failed: %s", e)

    async def _background_finish_photo() -> str | None:
        """Capture finish photo in background. Returns photo filename if captured."""
        # #2547: set once this function has raised the plate itself (the
        # timelapse path, where the moment producer returned without doing it).
        # Declared out here so the `finally` can lower it again no matter where
        # the capture below fails.
        plate_restored_z: float | None = None
        try:
            logger.info("[PHOTO-BG] Starting finish photo capture for archive %s", archive_id)

            from backend.app.api.routes.camera import _active_chamber_streams, _active_streams, get_buffered_frame

            # Read phase: settings + printer + archive in a short session, released
            # BEFORE the capture pipeline below. The capture (timelapse last-frame,
            # stage-22 wait, external-camera grab, or a fresh RTSP shot) can take
            # tens of seconds; holding this session across it pinned one pooled
            # connection idle-in-transaction per finishing print (issue #2572).
            async with async_session() as db:
                from backend.app.api.routes.settings import get_setting
                from backend.app.models.archive import PrintArchive
                from backend.app.models.printer import Printer

                capture_enabled = await get_setting(db, "capture_finish_photo")
                if capture_enabled is not None and capture_enabled.lower() != "true":
                    return None
                if not archive_id:
                    return None

                printer = (await db.execute(select(Printer).where(Printer.id == printer_id))).scalar_one_or_none()
                archive = (
                    await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))
                ).scalar_one_or_none()

            if not printer or not archive:
                return None

            import uuid
            from datetime import datetime

            from backend.app.utils.archive_paths import archive_dir as resolve_archive_dir

            if not archive.file_path:
                logger.warning("[PHOTO-BG] Archive %s has no file_path, using fallback dir", archive_id)
            archive_dir = resolve_archive_dir(archive)
            photo_filename = None

            # Prefer the timelapse last-frame source when a timelapse was
            # recording — it captures the moment after the toolhead parks
            # but before the bed drops, which the live-camera grab below
            # would miss (#1397). Skipped for external cameras (those have
            # their own framing and don't see a Bambu timelapse). Only
            # runs when the USER explicitly enabled timelapse for this
            # print — #1721 removed PrintLab's force-on at dispatch
            # because it caused per-layer nozzle parking on Smooth-mode
            # slicer profiles.
            prefer_timelapse_source = bool(data.get("timelapse_was_active")) and not (
                printer.external_camera_enabled and printer.external_camera_url
            )

            timelapse_still_pending = False
            if prefer_timelapse_source:
                photo_filename, timelapse_still_pending = await _capture_finish_photo_from_timelapse(
                    archive_id=archive_id,
                    archive_dir=archive_dir,
                    rotation=getattr(printer, "camera_rotation", 0),
                )

            # #1721: replacement framing path — on_finish_photo_moment
            # pre-captured a frame at the stage-22 / FINISH edge (toolhead
            # parked, bed not yet dropped) and cached the JPEG bytes in
            # _stage22_finish_frames. Consume them now so the saved photo
            # has the better framing instead of the post-bed-drop angle
            # the live-camera fallback below would give.
            if not photo_filename:
                # #1790: on the FINISH-state fallback path the producer
                # task is dispatched back-to-back with this consumer, so
                # a bare pop would race past with an empty result and
                # the RTSP fallback below would collide with the
                # producer's still-in-flight grab (single-client RTSP
                # on Bambu printers). Wait for the producer to finish
                # or give up before touching the cache.
                #
                # #2547: 20s was enough when the producer only ever grabbed a
                # frame. It now also raises the plate first, which costs the
                # settle window before the grab even starts — so the budget has
                # to cover settle + a worst-case 15s RTSP timeout, and still sit
                # under the notification's own photo wait below.
                in_flight = _stage22_finish_in_flight.pop(printer_id, None)
                if in_flight is not None:
                    try:
                        await asyncio.wait_for(in_flight.wait(), timeout=_FINISH_PHOTO_PRODUCER_WAIT_SECONDS)
                    except asyncio.TimeoutError:
                        logger.warning(
                            "[PHOTO-BG] timed out waiting for stage-22 producer for printer %s — proceeding to fallback",
                            printer_id,
                        )
                cached_frame = _stage22_finish_frames.pop(printer_id, None)
                if cached_frame:
                    # Already rotated by the producer (#2708) — rotating again
                    # here would undo the fix on the banked-frame path, whose
                    # bytes reach the cache having been rotated once already.
                    photos_dir = archive_dir / "photos"
                    photos_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    photo_filename = f"finish_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
                    photo_path = photos_dir / photo_filename
                    await asyncio.to_thread(photo_path.write_bytes, cached_frame)
                    logger.info(
                        "[PHOTO-BG] Saved stage-22 pre-captured frame: %s (%d bytes)",
                        photo_filename,
                        len(cached_frame),
                    )

            # #2547: the timelapse path reaches the live grab below whenever the
            # video hasn't landed in time — the documented usual outcome on
            # P1-series, where transfers are slowest. `on_finish_photo_moment`
            # returned early for those prints without raising the plate, so
            # without this the photo that actually ships in the notification is
            # of an already-dropped plate: exactly the framing #1145/#1397/#1565
            # asked us to fix. The archive still gets the better video frame
            # later; this is about the image the user is sent.
            #
            # Gated on `timelapse_was_active` precisely because that is the
            # condition under which the producer skipped. On every other path it
            # has already raised and lowered the plate, and repeating that here
            # would be a second pointless round trip.
            if (
                not photo_filename
                and data.get("timelapse_was_active")
                and not print_dispatch_context.end_gcode_injected(printer_id)
            ):
                try:
                    async with async_session() as db:
                        from backend.app.api.routes.settings import get_setting

                        restore_setting = await get_setting(db, "finish_photo_restore_plate")
                    if restore_setting is None or restore_setting.lower() == "true":
                        max_z = await _max_z_for_current_print(printer_id, data, logger)
                        if max_z is not None and not await _plate_restore_is_blocked_by_queue(printer_id):
                            if await _restore_plate_for_finish_photo(printer_id, max_z, logger):
                                plate_restored_z = max_z
                except Exception as e:
                    logger.warning("[PLATE-RESTORE] printer %s: restore failed: %s", printer_id, e)

            # Fallback chain: external camera → buffered live frame →
            # fresh RTSP capture. Only runs if the timelapse path above
            # didn't already produce a photo.
            if not photo_filename:
                if printer.external_camera_enabled and printer.external_camera_url:
                    logger.info("[PHOTO-BG] Using external camera")
                    from backend.app.api.routes.camera import live_frame_for_capture
                    from backend.app.services.external_camera import capture_frame

                    # #2707: the second half of the finish-photo failure — the
                    # pre-capture and this fallback both collided with the live
                    # view. None here continues down the fallback chain.
                    defer, buffered = live_frame_for_capture(printer_id)
                    if defer:
                        frame_data = buffered
                    else:
                        frame_data = await capture_frame(
                            printer.external_camera_url,
                            printer.external_camera_type or "mjpeg",
                            snapshot_url=printer.external_camera_snapshot_url,
                        )
                    if frame_data:
                        frame_data = _apply_camera_rotation(frame_data, printer, logger)
                        photos_dir = archive_dir / "photos"
                        photos_dir.mkdir(parents=True, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        photo_filename = f"finish_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
                        photo_path = photos_dir / photo_filename
                        await asyncio.to_thread(photo_path.write_bytes, frame_data)
                        logger.info("[PHOTO-BG] Saved external camera frame: %s", photo_filename)
                else:
                    # Check if camera stream is active - use buffered frame to avoid freeze
                    # Check both RTSP streams (_active_streams) and chamber image streams (_active_chamber_streams)
                    active_for_printer = [k for k in _active_streams if k.startswith(f"{printer_id}-")]
                    active_chamber_for_printer = [k for k in _active_chamber_streams if k.startswith(f"{printer_id}-")]
                    buffered_frame = get_buffered_frame(printer_id)

                    if (active_for_printer or active_chamber_for_printer) and buffered_frame:
                        # Use frame from active stream
                        logger.info("[PHOTO-BG] Using buffered frame from active stream")
                        buffered_frame = _apply_camera_rotation(buffered_frame, printer, logger)
                        photos_dir = archive_dir / "photos"
                        photos_dir.mkdir(parents=True, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        photo_filename = f"finish_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
                        photo_path = photos_dir / photo_filename
                        await asyncio.to_thread(photo_path.write_bytes, buffered_frame)
                        logger.info("[PHOTO-BG] Saved buffered frame: %s", photo_filename)
                    else:
                        # No active stream - capture new frame
                        from backend.app.services.camera import capture_finish_photo

                        photo_filename = await capture_finish_photo(
                            printer_id=printer_id,
                            ip_address=printer.ip_address,
                            access_code=printer.access_code,
                            model=printer.model,
                            archive_dir=archive_dir,
                            rotation=getattr(printer, "camera_rotation", 0),
                        )

            # Write phase: attach the photo in a fresh short-lived session.
            if photo_filename:
                async with async_session() as db:
                    from backend.app.models.archive import PrintArchive

                    arch = await db.get(PrintArchive, archive_id)
                    if arch is not None:
                        photos = arch.photos or []
                        photos.append(photo_filename)
                        arch.photos = photos
                        await db.commit()
                logger.info("[PHOTO-BG] Saved: %s", photo_filename)

            # The short wait above is bounded so a slow printer can't hold up
            # the print-complete notification, which is what the caller is
            # blocking on. When it ran out with the video still on its way,
            # keep waiting off to the side and add the better frame to the
            # archive once it arrives (#2704 follow-up) — otherwise P1-series
            # users, whose videos routinely take minutes to transfer, never get
            # the pre-bed-drop framing this path exists to provide.
            #
            # Spawned here rather than at the point the wait gave up: both this
            # function and the upgrade do a read-modify-write on `photos`, and
            # the live-camera fallback above can take tens of seconds. Starting
            # the upgrade before that write means the two can interleave and one
            # silently drops the other's entry, leaving a JPEG on disk that the
            # gallery never lists.
            if timelapse_still_pending:
                spawn_background_task(
                    _upgrade_finish_photo_from_timelapse(
                        archive_id, archive_dir, rotation=getattr(printer, "camera_rotation", 0)
                    ),
                    name=f"finish-photo-upgrade-{archive_id}",
                )

            return photo_filename
        except Exception as e:
            logger.warning("[PHOTO-BG] Failed: %s", e)
            return None
        finally:
            # #2547: we raised the plate, so we owe the move back down — even if
            # the capture in between threw. Otherwise the user finds the print
            # pinned under the nozzle.
            if plate_restored_z is not None:
                try:
                    _park_plate_after_finish_photo(printer_id, plate_restored_z, logger)
                except Exception as e:
                    logger.warning("[PLATE-RESTORE] printer %s: could not lower plate: %s", printer_id, e)

    spawn_background_task(_background_energy_calculation(), name="background-energy-calc")
    # Photo capture task - result will be used by notifications
    photo_task = spawn_background_task(_background_finish_photo(), name="background-finish-photo")
    log_timing("Background tasks scheduled (energy, photo)")

    # Also run smart plug, notifications, and maintenance as background tasks
    print_status = data.get("status", "completed")

    async def _background_smart_plug():
        """Handle smart plug automation in background."""
        try:
            logger.info("[AUTO-OFF-BG] Starting smart plug automation for printer %s", printer_id)
            async with async_session() as db:
                await smart_plug_manager.on_print_complete(printer_id, print_status, db)
                logger.info("[AUTO-OFF-BG] Completed")
        except Exception as e:
            logger.warning("[AUTO-OFF-BG] Failed: %s", e)

    async def _background_notifications(finish_photo_filename: str | None = None):
        """Send print complete notifications in background."""
        try:
            logger.info(
                "[NOTIFY-BG] Starting notifications for printer %s, photo=%s", printer_id, finish_photo_filename
            )
            async with async_session() as db:
                from backend.app.models.archive import PrintArchive
                from backend.app.models.printer import Printer

                result = await db.execute(select(Printer).where(Printer.id == printer_id))
                printer = result.scalar_one_or_none()
                printer_name = printer.name if printer else f"Printer {printer_id}"

                archive_data = None
                if archive_id:
                    archive_result = await db.execute(select(PrintArchive).where(PrintArchive.id == archive_id))
                    archive = archive_result.scalar_one_or_none()
                    if archive:
                        # Actual elapsed time from started_at/completed_at when both are
                        # populated (every terminal status sets completed_at after #1198).
                        # Falls back to None so the notification path can decide whether to
                        # render the slicer estimate as a last resort.
                        actual_time_seconds = None
                        if archive.started_at and archive.completed_at:
                            elapsed = (archive.completed_at - archive.started_at).total_seconds()
                            if elapsed > 0:
                                actual_time_seconds = int(elapsed)

                        archive_data = {
                            "print_time_seconds": archive.print_time_seconds,
                            "actual_time_seconds": actual_time_seconds,
                            "actual_filament_grams": archive.filament_used_grams,
                            "failure_reason": archive.failure_reason,
                            "created_by_id": archive.created_by_id,
                        }

                        # Scale filament usage for partial prints
                        if print_status != "completed" and archive.filament_used_grams:
                            progress = data.get("progress") or 0
                            scale = _partial_progress_scale(progress)
                            archive_data["actual_filament_grams"] = round(archive.filament_used_grams * scale, 1)
                            archive_data["progress"] = progress

                        # Pass per-slot data from archive.extra_data
                        if archive.extra_data and archive.extra_data.get("filament_slots"):
                            slots = archive.extra_data["filament_slots"]
                            if print_status != "completed":
                                scale = _partial_progress_scale(data.get("progress"))
                                slots = [{**s, "used_g": round(s["used_g"] * scale, 1)} for s in slots]
                            archive_data["filament_slots"] = slots

                        # Scope project-summed totals down to the plate that was
                        # actually printed — see _scope_notification_archive_data_to_plate
                        # for the why (#1785).
                        archive_data = _scope_notification_archive_data_to_plate(
                            archive_data,
                            archive.file_path,
                            notify_plate_id,
                            print_status,
                            data.get("progress"),
                            app_settings.base_dir,
                        )

                        # Enrich filament_grams from usage_results when archive has no 3MF data
                        if not archive_data.get("actual_filament_grams") and usage_results:
                            total_from_usage = sum(r.get("weight_used", 0) for r in usage_results)
                            if total_from_usage > 0:
                                archive_data["actual_filament_grams"] = round(total_from_usage, 1)

                        # Pass usage tracker results for AMS slot info in notifications
                        if usage_results:
                            archive_data["usage_results"] = usage_results
                        # Add finish photo URL and image bytes if available
                        if finish_photo_filename:
                            photo_url, photo_bytes = await _finish_photo_for_notification(
                                db, archive, archive_id, finish_photo_filename
                            )
                            if photo_url:
                                archive_data["finish_photo_url"] = photo_url
                            if photo_bytes:
                                archive_data["image_data"] = photo_bytes

                if not await _kill_switch_notification_already_sent(kill_switch_notification_task):
                    await notification_service.on_print_complete(
                        printer_id, printer_name, print_status, data, db, archive_data=archive_data
                    )
                else:
                    logger.info("[NOTIFY-BG] Skipped duplicate kill-switch provider notification")

                # Post-print outcome confirmation (#1898). Runs in this
                # background task so the finish photo fetched above rides
                # along with the prompt.
                if print_status == "completed" and archive_id:
                    await _dispatch_outcome_confirmation_safely(
                        db, printer_id, printer_name, data, archive_id, archive_data
                    )

                # Send user-specific email notification
                if archive_data:
                    created_by_id = archive_data.get("created_by_id")
                    raw_filename = data.get("subtask_name") or data.get("filename", "Unknown")
                    await _dispatch_user_print_email(
                        print_status,
                        created_by_id,
                        printer_name,
                        raw_filename,
                        db,
                        image_data=archive_data.get("image_data"),
                        finish_photo_url=archive_data.get("finish_photo_url"),
                    )

                logger.info("[NOTIFY-BG] Completed")
        except Exception as e:
            logger.error("[NOTIFY-BG] Failed: %s", e, exc_info=True)

    async def _background_maintenance_check():
        """Check for maintenance due in background."""
        if print_status != "completed":
            return
        try:
            logger.info("[MAINT-BG] Starting maintenance check for printer %s", printer_id)
            async with async_session() as db:
                from backend.app.models.printer import Printer

                result = await db.execute(select(Printer).where(Printer.id == printer_id))
                printer = result.scalar_one_or_none()
                printer_name = printer.name if printer else f"Printer {printer_id}"

                await ensure_default_types(db)
                overview = await _get_printer_maintenance_internal(printer_id, db, commit=True)

                items_needing_attention = [
                    {"name": item.maintenance_type_name, "is_due": item.is_due, "is_warning": item.is_warning}
                    for item in overview.maintenance_items
                    if item.enabled and (item.is_due or item.is_warning)
                ]

                if items_needing_attention:
                    await notification_service.on_maintenance_due(printer_id, printer_name, items_needing_attention, db)
                    logger.info("[MAINT-BG] Sent notification: %s items need attention", len(items_needing_attention))

                    # MQTT relay - publish maintenance alerts
                    for item in items_needing_attention:
                        try:
                            await mqtt_relay.on_maintenance_alert(
                                printer_id=printer_id,
                                printer_name=printer_name,
                                maintenance_type=item["name"],
                                current_value=0,  # Not easily available here
                                threshold=0,  # Not easily available here
                            )
                        except Exception:
                            pass  # Don't fail if MQTT fails
                else:
                    logger.info("[MAINT-BG] Completed (no items need attention)")
        except Exception as e:
            logger.warning("[MAINT-BG] Failed: %s", e)

    spawn_background_task(_background_smart_plug(), name="background-smart-plug")
    spawn_background_task(_background_maintenance_check(), name="background-maintenance-check")

    # Notification task waits for photo capture to complete first (with timeout).
    # When a timelapse was recording, photo sourcing polls the per-print
    # timelapse for up to 60s (#1397) — extend the budget so the notification
    # carries the correct bed-up photo instead of falling through to the
    # live-cam grab. Adds ~30s of notification latency at worst on slow links.
    #
    # #2547: both budgets now have to cover a plate restore as well.
    #
    # Without timelapse, the wait is on the moment producer, which raises the
    # plate before its grab — so this has to outlast that producer's own budget.
    #
    # With timelapse, the capture polls up to
    # `_FINISH_PHOTO_TIMELAPSE_POLL_TIMEOUT_SECONDS` for the video and only then
    # falls back to a live grab, which is the case that raises the plate. At the
    # old flat 75s that fallback was guaranteed to be cut off mid-settle, so the
    # restore would have moved the plate for a photo nobody waited for.
    photo_wait_timeout = (
        _FINISH_PHOTO_TIMELAPSE_POLL_TIMEOUT_SECONDS + _FINISH_PHOTO_PRODUCER_WAIT_SECONDS
        if data.get("timelapse_was_active")
        else _FINISH_PHOTO_PRODUCER_WAIT_SECONDS + 15
    )

    async def _photo_then_notify():
        """Wait for photo capture, then send notification with photo URL."""
        finish_photo = None
        try:
            finish_photo = await asyncio.wait_for(photo_task, timeout=photo_wait_timeout)
            logger.info("[PHOTO-NOTIFY] Photo task returned: %s", finish_photo)
        except TimeoutError:
            logger.warning(
                "[PHOTO-NOTIFY] Photo capture timed out after %ss, sending notification without photo",
                photo_wait_timeout,
            )
        except Exception as e:
            logger.warning("[PHOTO-NOTIFY] Photo task failed: %s", e)
        try:
            await _background_notifications(finish_photo)
        except Exception as e:
            logger.error("[PHOTO-NOTIFY] Notification sending failed: %s", e, exc_info=True)

    spawn_background_task(_photo_then_notify(), name="photo-then-notify")

    # Stitch external camera layer timelapse if session was active
    print_status = data.get("status", "completed")

    async def _background_layer_timelapse():
        """Stitch layer timelapse and attach to archive."""
        from backend.app.services.layer_timelapse import cancel_session, on_print_complete as tl_complete

        try:
            if print_status == "completed":
                logger.info("[LAYER-TL] Stitching layer timelapse for printer %s", printer_id)
                timelapse_path = await tl_complete(printer_id)
                if timelapse_path and archive_id:
                    logger.info("[LAYER-TL] Attaching timelapse %s to archive %s", timelapse_path, archive_id)
                    async with async_session() as db:
                        service = ArchiveService(db)
                        timelapse_data = await asyncio.to_thread(timelapse_path.read_bytes)
                        await service.attach_timelapse(archive_id, timelapse_data, "layer_timelapse.mp4")
                        # Clean up the temp file
                        await asyncio.to_thread(timelapse_path.unlink, missing_ok=True)
                        logger.info("[LAYER-TL] Layer timelapse attached successfully")
                elif timelapse_path:
                    # Timelapse created but no archive - just clean up
                    await asyncio.to_thread(timelapse_path.unlink, missing_ok=True)
            else:
                # Print failed or cancelled - cancel timelapse session
                cancel_session(printer_id)
                logger.info(
                    "[LAYER-TL] Cancelled layer timelapse for printer %s (status: %s)", printer_id, print_status
                )
        except Exception as e:
            logger.warning("[LAYER-TL] Failed: %s", e)
            # Try to cancel session on error
            try:
                cancel_session(printer_id)
            except Exception:
                pass  # Best-effort timelapse session cancellation on error

    spawn_background_task(_background_layer_timelapse(), name="background-layer-timelapse")

    log_timing("All background tasks scheduled")

    # Auto-scan for timelapse if recording was active during the print
    if archive_id and data.get("timelapse_was_active") and data.get("status") == "completed":
        logger.info("[TIMELAPSE] Timelapse was active during print, scheduling auto-scan for archive %s", archive_id)
        # Schedule timelapse scan as background task with retries
        # The printer needs time to encode the video after print completion
        baseline = _timelapse_baselines.pop(printer_id, None)
        spawn_background_task(
            _scan_for_timelapse_with_retries(archive_id, baseline),
            name=f"scan-timelapse-{archive_id}",
        )
        log_timing("Timelapse scan scheduled")

    logger.info("[CALLBACK] on_print_complete finished for printer %s, archive %s", printer_id, archive_id)


# Per-AMS "drying was live at" latch that suppresses the high-temperature alarm
# through a cycle and the cool-down after it (#1802). Stored in the settings
# table rather than alongside _ams_alarm_cooldown above, because a restart
# partway through a cool-down would otherwise resume alarming about heat the
# user asked for — the same internal-timestamp-row pattern as
# support.py's debug_logging_enabled_at.
AMS_DRYING_LATCH_KEY = "ams_drying_alarm_latch"

# Upper bound on that suppression. The latch normally clears as soon as the unit
# reads at or below the threshold; see utils.ams_drying for why this cap only
# matters when it never does.
AMS_DRYING_GRACE_MINUTES = 120


async def _load_ams_drying_latch(db) -> dict[str, datetime]:
    """Read the persisted per-AMS drying latch, dropping entries out of window.

    Anything older than the grace cap would expire on its next visit anyway, so
    discarding it here costs nothing and stops rows for deleted printers from
    accumulating.

    Stamps ahead of now get two defences, because a box whose clock jumps
    backwards (a Pi with no RTC coming up before NTP) writes them: wildly future
    ones are discarded outright, and the rest are clamped to now. Without the
    clamp the cap would measure from a moment that has not happened yet and hold
    the alarm quiet for the skew on top of the cap. One unnecessary notification
    after a clock jump is a far better failure than an alarm silently disabled
    for hours.
    """
    from backend.app.models.settings import Settings

    result = await db.execute(select(Settings).where(Settings.key == AMS_DRYING_LATCH_KEY))
    setting = result.scalar_one_or_none()
    if not setting or not setting.value:
        return {}
    try:
        raw = json.loads(setting.value)
    except (ValueError, TypeError):
        return {}  # Corrupted row → no latch, alarms behave as they did before
    if not isinstance(raw, dict):
        return {}

    now = datetime.now(timezone.utc)
    window = timedelta(minutes=AMS_DRYING_GRACE_MINUTES)
    latch: dict[str, datetime] = {}
    for key, value in raw.items():
        try:
            stamp = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if not (now - window <= stamp <= now + window):
            continue
        # Nothing may sit in the future: suppression is measured as now minus
        # the stamp, so a stamp ahead of now would extend it by the skew on top
        # of the cap. Clamping the survivors keeps the cap an actual cap.
        latch[str(key)] = min(stamp, now)
    return latch


async def _save_ams_drying_latch(db, latch: dict[str, datetime]) -> None:
    """Persist the latch, writing only when it actually changed.

    Adds the session change but does not commit — the caller's own commit
    carries it, so the latch lands in the same transaction as the sensor rows
    that produced it.
    """
    from backend.app.models.settings import Settings

    payload = json.dumps({key: stamp.isoformat() for key, stamp in sorted(latch.items())})
    result = await db.execute(select(Settings).where(Settings.key == AMS_DRYING_LATCH_KEY))
    setting = result.scalar_one_or_none()
    if setting is None:
        # Don't create the row on installs that never dry anything.
        if payload != "{}":
            db.add(Settings(key=AMS_DRYING_LATCH_KEY, value=payload))
    elif setting.value != payload:
        setting.value = payload


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # Install Windows-only asyncio Proactor cleanup-RST filter (#1113) before
    # anything else can spawn tasks that might trip it.
    from backend.app.core.asyncio_handlers import install_proactor_reset_filter, warn_if_running_on_uvloop

    install_proactor_reset_filter()

    # Before init_db, so the warning is near the top of the log rather than
    # below a migration run. See warn_if_running_on_uvloop for what is at stake.
    warn_if_running_on_uvloop()

    # Ein unterbrochener Werkseinstellungs-Lauf wird vor dem Anlegen des Schemas zu Ende geführt, damit der
    # nächste Start nicht mit halb verschobenen Daten und alter Datenbank beginnt.
    try:
        from backend.app.services import factory_reset

        factory_reset.apply_pending(app_settings.base_dir)
    except OSError as exc:  # pragma: no cover - nur bei fehlenden Dateirechten
        logging.warning("Werkseinstellungen konnten nicht abgeschlossen werden: %s", exc)

    await init_db()

    # Fork: Update bestätigen, Warnung bei offener Anmeldung (siehe services/fork_startup.py)
    from backend.app.services import fork_startup

    await fork_startup.on_startup(app_settings.base_dir, async_session)

    # Browser download tokens expire after five minutes. Remove abandoned
    # prepared ZIPs at startup as well as before each new preparation so a
    # quiet appliance cannot retain an unusable bundle indefinitely.
    try:
        from backend.app.services.printer_media import prune_stale_printer_file_bundles

        await prune_stale_printer_file_bundles()
    except Exception as exc:
        logging.warning("Failed to prune stale printer download bundles: %s", exc)

    # After migrations, so the is_env_managed column exists. Never raises --
    # a bad PRINTLAB_OIDC_* value is logged and skipped rather than blocking
    # startup (see apply_env_oidc_provider).
    from backend.app.core.oidc_env import apply_env_oidc_provider

    async with async_session() as oidc_db:
        await apply_env_oidc_provider(oidc_db)

    # Close out batches that finished before `completed` was a reachable status
    # (#342). Without this the Batches tab opens on every batch created since
    # the feature shipped, all still marked active. Never blocks startup.
    try:
        from backend.app.services.print_batch import backfill_batch_statuses

        async with async_session() as batch_db:
            await backfill_batch_statuses(batch_db)
    except Exception as exc:
        logging.warning("[BATCH] Startup status backfill failed: %s", exc)

    # Register an app-scoped httpx client for Bambu Cloud services so
    # per-request BambuCloudService instances reuse the same connection pool
    # (important for routes like /cloud/filament-info that chain many
    # get_setting_detail calls). The shared client stores no region/token
    # state, so the per-request ownership pattern that fixed the region-bleed
    # bug is preserved.
    import httpx as _httpx

    from backend.app.services.bambu_cloud import set_shared_http_client
    from backend.app.services.model_providers.makerworld.service import (
        set_shared_http_client as set_shared_makerworld_http_client,
    )
    from backend.app.services.orca_cloud import (
        set_shared_http_client as set_shared_orca_http_client,
    )

    _shared_cloud_http_client = _httpx.AsyncClient(timeout=30.0)
    set_shared_http_client(_shared_cloud_http_client)
    # Reuse the same connection pool for MakerWorld — different host, same
    # keep-alive pool saves a TLS handshake per request.
    set_shared_makerworld_http_client(_shared_cloud_http_client)
    # Same for Orca Cloud — without this the per-request OrcaCloudService()
    # each spun up (and never closed) its own client, leaking sockets.
    set_shared_orca_http_client(_shared_cloud_http_client)

    # Fix queue items stuck with invalid "aborted" status (should be "cancelled").
    # This can happen when a print was cancelled mid-print on versions before this fix.
    try:
        async with async_session() as db:
            from backend.app.models.print_queue import PrintQueueItem

            result = await db.execute(select(PrintQueueItem).where(PrintQueueItem.status == "aborted"))
            aborted_items = result.scalars().all()
            if aborted_items:
                for item in aborted_items:
                    item.status = "cancelled"
                await db.commit()
                logging.info("Fixed %d queue item(s) with invalid 'aborted' status → 'cancelled'", len(aborted_items))
    except Exception as e:
        logging.warning("Failed to fix aborted queue items: %s", e)

    # Restore debug logging state from previous session
    await init_debug_logging()

    # Set up printer manager callbacks
    loop = asyncio.get_event_loop()
    printer_manager.set_event_loop(loop)
    printer_manager.set_status_change_callback(on_printer_status_change)
    printer_manager.set_print_start_callback(on_print_start)
    printer_manager.set_print_complete_callback(on_print_complete)
    printer_manager.set_print_running_observed_callback(on_print_running_observed)
    printer_manager.set_finish_photo_moment_callback(on_finish_photo_moment)
    printer_manager.set_ams_change_callback(on_ams_change)
    printer_manager.set_fts_inlet_change_callback(on_fts_inlet_change)

    # Rehydrate persisted awaiting-plate-clear gate (#961) so prompts survive restarts
    await printer_manager.load_awaiting_plate_clear_from_db()

    # Layer change callback for external camera timelapse
    async def on_layer_change(printer_id: int, layer_num: int):
        """Capture timelapse frame on layer change + first layer notification."""
        from backend.app.services.first_layer_inspector import first_layer_inspector as first_layer_service
        from backend.app.services.layer_alerts import layer_alerts as layer_alert_service
        from backend.app.services.part_watcher import part_watcher as part_watcher_service

        await layer_alert_service.observe(printer_id, layer_num, printer_manager.get_client(printer_id))

        async def calibrate_snapshot(image: bytes) -> bytes | None:
            """Ein gemessenes Bild (Plattenaufsicht) anliefern, wenn eingerückt.

            - Einmessung vorhanden, Warp gelingt: das gewarppte Bild.
            - Einmessung vorhanden, Warp scheitert: ``None`` — ein Vergleich mit
              einer gewarppten Referenz wäre sonst unstatthaft (gewarpt gegen
              ungewarpt). Die Beobachter überspringen die Prüfung dann.
            - Keine Einmessung: das Original — Beobachter ohne Referenz rechnen
              einheitlich mit ungewarpten Bildern weiter, nie mit nichts.
            """
            try:
                from backend.app.services.plate_calibration import has_calibration, warp_snapshot

                if not has_calibration(printer_id):
                    return image
                return await warp_snapshot(printer_id, image) or None
            except Exception as exc:  # noqa: BLE001 - Kamerapfad darf nicht abbrechen
                logging.getLogger(__name__).warning("Platteinmessung übersprungen: %s", exc)
                return None

        # Erste-Schicht-Inspektor: Bild der ersten Schichten ohne Referenz beurteilen.
        fl_client = printer_manager.get_client(printer_id)
        fl_state = fl_client.state if fl_client else None
        if fl_state is not None:
            fl_key = fl_state.subtask_id or fl_state.gcode_file or ""
            if first_layer_service.needs_frame(printer_id, layer_num, fl_key):
                try:
                    from backend.app.models.printer import Printer

                    async with async_session() as fl_db:
                        result = await fl_db.execute(select(Printer).where(Printer.id == printer_id))
                        fl_printer = result.scalar_one_or_none()
                        if fl_printer:
                            image = await _capture_snapshot_for_notification(
                                printer_id, fl_printer, logging.getLogger(__name__)
                            )
                            image = await calibrate_snapshot(image)
                            warning = (
                                first_layer_service.observe(printer_id, layer_num, image, fl_key)
                                if image is not None
                                else None
                            )
                            if warning:
                                # Erste-Schicht-Gate: optional pausieren statt nur warnen —
                                # einmalig je Druck (observe markiert ihn als geprüft).
                                if (
                                    first_layer_service.pause_on_warning(printer_id)
                                    and fl_client.state.state == "RUNNING"
                                ):
                                    try:
                                        await fl_client.pause_print()
                                        warning["paused"] = True
                                        logging.getLogger(__name__).warning(
                                            "Erste Schicht auffällig (Drucker %s) — Druck pausiert.",
                                            printer_id,
                                        )
                                    except Exception as pause_exc:  # noqa: BLE001
                                        logging.getLogger(__name__).warning(
                                            "Pause nach Erste-Schicht-Warnung fehlgeschlagen: %s", pause_exc
                                        )
                                await notification_service.on_ai_failure_detection(
                                    printer_id,
                                    fl_printer.name,
                                    fl_state.subtask_name or "",
                                    0.5,
                                    "first_layer_inspector",
                                    fl_db,
                                    image_data=image,
                                )
                except Exception as exc:  # noqa: BLE001 - Callback darf nicht abbrechen
                    logging.getLogger(__name__).warning("Erste-Schicht-Inspektor fehlgeschlagen: %s", exc)

        # Bauteil-Wächter: Schicht 2 als Referenz, Mitte des Drucks als Vergleich.
        pw_client = printer_manager.get_client(printer_id)
        pw_state = pw_client.state if pw_client else None
        if pw_state is not None:
            pw_key = pw_state.subtask_id or pw_state.gcode_file or ""
            if part_watcher_service.needs_frame(printer_id, layer_num, pw_state.total_layers, pw_key):
                try:
                    from backend.app.models.printer import Printer

                    async with async_session() as pw_db:
                        result = await pw_db.execute(select(Printer).where(Printer.id == printer_id))
                        pw_printer = result.scalar_one_or_none()
                        if pw_printer:
                            image = await _capture_snapshot_for_notification(
                                printer_id, pw_printer, logging.getLogger(__name__)
                            )
                            image = await calibrate_snapshot(image)
                            warning = (
                                part_watcher_service.observe(
                                    printer_id,
                                    pw_printer.name,
                                    layer_num,
                                    pw_state.total_layers,
                                    image,
                                    pw_key,
                                )
                                if image is not None
                                else None
                            )
                            if warning:
                                await notification_service.on_ai_failure_detection(
                                    printer_id,
                                    pw_printer.name,
                                    pw_state.subtask_name or "",
                                    0.5,
                                    "part_watcher",
                                    pw_db,
                                    image_data=image,
                                )
                except Exception as exc:  # noqa: BLE001 - Callback darf nicht abbrechen
                    logging.getLogger(__name__).warning("Bauteil-Wächter fehlgeschlagen: %s", exc)

        from backend.app.services.layer_timelapse import on_layer_change as tl_layer_change

        await tl_layer_change(printer_id, layer_num)

        # #1867: bank a recent in-print frame so the finish-photo path has a
        # pre-End-G-code image to use instead of a live grab of a swapped plate.
        # #2547 added `on_print_progress` as a second driver — this one alone
        # stops firing once the final layer begins.
        await _maybe_bank_inprint_frame(printer_id, layer_num)

        # First layer complete notification (layer_num >= 2 means layer 1 is done).
        # Gate on actual printing state — Bambu firmware ticks layer_num during
        # the pre-print calibration sequence (homing / mesh-level / bed scan /
        # nozzle clean), so a bare layer_num check can fire minutes before the
        # first real extrusion. We require gcode_state == RUNNING and
        # mc_print_sub_stage in (0 = "Printing", None) so calibration sub-stages
        # (1, 9, 14, ...) are excluded. The window widens to [2, 10] because if
        # the layer counter advanced past 2 during PREPARE, the next on_layer_change
        # edge fires later; _first_layer_notified stays clear until we actually send
        # so a deferred re-evaluation can win. See issue #1837.
        if 2 <= layer_num <= 10 and not _first_layer_notified.get(printer_id, False):
            client = printer_manager.get_client(printer_id)
            state = client.state if client else None
            if not state or state.state != "RUNNING":
                return
            if state.mc_print_sub_stage not in (None, 0):
                return
            _first_layer_notified[printer_id] = True
            try:
                async with async_session() as db:
                    from backend.app.models.printer import Printer

                    result = await db.execute(select(Printer).where(Printer.id == printer_id))
                    printer = result.scalar_one_or_none()
                    if not printer:
                        return
                    printer_name = printer.name
                    filename = (state.subtask_name or state.gcode_file or "Unknown") if state else "Unknown"
                    total_layers = state.total_layers if state else 0

                    image_data = await _capture_snapshot_for_notification(
                        printer_id, printer, logging.getLogger(__name__)
                    )
                    await notification_service.on_first_layer_complete(
                        printer_id, printer_name, filename, total_layers, db, image_data=image_data
                    )
            except Exception as e:
                logging.getLogger(__name__).warning("First layer notification failed: %s", e)

    printer_manager.set_layer_change_callback(on_layer_change)

    async def on_print_progress(printer_id: int, percent: int):
        """#2547: keep the in-print frame bank fresh through the final layer.

        `on_layer_change` stops the moment the last layer starts, which on the
        H2C capture that closed #2547 left the bank stale for the three minutes
        that layer took. Progress is the only field that keeps advancing there,
        and it freezes before the End G-code runs — so banking on it stays
        inside the print and never sees a swapped plate.
        """
        client = printer_manager.get_client(printer_id)
        state = client.state if client else None
        await _maybe_bank_inprint_frame(printer_id, state.layer_num if state else 0)

    printer_manager.set_print_progress_callback(on_print_progress)

    # Event-driven bed cooldown: fires whenever bed_temper arrives via MQTT
    async def on_bed_temp_update(printer_id: int, bed_temp: float):
        waiter = _bed_cool_waiters.get(printer_id)
        if not waiter:
            return
        threshold = waiter["threshold"]
        if bed_temp > threshold:
            return
        # Bed is at or below threshold — fire notification and remove waiter
        waiter_info = _bed_cool_waiters.pop(printer_id, None)
        if not waiter_info:
            return  # Another callback already handled it
        bed_cool_logger = logging.getLogger(__name__)
        bed_cool_logger.info(
            "[BED-COOL] Bed cooled to %.1f°C on printer %s (threshold: %.0f°C)",
            bed_temp,
            printer_id,
            threshold,
        )
        try:
            printer_info = printer_manager.get_printer(printer_id)
            p_name = printer_info.name if printer_info else "Unknown"
            async with async_session() as db:
                await notification_service.on_bed_cooled(
                    printer_id=printer_id,
                    printer_name=p_name,
                    bed_temp=bed_temp,
                    threshold=threshold,
                    filename=waiter_info["filename"],
                    db=db,
                )
        except Exception as e:
            bed_cool_logger.warning("[BED-COOL] Failed to send notification: %s", e)

    printer_manager.set_bed_temp_update_callback(on_bed_temp_update)

    async def on_drying_complete(printer_id: int, ams_id: int):
        """Smart-plug auto-off-after-drying trigger (#1349).

        Fires once per AMS unit when ``dry_time`` falls from >0 to 0. The
        manager walks all plugs linked to this printer and turns off only
        the ones with ``auto_off_after_drying`` enabled, after their
        per-plug delay. Multiple AMS units finishing close together (e.g. a
        dual-AMS dry that ends within the same MQTT push) call this once
        per unit — the manager's ``_cancel_pending_off`` collapses
        repeated scheduling on the same plug to one timer, so duplicate
        fires are safe.
        """
        try:
            async with async_session() as db:
                await smart_plug_manager.on_drying_complete(printer_id, db)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Failed to schedule auto-off-after-drying for printer %d (AMS %d): %s",
                printer_id,
                ams_id,
                e,
            )

    printer_manager.set_drying_complete_callback(on_drying_complete)

    async def on_assignment_verified(printer_id: int, ams_id: int, tray_id: int, verified: bool, detail: dict):
        """Surface the read-back result of a spool assignment to the UI (#2582).

        The MQTT client confirms (or fails to confirm) that the tray telemetry
        echoed back the filament id we pushed. We relay that as a websocket
        event so the frontend can toast "loaded" / "assignment didn't take"
        instead of the historic silent fire-and-forget, which made the
        AMS→Studio hand-off feel random to users.
        """
        try:
            from backend.app.services.spool_assignment_notifications import (
                _slot_label_from_global_tray,
            )

            if ams_id == 255:
                global_id = 254 + tray_id
            elif ams_id >= 128:
                global_id = ams_id
            else:
                global_id = ams_id * 4 + tray_id
            slot_label = _slot_label_from_global_tray(global_id)

            printer_info = printer_manager.get_printer(printer_id)
            printer_name = printer_info.name if printer_info else f"Printer {printer_id}"

            await ws_manager.broadcast(
                {
                    "type": "spool_assignment_verified",
                    "printer_id": printer_id,
                    "printer_name": printer_name,
                    "ams_id": ams_id,
                    "tray_id": tray_id,
                    "slot": slot_label,
                    "verified": verified,
                    # Present on success: False means the filament setting landed
                    # but the K-profile (cali_idx) did not — the reporter's exact
                    # "loaded but no flow profile" symptom.
                    "kprofile_applied": detail.get("kprofile_applied", True),
                    # Present on failure: whether any tray telemetry was seen in
                    # the window (distinguishes "printer silent" from "printer
                    # stored something else").
                    "saw_tray": detail.get("saw_tray", False),
                }
            )
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Failed to broadcast assignment verification for printer %d AMS%d-T%d: %s",
                printer_id,
                ams_id,
                tray_id,
                e,
            )

    printer_manager.set_assignment_verified_callback(on_assignment_verified)

    async def on_tray_change(printer_id: int, tray_global: int, layer_num: int):
        """Persist a mid-print tray change for completion-time attribution.

        AMS filament backup switches trays without telling the slicer, so the
        tray-change log is the only record of which spool fed which layers.
        Keeping it only in memory meant a restart mid-print charged everything
        to the tray that finished the job.
        """
        try:
            from backend.app.services.usage_tracker import record_tray_change

            async with async_session() as db:
                await record_tray_change(db, printer_id, tray_global, layer_num)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Failed to persist tray change for printer %d (tray=%d, layer=%d): %s",
                printer_id,
                tray_global,
                layer_num,
                e,
            )

    printer_manager.set_tray_change_callback(on_tray_change)

    # Initialize MQTT relay from settings
    async with async_session() as db:
        from backend.app.api.routes.settings import get_setting

        mqtt_settings = {
            "mqtt_enabled": (await get_setting(db, "mqtt_enabled") or "false") == "true",
            "mqtt_broker": await get_setting(db, "mqtt_broker") or "",
            "mqtt_port": int(await get_setting(db, "mqtt_port") or "1883"),
            "mqtt_username": await get_setting(db, "mqtt_username") or "",
            "mqtt_password": await get_setting(db, "mqtt_password") or "",
            "mqtt_topic_prefix": await get_setting(db, "mqtt_topic_prefix") or "printlab",
            "mqtt_use_tls": (await get_setting(db, "mqtt_use_tls") or "false") == "true",
        }
        await mqtt_relay.configure(mqtt_settings)

        # Restore MQTT smart plug subscriptions
        if mqtt_settings.get("mqtt_enabled"):
            from backend.app.models.smart_plug import SmartPlug
            from backend.app.services.mqtt_smart_plug import subscribe_plug_to_mqtt

            result = await db.execute(select(SmartPlug).where(SmartPlug.plug_type == "mqtt"))
            mqtt_plugs = result.scalars().all()
            restored = 0
            for plug in mqtt_plugs:
                if subscribe_plug_to_mqtt(mqtt_relay.smart_plug_service, plug):
                    restored += 1
            if restored:
                logging.info("Restored %s MQTT smart plug subscriptions", restored)

    # Connect to all active printers
    async with async_session() as db:
        await init_printer_connections(db)

    # Auto-connect to Spoolman if enabled
    async with async_session() as db:
        from backend.app.api.routes.settings import get_setting

        spoolman_enabled = await get_setting(db, "spoolman_enabled")
        spoolman_url = await get_setting(db, "spoolman_url")

        if spoolman_enabled and spoolman_enabled.lower() == "true" and spoolman_url:
            try:
                client = await init_spoolman_client(spoolman_url)
                if await client.health_check():
                    logging.info("Auto-connected to Spoolman at %s", spoolman_url)
                    # Ensure the 'tag' extra field exists for RFID/UUID storage
                    field_ok = await client.ensure_tag_extra_field()
                    if not field_ok:
                        logging.error("Spoolman tag extra field registration failed — NFC tag links may not persist")
                    # Register the BambuStudio slicer-preset fields used by the
                    # spool-edit / assign flow. Spoolman rejects PATCHes with
                    # unknown extra keys, so these must exist before any update
                    # that touches them.
                    for field_name in ("bambu_slicer_filament", "bambu_slicer_filament_name"):
                        if not await client.ensure_extra_field(field_name):
                            logging.warning(
                                "Spoolman extra field %r registration failed — "
                                "spool slicer-preset edits will return 502",
                                field_name,
                            )
                else:
                    logging.warning("Spoolman at %s is not reachable", spoolman_url)
            except Exception as e:
                logging.warning("Failed to auto-connect to Spoolman: %s", e)

    # Start the print scheduler
    spawn_background_task(print_scheduler.run(), name="print-scheduler")
    from backend.app.services import queue_due_watch

    spawn_background_task(queue_due_watch.run(async_session), name="queue-due-watch")  # PrintLab: Termin-Meldung
    from backend.app.services import invoice_reminder

    spawn_background_task(invoice_reminder.run(async_session), name="invoice-reminder")  # PrintLab: Zahlungserinnerung
    from backend.app.services import countermeasures

    spawn_background_task(countermeasures.run(), name="countermeasures")  # PrintLab: Gegenmaßnahmen
    from backend.app.services import local_ai_watch

    spawn_background_task(local_ai_watch.run(), name="local-ai-watch")  # PrintLab: laufende Bildprüfung

    # Start the smart plug scheduler for time-based on/off
    smart_plug_manager.start_scheduler()

    # Start the Home Assistant sensor poller (#1148)
    ha_sensor_manager.start()
    location_ha_sensor_manager.start()

    # Resume any pending auto-offs that were interrupted by restart
    await smart_plug_manager.resume_pending_auto_offs()

    # Start the notification digest scheduler
    notification_service.start_digest_scheduler()

    # Start the Telegram reaction pollers (#3046), one per bot token used by a
    # provider in reactions/both mode; the notification routes resync them.
    # Never fatal: a bad provider row or a DB hiccup here costs reactions
    # until the next provider save, not the whole startup.
    try:
        await telegram_reaction_poller.start()
    except Exception as e:
        logging.warning("Telegram reaction poller did not start: %s", e)

    # Start the GitHub backup scheduler
    await github_backup_service.start_scheduler()

    # Start the local backup scheduler
    await local_backup_service.start_scheduler()
    await obico_detection_service.start()

    # Start the library trash sweeper (#1008)
    await library_trash_service.start_scheduler()

    # Start the archive auto-purge sweeper (#1008 follow-up)
    await archive_purge_service.start_scheduler()

    # Start AMS history recording
    start_ams_history_recording()

    # Start printer sensor (nozzle / bed / chamber) history recording
    start_printer_sensor_history_recording()

    # Start printer runtime tracking
    start_runtime_tracking()

    # Start SpoolBuddy device watchdog
    start_spoolbuddy_watchdog()

    # Start camera stream orphan cleanup
    start_camera_cleanup()

    # Start the backstop for MQTT sessions paho has stopped recovering (#2732)
    start_connection_watchdog()

    # One-shot sweep for timelapse session directories orphaned by a crash
    # or restart that happened mid-print (in-memory session tracking can't
    # survive that, and nothing else reaps the leftover frames/output file)
    try:
        from backend.app.services.layer_timelapse import cleanup_orphaned_timelapse_sessions

        removed = cleanup_orphaned_timelapse_sessions()
        if removed:
            logging.getLogger(__name__).info("Removed %d orphaned timelapse session artifact(s)", removed)
    except Exception as e:
        logging.getLogger(__name__).warning("Orphaned timelapse session cleanup failed: %s", e)

    # Start expected-print TTL eviction (prevents memory leak when prints are
    # registered but on_print_start never fires)
    start_expected_prints_cleanup()

    # L-2: Start periodic auth cleanup (stale TOTP + expired revoked JTIs)
    start_auth_cleanup()

    # Maintainer announcements: a signed feed fetched from GitHub every few hours.
    from backend.app.services import announcements as announcements_service

    announcements_service.start()

    from backend.app.services.printer_media import start_printer_download_cleanup

    start_printer_download_cleanup()

    # Event-loop stall watchdog: dumps all thread stacks to stderr if the loop
    # freezes (#1486 — silent "container hangs after adding a printer" reports).
    from backend.app.services.loop_watchdog import start_loop_watchdog

    start_loop_watchdog()

    # Initialize virtual printer manager and sync from DB
    from backend.app.services.virtual_printer import virtual_printer_manager

    virtual_printer_manager.set_session_factory(async_session)
    virtual_printer_manager.set_printer_manager(printer_manager)
    try:
        await virtual_printer_manager.sync_from_db()
        logging.info("Virtual printer manager synced from database")
    except Exception as e:
        logging.warning("Failed to sync virtual printers: %s", e)

    # Fernzugriff (Tailscale) wieder herstellen, falls er eingeschaltet war
    from backend.app.services import remote_access as remote_access_service

    asyncio.create_task(remote_access_service.autostart())

    yield

    # Shutdown
    remote_access_service.stop_daemon()
    print_scheduler.stop()
    smart_plug_manager.stop_scheduler()
    ha_sensor_manager.stop()
    location_ha_sensor_manager.stop()
    notification_service.stop_digest_scheduler()
    await telegram_reaction_poller.aclose()
    github_backup_service.stop_scheduler()
    local_backup_service.stop_scheduler()
    library_trash_service.stop_scheduler()
    archive_purge_service.stop_scheduler()
    obico_detection_service.stop()
    stop_ams_history_recording()
    stop_printer_sensor_history_recording()
    stop_runtime_tracking()
    stop_spoolbuddy_watchdog()
    stop_camera_cleanup()
    stop_connection_watchdog()
    from backend.app.services.loop_watchdog import stop_loop_watchdog

    stop_loop_watchdog()
    # Tear down all camera fan-out broadcasters (#1089) so subscribers exit
    # cleanly rather than waiting on a queue that nothing will ever fill.
    try:
        from backend.app.services.camera_fanout import shutdown_all_broadcasters

        await shutdown_all_broadcasters()
    except Exception as e:
        logging.warning("Failed to shut down camera broadcasters: %s", e)
    stop_expected_prints_cleanup()
    stop_auth_cleanup()
    from backend.app.services import announcements as announcements_service

    announcements_service.stop()
    from backend.app.services.printer_media import stop_printer_download_cleanup

    await stop_printer_download_cleanup()
    printer_manager.disconnect_all()
    slot_unlink_grace.reset()
    await close_spoolman_client()

    # Stop all virtual printer services
    await virtual_printer_manager.stop_all()

    await mqtt_smart_plug_service.disconnect(timeout=2)

    await mqtt_relay.disconnect(timeout=2)

    # Drop the shared Bambu Cloud HTTP client we registered at startup.
    set_shared_http_client(None)
    set_shared_makerworld_http_client(None)
    set_shared_orca_http_client(None)
    await _shared_cloud_http_client.aclose()

    # Checkpoint WAL (SQLite only) and close all database connections
    from backend.app.core.db_dialect import is_sqlite

    if is_sqlite():
        try:
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            logging.info("WAL checkpoint completed")
        except Exception as e:
            logging.warning("WAL checkpoint failed: %s", e)
    await engine.dispose()


app = FastAPI(
    title=app_settings.app_name,
    description="Archive and manage Bambu Lab 3MF files",
    version=APP_VERSION,
    lifespan=lifespan,
)


# =============================================================================
# Authentication Middleware - Secures ALL API routes by default
# =============================================================================
# Public routes that don't require authentication even when auth is enabled
PUBLIC_API_ROUTES = {
    # Auth routes needed before/during login
    "/api/v1/auth/status",
    "/api/v1/auth/login",
    "/api/v1/auth/setup",  # Needed for initial setup and recovery
    # Advanced auth status needed for login page
    "/api/v1/auth/advanced-auth/status",
    "/api/v1/auth/forgot-password",  # Password reset for advanced auth
    "/api/v1/auth/forgot-password/confirm",  # Complete password reset with token (H-6)
    # 2FA routes that are called BEFORE a JWT is issued (pre-auth flow)
    "/api/v1/auth/2fa/verify",  # Exchange pre_auth_token + 2FA code for JWT
    "/api/v1/auth/2fa/email/send",  # Send OTP email (pre_auth_token based)
    # OIDC routes that must be reachable without a JWT
    "/api/v1/auth/oidc/providers",  # Public list of enabled providers
    "/api/v1/auth/oidc/callback",  # Redirect target from OIDC provider
    "/api/v1/auth/oidc/exchange",  # Exchange short-lived OIDC token for JWT
    # Connected apps: the app's server swaps a code for the user's identity,
    # authenticated by its client secret rather than a login token.
    "/api/v1/connect/token",
    # Version check for updates (no sensitive data)
    "/api/v1/updates/version",
    # Metrics endpoint handles its own prometheus_token authentication
    "/api/v1/metrics",
    # Appliance bootstrap (#1589 follow-up): the SPA's i18n setup polls
    # this BEFORE a JWT is available to pick up the firstboot wizard's
    # hostname / timezone / locale and the chrony NTP-gate state. The
    # response contains user-set defaults and a public sync flag — no
    # secrets. Without this entry the global auth middleware returns 401
    # before the route handler runs, regardless of the route's own
    # "no auth required" intent.
    "/api/v1/system/appliance",
    # Cam Wall kiosk feed (#2531): a TV or Pi in kiosk mode has no login, so it
    # authenticates with a long-lived ``camwall``-scoped token in the query
    # string — exactly like the camera streams two lists below, and for the same
    # reason (no header to put a JWT in). "Public" here only means the middleware
    # steps aside; the route still runs RequireCamWallTokenIfAuthEnabled, which
    # rejects an absent, expired, revoked, or wrong-scoped token. In particular a
    # plain ``camera_stream`` token does NOT open this door.
    "/api/v1/camwall/printers",
}

# Route prefixes that are public (for routes with dynamic segments)
PUBLIC_API_PREFIXES = [
    # WebSocket connections handle their own auth
    "/api/v1/ws",
    # OIDC authorize redirects — include provider_id in path
    "/api/v1/auth/oidc/authorize/",
    # One-tap outcome-verdict links from push notifications (#1898). Tapped on
    # a phone with no session, so no header can carry a JWT — the single-use
    # capability token in the path IS the credential (same reasoning as the
    # /dl/ slicer downloads below). The route grants nothing beyond writing
    # good/reject on the one archive the token was minted for.
    "/api/v1/archives/confirm/",
    # Öffentlicher Angebots-Link (Angebote): der Kunde antwortet ohne Sitzung.
    # Das Merkmal in der Adresse ist die Berechtigung; die Seite zeigt nur
    # Kundenangaben und schreibt ausschließlich die Zusage/Ablehnung.
    "/api/v1/quote/shared/",
]

# Route patterns that are public (read-only display data)
# These are checked with "in path" - needed because browsers load images/videos
# via <img src> and <video src> which don't include Authorization headers
PUBLIC_API_PATTERNS = [
    # Thumbnails
    "/thumbnail",  # /archives/{id}/thumbnail, /library/files/{id}/thumbnail
    "/plate-thumbnail/",  # /archives/{id}/plate-thumbnail/{plate_id}
    # Images and media
    "/photos/",  # /archives/{id}/photos/{filename}
    "/project-image/",  # /archives/{id}/project-image/{path}
    "/qrcode",  # /archives/{id}/qrcode
    "/timelapse",  # /archives/{id}/timelapse (video)
    "/cover",  # /printers/{id}/cover
    "/icon",  # /external-links/{id}/icon
    # Camera (streams loaded via <img> tag)
    "/camera/stream",  # /printers/{id}/camera/stream
    "/camera/snapshot",  # /printers/{id}/camera/snapshot
    # Streaming-overlay status feed (#2613): OBS loads /overlay/{id} with no login
    # and this backs it, authenticated by an ``overlay``-scoped token in the query
    # string (same reasoning as the camera streams above — no header to carry a
    # JWT). "Public" only means the middleware steps aside; the route still runs
    # RequireOverlayTokenIfAuthEnabled, which rejects an absent, expired, revoked,
    # or wrong-scoped token — a camwall or camera_stream token does NOT open it.
    "/overlay-status",  # /printers/{id}/overlay-status
    # Slicer token-authenticated downloads — protocol handlers (bambustudioopen://,
    # orcaslicer://) cannot send auth headers. These endpoints validate a short-lived
    # download token in the URL path instead.
    "/dl/",  # /archives/{id}/dl/{token}/{filename}, /library/files/{id}/dl/{token}/{filename}
    # Same family, but the segment is "source-dl" — which does NOT contain "/dl/",
    # and these patterns match by substring. Without its own entry the middleware
    # 401s the slicer's header-less request before the route's token check runs,
    # so "Open source 3MF in slicer" failed whenever auth was enabled (#3029).
    "/source-dl/",  # /archives/{id}/source-dl/{token}/{filename}
    # Obico ML API fetches JPEG frames by one-shot nonce (issue #172 follow-up).
    # The nonce itself is the credential: 32-byte random, single-use, ~30s TTL.
    "/obico/cached-frame/",  # /obico/cached-frame/{nonce}
]


_security_headers_logger = logging.getLogger("backend.app.main.security_headers")


def _parse_trusted_frame_origins() -> tuple[str, ...]:
    """Parse TRUSTED_FRAME_ORIGINS env var into a validated allowlist (#1191).

    Format: comma-separated list of ``scheme://host[:port]`` origins.

    Used by ``security_headers_middleware`` to relax ``frame-ancestors`` for
    trusted same-LAN deployments (e.g. Home Assistant Webpage panel embedding
    PrintLab from a different port). Defaults to empty — strict ``'none'``.

    Invalid entries are dropped with a warning rather than failing startup, so
    a typo in one origin doesn't take the whole deployment down.
    """
    raw = os.environ.get("TRUSTED_FRAME_ORIGINS", "").strip()
    if not raw:
        return ()
    valid: list[str] = []
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            parsed = urlparse(candidate)
        except ValueError as e:
            _security_headers_logger.warning("TRUSTED_FRAME_ORIGINS: dropping %r — %s", candidate, e)
            continue
        if parsed.scheme not in ("http", "https"):
            _security_headers_logger.warning("TRUSTED_FRAME_ORIGINS: dropping %r — must be http(s)", candidate)
            continue
        if not parsed.netloc:
            _security_headers_logger.warning("TRUSTED_FRAME_ORIGINS: dropping %r — missing host", candidate)
            continue
        if parsed.path and parsed.path != "/":
            _security_headers_logger.warning("TRUSTED_FRAME_ORIGINS: dropping %r — paths not allowed", candidate)
            continue
        if parsed.query or parsed.fragment:
            _security_headers_logger.warning(
                "TRUSTED_FRAME_ORIGINS: dropping %r — query/fragment not allowed", candidate
            )
            continue
        if "*" in parsed.netloc:
            _security_headers_logger.warning("TRUSTED_FRAME_ORIGINS: dropping %r — wildcards not allowed", candidate)
            continue
        valid.append(f"{parsed.scheme}://{parsed.netloc}")
    if valid:
        _security_headers_logger.info("TRUSTED_FRAME_ORIGINS: %s", ", ".join(valid))
    return tuple(valid)


_TRUSTED_FRAME_ORIGINS: tuple[str, ...] = _parse_trusted_frame_origins()


def _frame_ancestors(default_value: str) -> str:
    """Compose the ``frame-ancestors`` CSP directive (#1191).

    ``default_value`` is the strict directive used when the operator has not
    configured ``TRUSTED_FRAME_ORIGINS`` — typically ``'none'`` (catch-all and
    docs) or ``'self'`` (the streaming overlay, embedded same-origin by the
    Settings URL builder's preview). When trusted origins
    are configured, ``'self'`` is always included so same-origin embedding never
    breaks even if an operator forgets to add their own origin to the list.
    """
    if _TRUSTED_FRAME_ORIGINS:
        return "frame-ancestors 'self' " + " ".join(_TRUSTED_FRAME_ORIGINS) + ";"
    return f"frame-ancestors {default_value};"


# The two Vite-emitted worker assets that compile WebAssembly (#2976). Both
# patterns are anchored on the exact emitted name so the relaxed policies
# below can never apply to any other asset.
#   src/workers/stepPreview.worker.ts -> /assets/stepPreview.worker-<hash>.js
#   pdfjs-dist/legacy/build/pdf.worker.min.mjs?worker&url
#                                     -> /assets/pdf.worker.min-<hash>.js
# Vite also emits a one-line chunk under the second name that only exports the
# worker's URL. The page imports it as a module, and a module script is run
# under the importing document's policy, never its own response's, so it
# matching as well changes nothing.
_STEP_WORKER_ASSET_RE = re.compile(r"^/assets/stepPreview\.worker-[\w-]+\.js$")
_PDF_WORKER_ASSET_RE = re.compile(r"^/assets/pdf\.worker\.min-[\w-]+\.js$")


# PrintLab: Meldungen der Erweiterungs-Endpunkte auf Englisch, wenn die Oberfläche nicht Deutsch ist.
from backend.app.i18n.fork_messages import ForkI18nMiddleware  # noqa: E402

app.add_middleware(ForkI18nMiddleware)


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    """Add standard HTTP security headers to every response."""
    # Per-request nonce stamped into `script-src` (#1460). On its own this
    # changes nothing for PrintLab's own pages — index.html has no inline
    # scripts since the SW registration moved to /sw-register.js. The reason
    # it's here is Cloudflare: a CF-fronted deployment has the bot-detection
    # script injected into the HTML on the edge, with a fresh hash on every
    # load (so hashes can't be allowlisted). When CF sees a nonce in our CSP,
    # it clones the same nonce onto its injected <script>, and the inline
    # script passes the policy without us needing 'unsafe-inline'. See
    # https://developers.cloudflare.com/cloudflare-challenges/challenge-types/javascript-detections/#if-you-have-a-content-security-policy-csp
    csp_nonce = secrets.token_urlsafe(16)
    # Routes that render their own HTML need it too, or their inline script is
    # blocked by the policy below. The outcome-confirmation page (#1898) is the
    # one that does: it submits its own form so a verdict still costs one tap.
    request.state.csp_nonce = csp_nonce
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    # X-Frame-Options is the legacy cross-origin embedding control. Modern
    # browsers honour CSP frame-ancestors instead, and the legacy
    # `ALLOW-FROM <url>` syntax is deprecated and inconsistent across vendors.
    # When operators have explicitly allowlisted trusted frame origins (#1191
    # — typically Home Assistant on a different port), drop X-Frame-Options
    # and let the CSP-side frame-ancestors directive govern embedding.
    if not _TRUSTED_FRAME_ORIGINS:
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Content-Security-Policy for the React SPA.
    # Notes:
    #   - 'unsafe-inline' for style-src: React and UI libs inject inline styles at runtime.
    #   - connect-src ws:/wss:: MQTT/printer WebSocket connections.
    #   - img-src data: / blob:: base64 thumbnails and Blob-URL timelapse previews.
    #   - media-src blob:: timelapse video player uses Blob URLs.
    #   - font-src data:: some icon fonts are embedded as data URIs.
    if request.url.path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        # FastAPI's built-in Swagger UI / ReDoc pages load assets from
        # cdn.jsdelivr.net and bootstrap with an inline <script>, so the
        # default CSP would render a blank page.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
            "connect-src 'self'; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "worker-src 'self' blob:; "
            "object-src 'none'; "
            "base-uri 'self'; " + _frame_ancestors("'none'")
        )
    elif _STEP_WORKER_ASSET_RE.match(request.url.path):
        # The STEP preview worker (#2976) runs OpenCascade compiled to WASM;
        # its emscripten/embind glue generates invoker functions with `new
        # Function(...)`, which needs 'unsafe-eval'. Per CSP3 a dedicated
        # worker is governed by the policy delivered with the WORKER SCRIPT's
        # own response — not the document's — so relaxing it here confines
        # eval to that DOM-less worker context. The document policy below
        # stays nonce-strict, and this response header has no effect when the
        # file is merely fetched (a fetch's CSP is enforced against the
        # requesting document, not the resource's own headers).
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'wasm-unsafe-eval' 'unsafe-eval'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; " + _frame_ancestors("'none'")
        )
    elif _PDF_WORKER_ASSET_RE.match(request.url.path):
        # pdf.js decodes JPEG2000/JBIG2 images and ICC colour with WebAssembly
        # and fetches those modules from /assets/pdfjs/wasm/ (#2976). Same CSP3
        # rule as the STEP worker above: the policy that governs a dedicated
        # worker is the one delivered with its own script, so the wasm compile
        # has to be permitted here rather than on the document. Unlike the STEP
        # worker this one needs no JS eval, so it gets 'wasm-unsafe-eval' only.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'wasm-unsafe-eval'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; " + _frame_ancestors("'none'")
        )
    else:
        # The streaming overlay is embedded same-origin by the URL builder's
        # preview in Settings (#1422), so this branch allows 'self'.
        # Embedding from anywhere else is still refused: 'self'
        # only permits a framer on this origin, which is PrintLab's own UI, so
        # a clickjacking page on another host is blocked exactly as before.
        # (The overlay draws status over a camera feed and its only interactive
        # element is the logo link, so there is nothing to bait a click into
        # even from a same-origin framer.) Cross-origin embedding of the
        # overlay — Home Assistant on another port — remains what
        # TRUSTED_FRAME_ORIGINS is for, and _frame_ancestors already folds that
        # allowlist in.
        #
        # The connected-app consent page (/connect/authorize) gets the same
        # 'self': an app opened from PrintLab's sidebar runs in an iframe, and
        # its "Sign in with PrintLab" navigates that iframe to this page. With
        # 'none' the browser refuses to show it even inside PrintLab. 'self'
        # requires every ancestor to be this origin, so a foreign page -- a
        # sidebar link's site included -- still cannot frame the consent
        # screen to bait a click.
        embeddable_same_origin = request.url.path.startswith("/overlay/") or request.url.path == "/connect/authorize"
        # No 'wasm-unsafe-eval' here: nothing compiles WebAssembly on the main
        # thread. Both wasm consumers — the STEP preview and pdf.js's image
        # decoders (#2976) — run in dedicated workers, which CSP3 governs by
        # the policy served with their own script, so each gets it in its own
        # branch above and the document policy stays as strict as it was.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{csp_nonce}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "connect-src 'self' ws: wss:; "
            "font-src 'self' data:; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-src 'self' http: https:; " + _frame_ancestors("'self'" if embeddable_same_origin else "'none'")
        )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def auth_middleware(request, call_next):
    """Enforce authentication on all API routes when auth is enabled.

    This middleware provides defense-in-depth by checking auth at the API gateway level,
    regardless of whether individual routes have auth dependencies.
    """
    from starlette.responses import JSONResponse

    path = request.url.path

    # Only apply to API routes
    if not path.startswith("/api/"):
        return await call_next(request)

    # Allow public routes
    if path in PUBLIC_API_ROUTES:
        return await call_next(request)

    # Fork: Bei vorgeschriebener Anmeldung (PRINTLAB_REQUIRE_AUTH=1) ist alles gesperrt, solange sie nicht
    # eingerichtet ist, auch die sonst öffentlichen Bilder und Kamera-Adressen (services/fork_startup.py).
    from backend.app.services import fork_startup

    gate = await fork_startup.auth_gate(async_session, path)
    if gate is not None:
        return JSONResponse(status_code=gate[0], content=gate[1])

    # Allow public prefixes
    for prefix in PUBLIC_API_PREFIXES:
        if path.startswith(prefix):
            return await call_next(request)

    # Allow public patterns (read-only display data like thumbnails)
    for pattern in PUBLIC_API_PATTERNS:
        if pattern in path:
            return await call_next(request)

    # Check if auth is enabled. Fail CLOSED on any exception during the
    # probe — GHSA-6mf4-q26m-47pv: the previous fail-open path here let
    # an attacker who could force a DB exception (e.g. file-descriptor
    # exhaustion via login flood) bypass auth on every protected endpoint.
    try:
        async with async_session() as db:
            from backend.app.core.auth import is_auth_enabled

            auth_enabled = await is_auth_enabled(db)

        if not auth_enabled:
            # Auth disabled, allow all requests
            return await call_next(request)
    except Exception:
        logging.getLogger(__name__).exception("auth_middleware: failing closed on auth-probe error from %s", path)
        return JSONResponse(
            status_code=503,
            content={"detail": "Authentication service temporarily unavailable"},
        )

    # Auth is enabled - require valid token
    auth_header = request.headers.get("Authorization")
    x_api_key = request.headers.get("X-API-Key")

    # Check for API key auth first
    if x_api_key or (auth_header and auth_header.startswith("Bearer bb_")):
        # API key authentication - let the request through to be validated by route handler
        # API keys are validated per-route since they have different permission levels
        return await call_next(request)

    # Check for JWT auth
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate JWT token
    import jwt

    try:
        from backend.app.core.auth import (
            ALGORITHM,
            SECRET_KEY,
            _is_token_fresh,
            get_user_by_username,
            is_jti_revoked,
        )

        token = auth_header.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise ValueError("No username in token")
        jti = payload.get("jti")
        if not jti:
            raise ValueError("No jti in token")
        iat = payload.get("iat")

        # Verify user exists, is active, and token is still fresh (L-R8-A).
        # Reject revoked tokens first (defense-in-depth gateway check), reusing
        # this session so the gateway adds a single pooled checkout, not two (#2572).
        async with async_session() as db:
            if await is_jti_revoked(jti, db):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token has been revoked"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            user = await get_user_by_username(db, username)
            if not user or not user.is_active:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "User not found or inactive"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if not _is_token_fresh(iat, user):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token no longer valid"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
    except jwt.ExpiredSignatureError:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token has expired"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (jwt.InvalidTokenError, ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


@app.middleware("http")
async def trace_id_middleware(request, call_next):
    """Stamp every HTTP request with a trace ID and echo it back.

    Decorated AFTER auth_middleware on purpose: Starlette stacks
    @app.middleware decorators LIFO, so the last-decorated runs first
    inbound. Putting the trace stamp last makes it the OUTERMOST layer,
    which means auth-middleware log lines (and every line emitted on the
    way down to and back from the route handler) all carry the same
    trace ID. If we put it before auth, auth's logs would be stamped
    with the *previous* request's ID — useless for correlation.

    Honours an inbound ``X-Trace-Id`` header so callers running their
    own tracing can correlate their span IDs with our log lines, but
    only if the value passes the whitelist gate in
    ``backend.app.core.trace.normalise_inbound_trace_id`` — anything
    rejected (too long, contains control chars, etc.) silently triggers
    a freshly minted server-side ID rather than failing the request.

    The minted (or echoed) ID is set on a ContextVar so that every log
    record emitted during the request — application logs *and* uvicorn's
    access log — carries it via TraceIDFilter, and is also written to
    the ``X-Trace-Id`` response header so clients can pin a server-side
    log search to the exact request they made.
    """
    from backend.app.core.trace import (
        generate_trace_id,
        normalise_inbound_trace_id,
        trace_id_var,
    )

    inbound = normalise_inbound_trace_id(request.headers.get("X-Trace-Id"))
    trace_id = inbound if inbound is not None else generate_trace_id()

    token = trace_id_var.set(trace_id)
    try:
        response = await call_next(request)
    finally:
        # Reset the ContextVar so a record emitted in a totally
        # unrelated background task that just happens to inherit this
        # context doesn't keep referencing this request's ID forever.
        # In practice ContextVar.reset is best-effort under asyncio
        # task-spawn semantics, but the cost is one attribute write so
        # we may as well do it.
        trace_id_var.reset(token)

    response.headers["X-Trace-Id"] = trace_id
    return response


# API routes
app.include_router(auth.router, prefix=app_settings.api_prefix)
app.include_router(mfa.router, prefix=app_settings.api_prefix)
app.include_router(bug_report.router, prefix=app_settings.api_prefix)
app.include_router(users.router, prefix=app_settings.api_prefix)
app.include_router(groups.router, prefix=app_settings.api_prefix)
app.include_router(printers.router, prefix=app_settings.api_prefix)
app.include_router(archives.router, prefix=app_settings.api_prefix)
app.include_router(filaments.router, prefix=app_settings.api_prefix)
app.include_router(finance.router, prefix=app_settings.api_prefix)
app.include_router(inventory.router, prefix=app_settings.api_prefix)
app.include_router(labels.router, prefix=app_settings.api_prefix)
app.include_router(settings_routes.router, prefix=app_settings.api_prefix)
app.include_router(cloud.router, prefix=app_settings.api_prefix)
app.include_router(orca_cloud.router, prefix=app_settings.api_prefix)
app.include_router(local_presets.router, prefix=app_settings.api_prefix)
app.include_router(smart_plugs.router, prefix=app_settings.api_prefix)
app.include_router(ha_sensors.router, prefix=app_settings.api_prefix)
app.include_router(location_ha_sensors.router, prefix=app_settings.api_prefix)
app.include_router(print_log.router, prefix=app_settings.api_prefix)
app.include_router(print_queue.router, prefix=app_settings.api_prefix)
app.include_router(scheduled_dryings.router, prefix=app_settings.api_prefix)
app.include_router(kprofiles.router, prefix=app_settings.api_prefix)
app.include_router(notifications.router, prefix=app_settings.api_prefix)
app.include_router(notification_templates.router, prefix=app_settings.api_prefix)
app.include_router(user_notifications.router, prefix=app_settings.api_prefix)
app.include_router(spoolman.router, prefix=app_settings.api_prefix)
app.include_router(spoolman_inventory.router, prefix=app_settings.api_prefix)
app.include_router(updates.router, prefix=app_settings.api_prefix)
app.include_router(announcements.router, prefix=app_settings.api_prefix)
from backend.app.api.routes import remote_access as remote_access_routes  # noqa: E402

app.include_router(remote_access_routes.router, prefix=app_settings.api_prefix)
app.include_router(maintenance.router, prefix=app_settings.api_prefix)
app.include_router(maintenance_programs.router, prefix=app_settings.api_prefix)
app.include_router(maintenance_print.router, prefix=app_settings.api_prefix)
app.include_router(layer_alerts.router, prefix=app_settings.api_prefix)
app.include_router(part_watcher.router, prefix=app_settings.api_prefix)

# Eigene Router des Forks: Registry statt einzelner Einblendungen (Zeilenbudget),
# siehe api/routes/fork_routers.py — gleiche Pfade, gleiche Reihenfolge.
from backend.app.api.routes.fork_routers import register_fork_routers  # noqa: E402

register_fork_routers(app, app_settings.api_prefix)
app.include_router(camera.router, prefix=app_settings.api_prefix)
app.include_router(camwall.router, prefix=app_settings.api_prefix)
app.include_router(external_links.router, prefix=app_settings.api_prefix)
app.include_router(projects.router, prefix=app_settings.api_prefix)
app.include_router(library.router, prefix=app_settings.api_prefix)
app.include_router(library_tags.router, prefix=app_settings.api_prefix)
app.include_router(library_trash.router, prefix=app_settings.api_prefix)
app.include_router(library_variants.router, prefix=app_settings.api_prefix)
app.include_router(slice_jobs.router, prefix=app_settings.api_prefix)
app.include_router(slicer_pipelines.router, prefix=app_settings.api_prefix)
app.include_router(pipeline_runs.pipeline_run_create_router, prefix=app_settings.api_prefix)
app.include_router(pipeline_runs.pipeline_run_router, prefix=app_settings.api_prefix)
app.include_router(slicer_presets.router, prefix=app_settings.api_prefix)
app.include_router(archive_purge.router, prefix=app_settings.api_prefix)
app.include_router(makerworld.router, prefix=app_settings.api_prefix)
app.include_router(api_keys.router, prefix=app_settings.api_prefix)
app.include_router(connected_apps.router, prefix=app_settings.api_prefix)
app.include_router(webhook.router, prefix=app_settings.api_prefix)
app.include_router(ams_history.router, prefix=app_settings.api_prefix)
app.include_router(printer_sensor_history.router, prefix=app_settings.api_prefix)
app.include_router(system.router, prefix=app_settings.api_prefix)
app.include_router(support.router, prefix=app_settings.api_prefix)
app.include_router(websocket.router, prefix=app_settings.api_prefix)
app.include_router(discovery.router, prefix=app_settings.api_prefix)
app.include_router(pending_uploads.router, prefix=app_settings.api_prefix)
app.include_router(firmware.router, prefix=app_settings.api_prefix)
app.include_router(github_backup.router, prefix=app_settings.api_prefix)
app.include_router(local_backup.router, prefix=app_settings.api_prefix)
app.include_router(obico.router, prefix=app_settings.api_prefix)
app.include_router(metrics.router, prefix=app_settings.api_prefix)
app.include_router(virtual_printers.router, prefix=app_settings.api_prefix)
app.include_router(spoolbuddy.router, prefix=app_settings.api_prefix)


# Die Oberfläche (React-Build), die PWA-Dateien und der Catch-all für den Router liegen in einem eigenen Modul.
from backend.app.api.frontend_routes import register_frontend  # noqa: E402


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Muss zuletzt stehen: Der Catch-all in ``register_frontend`` fängt jeden nicht belegten Pfad ab.
register_frontend(app)
