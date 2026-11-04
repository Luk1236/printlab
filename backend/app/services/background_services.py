"""Hintergrundwaechter und periodische Aufraeumer von main.py ausgelagert.

Enthalten: der SpoolBuddy-Waechter, der Verbindungswaechter fuer tote
MQTT-Sitzungen (#2732), das Aufraeumen der Kamera-Stromreste und die
staendliche Auth-Aufraeumrunde. Jeder Dienst besteht aus Zustand, Loop und
Start/Stop-Registern — die lifespan bleibt im ``main``-Modul und rueft die
Register dort, wo ihre Namen weiter liegen (Re-Export). Patchbare Namen
greift das Modul ueber :func:`_rt`; ``except asyncio.CancelledError``
braucht die echte Ausnahmeklasse und bleibt deshalb direkt importiert.
"""

import asyncio  # noqa: F401 — Annotationen und CancelledError brauchen die echte Klasse
import logging
from datetime import timedelta

from sqlalchemy import delete, select

# Der Logger-Name bleibt der der alten Heimat, damit Protokollzeilen in den
# Support-Bundles unverändert unter ``backend.app.main`` auftauchen.
logger = logging.getLogger("backend.app.main")


def _rt():
    """Das Fassadenmodul, damit Patches an ``backend.app.main.<name>`` greifen."""
    import importlib

    return importlib.import_module("backend.app.main")


# SpoolBuddy device watchdog
_spoolbuddy_watchdog_task: asyncio.Task | None = None
SPOOLBUDDY_WATCHDOG_INTERVAL = 15


async def _spoolbuddy_watchdog_loop():
    """Periodic check for SpoolBuddy devices that have gone offline."""
    from backend.app.api.routes.spoolbuddy import spoolbuddy_watchdog

    while True:
        try:
            await spoolbuddy_watchdog()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("SpoolBuddy watchdog failed: %s", e)
        await _rt().asyncio.sleep(SPOOLBUDDY_WATCHDOG_INTERVAL)


def start_spoolbuddy_watchdog():
    global _spoolbuddy_watchdog_task
    if _spoolbuddy_watchdog_task is None:
        _spoolbuddy_watchdog_task = _rt().asyncio.create_task(_spoolbuddy_watchdog_loop())
        logger.info("SpoolBuddy watchdog started")


def stop_spoolbuddy_watchdog():
    global _spoolbuddy_watchdog_task
    if _spoolbuddy_watchdog_task:
        _spoolbuddy_watchdog_task.cancel()
        _spoolbuddy_watchdog_task = None
        logger.info("SpoolBuddy watchdog stopped")


# Dead-MQTT-session recovery
#
# check_staleness() guards the "connected but silent" half-broken session. It
# does nothing once ``state.connected`` is False, and paho's own auto-reconnect
# is the only thing left watching at that point. When paho stops making
# progress there is no backstop at all: the #2732 bundle has a P1S drop on a
# keep-alive timeout at 02:19 and not reconnect until 11:24 — nine hours
# offline with the UI open the whole time, recovered only when something
# happened to nudge it.
#
# This loop is that backstop. It only touches printers that had a working
# session and lost it, and only when the MQTT port still answers — a printer
# that is simply switched off is left to paho, since rebuilding a client
# against an unreachable host achieves nothing and would fill the log every
# night.
_connection_watchdog_task: asyncio.Task | None = None
CONNECTION_WATCHDOG_INTERVAL = 60
# How long a printer must have been silent before we stop trusting paho.
# Comfortably above STALE_TIMEOUT (60 s) and the max reconnect backoff (30 s),
# so a session that is recovering on its own is never interrupted.
CONNECTION_WATCHDOG_OFFLINE_GRACE = 300
# Per-printer floor between rebuild attempts.
CONNECTION_WATCHDOG_RETRY_INTERVAL = 300
_connection_watchdog_last_attempt: dict[int, float] = {}


async def _recover_dead_printer_sessions() -> int:
    """Rebuild MQTT clients that have been offline too long to still be trying.

    Returns the number of printers a rebuild was attempted for (for tests and
    for the caller's logging). Never raises: one unreachable printer must not
    stop the sweep for the rest of the farm.
    """
    from backend.app.services.printer_diagnostic import PORT_MQTT, check_port

    now = _rt().time.monotonic()
    recovered = 0

    for printer_id, client in list(_rt().printer_manager._clients.items()):
        try:
            if client.state.connected:
                _connection_watchdog_last_attempt.pop(printer_id, None)
                continue

            # Time since the last inbound message is the age of the last known
            # good session — no extra bookkeeping needed, and it is the same
            # clock is_stale() reads. 0 means this client has never had one:
            # that is the initial-connect path, where paho retrying is the
            # correct and only behaviour, so leave it be.
            last_msg = client._last_message_time
            if not last_msg:
                continue
            offline_for = _rt().time.time() - last_msg
            if offline_for < CONNECTION_WATCHDOG_OFFLINE_GRACE:
                continue

            last_attempt = _connection_watchdog_last_attempt.get(printer_id)
            if last_attempt is not None and now - last_attempt < CONNECTION_WATCHDOG_RETRY_INTERVAL:
                continue

            if not await check_port(client.ip_address, PORT_MQTT):
                # Switched off, unplugged, or off the network. Paho's retry is
                # the right handler; say so at debug level and move on.
                logger.debug(
                    "[#2732] Printer %s offline for %.0fs and its MQTT port is not answering "
                    "— leaving the reconnect to paho",
                    printer_id,
                    offline_for,
                )
                _connection_watchdog_last_attempt[printer_id] = now
                continue

            _connection_watchdog_last_attempt[printer_id] = now
            recovered += 1
            logger.warning(
                "[#2732] Printer %s has been offline for %.0fs but answers on MQTT port %d — "
                "rebuilding the client with a fresh session (last connect error: %s)",
                printer_id,
                offline_for,
                PORT_MQTT,
                client.last_connect_error or "none recorded",
            )
            # Async context, so this takes the hard-reset path: fresh client_id,
            # paho's QoS 1 queue dropped. That matters — a project_file left
            # unacked on the dead session would otherwise replay into the new
            # one and trip 0500_4003 on the printer (#1136).
            client.force_reconnect_stale_session(f"offline for {offline_for:.0f}s, port still answering")
        except Exception as e:
            logger.warning("[#2732] Connection watchdog failed for printer %s: %s", printer_id, e)

    return recovered


async def _connection_watchdog_loop():
    # Let the initial connects settle before judging anyone offline.
    await _rt().asyncio.sleep(CONNECTION_WATCHDOG_OFFLINE_GRACE)
    while True:
        try:
            await _recover_dead_printer_sessions()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Connection watchdog sweep failed: %s", e)
        await _rt().asyncio.sleep(CONNECTION_WATCHDOG_INTERVAL)


def start_connection_watchdog():
    global _connection_watchdog_task
    if _connection_watchdog_task is None:
        _connection_watchdog_task = _rt().asyncio.create_task(_connection_watchdog_loop())
        logger.info("Printer connection watchdog started")


def stop_connection_watchdog():
    global _connection_watchdog_task
    if _connection_watchdog_task:
        _connection_watchdog_task.cancel()
        _connection_watchdog_task = None
        _connection_watchdog_last_attempt.clear()
        logger.info("Printer connection watchdog stopped")


# Camera stream orphan cleanup
_camera_cleanup_task: asyncio.Task | None = None
CAMERA_CLEANUP_INTERVAL = 60


async def _camera_cleanup_loop():
    """Periodically clean up orphaned ffmpeg processes."""
    from backend.app.api.routes.camera import cleanup_orphaned_streams

    while True:
        try:
            await cleanup_orphaned_streams()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Camera stream cleanup failed: %s", e)
        await _rt().asyncio.sleep(CAMERA_CLEANUP_INTERVAL)


def start_camera_cleanup():
    global _camera_cleanup_task
    if _camera_cleanup_task is None:
        _camera_cleanup_task = _rt().asyncio.create_task(_camera_cleanup_loop())
        logger.info("Camera stream cleanup started")


def stop_camera_cleanup():
    global _camera_cleanup_task
    if _camera_cleanup_task:
        _camera_cleanup_task.cancel()
        _camera_cleanup_task = None
        logger.info("Camera stream cleanup stopped")


# ---------------------------------------------------------------------------
# L-2: Periodic auth-token cleanup (stale TOTP + expired revoked JTIs)
# ---------------------------------------------------------------------------

_auth_cleanup_task: asyncio.Task | None = None
_AUTH_CLEANUP_INTERVAL = 3600  # seconds (hourly)


async def _run_auth_cleanup() -> None:
    """Single cleanup pass: remove stale TOTP records, expired revoked JTIs, and old rate-limit events."""
    from backend.app.models.auth_ephemeral import AuthEphemeralToken, AuthRateLimitEvent
    from backend.app.models.user_totp import UserTOTP

    now = _rt().datetime.now(_rt().timezone.utc)

    # Remove unconfirmed (is_enabled=False) TOTP records older than 1 hour.
    try:
        async with _rt().async_session() as db:
            stale_cutoff = now - timedelta(hours=1)
            result = await db.execute(
                select(UserTOTP).where(
                    UserTOTP.is_enabled.is_(False),
                    UserTOTP.created_at < stale_cutoff,
                )
            )
            stale_records = result.scalars().all()
            if stale_records:
                for rec in stale_records:
                    await db.delete(rec)
                await db.commit()
                logging.info("Auth cleanup: removed %d stale unconfirmed TOTP record(s)", len(stale_records))
    except Exception as e:
        logging.warning("Auth cleanup: failed to purge stale TOTP records: %s", e)

    # Remove expired revoked-JTI entries (they are no longer needed once the
    # original token's exp has passed — the token would be rejected by JWT
    # signature verification regardless).
    try:
        async with _rt().async_session() as db:
            await db.execute(
                delete(AuthEphemeralToken).where(
                    AuthEphemeralToken.token_type == "revoked_jti",
                    AuthEphemeralToken.expires_at < now,
                )
            )
            await db.commit()
    except Exception as e:
        logging.warning("Auth cleanup: failed to purge expired revoked JTIs: %s", e)

    # L-R6-B: Purge AuthRateLimitEvent rows older than the lockout window (15 min).
    # Events outside this window can never affect rate-limit decisions — they only
    # consume DB space.  Use the same window constant as the rate limiter so the
    # two are always in sync.
    try:
        from backend.app.api.routes.mfa import LOCKOUT_WINDOW

        async with _rt().async_session() as db:
            await db.execute(
                delete(AuthRateLimitEvent).where(
                    AuthRateLimitEvent.occurred_at < now - LOCKOUT_WINDOW,
                )
            )
            await db.commit()
    except Exception as e:
        logging.warning("Auth cleanup: failed to purge stale rate-limit events: %s", e)


async def _auth_cleanup_loop() -> None:
    """Periodic background task: run auth cleanup every hour."""
    while True:
        try:
            await _run_auth_cleanup()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.warning("Auth cleanup loop error: %s", e)
        await _rt().asyncio.sleep(_AUTH_CLEANUP_INTERVAL)


def start_auth_cleanup() -> None:
    global _auth_cleanup_task
    if _auth_cleanup_task is None:
        _auth_cleanup_task = _rt().asyncio.create_task(_auth_cleanup_loop())
        logger.info("Auth periodic cleanup started")


def stop_auth_cleanup() -> None:
    global _auth_cleanup_task
    if _auth_cleanup_task:
        _auth_cleanup_task.cancel()
        _auth_cleanup_task = None
        logger.info("Auth periodic cleanup stopped")
