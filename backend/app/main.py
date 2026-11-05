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
from backend.app.services.completion_photo_plate import (  # noqa: F401 — Namensraum bleibt hier
    _PLATE_PARK_DROP_MM,
    _PLATE_RESTORE_CLEARANCE_MM,
    _PLATE_RESTORE_FEEDRATE,
    _PLATE_RESTORE_SETTLE_SECONDS,
    _apply_camera_rotation,
    _capture_snapshot_for_notification,
    _max_z_for_current_print,
    _maybe_bank_inprint_frame,
    _park_plate_after_finish_photo,
    _plate_restore_is_blocked_by_queue,
    _restore_plate_for_finish_photo,
    on_finish_photo_moment,
)
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
from backend.app.services.mqtt_print_complete import (  # noqa: F401 — Namensraum bleibt hier
    on_print_complete,
)
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
from backend.app.services.print_complete_flow import (  # noqa: F401 — Namensraum bleibt hier
    _completion_belongs_to_queue_item,
    _compute_run_filament_grams,
    _dispatch_outcome_confirmation_safely,
    _dispatch_user_print_email,
    _finish_photo_for_notification,
    _is_active_archive_stale,
    _normalise_subtask_name,
    _partial_progress_scale,
    _recover_fallback_from_cache_before_eviction,
    _restore_usage_tracking_session,
    _scope_notification_archive_data_to_plate,
    _subtask_name_from_filename,
    _subtask_names_match,
    dispatch_outcome_confirmation,
    on_print_running_observed,
    reconcile_stale_active_prints,
)
from backend.app.services.print_cost_estimate import plate_scoped_run_estimate as _plate_scoped_run_estimate
from backend.app.services.print_scheduler import scheduler as print_scheduler
from backend.app.services.print_start_flow import (  # noqa: F401 — Namensraum bleibt hier
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
from backend.app.services.printer_telemetry_flow import (  # noqa: F401 — Namensraum bleibt hier
    calibrate_snapshot,
    on_assignment_verified,
    on_bed_temp_update,
    on_drying_complete,
    on_layer_change,
    on_print_progress,
    on_tray_change,
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


# Retry ladder for a fallback archive created while the printer's FTPS cool-off
# was running (#2957). The cool-off is 300s, so the first attempt is placed just
# past it; the second covers a handshake that failed again on the way back and
# armed a fresh one. Module-level so tests can shrink them.
_FALLBACK_3MF_RETRY_DELAYS_SECONDS: tuple[float, ...] = (310.0, 620.0)

# Retry ladder for the other temporary give-up: the file service answered and
# the transfer still did not finish, which at print start is usually the printer
# serving MQTT, the camera and a job upload at the same time (#3063). Nothing has
# to expire here, so the first attempt comes early -- #3063's reporter had the
# same 19MB file complete 48 seconds after the download budget ran out. The later
# two cover a printer that stays busy well into the print.
_FALLBACK_3MF_TRANSFER_RETRY_DELAYS_SECONDS: tuple[float, ...] = (60.0, 240.0, 600.0)


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


# How long `_background_finish_photo` waits for this producer. Must cover the
# settle window plus a worst-case RTSP grab (15s), and stay below the
# notification path's own photo wait so a slow producer degrades to a
# photo-less notification rather than a missed one.
_FINISH_PHOTO_PRODUCER_WAIT_SECONDS = _PLATE_RESTORE_SETTLE_SECONDS + 23.0


# How the printer marks a subtask name it had to cut short. Observed on real
# hardware at ~100 characters, but the cut-off is not a fixed character count
# (a name with multibyte characters came back at 98), so match the marker
# rather than a length.
_SUBTASK_TRUNCATION_MARKER = "..."


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

    # Register printer telemetry callbacks
    printer_manager.set_layer_change_callback(on_layer_change)
    printer_manager.set_print_progress_callback(on_print_progress)
    printer_manager.set_bed_temp_update_callback(on_bed_temp_update)
    printer_manager.set_drying_complete_callback(on_drying_complete)
    printer_manager.set_assignment_verified_callback(on_assignment_verified)
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
    # Permissions-Policy (best practices): die Weboberfläche braucht keine der
    # mächtigen Browser-APIs selbst — Kamerabilder kommen als MJPEG/Blob-Streams
    # bzw. Snapshots aus dem Netzwerk, nicht über getUserMedia; das Mikrofon und
    # Geo­lokation haben keinen Anwendungsfall. Voll restriktiv statt offen.
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
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
