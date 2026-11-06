"""Unit tests for automated queue plate empty check."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.app.services.queue_plate_check import check_queue_plate_clear


class FakePrinter:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.name = kwargs.get("name", "X1 Carbon")
        self.ip_address = kwargs.get("ip_address", "192.168.1.100")
        self.access_code = kwargs.get("access_code", "12345678")
        self.model = kwargs.get("model", "X1C")
        self.plate_detection_enabled = kwargs.get("plate_detection_enabled", True)
        self.external_camera_enabled = kwargs.get("external_camera_enabled", False)
        self.external_camera_url = kwargs.get("external_camera_url", None)
        self.external_camera_type = kwargs.get("external_camera_type", None)
        self.external_camera_snapshot_url = kwargs.get("external_camera_snapshot_url", None)
        self.plate_detection_roi_x = kwargs.get("plate_detection_roi_x", None)
        self.plate_detection_roi_y = kwargs.get("plate_detection_roi_y", None)
        self.plate_detection_roi_w = kwargs.get("plate_detection_roi_w", None)
        self.plate_detection_roi_h = kwargs.get("plate_detection_roi_h", None)


class FakeQueueItem:
    def __init__(self, item_id=42, file_name="benchy.gcode.3mf"):
        self.id = item_id
        self.file_name = file_name


class FakeDetectionResult:
    def __init__(self, is_empty=True, difference_percent=0.0, needs_calibration=False, message="Empty"):
        self.is_empty = is_empty
        self.difference_percent = difference_percent
        self.needs_calibration = needs_calibration
        self.message = message
        self.debug_image = b"fake_img"


@pytest.mark.asyncio
async def test_plate_check_disabled():
    printer = FakePrinter(plate_detection_enabled=False)
    item = FakeQueueItem()
    db = MagicMock()

    is_clear, reason = await check_queue_plate_clear(printer, item, db)
    assert is_clear is True
    assert reason is None


@pytest.mark.asyncio
async def test_plate_check_clear():
    printer = FakePrinter(plate_detection_enabled=True)
    item = FakeQueueItem()
    db = MagicMock()

    res = FakeDetectionResult(is_empty=True, difference_percent=0.5)
    with patch("backend.app.services.plate_detection.check_plate_empty", AsyncMock(return_value=res)):
        is_clear, reason = await check_queue_plate_clear(printer, item, db)
        assert is_clear is True
        assert reason is None


@pytest.mark.asyncio
async def test_plate_check_needs_calibration_does_not_block():
    printer = FakePrinter(plate_detection_enabled=True)
    item = FakeQueueItem()
    db = MagicMock()

    res = FakeDetectionResult(is_empty=False, needs_calibration=True)
    with patch("backend.app.services.plate_detection.check_plate_empty", AsyncMock(return_value=res)):
        is_clear, reason = await check_queue_plate_clear(printer, item, db)
        assert is_clear is True
        assert reason is None


@pytest.mark.asyncio
async def test_plate_check_blocked_when_object_detected():
    printer = FakePrinter(plate_detection_enabled=True, plate_detection_roi_x=0.1, plate_detection_roi_w=0.8)
    item = FakeQueueItem()
    db = MagicMock()

    res = FakeDetectionResult(is_empty=False, difference_percent=24.5, message="Object found")
    with patch("backend.app.services.plate_detection.check_plate_empty", AsyncMock(return_value=res)), \
         patch("backend.app.services.printer_manager.printer_manager.set_awaiting_plate_clear") as mock_set_awaiting, \
         patch("backend.app.services.notification_service.notification_service.on_plate_not_empty", AsyncMock()) as mock_notif:

        is_clear, reason = await check_queue_plate_clear(printer, item, db)
        assert is_clear is False
        assert "Objekt auf Druckbett erkannt" in reason
        mock_set_awaiting.assert_called_once_with(printer.id, True)
        mock_notif.assert_called_once()


@pytest.mark.asyncio
async def test_plate_check_exception_failsafe():
    printer = FakePrinter(plate_detection_enabled=True)
    item = FakeQueueItem()
    db = MagicMock()

    with patch("backend.app.services.plate_detection.check_plate_empty", AsyncMock(side_effect=RuntimeError("Camera timeout"))):
        is_clear, reason = await check_queue_plate_clear(printer, item, db)
        assert is_clear is True
        assert reason is None
