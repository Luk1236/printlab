"""Regressionstests zu den Befunden T4-01, T4-02 und T4-03 der Code-Analyse (docs/analyse/T4-...).

* T4-02: Reservierungen beendeter Aufträge werden vom Aufräumer freigegeben.
* T4-01: Einschalten für Aufträge mit festem Drucker: ein Versuch je Runde, Abkühlzeit nach Fehlschlag.
* T4-03: Modell-Aufträge, die der Upload-Pool nicht nimmt, verlieren den zugewiesenen Drucker wieder.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.models.finance import BudgetReservation, CostCenter
from backend.app.models.print_queue import PrintQueueItem
from backend.app.services.scheduler import reservations
from backend.app.services.scheduler.queue_pass import QueuePass
from backend.app.services.scheduler.wake import try_power_on_pinned


@pytest.fixture
async def session_maker():
    import backend.app.models  # noqa: F401  — Base.metadata füllen
    from backend.app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _reserve(db, item_id: int | None, amount: float = 40.0) -> BudgetReservation:
    center = (await db.execute(select(CostCenter))).scalars().first()
    if center is None:
        center = CostCenter(name="Werkstatt", monthly_budget=100.0)
        db.add(center)
        await db.flush()
    reservation = BudgetReservation(
        cost_center_id=center.id, amount=amount, status="active", source_type="print_queue", source_id=item_id
    )
    db.add(reservation)
    await db.flush()
    return reservation


def _naive_utc(minutes_ago: float) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).replace(tzinfo=None)


class TestReservationJanitor:
    """T4-02: ``release_orphaned_reservations``."""

    async def _scenario(self, session_maker):
        async with session_maker() as db:
            items = {
                "pending": PrintQueueItem(status="pending"),
                "printing": PrintQueueItem(status="printing"),
                "failed_old": PrintQueueItem(status="failed", completed_at=_naive_utc(60)),
                "failed_fresh": PrintQueueItem(status="failed", completed_at=_naive_utc(1)),
                "cancelled_no_time": PrintQueueItem(status="cancelled"),
            }
            db.add_all(items.values())
            await db.flush()
            held = {name: await _reserve(db, item.id) for name, item in items.items()}
            held["item_gone"] = await _reserve(db, 987654)
            await db.commit()
            return {name: r.id for name, r in held.items()}

    @pytest.mark.asyncio
    async def test_releases_only_what_is_finished_or_gone(self, session_maker):
        ids = await self._scenario(session_maker)

        async with session_maker() as db:
            released = await reservations.release_orphaned_reservations(db, force=True)

        assert released == 3
        async with session_maker() as db:
            status = {name: (await db.get(BudgetReservation, rid)).status for name, rid in ids.items()}
        assert status == {
            "pending": "active",  # wartet noch auf seinen Druck
            "printing": "active",  # druckt, wird später abgerechnet
            "failed_old": "released",
            "failed_fresh": "active",  # innerhalb der Schonfrist: die Abrechnung darf noch verbrauchen
            "cancelled_no_time": "released",
            "item_gone": "released",
        }

    @pytest.mark.asyncio
    async def test_budget_is_available_again(self, session_maker):
        from backend.app.services.finance_budget import get_cost_center_reserved_map

        async with session_maker() as db:
            item = PrintQueueItem(status="completed", completed_at=_naive_utc(60))
            db.add(item)
            await db.flush()
            reservation = await _reserve(db, item.id, amount=40.0)
            center_id = reservation.cost_center_id
            await db.commit()
            assert (await get_cost_center_reserved_map(db, [center_id]))[center_id] == 40.0

            await reservations.release_orphaned_reservations(db, force=True)

            assert (await get_cost_center_reserved_map(db, [center_id])).get(center_id, 0.0) == 0.0

    @pytest.mark.asyncio
    async def test_is_throttled_and_never_raises(self, session_maker, monkeypatch):
        monkeypatch.setattr(reservations, "_next_run", 0.0)
        async with session_maker() as db:
            await reservations.release_orphaned_reservations(db)  # setzt die Sperre
            item = PrintQueueItem(status="failed", completed_at=_naive_utc(60))
            db.add(item)
            await db.flush()
            await _reserve(db, item.id)
            await db.commit()

            assert await reservations.release_orphaned_reservations(db) == 0, "innerhalb einer Stunde nicht noch einmal"

            broken = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db weg")), rollback=AsyncMock())
            assert await reservations.release_orphaned_reservations(broken, force=True) == 0


def _pass(*, attempted: bool = False, wake_failures: dict[int, float] | None = None, power_on) -> SimpleNamespace:
    scheduler = SimpleNamespace(
        _wake_failures=wake_failures if wake_failures is not None else {},
        _wake_failure_cooloff=600,
        _power_on_and_wait=power_on,
    )
    return SimpleNamespace(_s=scheduler, power_on_attempted=attempted, db=object())


class TestPinnedPowerOn:
    """T4-01: ``try_power_on_pinned``."""

    @pytest.mark.asyncio
    async def test_first_attempt_runs_and_second_in_the_same_pass_does_not(self):
        power_on = AsyncMock(return_value=True)
        qp = _pass(power_on=power_on)

        assert await try_power_on_pinned(qp, 1, "plug-1") is True
        assert await try_power_on_pinned(qp, 2, "plug-2") is None, "ein Einschalten je Runde"
        assert power_on.await_count == 1

    @pytest.mark.asyncio
    async def test_failure_starts_a_cooloff_that_a_later_pass_respects(self):
        failures: dict[int, float] = {}
        power_on = AsyncMock(return_value=False)

        assert await try_power_on_pinned(_pass(power_on=power_on, wake_failures=failures), 1, "plug") is False
        assert failures[1] > time.monotonic() + 500

        later = _pass(power_on=power_on, wake_failures=failures)
        assert await try_power_on_pinned(later, 1, "plug") is None, "Abkühlzeit läuft"
        assert later.power_on_attempted is False, "ein übersprungener Drucker verbraucht das Einschalten nicht"
        assert power_on.await_count == 1

    @pytest.mark.asyncio
    async def test_an_expired_cooloff_allows_another_try(self):
        failures = {1: time.monotonic() - 1}
        power_on = AsyncMock(return_value=True)

        assert await try_power_on_pinned(_pass(power_on=power_on, wake_failures=failures), 1, "plug") is True
        assert 1 not in failures

    @pytest.mark.asyncio
    async def test_a_cooled_off_printer_does_not_block_a_healthy_one(self):
        failures = {1: time.monotonic() + 300}
        power_on = AsyncMock(return_value=True)
        qp = _pass(power_on=power_on, wake_failures=failures)

        assert await try_power_on_pinned(qp, 1, "bad") is None
        assert await try_power_on_pinned(qp, 2, "good") is True


def _queue_pass(*, inflight: int, assigned: dict[int, str | None], dispatch_ids: list[int], items: list) -> QueuePass:
    scheduler = SimpleNamespace(_inflight=dict.fromkeys(range(inflight), (None, None)))
    qp = QueuePass(scheduler)
    qp.items = items
    qp.dispatch_ids = dispatch_ids
    qp.model_assigned = assigned
    return qp


class TestDeferredModelItems:
    """T4-03: ``QueuePass._unpin_deferred``."""

    @staticmethod
    def _item(item_id: int, printer_id: int | None, mapping: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(id=item_id, printer_id=printer_id, ams_mapping=mapping)

    def test_items_beyond_the_pool_get_their_old_state_back(self):
        items = [self._item(i, printer_id=10 + i, mapping="[0]") for i in range(1, 6)]
        qp = _queue_pass(
            inflight=0,
            assigned=dict.fromkeys(range(1, 6)),  # alle kamen aus der Modellsuche, vorher ohne Zuordnung
            dispatch_ids=[1, 2, 3, 4, 5],
            items=items,
        )

        released = qp._unpin_deferred(upload_limit=2)

        assert released == [3, 4, 5]
        assert [(i.printer_id, i.ams_mapping) for i in items[:2]] == [(11, "[0]"), (12, "[0]")]
        assert [(i.printer_id, i.ams_mapping) for i in items[2:]] == [(None, None)] * 3

    def test_a_pinned_item_keeps_its_printer(self):
        items = [self._item(1, 11), self._item(2, 12), self._item(3, 13)]
        qp = _queue_pass(inflight=0, assigned={3: None}, dispatch_ids=[1, 2, 3], items=items)

        # Auftrag 2 hat der Nutzer fest an Drucker 12 gebunden, Auftrag 3 kam aus der Modellsuche.
        assert qp._unpin_deferred(upload_limit=1) == [3]
        assert items[1].printer_id == 12 and items[2].printer_id is None

    def test_the_mapping_from_before_the_pass_is_restored(self):
        item = self._item(1, 11, mapping="[1, 3]")  # in dieser Runde für Drucker 11 berechnet; vorher stand [2] drin
        qp = _queue_pass(inflight=0, assigned={1: "[2]"}, dispatch_ids=[1], items=[item])

        qp._unpin_deferred(upload_limit=0)  # kein freier Platz: alles wird zurückgestellt

        assert (item.printer_id, item.ams_mapping) == (None, "[2]")

    def test_inflight_uploads_use_up_slots(self):
        items = [self._item(1, 11), self._item(2, 12)]
        qp = _queue_pass(inflight=3, assigned={1: None, 2: None}, dispatch_ids=[1, 2], items=items)

        assert qp._unpin_deferred(upload_limit=4) == [2], "von vier Plätzen sind drei belegt, einer bleibt"

    def test_nothing_is_touched_when_everything_fits(self):
        items = [self._item(1, 11), self._item(2, 12)]
        qp = _queue_pass(inflight=0, assigned={1: None, 2: None}, dispatch_ids=[1, 2], items=items)

        assert qp._unpin_deferred(upload_limit=4) == []
        assert [i.printer_id for i in items] == [11, 12]
