"""Übertragung und Zustellung des Druckplaners.

Fortschritts-Brücke für den Datei-Upload, Wartezeiten nach abgelehnten
Uploads und die Wahl der Platte. Aus ``print_scheduler.py`` ausgelagert;
die Namen werden dort weiterhin importiert.
"""

import asyncio
import logging
import time
import zipfile
from pathlib import Path

from backend.app.core.websocket import ws_manager
from backend.app.services.bambu_ftp import FtpFailureKind
from backend.app.utils.threemf_tools import default_plate_number, select_plate_gcode_name

logger = logging.getLogger(__name__)


# Dispatch-toast progress throttling (#1625 follow-up). Mirrors the legacy
# background_dispatch.py upload_progress_callback (200 ms time gate + 256 KB
# byte gate) from before the scheduler unification. Time gate keeps small
# files from going silent (a single 8 KB chunk fires once and that's it);
# byte gate caps the broadcast rate on slow LAN where 200 ms covers many
# chunks. uploaded >= total always emits so the bar closes cleanly even on
# sub-200 ms files.
_DISPATCH_PROGRESS_BYTE_STEP = 256 * 1024
_DISPATCH_PROGRESS_MIN_INTERVAL_SECS = 0.2


class _UploadProgressBridge:
    """Thread-safe bridge from ``upload_file_async`` to the WS broadcaster.

    ``upload_file_async`` runs the FTP transfer in an executor thread and
    invokes its ``progress_callback`` from that thread, so the callback
    body cannot ``await`` directly. This bridge captures the asyncio loop
    at construction (on the scheduler thread) and uses
    ``run_coroutine_threadsafe`` to hop back. The byte/time throttle
    matches the legacy background_dispatch.py path 1:1 so the toast feels
    identical to the pre-#1625 experience.

    Failures inside the emit are swallowed — progress is a UX nicety, the
    upload itself must not fail because of a WS hiccup.
    """

    def __init__(self, user_id: int | None, queue_item_id: int):
        self._user_id = user_id
        self._queue_item_id = queue_item_id
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._last_emit_bytes = 0
        self._last_emit_monotonic = 0.0
        self._has_emitted = False

    def __call__(self, bytes_transferred: int, total_bytes: int) -> None:
        if self._loop is None or total_bytes <= 0:
            return
        now = time.monotonic()
        # Mirrors legacy bg-dispatch: emit if first call OR upload complete
        # OR 200 ms elapsed OR ≥256 KB transferred since last emit. Two of
        # the four matter most: first-call so the user sees something even
        # for sub-chunk-size files; uploaded >= total so the bar locks at
        # 100% even when the throttle would otherwise eat it.
        should_emit = (
            not self._has_emitted
            or bytes_transferred >= total_bytes
            or now - self._last_emit_monotonic >= _DISPATCH_PROGRESS_MIN_INTERVAL_SECS
            or bytes_transferred - self._last_emit_bytes >= _DISPATCH_PROGRESS_BYTE_STEP
        )
        if not should_emit:
            return
        self._has_emitted = True
        self._last_emit_bytes = bytes_transferred
        self._last_emit_monotonic = now
        try:
            asyncio.run_coroutine_threadsafe(
                ws_manager.send_queue_item_upload_progress(
                    user_id=self._user_id,
                    queue_item_id=self._queue_item_id,
                    bytes_transferred=bytes_transferred,
                    total_bytes=total_bytes,
                ),
                self._loop,
            )
        except Exception:
            pass  # progress is best-effort, never block the upload


# Bambu firmware states that mean the project_file has actually been accepted
# and the printer is now processing / running / paused mid-print. Used by the
# dispatch watchdog (#1370): a transition into one of these states means the
# print landed, anything else (e.g. FINISH -> IDLE after the user dismisses
# a post-print prompt) is NOT a valid "command landed" signal even though the
# state value did change. SLICING is included because some firmwares park
# briefly in SLICING between PREPARE and RUNNING while parsing the g-code.
_ACTIVE_PRINT_STATES: frozenset[str] = frozenset({"PREPARE", "SLICING", "RUNNING", "PAUSE"})

# How many times the start-watchdog may revert an item to 'pending' before it
# gives up and fails the row instead (#2555). Each attempt costs a full 3MF
# re-upload plus the watchdog's wait, so a wedged printer left to retry forever
# both never recovers and starves the other printers of dispatch slots. Three
# is chosen to clear the transient causes the watchdog already recovers from —
# a lost MQTT publish on a half-broken session (#887/#936) is fixed by the
# force-reconnect on the very next attempt — while still bounding the loop.
DISPATCH_MAX_ATTEMPTS = 3

# Upload failures that mean the file never reached the printer's storage: the
# file service refused or never answered (#3210). These put the item back in
# the queue instead of failing it, because nothing about the job is wrong --
# and failing it left the printer idle, so the next pass handed it the next
# item, which failed the same way. One P2S whose file service was out of
# connection slots ate 43 queued jobs in ten minutes that way.
#
# Not here: AUTH (a wrong access code needs the user), STORAGE (a full or
# missing card does too), NOT_FOUND (a PrintLab-side path problem), UNKNOWN,
# and an upload that overran its deadline -- each of those would fail the same
# way on every retry.
_UPLOAD_REQUEUE_KINDS: frozenset[FtpFailureKind] = frozenset(
    {FtpFailureKind.HANDSHAKE, FtpFailureKind.COOLOFF, FtpFailureKind.TIMEOUT, FtpFailureKind.NETWORK}
)

# How long a printer whose upload was put back stays out of dispatch (#3210).
# The first window matches the FTP client's own handshake cool-off, so the
# retry lands after the client would talk to the printer again anyway. Each
# further refusal in a row doubles it, up to the cap: #3210's printer refused
# for some 40 hours, and every retry costs a preheat cycle where preheat is on,
# five connection attempts and a page of log. A successful upload resets it.
UPLOAD_FAILURE_BACKOFF_SECONDS = 300
UPLOAD_FAILURE_BACKOFF_MAX_SECONDS = 3600


def _upload_backoff_seconds(refusals: int) -> int:
    """Backoff after the *refusals*-th refused upload in a row (1-based)."""
    return min(UPLOAD_FAILURE_BACKOFF_SECONDS * 2 ** max(refusals - 1, 0), UPLOAD_FAILURE_BACKOFF_MAX_SECONDS)


def _effective_plate_id(explicit_plate_id: int | None, file_path: Path) -> int:
    """The plate to dispatch, resolved once in ``_start_print`` and reused at
    every call site below it: G-code injection, usage registration, rack-plan
    lookup, slot-extruder lookup, the external-spool check, and the actual
    print command.

    A positive explicit ``plate_id`` on the queue item always wins. A
    non-positive one is treated as "not set" and resolved from the archive,
    the way the rest of the queue code already reads it (``if item.plate_id:``
    in ``api/routes/print_queue.py``): the schemas put no lower bound on the
    field, and passing a 0 straight through would build a print command for
    ``Metadata/plate_0.gcode``, which is the same wedge this function exists
    to prevent. The ``item.plate_id or 1`` this replaced mapped 0 to 1.

    Falling back to a bare ``1`` instead of reading the archive assumes a
    single-plate file's one G-code is numbered 1, which only holds for a
    plate exported on its own: one cut out of a larger project keeps its
    ORIGINAL plate number, so a printer asked to print "plate 1" of a file
    whose only G-code is ``plate_2.gcode`` accepts the command, can't find
    the file, throws an HMS error, and sits wedged in IDLE until
    power-cycled (#2947).

    The call sites agreed on a fallback only by accident before this:
    with G-code injection on, ``inject_gcode_into_3mf`` already falls back to
    the archive's own default plate internally whenever the plate id it's
    handed isn't in the file, so it could silently inject into a different
    plate than the one the print command itself asked for.

    Falls back to 1 when the archive can't be read, holds no G-code member at
    all, or its default member doesn't follow the ``plate_N`` naming
    convention (a slicer that doesn't use it has no number to dispatch).

    An explicit plate the archive doesn't hold is logged and then sent
    anyway. It wedges the printer exactly like #2947 did, but redirecting it
    to a plate that is in the file would print a model nobody asked for,
    which is the worse of the two.
    """
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            names = zf.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        logger.warning(
            "Dispatch plate: cannot read %s (%s), so the archive's own plate numbering "
            "is unavailable; dispatching plate %s",
            file_path,
            exc,
            explicit_plate_id if explicit_plate_id is not None and explicit_plate_id > 0 else 1,
        )
        names = None

    if explicit_plate_id is not None and explicit_plate_id > 0:
        if (
            names is not None
            and default_plate_number(names) is not None
            and select_plate_gcode_name(names, explicit_plate_id) is None
        ):
            logger.warning(
                "Dispatch plate: %s was queued for plate %s but holds no G-code for it "
                "(it has %s). Sending plate %s as asked; expect the printer to reject the "
                "file, since printing a different plate would print the wrong model (#2947)",
                file_path,
                explicit_plate_id,
                ", ".join(sorted(n for n in names if n.endswith(".gcode"))),
                explicit_plate_id,
            )
        return explicit_plate_id

    resolved = default_plate_number(names) if names is not None else None
    return resolved if resolved is not None else 1
