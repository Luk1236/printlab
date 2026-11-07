"""Background services, connections and shutdown routines for the application lifespan.

Part of Welle 11 refactoring: extracts MQTT connection setup, background workers,
schedulers, watchdog lifecycle and clean shutdown from backend/app/main.py.

All monkeypatchable targets (like init_printer_connections, spawn_background_task,
async_session) are accessed dynamically via _rt() to preserve test suite compatibility.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Any

from sqlalchemy import select, text

logger = logging.getLogger(__name__)


def _rt() -> Any:
    """Return the runtime ``backend.app.main`` module.

    Tests monkeypatch targets on ``backend.app.main`` (e.g. ``async_session``,
    ``init_printer_connections``, ``spawn_background_task``, ``printer_manager``).
    Late lookup via ``_rt()`` ensures those patches take effect even though
    the orchestration lives in this service.
    """
    return importlib.import_module("backend.app.main")


# Module-level holder for the shared cloud HTTP client (httpx.AsyncClient)
_shared_cloud_http_client: Any = None


async def setup_cloud_http_clients() -> Any:
    """Register an app-scoped httpx client for Bambu Cloud, MakerWorld, and Orca Cloud.

    Reuses the same connection pool across requests to avoid socket exhaustion
    and reduce TLS handshakes.
    """
    global _shared_cloud_http_client
    import httpx

    from backend.app.services.bambu_cloud import set_shared_http_client
    from backend.app.services.model_providers.makerworld.service import (
        set_shared_http_client as set_shared_makerworld_http_client,
    )
    from backend.app.services.orca_cloud import (
        set_shared_http_client as set_shared_orca_http_client,
    )

    _shared_cloud_http_client = httpx.AsyncClient(timeout=30.0)
    set_shared_http_client(_shared_cloud_http_client)
    set_shared_makerworld_http_client(_shared_cloud_http_client)
    set_shared_orca_http_client(_shared_cloud_http_client)
    return _shared_cloud_http_client


async def close_cloud_http_clients() -> None:
    """Unset and close the app-scoped httpx client."""
    global _shared_cloud_http_client
    from backend.app.services.bambu_cloud import set_shared_http_client
    from backend.app.services.model_providers.makerworld.service import (
        set_shared_http_client as set_shared_makerworld_http_client,
    )
    from backend.app.services.orca_cloud import (
        set_shared_http_client as set_shared_orca_http_client,
    )

    set_shared_http_client(None)
    set_shared_makerworld_http_client(None)
    set_shared_orca_http_client(None)
    if _shared_cloud_http_client is not None:
        await _shared_cloud_http_client.aclose()
        _shared_cloud_http_client = None


async def run_startup_fixups() -> None:
    """Run non-critical startup database fixups.

    - Backfill batch statuses for legacy completed batches (#342)
    - Fix queue items stuck with invalid 'aborted' status -> 'cancelled'
    """
    rt = _rt()
    try:
        from backend.app.services.print_batch import backfill_batch_statuses

        async with rt.async_session() as batch_db:
            await backfill_batch_statuses(batch_db)
    except Exception as exc:
        logger.warning("[BATCH] Startup status backfill failed: %s", exc)

    try:
        async with rt.async_session() as db:
            from backend.app.models.print_queue import PrintQueueItem

            result = await db.execute(select(PrintQueueItem).where(PrintQueueItem.status == "aborted"))
            aborted_items = result.scalars().all()
            if aborted_items:
                for item in aborted_items:
                    item.status = "cancelled"
                await db.commit()
                logger.info("Fixed %d queue item(s) with invalid 'aborted' status → 'cancelled'", len(aborted_items))
    except Exception as e:
        logger.warning("Failed to fix aborted queue items: %s", e)


async def setup_printer_manager_callbacks() -> None:
    """Set event loop, callbacks, and restore awaiting-plate-clear on printer manager."""
    rt = _rt()
    loop = asyncio.get_event_loop()
    rt.printer_manager.set_event_loop(loop)
    rt.printer_manager.set_status_change_callback(rt.on_printer_status_change)
    rt.printer_manager.set_print_start_callback(rt.on_print_start)
    rt.printer_manager.set_print_complete_callback(rt.on_print_complete)
    rt.printer_manager.set_print_running_observed_callback(rt.on_print_running_observed)
    rt.printer_manager.set_finish_photo_moment_callback(rt.on_finish_photo_moment)
    rt.printer_manager.set_ams_change_callback(rt.on_ams_change)
    rt.printer_manager.set_fts_inlet_change_callback(rt.on_fts_inlet_change)

    # Rehydrate persisted awaiting-plate-clear gate (#961) so prompts survive restarts
    await rt.printer_manager.load_awaiting_plate_clear_from_db()

    # Register printer telemetry callbacks
    rt.printer_manager.set_layer_change_callback(rt.on_layer_change)
    rt.printer_manager.set_print_progress_callback(rt.on_print_progress)
    rt.printer_manager.set_bed_temp_update_callback(rt.on_bed_temp_update)
    rt.printer_manager.set_drying_complete_callback(rt.on_drying_complete)
    rt.printer_manager.set_assignment_verified_callback(rt.on_assignment_verified)
    rt.printer_manager.set_tray_change_callback(rt.on_tray_change)


async def setup_mqtt_and_connections() -> None:
    """Initialize MQTT relay, restore MQTT plugs, connect printers and Spoolman."""
    rt = _rt()

    # Initialize MQTT relay from settings
    async with rt.async_session() as db:
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
        await rt.mqtt_relay.configure(mqtt_settings)

        # Restore MQTT smart plug subscriptions
        if mqtt_settings.get("mqtt_enabled"):
            from backend.app.models.smart_plug import SmartPlug
            from backend.app.services.mqtt_smart_plug import subscribe_plug_to_mqtt

            result = await db.execute(select(SmartPlug).where(SmartPlug.plug_type == "mqtt"))
            mqtt_plugs = result.scalars().all()
            restored = 0
            for plug in mqtt_plugs:
                if subscribe_plug_to_mqtt(rt.mqtt_relay.smart_plug_service, plug):
                    restored += 1
            if restored:
                logger.info("Restored %s MQTT smart plug subscriptions", restored)

    # Connect to all active printers
    async with rt.async_session() as db:
        await rt.init_printer_connections(db)

    # Auto-connect to Spoolman if enabled
    async with rt.async_session() as db:
        from backend.app.api.routes.settings import get_setting

        spoolman_enabled = await get_setting(db, "spoolman_enabled")
        spoolman_url = await get_setting(db, "spoolman_url")

        if spoolman_enabled and spoolman_enabled.lower() == "true" and spoolman_url:
            try:
                client = await rt.init_spoolman_client(spoolman_url)
                if await client.health_check():
                    logger.info("Auto-connected to Spoolman at %s", spoolman_url)
                    field_ok = await client.ensure_tag_extra_field()
                    if not field_ok:
                        logger.error("Spoolman tag extra field registration failed — NFC tag links may not persist")
                    for field_name in ("bambu_slicer_filament", "bambu_slicer_filament_name"):
                        if not await client.ensure_extra_field(field_name):
                            logger.warning(
                                "Spoolman extra field %r registration failed — "
                                "spool slicer-preset edits will return 502",
                                field_name,
                            )
                else:
                    logger.warning("Spoolman at %s is not reachable", spoolman_url)
            except Exception as e:
                logger.warning("Failed to auto-connect to Spoolman: %s", e)


async def start_background_services() -> None:
    """Start schedulers, background workers, watchdogs and virtual printers."""
    rt = _rt()

    # Start the print scheduler
    rt.spawn_background_task(rt.print_scheduler.run(), name="print-scheduler")
    from backend.app.services import queue_due_watch

    rt.spawn_background_task(queue_due_watch.run(rt.async_session), name="queue-due-watch")
    from backend.app.services import invoice_reminder

    rt.spawn_background_task(invoice_reminder.run(rt.async_session), name="invoice-reminder")
    from backend.app.services import countermeasures

    rt.spawn_background_task(countermeasures.run(), name="countermeasures")
    from backend.app.services import local_ai_watch

    rt.spawn_background_task(local_ai_watch.run(), name="local-ai-watch")
    from backend.app.services import slicer_cache

    rt.spawn_background_task(slicer_cache.run_slicer_cache_watchdog(), name="slicer-cache-watchdog")

    # Start the smart plug scheduler for time-based on/off
    rt.smart_plug_manager.start_scheduler()

    # Start the Home Assistant sensor poller (#1148)
    rt.ha_sensor_manager.start()
    rt.location_ha_sensor_manager.start()

    # Resume any pending auto-offs that were interrupted by restart
    await rt.smart_plug_manager.resume_pending_auto_offs()

    # Start the notification digest scheduler
    rt.notification_service.start_digest_scheduler()

    # Start the Telegram reaction pollers (#3046)
    try:
        await rt.telegram_reaction_poller.start()
    except Exception as e:
        logger.warning("Telegram reaction poller did not start: %s", e)

    # Start backup schedulers
    await rt.github_backup_service.start_scheduler()
    await rt.local_backup_service.start_scheduler()
    await rt.obico_detection_service.start()

    # Start trash / purge sweepers
    await rt.library_trash_service.start_scheduler()
    await rt.archive_purge_service.start_scheduler()

    # Start telemetry & watchdog loops
    rt.start_ams_history_recording()
    rt.start_printer_sensor_history_recording()
    rt.start_runtime_tracking()
    rt.start_spoolbuddy_watchdog()
    rt.start_camera_cleanup()
    rt.start_connection_watchdog()

    # One-shot sweep for timelapse session directories orphaned by crash/restart
    try:
        from backend.app.services.layer_timelapse import cleanup_orphaned_timelapse_sessions

        removed = cleanup_orphaned_timelapse_sessions()
        if removed:
            logger.info("Removed %d orphaned timelapse session artifact(s)", removed)
    except Exception as e:
        logger.warning("Orphaned timelapse session cleanup failed: %s", e)

    # Start expected-print TTL eviction
    rt.start_expected_prints_cleanup()

    # Periodic auth cleanup
    rt.start_auth_cleanup()

    # Maintainer announcements
    from backend.app.services import announcements as announcements_service

    announcements_service.start()

    from backend.app.services.printer_media import start_printer_download_cleanup

    start_printer_download_cleanup()

    # Event-loop stall watchdog (#1486)
    from backend.app.services.loop_watchdog import start_loop_watchdog

    start_loop_watchdog()

    # Initialize virtual printer manager and sync from DB
    from backend.app.services.virtual_printer import virtual_printer_manager

    virtual_printer_manager.set_session_factory(rt.async_session)
    virtual_printer_manager.set_printer_manager(rt.printer_manager)
    try:
        await virtual_printer_manager.sync_from_db()
        logger.info("Virtual printer manager synced from database")
    except Exception as e:
        logger.warning("Failed to sync virtual printers: %s", e)

    # Fernzugriff (Tailscale) wieder herstellen
    from backend.app.services import remote_access as remote_access_service

    asyncio.create_task(remote_access_service.autostart())


async def stop_background_services() -> None:
    """Stop all background workers, schedulers, watchdogs, close connections, and dispose engine."""
    rt = _rt()

    from backend.app.services import remote_access as remote_access_service

    remote_access_service.stop_daemon()
    rt.print_scheduler.stop()
    rt.smart_plug_manager.stop_scheduler()
    rt.ha_sensor_manager.stop()
    rt.location_ha_sensor_manager.stop()
    rt.notification_service.stop_digest_scheduler()
    await rt.telegram_reaction_poller.aclose()
    rt.github_backup_service.stop_scheduler()
    rt.local_backup_service.stop_scheduler()
    rt.library_trash_service.stop_scheduler()
    rt.archive_purge_service.stop_scheduler()
    rt.obico_detection_service.stop()
    rt.stop_ams_history_recording()
    rt.stop_printer_sensor_history_recording()
    rt.stop_runtime_tracking()
    rt.stop_spoolbuddy_watchdog()
    rt.stop_camera_cleanup()
    rt.stop_connection_watchdog()

    from backend.app.services.loop_watchdog import stop_loop_watchdog

    stop_loop_watchdog()

    try:
        from backend.app.services.camera_fanout import shutdown_all_broadcasters

        await shutdown_all_broadcasters()
    except Exception as e:
        logger.warning("Failed to shut down camera broadcasters: %s", e)

    rt.stop_expected_prints_cleanup()
    rt.stop_auth_cleanup()

    from backend.app.services import announcements as announcements_service

    announcements_service.stop()

    from backend.app.services.printer_media import stop_printer_download_cleanup

    await stop_printer_download_cleanup()
    rt.printer_manager.disconnect_all()
    from backend.app.services import slot_unlink_grace

    slot_unlink_grace.reset()
    await rt.close_spoolman_client()

    from backend.app.services.virtual_printer import virtual_printer_manager

    await virtual_printer_manager.stop_all()

    await rt.mqtt_smart_plug_service.disconnect(timeout=2)
    await rt.mqtt_relay.disconnect(timeout=2)

    await close_cloud_http_clients()

    # Checkpoint WAL (SQLite only) and close all database connections
    from backend.app.core.db_dialect import is_sqlite

    if is_sqlite():
        try:
            async with rt.engine.begin() as conn:
                await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            logger.info("WAL checkpoint completed")
        except Exception as e:
            logger.warning("WAL checkpoint failed: %s", e)
    await rt.engine.dispose()
