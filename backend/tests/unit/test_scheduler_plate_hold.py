"""Eine Sperre der Plattenprüfung hält den Auftrag sichtbar und ohne Dauerschleife.

Fall vom 11.11.2026 (v2.0.55, P2S "lukas"): nach einem fehlgeschlagenen Druck sah die
Kamera 15 % Abweichung zur Referenz. Der Auftrag stand ohne Wartegrund und mit ETA in der
Warteschlange, als könnte er sofort starten, während jeder Durchlauf alle 3 Sekunden den
freien Drucker wählte, die Prüfung erneut sperrte und die Runde als produktiv zählte:
455 Sperren in 37 Minuten, jede mit Kamerabild und KI-Prüfung.
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.models.printer import Printer
from backend.app.services.print_scheduler import PrintScheduler
from backend.app.services.scheduler.plate_hold import PLATE_RECHECK_SECONDS
from backend.tests.unit.test_scheduler_upload_requeue_3210 import _item, _scheduler, farm  # noqa: F401

pytestmark = pytest.mark.unit


def _detection(is_empty: bool):
    return SimpleNamespace(
        is_empty=is_empty,
        needs_calibration=False,
        difference_percent=0.5 if is_empty else 15.0,
        message="Empty" if is_empty else "Objects detected on plate",
        debug_image=None,
    )


async def _enable_plate_detection(ctx, printer_id: int) -> None:
    async with ctx.session_maker() as db:
        printer = await db.get(Printer, printer_id)
        printer.plate_detection_enabled = True
        await db.commit()


async def _pass(ctx, scheduler, *, plate_empty: bool, notify: AsyncMock) -> tuple[bool, AsyncMock]:
    """Ein Durchlauf; liefert, ob er als produktiv galt, und die Kamera-Attrappe."""
    camera = AsyncMock(return_value=_detection(plate_empty))
    # Außen um das Harness: die Starts laufen als Hintergrundaufgaben, die es erst beim Verlassen abwartet.
    with (
        patch("backend.app.services.plate_detection.check_plate_empty", camera),
        patch("backend.app.services.notification_service.notification_service.on_plate_not_empty", notify),
        patch("backend.app.services.printer_manager.printer_manager.set_awaiting_plate_clear"),
    ):
        async with _scheduler(ctx, AsyncMock(return_value=True), scheduler=scheduler):
            productive = await scheduler.check_queue()
    return productive, camera


@pytest.fixture
async def blocked(farm):  # noqa: F811
    """Ein Auftrag auf einem Drucker mit eingeschalteter Plattenprüfung."""
    printer_id = farm.ids.healthy
    await _enable_plate_detection(farm, printer_id)
    item_id = await farm.add_item(printer_id=printer_id)
    return SimpleNamespace(ctx=farm, printer_id=printer_id, item_id=item_id, scheduler=PrintScheduler())


class TestABlockedPlate:
    @pytest.mark.asyncio
    async def test_the_row_says_why_it_does_not_start(self, blocked):
        await _pass(blocked.ctx, blocked.scheduler, plate_empty=False, notify=AsyncMock())

        item = await _item(blocked.ctx, blocked.item_id)
        assert item.status == "pending"
        assert item.waiting_reason is not None
        assert "Objekt auf Druckbett erkannt (15.0% Differenz)" in item.waiting_reason
        assert "P2S-9" in item.waiting_reason

    @pytest.mark.asyncio
    async def test_the_camera_is_not_asked_again_inside_the_window(self, blocked):
        """Der Fehler vom Pi: jeder Durchlauf schaute neu, alle 3 Sekunden."""
        notify = AsyncMock()
        await _pass(blocked.ctx, blocked.scheduler, plate_empty=False, notify=notify)

        for _ in range(5):
            productive, camera = await _pass(blocked.ctx, blocked.scheduler, plate_empty=False, notify=notify)
            camera.assert_not_awaited()
            assert productive is False, "a held printer must not keep the loop on the fast interval"

        item = await _item(blocked.ctx, blocked.item_id)
        assert item.status == "pending"
        assert "Objekt auf Druckbett erkannt" in item.waiting_reason
        retry_at, _text = blocked.scheduler._plate_blocks[blocked.printer_id]
        assert retry_at - time.monotonic() == pytest.approx(PLATE_RECHECK_SECONDS, abs=5)

    @pytest.mark.asyncio
    async def test_one_blocked_run_notifies_once(self, blocked):
        notify = AsyncMock()
        for _ in range(3):
            await _pass(blocked.ctx, blocked.scheduler, plate_empty=False, notify=notify)
            # Die Minute ist um: die Kamera schaut wieder, die Platte ist noch belegt.
            retry_at, text = blocked.scheduler._plate_blocks[blocked.printer_id]
            blocked.scheduler._plate_blocks[blocked.printer_id] = (time.monotonic() - 1, text)

        assert notify.await_count == 1

    @pytest.mark.asyncio
    async def test_a_cleared_plate_starts_the_print_after_the_window(self, blocked):
        await _pass(blocked.ctx, blocked.scheduler, plate_empty=False, notify=AsyncMock())
        _retry_at, text = blocked.scheduler._plate_blocks[blocked.printer_id]
        blocked.scheduler._plate_blocks[blocked.printer_id] = (time.monotonic() - 1, text)

        _productive, camera = await _pass(blocked.ctx, blocked.scheduler, plate_empty=True, notify=AsyncMock())

        camera.assert_awaited_once()
        item = await _item(blocked.ctx, blocked.item_id)
        assert item.status == "printing"
        assert item.waiting_reason is None
        assert blocked.printer_id not in blocked.scheduler._plate_blocks

    @pytest.mark.asyncio
    async def test_confirming_the_plate_ends_the_wait_at_once(self, blocked):
        await _pass(blocked.ctx, blocked.scheduler, plate_empty=False, notify=AsyncMock())

        blocked.scheduler.clear_plate_block(blocked.printer_id)
        _productive, camera = await _pass(blocked.ctx, blocked.scheduler, plate_empty=True, notify=AsyncMock())

        camera.assert_awaited_once()
        assert (await _item(blocked.ctx, blocked.item_id)).status == "printing"

    @pytest.mark.asyncio
    async def test_a_block_long_past_its_window_notifies_again(self, blocked):
        """Eine Sperre, auf die eine Stunde lang niemand gewartet hat (z. B. Auftrag gelöscht), ist eine neue Folge."""
        blocked.scheduler._plate_blocks[blocked.printer_id] = (time.monotonic() - 3601, "alt")
        notify = AsyncMock()

        await _pass(blocked.ctx, blocked.scheduler, plate_empty=False, notify=notify)

        notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_plate_check_can_stay_quiet():
    """``notify=False`` sperrt genauso, schickt aber keine Benachrichtigung."""
    from backend.app.services.queue_plate_check import check_queue_plate_clear

    printer = SimpleNamespace(
        id=1,
        name="P2S",
        plate_detection_enabled=True,
        plate_detection_roi_x=None,
        plate_detection_roi_w=None,
        ip_address="10.0.0.1",
        access_code="x",
        model="P2S",
        external_camera_url=None,
        external_camera_type=None,
        external_camera_enabled=False,
        external_camera_snapshot_url=None,
    )
    notify = AsyncMock()
    with (
        patch("backend.app.services.plate_detection.check_plate_empty", AsyncMock(return_value=_detection(False))),
        patch("backend.app.services.printer_manager.printer_manager.set_awaiting_plate_clear"),
        patch("backend.app.services.notification_service.notification_service.on_plate_not_empty", notify),
    ):
        clear, reason = await check_queue_plate_clear(printer, SimpleNamespace(id=7), None, notify=False)

    assert clear is False
    assert "Objekt auf Druckbett erkannt" in reason
    notify.assert_not_awaited()
