"""Systemprüfung: jede Prüfung mit ihren Ausgängen, der Gesamtlauf, die Probemeldung und die Schnittstelle."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from backend.app.api.routes import selftest as route
from backend.app.models.print_queue import PrintQueueItem
from backend.app.services import assistant_llm, queue_due_watch, selftest

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def deps(db, **over):
    base = {
        "db": db,
        "data_dir": Path("."),
        "now": NOW,
        "scheduler_running": lambda: True,
        "printer_connected": lambda _pid: True,
        "due_watch_state": {
            "started": NOW - timedelta(hours=1),
            "last_run": NOW - timedelta(minutes=2),
            "last_error": None,
        },
        "assistant_config": {
            "enabled": False,
            "base_url": "http://127.0.0.1:11434",
            "model": "qwen2.5:3b",
            "timeout_seconds": 180,
        },
        "assistant_status": AsyncMock(
            return_value={"reachable": True, "models": ["qwen2.5:3b"], "model_present": True}
        ),
        "assistant_probe": AsyncMock(return_value=2.5),
        "send_test_notification": AsyncMock(return_value=(0, [])),
        "health": lambda _dir: {"warnings": []},
        "guard_state": lambda: "ok",
        "auth_enabled": AsyncMock(return_value=True),
    }
    return selftest.Deps(**{**base, **over})


async def add_item(db, printer, archive, **over):
    item = PrintQueueItem(
        printer_id=over.pop("printer_id", printer.id), archive_id=archive.id, status=over.pop("status", "pending"),
        position=over.pop("position", 0), print_time_seconds=over.pop("seconds", 3600), **over,
    )  # fmt: skip
    db.add(item)
    await db.commit()
    return item


class TestSimpleChecks:
    @pytest.mark.asyncio
    async def test_database_is_ok_and_reports_missing_columns(self, db_session):
        assert (await selftest.check_database(deps(db_session))).status == selftest.OK

        class Broken:
            async def execute(self, statement):
                if "notification_providers" in str(statement):
                    raise RuntimeError("no such column")

            async def rollback(self):
                pass

        result = await selftest.check_database(deps(Broken()))
        assert result.status == selftest.FAIL and "notification_providers" in result.detail["de"] and result.fix

    @pytest.mark.asyncio
    async def test_scheduler(self, db_session):
        assert (await selftest.check_scheduler(deps(db_session))).status == selftest.OK
        stopped = await selftest.check_scheduler(deps(db_session, scheduler_running=lambda: False))
        assert stopped.status == selftest.FAIL and stopped.fix

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ({"started": None}, selftest.FAIL),
            ({"started": NOW - timedelta(hours=1), "last_error": "kaputt"}, selftest.WARN),
            ({"started": NOW - timedelta(seconds=60), "last_run": None}, selftest.WARN),
            ({"started": NOW - timedelta(minutes=10), "last_run": None}, selftest.FAIL),
            ({"started": NOW - timedelta(hours=2), "last_run": NOW - timedelta(minutes=3)}, selftest.OK),
            ({"started": NOW - timedelta(hours=2), "last_run": NOW - timedelta(minutes=40)}, selftest.WARN),
        ],
    )
    async def test_due_watch(self, db_session, state, expected):
        result = await selftest.check_due_watch(
            deps(db_session, due_watch_state={"last_run": None, "last_error": None, **state})
        )
        assert result.status == expected

    @pytest.mark.asyncio
    async def test_auth_and_guard(self, db_session):
        assert (await selftest.check_auth(deps(db_session))).status == selftest.OK
        off = await selftest.check_auth(deps(db_session, auth_enabled=AsyncMock(return_value=False)))
        assert off.status == selftest.WARN
        for state, expected in (("ok", selftest.OK), ("no_unit", selftest.SKIP), ("missing", selftest.WARN)):
            assert (await selftest.check_guard(deps(db_session, guard_state=lambda s=state: s))).status == expected

    @pytest.mark.asyncio
    async def test_backup_and_device_use_the_health_warnings(self, db_session):
        warnings = [
            {"level": "warn", "code": "backup_old"},
            {"level": "crit", "code": "temp_critical"},
            {"level": "warn", "code": "sd_card"},
            {"level": "crit", "code": "external_failed"},
        ]
        info = {"warnings": warnings}
        backup = await selftest.check_backup(deps(db_session), info)
        assert backup.status == selftest.FAIL and "alt" in backup.detail["de"] and "failed" in backup.detail["en"]
        device = await selftest.check_device(deps(db_session), info)
        assert device.status == selftest.FAIL and "heiß" in device.detail["de"] and "SD card" in device.detail["en"]
        assert (await selftest.check_backup(deps(db_session), {"warnings": []})).status == selftest.OK
        assert (
            await selftest.check_device(deps(db_session), {"warnings": [{"level": "warn", "code": "sd_card"}]})
        ).status == selftest.WARN
        assert (
            await selftest.check_device(deps(db_session), {"warnings": [{"level": "warn", "code": "unbekannt"}]})
        ).status == selftest.OK


class TestDataChecks:
    @pytest.mark.asyncio
    async def test_printers(self, db_session, printer_factory):
        assert (await selftest.check_printers(deps(db_session))).status == selftest.WARN  # keiner eingerichtet
        a, b = await printer_factory(name="A"), await printer_factory(name="B")
        assert (await selftest.check_printers(deps(db_session))).status == selftest.OK
        some = await selftest.check_printers(deps(db_session, printer_connected=lambda pid: pid == a.id))
        assert some.status == selftest.WARN and "B" in some.detail["de"]
        none = await selftest.check_printers(deps(db_session, printer_connected=lambda _pid: False))
        assert none.status == selftest.FAIL and b.id

    @pytest.mark.asyncio
    async def test_forecast(self, db_session, printer_factory, archive_factory):
        assert (await selftest.check_forecast(deps(db_session))).status == selftest.OK  # leere Warteschlange
        printer = await printer_factory()
        archive = await archive_factory(printer.id)
        await add_item(db_session, printer, archive)
        ok = await selftest.check_forecast(deps(db_session))
        assert ok.status == selftest.OK and "1" in ok.detail["de"]
        await add_item(db_session, printer, archive, seconds=None)
        unknown = await selftest.check_forecast(deps(db_session))
        assert (
            unknown.status == selftest.WARN
            and "keine Druckzeit" in unknown.detail["de"]
            and "no print time" in unknown.detail["en"]
        )

    @pytest.mark.asyncio
    async def test_forecast_warns_about_unplaceable_jobs(self, db_session, printer_factory, archive_factory):
        printer = await printer_factory(model="X1C")
        archive = await archive_factory(printer.id)
        await add_item(db_session, printer, archive, printer_id=None, target_model="H2D")
        result = await selftest.check_forecast(deps(db_session))
        assert result.status == selftest.WARN and "keinem Drucker" in result.detail["de"]

    @pytest.mark.asyncio
    async def test_channels(self, db_session, notification_provider_factory):
        assert (await selftest.check_channels(deps(db_session))).status == selftest.WARN
        await notification_provider_factory(on_queue_due_risk=False)
        no_event = await selftest.check_channels(deps(db_session))
        assert no_event.status == selftest.WARN and "Termin in Gefahr" in no_event.detail["de"]
        await notification_provider_factory(on_queue_due_risk=True, name="Handy")
        assert (await selftest.check_channels(deps(db_session))).status == selftest.OK


class TestProbes:
    @pytest.mark.asyncio
    async def test_notification_probe(self, db_session):
        sent = await selftest.probe_notification(
            deps(db_session, send_test_notification=AsyncMock(return_value=(2, [])))
        )
        assert sent.status == selftest.OK and "2" in sent.detail["de"]
        partly = await selftest.probe_notification(
            deps(db_session, send_test_notification=AsyncMock(return_value=(1, ["Handy (HTTP 500)"])))
        )
        assert partly.status == selftest.FAIL and "Handy (HTTP 500)" in partly.detail["de"]
        none = await selftest.probe_notification(deps(db_session))
        assert none.status == selftest.SKIP
        broken = await selftest.probe_notification(
            deps(db_session, send_test_notification=AsyncMock(side_effect=RuntimeError("Netz weg")))
        )
        assert broken.status == selftest.FAIL and "Netz weg" in broken.detail["en"]

    @pytest.mark.asyncio
    async def test_assistant_states_and_probe(self, db_session):
        config = {"enabled": True, "base_url": "http://x:1", "model": "m", "timeout_seconds": 60}
        off = await selftest.check_assistant(deps(db_session))
        assert off.status == selftest.SKIP
        down = await selftest.check_assistant(
            deps(db_session, assistant_config=config, assistant_status=AsyncMock(return_value={"reachable": False}))
        )
        assert down.status == selftest.FAIL and "http://x:1" in down.detail["de"]
        nomodel = await selftest.check_assistant(
            deps(
                db_session,
                assistant_config=config,
                assistant_status=AsyncMock(return_value={"reachable": True, "model_present": False}),
            )
        )
        assert nomodel.status == selftest.WARN and nomodel.fix["de"] == "ollama pull m"
        ready = await selftest.check_assistant(deps(db_session, assistant_config=config))
        assert ready.status == selftest.OK
        fast = await selftest.probe_assistant(deps(db_session, assistant_config=config), ready)
        assert fast.status == selftest.OK and "2.5" in fast.detail["de"]
        slow = await selftest.probe_assistant(
            deps(db_session, assistant_config=config, assistant_probe=AsyncMock(return_value=75.0)), ready
        )
        assert slow.status == selftest.WARN and slow.fix
        busy = await selftest.probe_assistant(
            deps(db_session, assistant_config=config, assistant_probe=AsyncMock(return_value=None)), ready
        )
        assert busy.status == selftest.SKIP
        failed = await selftest.probe_assistant(
            deps(
                db_session,
                assistant_config=config,
                assistant_probe=AsyncMock(side_effect=assistant_llm.AssistantError("zu langsam")),
            ),
            ready,
        )
        assert failed.status == selftest.FAIL and "zu langsam" in failed.detail["de"]
        skipped = await selftest.probe_assistant(deps(db_session, assistant_config=config), down)
        assert skipped.status == selftest.SKIP


class TestRun:
    @pytest.mark.asyncio
    async def test_runs_everything_in_a_fixed_order_with_a_summary_and_both_languages(self, db_session):
        german = await selftest.run(deps(db_session), "de")
        english = await selftest.run(deps(db_session), "en")
        ids = [r["id"] for r in german["results"]]
        assert ids == [
            "database",
            "scheduler",
            "due_watch",
            "printers",
            "forecast",
            "channels",
            "backup",
            "device",
            "auth",
            "update_guard",
            "assistant",
            "probe_notification",
            "probe_assistant",
        ]
        assert [r["id"] for r in english["results"]] == ids
        assert german["results"][0]["title"] == "Datenbank" and english["results"][0]["title"] == "Database"
        assert sum(german["summary"].values()) == len(ids) and german["checked_at"].endswith("+00:00")
        assert all(r["status"] in ("ok", "warn", "fail", "skip") and r["detail"] for r in german["results"])

    @pytest.mark.asyncio
    async def test_unknown_language_falls_back_to_german(self, db_session):
        assert (await selftest.run(deps(db_session), "fr"))["results"][0]["title"] == "Datenbank"

    @pytest.mark.asyncio
    async def test_a_crashing_check_is_reported_and_does_not_stop_the_others(self, db_session):
        def boom():
            raise RuntimeError("Planer kaputt")

        out = await selftest.run(deps(db_session, scheduler_running=boom), "en")
        scheduler = next(r for r in out["results"] if r["id"] == "scheduler")
        assert scheduler["status"] == "fail" and "Planer kaputt" in scheduler["detail"]
        assert len(out["results"]) == 13 and out["summary"]["fail"] >= 1

    @pytest.mark.asyncio
    async def test_a_failing_health_snapshot_does_not_break_the_run(self, db_session):
        def broken(_dir):
            raise OSError("kein /proc")

        out = await selftest.run(deps(db_session, health=broken), "de")
        assert next(r for r in out["results"] if r["id"] == "device")["status"] == "ok"


class TestSendTest:
    @pytest.mark.asyncio
    async def test_counts_successes_and_failures_per_channel_and_records_the_state(self, db_session):
        service = "backend.app.services.notification_service.notification_service"
        good, bad = SimpleNamespace(id=1, name="Handy"), SimpleNamespace(id=2, name="Mail")
        with (
            patch(f"{service}._get_providers_for_event", AsyncMock(return_value=[good, bad])),
            patch(f"{service}._build_message_from_template", AsyncMock(return_value=("Termin in Gefahr", "Text"))),
            patch(f"{service}._send_to_provider", AsyncMock(side_effect=[(True, None), (False, "SMTP 535")])) as send,
            patch(f"{service}._update_provider_status", AsyncMock()) as status,
        ):
            sent, failed = await queue_due_watch.send_test(db_session)
        assert sent == 1 and failed == ["Mail (SMTP 535)"]
        assert send.call_args_list[0].args[1] == "Test: Termin in Gefahr"
        assert [c.args[1:] for c in status.call_args_list] == [(1, True, None), (2, False, "SMTP 535")]

    @pytest.mark.asyncio
    async def test_without_wanting_channels_nothing_is_sent(self, db_session):
        with patch(
            "backend.app.services.notification_service.notification_service._get_providers_for_event",
            AsyncMock(return_value=[]),
        ):
            assert await queue_due_watch.send_test(db_session) == (0, [])


class TestWatchState:
    @pytest.mark.asyncio
    async def test_the_loop_records_start_and_successful_runs(self, monkeypatch):
        monkeypatch.setattr(queue_due_watch, "STATE", {"started": None, "last_run": None, "last_error": None})
        calls = {"n": 0}

        async def fake_sleep(_seconds):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise asyncio.CancelledError

        class Session:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *_):
                return None

        monkeypatch.setattr(queue_due_watch.asyncio, "sleep", fake_sleep)
        with (
            patch.object(queue_due_watch, "check_due_dates", AsyncMock(return_value=[])),
            pytest.raises(asyncio.CancelledError),
        ):
            await queue_due_watch.run(Session, interval=1)
        assert queue_due_watch.STATE["started"] is not None and queue_due_watch.STATE["last_run"] is not None
        assert queue_due_watch.STATE["last_error"] is None

    @pytest.mark.asyncio
    async def test_the_loop_records_an_error_and_keeps_going(self, monkeypatch):
        monkeypatch.setattr(queue_due_watch, "STATE", {"started": None, "last_run": None, "last_error": None})
        calls = {"n": 0}

        async def fake_sleep(_seconds):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise asyncio.CancelledError

        class Session:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *_):
                return None

        monkeypatch.setattr(queue_due_watch.asyncio, "sleep", fake_sleep)
        with (
            patch.object(queue_due_watch, "check_due_dates", AsyncMock(side_effect=RuntimeError("DB weg"))),
            pytest.raises(asyncio.CancelledError),
        ):
            await queue_due_watch.run(Session, interval=1)
        assert queue_due_watch.STATE["last_error"] == "DB weg" and queue_due_watch.STATE["last_run"] is None


class TestApi:
    @pytest.fixture(autouse=True)
    def quiet(self, tmp_path, monkeypatch):
        monkeypatch.setattr(route, "settings", SimpleNamespace(base_dir=tmp_path))
        with (
            patch.object(route.queue_due_watch, "send_test", AsyncMock(return_value=(0, []))),
            patch.object(route.pi_health, "snapshot", lambda _dir: {"warnings": []}),
        ):
            yield

    @pytest.mark.asyncio
    async def test_runs_and_answers_in_the_requested_language(self, async_client: AsyncClient):
        german = (await async_client.post("/api/v1/selftest")).json()
        english = (await async_client.post("/api/v1/selftest", headers={"Accept-Language": "en"})).json()
        assert german["results"][0]["title"] == "Datenbank" and english["results"][0]["title"] == "Database"
        assert len(german["results"]) == 13 and set(german["summary"]) == {"ok", "warn", "fail", "skip"}

    @pytest.mark.asyncio
    async def test_a_second_run_at_the_same_time_gets_429(self, async_client: AsyncClient):
        async with route._lock:
            resp = await async_client.post("/api/v1/selftest", headers={"Accept-Language": "en"})
        assert resp.status_code == 429 and resp.json()["detail"] == "The system check is already running."
        assert (await async_client.post("/api/v1/selftest")).status_code == 200

    @pytest.mark.asyncio
    async def test_the_probe_and_the_probe_message_really_run(self, async_client: AsyncClient, tmp_path):
        from backend.app.services import assistant_config

        assistant_config.write(tmp_path, {"enabled": True})
        server = {"reachable": True, "models": ["qwen2.5:3b"], "model_present": True, "error": ""}
        with (
            patch.object(route.assistant_llm, "status", AsyncMock(return_value=server)),
            patch.object(route.assistant_llm, "probe", AsyncMock(return_value=3.2)) as probe,
            patch.object(route.queue_due_watch, "send_test", AsyncMock(return_value=(1, []))) as notify,
        ):
            body = (await async_client.post("/api/v1/selftest")).json()
        results = {r["id"]: r for r in body["results"]}
        assert results["probe_assistant"]["status"] == "ok" and probe.await_count == 1
        assert results["probe_notification"]["status"] == "ok" and notify.await_count == 1

    def test_the_guard_state_follows_the_unit_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(route.Path, "home", classmethod(lambda cls: tmp_path))
        assert route._guard_state() == "no_unit"
        unit = tmp_path / ".config" / "systemd" / "user"
        unit.mkdir(parents=True)
        (unit / "printlab.service").write_text("[Service]\nExecStart=/x\n", encoding="utf-8")
        assert route._guard_state() == "missing"
        (unit / "printlab.service").write_text("[Service]\nExecStartPre=/x/update_guard.py\n", encoding="utf-8")
        assert route._guard_state() == "ok"
