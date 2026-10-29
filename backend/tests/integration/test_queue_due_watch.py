"""Termin-Meldung: Überwachung der Liefertermine und das Ereignis ``queue_due_risk``."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from backend.app.models.print_queue import PrintQueueItem
from backend.app.services import queue_due_watch as watch

NOW = datetime.now(timezone.utc)


def no_status(_printer_id):
    return None


class Recorder:
    def __init__(self, result=True, error=None):
        self.calls: list[tuple[int, bool]] = []
        self.result, self.error = result, error

    async def __call__(self, db, item, end, overdue):
        self.calls.append((item.id, overdue))
        if self.error:
            raise self.error
        return self.result


async def add(db, printer, archive, **over):
    item = PrintQueueItem(
        printer_id=printer.id, archive_id=archive.id, status=over.pop("status", "pending"), position=over.pop("position", 0),
        print_time_seconds=over.pop("seconds", 3600), **over,
    )  # fmt: skip
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@pytest.fixture
async def base(db_session, printer_factory, archive_factory):
    printer = await printer_factory()
    archive = await archive_factory(printer.id)
    return db_session, printer, archive


class TestCheck:
    @pytest.mark.asyncio
    async def test_reports_a_job_that_will_miss_its_due_date_once(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW + timedelta(minutes=30))
        notifier = Recorder()
        assert await watch.check_due_dates(db, no_status, notifier, NOW) == [item.id]
        assert notifier.calls == [(item.id, False)]
        await db.refresh(item)
        assert item.due_risk_notified is True
        assert await watch.check_due_dates(db, no_status, notifier, NOW) == []
        assert len(notifier.calls) == 1

    @pytest.mark.asyncio
    async def test_a_job_that_fits_is_not_reported(self, base):
        db, printer, archive = base
        await add(db, printer, archive, due_at=NOW + timedelta(hours=5))
        notifier = Recorder()
        assert await watch.check_due_dates(db, no_status, notifier, NOW) == []
        assert notifier.calls == []

    @pytest.mark.asyncio
    async def test_an_overdue_job_is_reported_as_overdue(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW - timedelta(hours=1))
        notifier = Recorder()
        await watch.check_due_dates(db, no_status, notifier, NOW)
        assert notifier.calls == [(item.id, True)]

    @pytest.mark.asyncio
    async def test_waiting_behind_other_jobs_counts(self, base):
        db, printer, archive = base
        await add(db, printer, archive, seconds=5 * 3600, position=0)
        tight = await add(db, printer, archive, seconds=1800, position=1, due_at=NOW + timedelta(hours=2))
        notifier = Recorder()
        assert await watch.check_due_dates(db, no_status, notifier, NOW) == [tight.id]

    @pytest.mark.asyncio
    async def test_a_higher_priority_takes_the_job_out_of_danger(self, base):
        db, printer, archive = base
        await add(db, printer, archive, seconds=5 * 3600, position=0)
        tight = await add(db, printer, archive, seconds=1800, position=1, due_at=NOW + timedelta(hours=2), priority=2)
        notifier = Recorder()
        assert await watch.check_due_dates(db, no_status, notifier, NOW) == []
        assert notifier.calls == [] and tight.due_risk_notified is False

    @pytest.mark.asyncio
    async def test_a_recovered_job_can_be_reported_again_when_it_slips_later(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW + timedelta(minutes=30))
        notifier = Recorder()
        await watch.check_due_dates(db, no_status, notifier, NOW)
        item.due_at = NOW + timedelta(hours=9)
        await db.commit()
        await watch.check_due_dates(db, no_status, notifier, NOW)
        await db.refresh(item)
        assert item.due_risk_notified is False
        item.due_at = NOW + timedelta(minutes=10)
        await db.commit()
        assert await watch.check_due_dates(db, no_status, notifier, NOW) == [item.id]
        assert len(notifier.calls) == 2

    @pytest.mark.asyncio
    async def test_without_a_channel_the_job_stays_unreported_for_later(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW + timedelta(minutes=30))
        notifier = Recorder(result=False)
        assert await watch.check_due_dates(db, no_status, notifier, NOW) == []
        await db.refresh(item)
        assert item.due_risk_notified is False and item.due_risk_retry_pending is True
        notifier.result = True
        assert await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(minutes=5)) == [item.id]
        await db.refresh(item)
        assert item.due_risk_notified is True and item.due_risk_retry_pending is False

    @pytest.mark.asyncio
    async def test_a_failed_notification_is_retried_with_growing_gaps(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW + timedelta(minutes=10))
        notifier = Recorder(result=False)
        await watch.check_due_dates(db, no_status, notifier, NOW)
        await db.refresh(item)
        assert item.due_risk_notify_count == 1 and item.due_risk_retry_pending is True
        # Vor Ablauf der Wartezeit wird nicht noch einmal gesendet.
        assert await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(minutes=4)) == []
        assert len(notifier.calls) == 1
        # Nach fünf Minuten schon.
        await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(minutes=5))
        assert len(notifier.calls) == 2
        # Danach verdoppelt sich der Abstand: nach weiteren fünf Minuten noch nicht, nach zehn schon.
        assert await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(minutes=10)) == []
        assert len(notifier.calls) == 2
        await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(minutes=15))
        assert len(notifier.calls) == 3

    @pytest.mark.asyncio
    async def test_a_retry_that_succeeds_marks_the_job_and_stops(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW + timedelta(minutes=10))
        notifier = Recorder(result=False)
        await watch.check_due_dates(db, no_status, notifier, NOW)
        notifier.result = True
        assert await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(minutes=5)) == [item.id]
        await db.refresh(item)
        assert item.due_risk_notified is True and item.due_risk_notify_count == 2
        assert await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(hours=1)) == []
        assert len(notifier.calls) == 2

    @pytest.mark.asyncio
    async def test_after_five_failed_attempts_the_message_rests_until_recovery(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW + timedelta(minutes=10))
        notifier = Recorder(result=False)
        for attempt in range(watch.MAX_NOTIFY_ATTEMPTS):
            await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(hours=2 * attempt))
        assert len(notifier.calls) == watch.MAX_NOTIFY_ATTEMPTS
        await db.refresh(item)
        assert item.due_risk_notify_count == watch.MAX_NOTIFY_ATTEMPTS
        # Der nächste Durchlauf nimmt die Wiederholung zurück und bleibt ruhig.
        assert await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(days=1)) == []
        await db.refresh(item)
        assert item.due_risk_retry_pending is False and item.due_risk_notified is False
        assert len(notifier.calls) == watch.MAX_NOTIFY_ATTEMPTS
        # Sobald er wieder in den Plan passt, beginnt die Prüfung von vorn.
        item.due_at = NOW + timedelta(days=30)
        await db.commit()
        await watch.check_due_dates(db, no_status, notifier, NOW + timedelta(days=1))
        await db.refresh(item)
        assert item.due_risk_notify_count == 0 and item.due_risk_notified is False

    @pytest.mark.asyncio
    async def test_without_any_channel_nothing_counts_as_an_attempt(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW + timedelta(minutes=10))

        async def no_channels(_db, _item, _end, _overdue):
            return None

        assert await watch.check_due_dates(db, no_status, no_channels, NOW) == []
        await db.refresh(item)
        assert item.due_risk_notify_count == 0 and item.due_risk_retry_pending is False

    @pytest.mark.asyncio
    async def test_a_failing_notifier_does_not_stop_the_other_jobs(self, base):
        db, printer, archive = base
        first = await add(db, printer, archive, due_at=NOW + timedelta(minutes=10), position=0)
        notifier = Recorder(error=RuntimeError("Kanal kaputt"))
        assert await watch.check_due_dates(db, no_status, notifier, NOW) == []
        assert notifier.calls == [(first.id, False)]
        await db.refresh(first)
        assert first.due_risk_notified is False

    @pytest.mark.asyncio
    async def test_finished_jobs_without_due_dates_and_removed_dates(self, base):
        db, printer, archive = base
        done = await add(db, printer, archive, due_at=NOW - timedelta(days=1), status="completed")
        plain = await add(db, printer, archive)
        flagged = await add(db, printer, archive, due_risk_notified=True)
        notifier = Recorder()
        await watch.check_due_dates(db, no_status, notifier, NOW)
        assert notifier.calls == []
        await db.refresh(flagged)
        assert flagged.due_risk_notified is False and done.id != plain.id

    @pytest.mark.asyncio
    async def test_the_running_print_pushes_the_forecast_back(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, seconds=1800, due_at=NOW + timedelta(hours=1))
        notifier = Recorder()

        def busy(_pid):
            return SimpleNamespace(remaining_time=120, state="RUNNING", progress=10)

        assert await watch.check_due_dates(db, busy, notifier, NOW) == [item.id]


class TestNotifyDueRisk:
    @pytest.mark.asyncio
    async def test_sends_the_event_through_the_providers_that_want_it(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW + timedelta(hours=1))
        service = "backend.app.services.notification_service.notification_service"
        with (
            patch(f"{service}._get_providers_for_event", AsyncMock(return_value=[object()])) as get,
            patch(f"{service}._build_message_from_template", AsyncMock(return_value=("Titel", "Text"))) as build,
            patch(f"{service}._send_to_providers_with_results", AsyncMock(return_value=[(True, "")])) as send,
        ):
            assert await watch.notify_due_risk(db, item, NOW + timedelta(hours=3), overdue=False) is True
        assert get.call_args.args[1] == "on_queue_due_risk"
        variables = build.call_args.args[2]
        assert build.call_args.args[1] == "queue_due_risk"
        assert variables["reason"] == "Expected to finish after the due date." and variables["job_name"]
        assert send.call_args.args[1:3] == ("Titel", "Text")

    @pytest.mark.asyncio
    async def test_returns_none_without_providers(self, base):
        db, printer, archive = base
        item = await add(db, printer, archive, due_at=NOW + timedelta(hours=1))
        with patch(
            "backend.app.services.notification_service.notification_service._get_providers_for_event",
            AsyncMock(return_value=[]),
        ):
            assert await watch.notify_due_risk(db, item, None, overdue=True) is None


class TestProviderField:
    @pytest.mark.asyncio
    async def test_the_toggle_defaults_on_and_can_be_changed(self, async_client: AsyncClient):
        data = {"name": "Termin", "provider_type": "ntfy", "config": {"server": "https://ntfy.sh", "topic": "t"}}
        created = (await async_client.post("/api/v1/notifications/", json=data)).json()
        assert created["on_queue_due_risk"] is True
        updated = await async_client.patch(f"/api/v1/notifications/{created['id']}", json={"on_queue_due_risk": False})
        assert updated.status_code == 200 and updated.json()["on_queue_due_risk"] is False

    def test_the_default_template_and_its_variables_exist(self):
        from backend.app.models.notification_template import DEFAULT_TEMPLATES
        from backend.app.schemas.notification_template import EVENT_VARIABLES, SAMPLE_DATA

        entry = next(t for t in DEFAULT_TEMPLATES if t["event_type"] == "queue_due_risk")
        assert "{due}" in entry["body_template"] and "{job_name}" in entry["body_template"]
        assert set(EVENT_VARIABLES["queue_due_risk"]) >= {"job_name", "due", "expected", "reason"}
        assert SAMPLE_DATA["queue_due_risk"]["job_name"]
