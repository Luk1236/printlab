"""Pre-dispatch build plate empty check for print scheduler.

Safeguards against starting prints when the build plate is occupied,
preventing nozzle collisions and print failures.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from backend.app.models.printer import Printer
    from backend.app.models.print_queue import PrintQueueItem

logger = logging.getLogger(__name__)


async def check_queue_plate_clear(
    printer: Printer,
    item: PrintQueueItem,
    db: AsyncSession,
) -> tuple[bool, str | None]:
    """Check build plate emptiness before queue print dispatch if enabled.

    Returns:
        (is_clear, reason_if_blocked)
    """
    if not getattr(printer, "plate_detection_enabled", False):
        return True, None

    logger.info("Checking build plate for printer %s before dispatching queue item %s", printer.name, item.id)

    roi = None
    if printer.plate_detection_roi_x is not None and printer.plate_detection_roi_w is not None:
        roi = (
            float(printer.plate_detection_roi_x or 0.0),
            float(printer.plate_detection_roi_y or 0.0),
            float(printer.plate_detection_roi_w or 1.0),
            float(printer.plate_detection_roi_h or 1.0),
        )

    try:
        from backend.app.services.plate_detection import check_plate_empty

        result = await check_plate_empty(
            printer_id=printer.id,
            ip_address=printer.ip_address,
            access_code=printer.access_code,
            model=printer.model,
            external_camera_url=printer.external_camera_url,
            external_camera_type=printer.external_camera_type,
            use_external=bool(printer.external_camera_enabled),
            roi=roi,
            external_camera_snapshot_url=printer.external_camera_snapshot_url,
            include_debug_image=True,
        )
    except Exception as exc:
        logger.warning("Plate detection check failed for printer %s: %s", printer.id, exc)
        return True, None

    # If needs calibration, do not block dispatch
    if result.needs_calibration:
        logger.info("Plate detection needs calibration for printer %s - skipping check", printer.id)
        return True, None

    if not result.is_empty:
        reason = f"Objekt auf Druckbett erkannt ({result.difference_percent:.1f}% Differenz)"
        logger.warning(
            "Plate check BLOCKED queue item %s on printer %s: %s (diff: %s%%)",
            item.id,
            printer.name,
            result.message,
            result.difference_percent,
        )

        from backend.app.services.printer_manager import printer_manager
        printer_manager.set_awaiting_plate_clear(printer.id, True)

        try:
            from backend.app.services.notification_service import notification_service

            await notification_service.on_plate_not_empty(
                printer_id=printer.id,
                printer_name=printer.name or f"Drucker {printer.id}",
                db=db,
                difference_percent=result.difference_percent,
                image_data=result.debug_image,
            )
        except Exception:
            logger.debug("Could not send plate_not_empty notification", exc_info=True)

        return False, reason

    return True, None
