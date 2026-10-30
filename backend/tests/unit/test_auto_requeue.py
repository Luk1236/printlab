"""Tests für die automatische Umverteilung gescheiterter Warteschlangen-Aufträge."""

from types import SimpleNamespace

import pytest

from backend.app.models.print_queue import PrintQueueItem
from backend.app.services import auto_requeue
from backend.app.services.notification_service import notification_service


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_requeue, "CONFIG_PATH", tmp_path / "auto_requeue.json")
    monkeypatch.setattr(auto_requeue, "LOG_PATH", tmp_path / "auto_requeue_log.json")

    async def fake_job_name(db, item):
        return "Teil.3mf"

    async def fake_added(**kwargs):
        return None

    async def fake_broadcast(payload):
        return None

    monkeypatch.setattr(auto_requeue, "_job_name", fake_job_name)
    monkeypatch.setattr(notification_service, "on_queue_job_added", fake_added)
    from backend.app.core import websocket

    monkeypatch.setattr(websocket.ws_manager, "broadcast", fake_broadcast)
    return tmp_path


class FakeDB:
    """Minimaler Ersatz: liefert die vorgegebenen scalar()-Ergebnisse der Reihe nach."""

    def __init__(self, scalars):
        self._scalars = list(scalars)
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def scalar(self, query):
        return self._scalars.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, obj):
        obj.id = 4711


def _item(item_id=1, status="failed", model=None, archive_id=5):
    return SimpleNamespace(
        id=item_id,
        status=status,
        printer_id=3,
        target_model=model,
        target_location=None,
        required_filament_types=None,
        archive_id=archive_id,
        library_file_id=None,
        plate_id=None,
        priority=1,
        ams_mapping="[1]",
        filament_overrides=None,
        print_time_seconds=600,
        created_by_id=2,
        cost_center_id=None,
        project_id=None,
        batch_id=None,
        error_message="Düsenverstopfung",
    )


def _printer(model="P1S"):
    return SimpleNamespace(id=3, model=model)


class TestConfig:
    def test_defaults_off(self):
        cfg = auto_requeue.read_config()
        assert cfg == {"enabled": False, "max_retries": 1, "require_sibling": True}

    def test_values_are_clamped_and_unknown_ignored(self):
        cfg = auto_requeue.write_config({"enabled": True, "max_retries": 99, "bogus": 3})
        assert cfg["enabled"] is True
        assert cfg["max_retries"] == 1  # außerhalb 0..5 -> Vorgabe
        assert "bogus" not in cfg


class TestRules:
    def test_only_failed(self):
        cfg = {"enabled": True, "max_retries": 1}
        assert auto_requeue.should_requeue("failed", cfg, 0) is True
        assert auto_requeue.should_requeue("cancelled", cfg, 0) is False
        assert auto_requeue.should_requeue("completed", cfg, 0) is False

    def test_disabled_and_budget(self):
        assert auto_requeue.should_requeue("failed", {"enabled": False, "max_retries": 1}, 0) is False
        assert auto_requeue.should_requeue("failed", {"enabled": True, "max_retries": 1}, 1) is False

    def test_chain_tracks_retries(self):
        auto_requeue.record(5, 9, 3, "P1S", "Filament")
        assert auto_requeue.root_of(9) == 5
        assert auto_requeue.root_of(7) == 7
        assert auto_requeue.retries_used(5) == 1
        assert auto_requeue.retries_used(9) == 0  # der neue Auftrag selbst hat noch keine Wiederholung


class TestMaybeRequeue:
    @pytest.mark.asyncio
    async def test_disabled_does_nothing(self):
        db = FakeDB([])
        assert await auto_requeue.maybe_requeue(db, 1, "failed") is None
        assert db.added == []

    @pytest.mark.asyncio
    async def test_cancelled_is_never_requeued(self):
        auto_requeue.write_config({"enabled": True})
        db = FakeDB([])
        assert await auto_requeue.maybe_requeue(db, 1, "cancelled") is None
        assert db.added == []

    @pytest.mark.asyncio
    async def test_creates_one_retry_on_the_model(self):
        auto_requeue.write_config({"enabled": True})
        db = FakeDB([_item(), _printer("P1S"), 1])
        entry = await auto_requeue.maybe_requeue(db, 1, "failed")
        assert entry is not None
        retry = db.added[0]
        assert isinstance(retry, PrintQueueItem)
        assert retry.target_model == "P1S"
        assert retry.printer_id is None
        assert retry.status == "pending"
        assert retry.archive_id == 5
        assert retry.ams_mapping is None  # Zuordnung des gescheiterten Geräts nicht übernehmen
        assert db.committed is True
        assert auto_requeue.entries()[0]["retry_id"] == 4711

    @pytest.mark.asyncio
    async def test_budget_stops_the_second_attempt(self):
        auto_requeue.write_config({"enabled": True, "max_retries": 1})
        auto_requeue.record(1, 99, 3, "P1S", "erster Versuch")
        db = FakeDB([_item()])
        assert await auto_requeue.maybe_requeue(db, 1, "failed") is None
        assert db.added == []

    @pytest.mark.asyncio
    async def test_without_sibling_no_requeue(self):
        auto_requeue.write_config({"enabled": True, "require_sibling": True})
        db = FakeDB([_item(), _printer("P1S"), 0])
        assert await auto_requeue.maybe_requeue(db, 1, "failed") is None
        assert db.added == []

    @pytest.mark.asyncio
    async def test_sibling_not_required_lets_it_retry_on_the_same_printer(self):
        auto_requeue.write_config({"enabled": True, "require_sibling": False})
        db = FakeDB([_item(), _printer("P1S")])
        assert await auto_requeue.maybe_requeue(db, 1, "failed") is not None
        assert db.added[0].target_model == "P1S"

    @pytest.mark.asyncio
    async def test_item_must_still_be_failed(self):
        auto_requeue.write_config({"enabled": True})
        db = FakeDB([_item(status="completed")])
        assert await auto_requeue.maybe_requeue(db, 1, "failed") is None

    @pytest.mark.asyncio
    async def test_broken_item_load_is_swallowed(self):
        auto_requeue.write_config({"enabled": True})

        class BrokenDB:
            async def scalar(self, query):
                raise RuntimeError("db weg")

        assert await auto_requeue.maybe_requeue(BrokenDB(), 1, "failed") is None
