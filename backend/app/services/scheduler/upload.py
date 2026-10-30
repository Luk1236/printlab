"""Übertragung der Druckdatei an den Drucker (FTP) für den Druckplaner.

Aus ``print_scheduler._start_print`` ausgelagert: vorhandene Datei löschen,
Fortschritts-Toast, Upload mit oder ohne Wiederholung, und die Übersetzung des
Fehlers in den Satz, den die Warteschlange anzeigt.

Was *nach* der Übertragung mit dem Auftrag geschieht — Status schreiben,
Benachrichtigung, erneutes Einreihen bei Ablehnung — bleibt beim Planer. Hier
geht es nur um die Leitung zum Drucker; deshalb bekommt die Funktion keine
Datenbank, sondern gibt ein Ergebnis zurück.

Die Tests patchen die Namen im Modul ``print_scheduler``
(``delete_file_async``, ``upload_file_async``, ``get_ftp_retry_settings``,
``ws_manager``). Sie werden deshalb über das Fassadenmodul aufgelöst, nicht über
eigene Importe — sonst liefen die Attrappen ins Leere.
"""

import importlib
import logging
from dataclasses import dataclass
from pathlib import Path

from backend.app.models.printer import Printer
from backend.app.services.bambu_ftp import (
    FtpFailureReport,
    UploadCancelled,
    describe_upload_failure,
    with_ftp_retry,
)
from backend.app.services.scheduler.dispatch import _UPLOAD_REQUEUE_KINDS
from backend.app.utils.filename import derive_remote_filename

logger = logging.getLogger("backend.app.services.print_scheduler")  # ein Logger für den ganzen Planer


def _rt():
    """Das Fassadenmodul, damit Patches an ``print_scheduler.<name>`` greifen."""
    return importlib.import_module("backend.app.services.print_scheduler")


@dataclass(slots=True)
class UploadOutcome:
    """Ergebnis der Übertragung — alles, was der Planer danach braucht.

    ``refused`` unterscheidet „der Drucker hat die Datei abgelehnt" (busy, keine
    SD-Karte, kein Platz: erneut einreihen, mit Backoff) von einem echten
    Fehlschlag, der den Auftrag scheitern lässt. ``error_message`` ist bereits
    der fertige Satz für Karte und Push — beide zeigen dasselbe (#2899).

    ``ftp_timeout`` ist die Zeitgrenze, die diese Übertragung benutzt hat. Der
    Planer braucht sie, wenn er die Datei später wieder entfernt.
    """

    remote_filename: str
    remote_path: str
    uploaded: bool
    ftp_timeout: float
    error_message: str | None = None
    refused: bool = False


async def deliver_file(
    *,
    printer: Printer,
    queue_item_id: int,
    user_id: int | None,
    file_path: Path,
    filename: str,
) -> UploadOutcome:
    """Die Datei auf den Drucker legen (Wurzelverzeichnis, nicht ``/cache/``).

    ``start_print`` verweist nur auf den Dateinamen (``ftp://{filename}``), die
    Datei muss also im Wurzelverzeichnis liegen. Der Rückgabewert sagt, ob sie
    dort angekommen ist, und wenn nicht, warum.
    """
    rt = _rt()

    remote_filename = derive_remote_filename(filename)
    remote_path = f"/{remote_filename}"

    # Get FTP retry settings
    ftp_retry_enabled, ftp_retry_count, ftp_retry_delay, ftp_timeout = await rt.get_ftp_retry_settings()

    logger.info(
        f"Queue item {queue_item_id}: FTP upload starting - printer={printer.name} ({printer.model}), "
        f"ip={printer.ip_address}, file={remote_filename}, local_path={file_path}, "
        f"retry_enabled={ftp_retry_enabled}, retry_count={ftp_retry_count}, timeout={ftp_timeout}"
    )

    # Delete existing file if present (avoids 553 error on overwrite)
    try:
        logger.debug("Queue item %s: Deleting existing file %s if present...", queue_item_id, remote_path)
        delete_result = await rt.delete_file_async(
            printer.ip_address,
            printer.access_code,
            remote_path,
            socket_timeout=ftp_timeout,
            printer_model=printer.model,
            # This delete and the upload below are one bounded, user-initiated
            # unit -- at most nine connections -- so neither skips on the
            # handshake cool-off the opportunistic sweeps rely on. In #2898's
            # trace this delete took the TLS failure and armed the cool-off,
            # and the upload's four attempts were then spent against it
            # without a socket being opened.
            respect_handshake_cooloff=False,
        )
        logger.debug("Queue item %s: Delete result: %s", queue_item_id, delete_result)
    except Exception as e:
        logger.debug("Queue item %s: Delete failed (may not exist): %s", queue_item_id, e)

    # Dispatch toast — announce the upload start with the total byte count so
    # the frontend can render an honest progress bar.
    toast_file_name = filename.replace(".gcode.3mf", "").replace(".3mf", "")
    try:
        total_bytes = file_path.stat().st_size
    except OSError:
        total_bytes = 0
    try:
        await rt.ws_manager.send_queue_item_uploading(
            user_id=user_id,
            queue_item_id=queue_item_id,
            printer_id=printer.id,
            printer_name=printer.name,
            file_name=toast_file_name,
            total_bytes=total_bytes,
        )
    except Exception:
        pass  # toast is best-effort

    progress_bridge = rt._UploadProgressBridge(user_id, queue_item_id)

    # A deadline expiry gets its own message: "check your SD card" is the wrong
    # advice for a link that was simply too slow to finish (#2529).
    upload_error: str | None = None

    # Why the upload failed, straight from the client rather than inferred.
    # Owned here, so a background fetch for another print cannot overwrite it
    # between the failure and the sentence built from it (#2899).
    upload_failure = FtpFailureReport()

    try:
        if ftp_retry_enabled:
            uploaded = await with_ftp_retry(
                rt.upload_file_async,
                printer.ip_address,
                printer.access_code,
                file_path,
                remote_path,
                socket_timeout=ftp_timeout,
                printer_model=printer.model,
                progress_callback=progress_bridge,
                respect_handshake_cooloff=False,
                failure=upload_failure,
                max_retries=ftp_retry_count,
                retry_delay=ftp_retry_delay,
                operation_name=f"Upload print to {printer.name}",
            )
        else:
            uploaded = await rt.upload_file_async(
                printer.ip_address,
                printer.access_code,
                file_path,
                remote_path,
                socket_timeout=ftp_timeout,
                printer_model=printer.model,
                progress_callback=progress_bridge,
                respect_handshake_cooloff=False,
                failure=upload_failure,
            )
    except UploadCancelled as e:
        uploaded = False
        upload_error = (
            "Upload was too slow to finish and was cancelled. The printer's connection could not sustain "
            "the transfer — check its Wi-Fi signal, or move it closer to the access point."
        )
        logger.error("Queue item %s: upload deadline exceeded: %s", queue_item_id, e)
    except Exception as e:
        uploaded = False
        logger.error("Queue item %s: FTP error: %s (type: %s)", queue_item_id, e, type(e).__name__)

    if uploaded:
        return UploadOutcome(
            remote_filename=remote_filename,
            remote_path=remote_path,
            uploaded=True,
            ftp_timeout=ftp_timeout,
        )

    # This used to be one string for every upload failure, telling everyone to
    # check the SD card. The client knows which of seven things went wrong and
    # logs each one differently; it just had no way to say so here, so the card
    # got named even for a TLS handshake that never reached the printer's
    # filesystem (#2899).
    failure = upload_failure.failure
    error_message = upload_error or describe_upload_failure(failure)
    refused = upload_error is None and failure is not None and failure.kind in _UPLOAD_REQUEUE_KINDS
    return UploadOutcome(
        remote_filename=remote_filename,
        remote_path=remote_path,
        uploaded=False,
        ftp_timeout=ftp_timeout,
        error_message=error_message,
        refused=refused,
    )
