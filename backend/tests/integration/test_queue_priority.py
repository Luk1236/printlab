"""Auftrags-Priorität, Liefertermin und gleichmäßige Druckerwahl der Warteschlange (PrintLab)."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from backend.app.services import queue_priority as qp
from backend.app.services.print_scheduler import PrintScheduler


class TestHelpers:
    NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)

    def test_usage_adds_the_offset_hours(self):
        assert qp.printer_usage_seconds(3600, 2.0) == 3600 + 7200
        assert qp.printer_usage_seconds(None, None) == 0.0

    def test_due_warning_levels(self):
        past = self.NOW - timedelta(hours=1)
        soon = self.NOW + timedelta(hours=1)
        assert qp.due_warning(past, "pending", None, self.NOW) == qp.DUE_OVERDUE
        assert qp.due_warning(past, "printing", 60, self.NOW) == qp.DUE_OVERDUE
        assert qp.due_warning(soon, "pending", 7200, self.NOW) == qp.DUE_TOO_LATE
        assert qp.due_warning(soon, "pending", 1800, self.NOW) is None
        assert qp.due_warning(soon, "pending", None, self.NOW) is None

    def test_no_warning_without_a_date_or_when_finished(self):
        assert qp.due_warning(None, "pending", 60, self.NOW) is None
        for status in ("completed", "failed", "cancelled", "skipped"):
            assert qp.due_warning(self.NOW - timedelta(days=1), status, 60, self.NOW) is None

    def test_naive_datetimes_count_as_utc(self):
        naive_past = (self.NOW - timedelta(hours=2)).replace(tzinfo=None)
        assert qp.due_warning(naive_past, "pending", None, self.NOW) == qp.DUE_OVERDUE


class TestPriorityApi:
    @pytest.mark.asyncio
    async def test_default_is_normal_and_levels_are_stored(
        self, async_client: AsyncClient, printer_factory, archive_factory
    ):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        base = {"printer_id": printer.id, "archive_id": archive.id}
        normal = (await async_client.post("/api/v1/queue/", json=base)).json()
        urgent = (await async_client.post("/api/v1/queue/", json={**base, "priority": 2})).json()
        assert normal["priority"] == 1 and urgent["priority"] == 2
        assert normal["due_at"] is None and normal["due_warning"] is None

    @pytest.mark.asyncio
    async def test_out_of_range_priority_is_rejected(self, async_client: AsyncClient, printer_factory, archive_factory):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        for bad in (-1, 3, "hoch"):
            resp = await async_client.post(
                "/api/v1/queue/", json={"printer_id": printer.id, "archive_id": archive.id, "priority": bad}
            )
            assert resp.status_code == 422, bad

    @pytest.mark.asyncio
    async def test_the_list_shows_urgent_first_then_by_position(
        self, async_client: AsyncClient, printer_factory, archive_factory
    ):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        base = {"printer_id": printer.id, "archive_id": archive.id}
        ids = {}
        for name, prio in (("low", 0), ("normal1", 1), ("urgent", 2), ("normal2", 1)):
            ids[name] = (await async_client.post("/api/v1/queue/", json={**base, "priority": prio})).json()["id"]
        listed = [item["id"] for item in (await async_client.get("/api/v1/queue/")).json()]
        assert listed == [ids["urgent"], ids["normal1"], ids["normal2"], ids["low"]]

    @pytest.mark.asyncio
    async def test_priority_and_due_date_can_be_changed_later(
        self, async_client: AsyncClient, printer_factory, archive_factory
    ):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        item = (
            await async_client.post("/api/v1/queue/", json={"printer_id": printer.id, "archive_id": archive.id})
        ).json()
        due = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        resp = await async_client.patch(f"/api/v1/queue/{item['id']}", json={"priority": 2, "due_at": due})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["priority"] == 2 and body["due_at"] is not None
        assert body["due_warning"] == "overdue"
        assert (await async_client.patch(f"/api/v1/queue/{item['id']}", json={"priority": 7})).status_code == 422

    @pytest.mark.asyncio
    async def test_a_far_due_date_gives_no_warning(self, async_client: AsyncClient, printer_factory, archive_factory):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        due = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        item = (
            await async_client.post(
                "/api/v1/queue/", json={"printer_id": printer.id, "archive_id": archive.id, "due_at": due}
            )
        ).json()
        assert item["due_at"] is not None and item["due_warning"] is None


class TestBalancedPrinterChoice:
    @pytest.mark.asyncio
    async def test_least_used_matching_printer_comes_first(self, db_session, printer_factory):
        busy = await printer_factory(model="X1C", name="Viel", runtime_seconds=500_000)
        fresh = await printer_factory(model="X1C", name="Neu", runtime_seconds=1_000)
        offset = await printer_factory(model="X1C", name="Sockel", runtime_seconds=0, print_hours_offset=100.0)
        await printer_factory(model="P1S", name="Anderes Modell", runtime_seconds=0)
        ordered = await PrintScheduler()._printers_for_model(db_session, "X1C")
        assert [p.id for p in ordered] == [fresh.id, offset.id, busy.id]

    @pytest.mark.asyncio
    async def test_ties_fall_back_to_the_printer_id(self, db_session, printer_factory):
        first = await printer_factory(model="X1C", runtime_seconds=0)
        second = await printer_factory(model="X1C", runtime_seconds=0)
        ordered = await PrintScheduler()._printers_for_model(db_session, "X1C")
        assert [p.id for p in ordered] == [first.id, second.id]

    @pytest.mark.asyncio
    async def test_location_filter_still_applies(self, db_session, printer_factory):
        a = await printer_factory(model="X1C", location="Werkstatt", runtime_seconds=5)
        await printer_factory(model="X1C", location="Keller", runtime_seconds=1)
        ordered = await PrintScheduler()._printers_for_model(db_session, "X1C", "Werkstatt")
        assert [p.id for p in ordered] == [a.id]


class TestBulkPriority:
    async def make(self, client: AsyncClient, printer, archive, **extra):
        body = {"printer_id": printer.id, "archive_id": archive.id, **extra}
        return (await client.post("/api/v1/queue/", json=body)).json()["id"]

    @pytest.mark.asyncio
    async def test_sets_priority_and_due_date_for_several_items_at_once(
        self, async_client: AsyncClient, printer_factory, archive_factory
    ):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        ids = [await self.make(async_client, printer, archive) for _ in range(3)]
        due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        resp = await async_client.patch("/api/v1/queue/bulk", json={"item_ids": ids[:2], "priority": 2, "due_at": due})
        assert resp.status_code == 200, resp.text
        assert resp.json()["updated_count"] == 2
        items = {i["id"]: i for i in (await async_client.get("/api/v1/queue/")).json()}
        assert [items[i]["priority"] for i in ids] == [2, 2, 1]
        assert items[ids[0]]["due_at"] is not None and items[ids[2]]["due_at"] is None

    @pytest.mark.asyncio
    async def test_a_priority_only_change_keeps_the_due_dates(
        self, async_client: AsyncClient, printer_factory, archive_factory
    ):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        item_id = await self.make(async_client, printer, archive, due_at=due)
        await async_client.patch("/api/v1/queue/bulk", json={"item_ids": [item_id], "priority": 0})
        item = (await async_client.get("/api/v1/queue/")).json()[0]
        assert item["priority"] == 0 and item["due_at"] is not None

    @pytest.mark.asyncio
    async def test_an_explicit_null_removes_the_due_date(
        self, async_client: AsyncClient, printer_factory, archive_factory
    ):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        item_id = await self.make(async_client, printer, archive, due_at=due)
        resp = await async_client.patch("/api/v1/queue/bulk", json={"item_ids": [item_id], "due_at": None})
        assert resp.status_code == 200
        item = (await async_client.get("/api/v1/queue/")).json()[0]
        assert item["due_at"] is None and item["priority"] == 1

    @pytest.mark.asyncio
    async def test_invalid_and_null_priority_are_rejected_without_touching_anything(
        self, async_client: AsyncClient, printer_factory, archive_factory
    ):
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        item_id = await self.make(async_client, printer, archive)
        for bad in (3, -1, None, "hoch"):
            resp = await async_client.patch("/api/v1/queue/bulk", json={"item_ids": [item_id], "priority": bad})
            assert resp.status_code == 422, bad
        single = await async_client.patch(f"/api/v1/queue/{item_id}", json={"priority": None})
        assert single.status_code == 422
        assert (await async_client.get("/api/v1/queue/")).json()[0]["priority"] == 1

    @pytest.mark.asyncio
    async def test_non_pending_items_are_skipped(
        self, async_client: AsyncClient, printer_factory, archive_factory, db_session
    ):
        from backend.app.models.print_queue import PrintQueueItem

        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        pending = await self.make(async_client, printer, archive)
        done = await self.make(async_client, printer, archive)
        row = await db_session.get(PrintQueueItem, done)
        row.status = "completed"
        await db_session.commit()
        resp = await async_client.patch("/api/v1/queue/bulk", json={"item_ids": [pending, done], "priority": 2})
        assert resp.json()["updated_count"] == 1 and resp.json()["skipped_count"] == 1
        await db_session.refresh(row)
        assert row.priority == 1
