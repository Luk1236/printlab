"""Verlaufs- und Laufzeitdienste: AMS-Historie, Sensor-Historie, Betriebsstunden.

Aus ``backend/app/main.py`` ausgelagert: drei Schleifen, die alle paar Minuten
Messwerte eintragen, Alarme kuehlen und Laufzeit buchen, samt Zustand und
Start/Stop-Registern. Patchbare Namen greifen weiterhin im Modul ``main`` —
das Modul liest sie ueber :func:`_rt`. Aufrufer und Tests sehen keinen
Unterschied.
"""

import asyncio  # noqa: F401 — Annotationen und CancelledError brauchen die echte Klasse
import json
import logging
import math
from datetime import datetime, timedelta, timezone  # noqa: F401 — Annotation + lokale Nutzung

from sqlalchemy import delete, select

from backend.app.services.print_scheduler import PrintScheduler
from backend.app.utils.ams_drying import is_drying_active, temperature_alarm_suppressed
from backend.app.utils.ams_humidity import ams_humidity_percent
from backend.app.utils.local_time import utcnow_naive

# Der Logger-Name bleibt der der alten Heimat, damit Protokollzeilen in den
# Support-Bundles unverändert unter ``backend.app.main`` auftauchen.
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen.

    ``asyncio``, ``async_session``, ``printer_manager``, ``notification_service``,
    ``_load_ams_drying_latch``, ``_save_ams_drying_latch`` und
    ``AMS_DRYING_GRACE_MINUTES`` werden im Modul ``main`` gepatcht bzw. gehalten;
    ``except asyncio.CancelledError`` braucht die echte Ausnahmeklasse, die
    bleibt deshalb als Import hier.
    """
    import importlib

    return importlib.import_module("backend.app.main")


# AMS sensor history recording
_ams_history_task: asyncio.Task | None = None
AMS_HISTORY_INTERVAL = 300  # Record every 5 minutes
AMS_HISTORY_RETENTION_DAYS = 30  # Keep data for 30 days
_ams_cleanup_counter = 0  # Track recordings to trigger periodic cleanup
# Track alarm cooldowns (printer_id:ams_id:type -> last_alarm_time)
_ams_alarm_cooldown: dict[str, datetime] = {}
AMS_ALARM_COOLDOWN_MINUTES = 60  # Don't send same alarm more than once per hour
# (printer_id, ams_id) already reported as sending the drop index and no
# percentage. Logged once each so a supported printer that turns out to do this
# shows up in a support bundle rather than as a user wondering where the
# humidity reading went -- see the note at the read site below (#3140).
_ams_index_only_logged: set[tuple[int, int]] = set()


def _resolve_temp_alarm_threshold(fair_threshold: float, raw_alarm_value: str | None) -> float:
    """Temperature at which the AMS alarm fires, falling back to the display band.

    ``ams_temp_fair`` decides when the AMS card turns amber. It used to decide
    when a notification was sent as well, which is why a room above it made the
    alarm fire once an hour for as long as the weather lasted -- and the only way
    to stop that was to raise the display band and lose the colour that says the
    unit is warm (#2905).

    Unset resolves to the fair threshold, so an install that never sets one is
    unchanged. Settings storage stringifies ``None`` to the literal ``"None"``,
    so that arrives here as a string and is handled by the same branch as any
    other unparseable value -- there is no separate sentinel to keep in sync.

    A non-positive value is refused rather than honoured: zero would alarm
    permanently, and it is far more likely to be a cleared field than a
    deliberate choice.
    """
    if raw_alarm_value is None:
        return fair_threshold
    try:
        value = float(raw_alarm_value)
    except (TypeError, ValueError):
        return fair_threshold
    if not math.isfinite(value) or value <= 0:
        return fair_threshold
    return value


def _ams_has_filament(ams_data: dict) -> bool:
    """True if this AMS unit has at least one tray slot holding filament.

    Bambu firmware reports loaded slots via `tray_exist_bits`, a per-AMS hex
    bitmap (one bit per tray slot — bit set = spool present). Empty AMS units
    still report sensor readings, but those readings are ambient and not
    actionable: no filament to dry, no humidity to push down. #1619 — gate
    humidity/temperature alarms on this check so empty units don't generate
    hourly noise. Sensor history still records regardless so the UI charts
    stay continuous.

    Fallback path inspects the `tray` array's `tray_type` fields for setups
    where `tray_exist_bits` is missing (some early-connection pushall shapes).
    """
    bits = ams_data.get("tray_exist_bits")
    if isinstance(bits, str) and bits.strip():
        try:
            return int(bits, 16) > 0
        except ValueError:
            pass
    trays = ams_data.get("tray")
    if isinstance(trays, list):
        return any(
            isinstance(t, dict) and isinstance(t.get("tray_type"), str) and t["tray_type"].strip() for t in trays
        )
    return False


async def record_ams_history():
    """Background task to record AMS humidity and temperature data."""

    # Wait a short time for MQTT connections to establish on startup
    await _rt().asyncio.sleep(10)

    while True:
        try:
            from backend.app.models.ams_history import AMSSensorHistory
            from backend.app.models.printer import Printer
            from backend.app.models.settings import Settings

            async with _rt().async_session() as db:
                # Get all active printers
                result = await db.execute(select(Printer).where(Printer.is_active.is_(True)))
                printers = result.scalars().all()

                # Get alarm thresholds from settings
                humidity_threshold = 60.0  # Default: fair threshold
                temp_fair_threshold = 35.0  # Display band default (ams_temp_fair)
                result = await db.execute(select(Settings).where(Settings.key == "ams_humidity_fair"))
                setting = result.scalar_one_or_none()
                if setting:
                    try:
                        humidity_threshold = float(setting.value)
                    except (ValueError, TypeError):
                        pass  # Keep default threshold if stored value is invalid
                result = await db.execute(select(Settings).where(Settings.key == "ams_temp_fair"))
                setting = result.scalar_one_or_none()
                if setting:
                    try:
                        temp_fair_threshold = float(setting.value)
                    except (ValueError, TypeError):
                        pass  # Keep default threshold if stored value is invalid

                # The alarm gets its own threshold, seeded from the resolved fair
                # value so an install that has never set one behaves exactly as
                # it did before (#2905). ams_temp_fair decides when the card turns
                # amber; 35 C is a reasonable place to change a colour and not a
                # reasonable place to page someone. A room above it makes the
                # alarm fire once an hour for as long as the weather lasts, and
                # the only way to stop it was to raise the display band and lose
                # the colour that says the unit is warm.
                #
                # An unset value is stored as the literal "None", which the except
                # below swallows the same way it swallows garbage -- so the
                # fallback costs nothing and needs no sentinel of its own.
                result = await db.execute(select(Settings).where(Settings.key == "ams_temp_alarm"))
                setting = result.scalar_one_or_none()
                temp_alarm_threshold = _resolve_temp_alarm_threshold(
                    temp_fair_threshold, setting.value if setting else None
                )

                # Per-filament humidity threshold overrides (#1605) — resolved
                # per-AMS below from the loaded tray types. Reuses the same
                # resolver as the auto-drying scheduler so behavior stays in
                # lockstep across both consumers.

                per_type_humidity_thresholds: dict[str, int] = {}
                result = await db.execute(select(Settings).where(Settings.key == "ams_humidity_thresholds"))
                setting = result.scalar_one_or_none()
                if setting and setting.value:
                    try:
                        raw = json.loads(setting.value)
                        if isinstance(raw, dict):
                            for k, v in raw.items():
                                try:
                                    per_type_humidity_thresholds[str(k).upper() if k != "default" else "default"] = int(
                                        v
                                    )
                                except (TypeError, ValueError):
                                    continue
                    except (ValueError, TypeError):
                        pass  # Invalid JSON → no overrides, fall through to global threshold

                # Per-AMS drying latch (#1802), loaded once per pass and written
                # back below only if a unit changed it.
                drying_latch = await _rt()._load_ams_drying_latch(db)
                drying_latch_before = dict(drying_latch)

                recorded_count = 0
                for printer in printers:
                    # Get current state from printer manager
                    state = _rt().printer_manager.get_status(printer.id)
                    if not state or not state.connected or not state.raw_data:
                        continue  # Skip disconnected printers - don't use stale data

                    raw_data = state.raw_data
                    if "ams" not in raw_data or not isinstance(raw_data["ams"], list):
                        continue

                    # Record data for each AMS unit
                    for ams_data in raw_data["ams"]:
                        ams_id = int(ams_data.get("id", 0))

                        # Percentage only. The 1-5 index is inverted, so
                        # charting it as a percentage drew the wettest units as
                        # the driest (#3140); a unit that reports no percentage
                        # leaves a gap in the chart instead. See
                        # utils/ams_humidity.
                        humidity = ams_humidity_percent(ams_data)

                        # No supported printer is known to send the index
                        # alone -- the report came from unsupported firmware,
                        # and no install has been seen using the old fallback.
                        # "Known" is doing work there, so say so once per unit:
                        # the alternative is a silent blank card.
                        if humidity is None and ams_data.get("humidity") is not None:
                            unit_key = (printer.id, ams_id)
                            if unit_key not in _ams_index_only_logged:
                                _ams_index_only_logged.add(unit_key)
                                logger.info(
                                    "[%s] AMS %d reports the 1-5 humidity index but no usable humidity_raw "
                                    "percentage. The index is inverted and is not shown as a percentage "
                                    "(#3140), so this unit has no humidity reading, chart or alarm. "
                                    "Please report this with the printer and AMS firmware versions.",
                                    printer.name,
                                    ams_id,
                                )

                        # Get temperature
                        temperature = None
                        temp_str = ams_data.get("temp")
                        if temp_str is not None:
                            try:
                                temperature = float(temp_str)
                            except (ValueError, TypeError):
                                pass  # Skip unparseable temperature value

                        # Skip if no data
                        if humidity is None and temperature is None:
                            continue

                        # Record the data point
                        history = AMSSensorHistory(
                            printer_id=printer.id,
                            ams_id=ams_id,
                            humidity=humidity,
                            # Both columns hold the same reading now that the
                            # index can no longer reach ``humidity``. Writing it
                            # through the same value also stops a genuine 0%
                            # from being stored as NULL, which the old truthiness
                            # test did.
                            humidity_raw=humidity,
                            temperature=temperature,
                        )
                        db.add(history)
                        recorded_count += 1

                        # Generate AMS label and determine if it's AMS-HT (A, B, C, D or HT-A for AMS-Lite/Hub)
                        is_ams_ht = ams_id >= 128
                        if is_ams_ht:
                            ams_label = f"HT-{chr(65 + (ams_id - 128))}"
                        else:
                            ams_label = f"AMS-{chr(65 + ams_id)}"

                        # Skip alarm dispatch for empty AMS units — humidity /
                        # temperature readings are ambient with no filament to
                        # protect, and the hourly notification just becomes
                        # noise. Sensor history was already recorded above so
                        # the UI charts stay continuous (#1619). Per-AMS check
                        # so a multi-AMS setup with one loaded + one empty
                        # still alarms on the loaded unit.
                        if not _ams_has_filament(ams_data):
                            continue

                        # Resolve per-filament humidity threshold for this AMS
                        # unit (#1605). Falls back to the global ams_humidity_fair
                        # when no per-type overrides are configured.
                        trays = ams_data.get("tray", []) or []
                        effective_humidity_threshold = float(
                            PrintScheduler.resolve_humidity_threshold(
                                trays, per_type_humidity_thresholds, int(humidity_threshold)
                            )
                        )

                        # Check humidity alarm (only if above threshold)
                        if humidity is not None and humidity > effective_humidity_threshold:
                            cooldown_key = f"{printer.id}:{ams_id}:humidity"
                            last_alarm = _ams_alarm_cooldown.get(cooldown_key)
                            now = _rt().datetime.now(_rt().timezone.utc)
                            if (
                                last_alarm is None
                                or (now - last_alarm).total_seconds() >= AMS_ALARM_COOLDOWN_MINUTES * 60
                            ):
                                _ams_alarm_cooldown[cooldown_key] = now
                                logger.info(
                                    f"Sending humidity alarm for {printer.name} {ams_label}: {humidity}% > {effective_humidity_threshold}%"
                                )
                                try:
                                    # Call different notification method based on AMS type
                                    if is_ams_ht:
                                        await _rt().notification_service.on_ams_ht_humidity_high(
                                            printer.id,
                                            printer.name,
                                            ams_label,
                                            humidity,
                                            effective_humidity_threshold,
                                            db,
                                        )
                                    else:
                                        await _rt().notification_service.on_ams_humidity_high(
                                            printer.id,
                                            printer.name,
                                            ams_label,
                                            humidity,
                                            effective_humidity_threshold,
                                            db,
                                        )
                                except Exception as e:
                                    logger.warning("Failed to send humidity alarm: %s", e)

                        # A drying cycle heats the unit far past ams_temp_fair on
                        # purpose — 45 C for PLA, 65 C for PETG, 85 C on an
                        # AMS-HT, against a 35 C default — so the alarm fired
                        # once an hour for the whole cycle and kept firing while
                        # the unit cooled back down (#1802). Latch on the
                        # firmware's own drying state and hold until the reading
                        # returns to normal. Humidity is deliberately left alone:
                        # it falls during drying, which is the whole point.
                        latch_key = f"{printer.id}:{ams_id}"
                        # The latch releases at `threshold`, so it takes the alarm
                        # number too. Handing it the display band would strand the
                        # latch on any unit that settles back above it -- a room
                        # where the AMS rests at 37.7 C never returns under a 35 C
                        # band, so the latch could only expire on the grace cap
                        # rather than releasing when the unit had actually cooled.
                        suppress_temp_alarm, new_latch = temperature_alarm_suppressed(
                            drying_active=is_drying_active(ams_data),
                            temperature=temperature,
                            threshold=temp_alarm_threshold,
                            latched_at=drying_latch.get(latch_key),
                            now=_rt().datetime.now(_rt().timezone.utc),
                            grace_minutes=_rt().AMS_DRYING_GRACE_MINUTES,
                        )
                        if new_latch is None:
                            drying_latch.pop(latch_key, None)
                        else:
                            drying_latch[latch_key] = new_latch

                        # Check temperature alarm (only if above threshold)
                        if temperature is not None and temperature > temp_alarm_threshold and not suppress_temp_alarm:
                            cooldown_key = f"{printer.id}:{ams_id}:temperature"
                            last_alarm = _ams_alarm_cooldown.get(cooldown_key)
                            now = _rt().datetime.now(_rt().timezone.utc)
                            if (
                                last_alarm is None
                                or (now - last_alarm).total_seconds() >= AMS_ALARM_COOLDOWN_MINUTES * 60
                            ):
                                _ams_alarm_cooldown[cooldown_key] = now
                                logger.info(
                                    f"Sending temperature alarm for {printer.name} {ams_label}: "
                                    f"{temperature}°C > {temp_alarm_threshold}°C"
                                )
                                try:
                                    # Call different notification method based on AMS type
                                    if is_ams_ht:
                                        # The reported threshold has to be the one
                                        # that fired, or the message says "> 35 °C"
                                        # while firing at 45.
                                        await _rt().notification_service.on_ams_ht_temperature_high(
                                            printer.id, printer.name, ams_label, temperature, temp_alarm_threshold, db
                                        )
                                    else:
                                        await _rt().notification_service.on_ams_temperature_high(
                                            printer.id, printer.name, ams_label, temperature, temp_alarm_threshold, db
                                        )
                                except Exception as e:
                                    logger.warning("Failed to send temperature alarm: %s", e)

                if drying_latch != drying_latch_before:
                    await _rt()._save_ams_drying_latch(db, drying_latch)

                await db.commit()
                if recorded_count > 0:
                    logger.info("Recorded %s AMS sensor history entries", recorded_count)

                # Periodic cleanup of old data (every ~288 recordings = ~24 hours at 5min interval)
                global _ams_cleanup_counter
                _ams_cleanup_counter += 1
                if _ams_cleanup_counter >= 288:
                    _ams_cleanup_counter = 0
                    # Get retention days from settings
                    from backend.app.models.settings import Settings

                    result = await db.execute(select(Settings).where(Settings.key == "ams_history_retention_days"))
                    setting = result.scalar_one_or_none()
                    retention_days = int(setting.value) if setting else AMS_HISTORY_RETENTION_DAYS

                    cutoff = utcnow_naive() - timedelta(days=retention_days)
                    result = await db.execute(delete(AMSSensorHistory).where(AMSSensorHistory.recorded_at < cutoff))
                    await db.commit()
                    if result.rowcount > 0:
                        logger.info(
                            f"Cleaned up {result.rowcount} old AMS sensor history entries (older than {retention_days} days)"
                        )

            # Wait until next recording interval
            await _rt().asyncio.sleep(AMS_HISTORY_INTERVAL)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("AMS history recording failed: %s", e)
            await _rt().asyncio.sleep(60)  # Wait a bit before retrying


def start_ams_history_recording():
    """Start the AMS history recording background task."""
    global _ams_history_task
    if _ams_history_task is None:
        _ams_history_task = _rt().asyncio.create_task(record_ams_history())
        logger.info("AMS history recording started")


def stop_ams_history_recording():
    """Stop the AMS history recording background task."""
    global _ams_history_task
    if _ams_history_task:
        _ams_history_task.cancel()
        _ams_history_task = None
        logger.info("AMS history recording stopped")


# Printer sensor history recording (nozzle / bed / chamber)
_printer_sensor_history_task: asyncio.Task | None = None
PRINTER_SENSOR_HISTORY_INTERVAL = 60  # Record every minute — heaters move faster than AMS humidity
PRINTER_SENSOR_HISTORY_RETENTION_DAYS = 30
_printer_sensor_cleanup_counter = 0
# Sensor kinds tracked in state.temperatures — these are the normalised keys the
# MQTT parser writes, so we don't need to handle per-model field aliases here
# (nozzle_temper / left_nozzle_temper / right_nozzle_temper / chamber_temper
# are all collapsed by services/bambu_mqtt.py before they reach this loop).
_SENSOR_KINDS = ("nozzle", "nozzle_2", "bed", "chamber")
_SENSOR_TARGET_KEYS = {
    "nozzle": "nozzle_target",
    "nozzle_2": "nozzle_2_target",
    "bed": "bed_target",
    "chamber": "chamber_target",
}


async def record_printer_sensor_history():
    """Background task to record nozzle / bed / chamber readings.

    Pulls from `state.temperatures` (already normalised across all printer
    models by the MQTT parser) rather than re-parsing raw_data, so we get
    free coverage of dual-nozzle H2D, sensor-only X1C chamber, etc.
    """

    await _rt().asyncio.sleep(10)

    while True:
        try:
            from backend.app.models.printer import Printer
            from backend.app.models.printer_sensor_history import PrinterSensorHistory
            from backend.app.models.settings import Settings

            async with _rt().async_session() as db:
                result = await db.execute(select(Printer).where(Printer.is_active.is_(True)))
                printers = result.scalars().all()

                recorded_count = 0
                for printer in printers:
                    state = _rt().printer_manager.get_status(printer.id)
                    if not state or not state.connected:
                        continue

                    temps = getattr(state, "temperatures", None) or {}
                    if not isinstance(temps, dict):
                        continue

                    for kind in _SENSOR_KINDS:
                        if kind not in temps:
                            continue
                        try:
                            value = float(temps[kind])
                        except (ValueError, TypeError):
                            continue

                        target_raw = temps.get(_SENSOR_TARGET_KEYS[kind])
                        target_val: float | None = None
                        if target_raw is not None:
                            try:
                                target_val = float(target_raw)
                            except (ValueError, TypeError):
                                target_val = None

                        db.add(
                            PrinterSensorHistory(
                                printer_id=printer.id,
                                sensor_kind=kind,
                                value=value,
                                target=target_val,
                            )
                        )
                        recorded_count += 1

                await db.commit()
                if recorded_count > 0:
                    logger.debug("Recorded %s printer sensor history entries", recorded_count)

                # Periodic cleanup — once every ~24h at this interval.
                global _printer_sensor_cleanup_counter
                _printer_sensor_cleanup_counter += 1
                cleanup_every = max(1, (24 * 60 * 60) // PRINTER_SENSOR_HISTORY_INTERVAL)
                if _printer_sensor_cleanup_counter >= cleanup_every:
                    _printer_sensor_cleanup_counter = 0
                    result = await db.execute(
                        select(Settings).where(Settings.key == "printer_sensor_history_retention_days")
                    )
                    setting = result.scalar_one_or_none()
                    retention_days = int(setting.value) if setting else PRINTER_SENSOR_HISTORY_RETENTION_DAYS

                    cutoff = utcnow_naive() - timedelta(days=retention_days)
                    cleanup = await db.execute(
                        delete(PrinterSensorHistory).where(PrinterSensorHistory.recorded_at < cutoff)
                    )
                    await db.commit()
                    if cleanup.rowcount > 0:
                        logger.info(
                            "Cleaned up %s old printer sensor history entries (older than %s days)",
                            cleanup.rowcount,
                            retention_days,
                        )

            await _rt().asyncio.sleep(PRINTER_SENSOR_HISTORY_INTERVAL)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Printer sensor history recording failed: %s", e)
            await _rt().asyncio.sleep(60)


def start_printer_sensor_history_recording():
    global _printer_sensor_history_task
    if _printer_sensor_history_task is None:
        _printer_sensor_history_task = _rt().asyncio.create_task(record_printer_sensor_history())
        logger.info("Printer sensor history recording started")


def stop_printer_sensor_history_recording():
    global _printer_sensor_history_task
    if _printer_sensor_history_task:
        _printer_sensor_history_task.cancel()
        _printer_sensor_history_task = None
        logger.info("Printer sensor history recording stopped")


# Printer runtime tracking
_runtime_tracking_task: asyncio.Task | None = None
RUNTIME_TRACKING_INTERVAL = 30  # Update every 30 seconds


async def track_printer_runtime():
    """Background task to track printer active runtime (RUNNING state only).

    PAUSE is intentionally excluded — the runtime counter feeds hours-based
    maintenance intervals (rod lubrication, belt checks, nozzle cleaning)
    which track mechanical wear. Pause time has no motion and no wear, so
    counting it inflates maintenance warnings (#1521).
    """

    # Wait for MQTT connections to establish on startup
    await _rt().asyncio.sleep(15)

    while True:
        try:
            from backend.app.models.printer import Printer

            # Fetch printer IDs in a short-lived read-only session
            async with _rt().async_session() as db:
                result = await db.execute(
                    select(Printer.id, Printer.name, Printer.runtime_seconds, Printer.last_runtime_update).where(
                        Printer.is_active.is_(True)
                    )
                )
                printer_rows = result.all()

            now = _rt().datetime.now(_rt().timezone.utc)
            updated_count = 0

            # Update each printer in its own short session to minimise write-lock
            # hold time and avoid blocking critical commits like queue status
            # updates (#897).
            for pid, pname, runtime_secs, last_update in printer_rows:
                state = _rt().printer_manager.get_status(pid)
                if not state:
                    logger.debug("[%s] Runtime tracking: no state available", pname)
                    continue
                if not state.connected:
                    logger.debug("[%s] Runtime tracking: not connected", pname)
                    continue

                needs_commit = False
                new_runtime = runtime_secs
                new_last_update = last_update

                if state.state == "RUNNING":
                    if last_update:
                        lu = last_update if last_update.tzinfo else last_update.replace(tzinfo=_rt().timezone.utc)
                        elapsed = (now - lu).total_seconds()
                        if elapsed > 0:
                            new_runtime = runtime_secs + int(elapsed)
                            updated_count += 1
                            needs_commit = True
                            logger.debug(
                                f"[{pname}] Runtime tracking: added {int(elapsed)}s, "
                                f"total={new_runtime}s ({new_runtime / 3600:.2f}h)"
                            )
                    else:
                        needs_commit = True
                        logger.debug("[%s] Runtime tracking: first active detection", pname)
                    new_last_update = now
                else:
                    if last_update is not None:
                        logger.debug(f"[{pname}] Runtime tracking: state={state.state}, clearing last_runtime_update")
                        new_last_update = None
                        needs_commit = True

                if needs_commit:
                    try:
                        async with _rt().async_session() as db:
                            result = await db.execute(select(Printer).where(Printer.id == pid))
                            printer = result.scalar_one_or_none()
                            if printer:
                                printer.runtime_seconds = new_runtime
                                printer.last_runtime_update = new_last_update
                                await db.commit()
                    except Exception as e:
                        logger.warning("[%s] Runtime tracking commit failed: %s", pname, e)

            if updated_count > 0:
                logger.debug("Updated runtime for %s printer(s)", updated_count)

        except asyncio.CancelledError:
            logger.info("Runtime tracking cancelled")
            break
        except Exception as e:
            logger.warning("Runtime tracking failed: %s", e)

        await _rt().asyncio.sleep(RUNTIME_TRACKING_INTERVAL)


def start_runtime_tracking():
    """Start the printer runtime tracking background task."""
    global _runtime_tracking_task
    if _runtime_tracking_task is None:
        _runtime_tracking_task = _rt().asyncio.create_task(track_printer_runtime())
        logger.info("Printer runtime tracking started")


def stop_runtime_tracking():
    """Stop the printer runtime tracking background task."""
    global _runtime_tracking_task
    if _runtime_tracking_task:
        _runtime_tracking_task.cancel()
        _runtime_tracking_task = None
        logger.info("Printer runtime tracking stopped")
