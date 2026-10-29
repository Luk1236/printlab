"""Server-Prognose der Warteschlange; gleiche Fälle wie ``frontend/src/__tests__/utils/queueForecast.test.ts``."""

import itertools
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.services.queue_forecast import PrinterLive, forecast_ends

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)
HOUR = timedelta(hours=1)
_seq = itertools.count(1)


def printer(pid, model="X1C", **over):
    return SimpleNamespace(**{"id": pid, "model": model, "location": None, "is_active": True, **over})


def job(**over):
    n = next(_seq)
    base = {
        "id": n, "status": "pending", "printer_id": None, "target_model": None, "target_location": None,
        "waiting_reason": None, "manual_start": False, "position": n, "priority": 1, "print_time_seconds": 3600,
        "scheduled_time": None, "variants": [], "been_jumped": False,
    }  # fmt: skip
    return SimpleNamespace(**{**base, **over})


def run(items, printers, live=None, sjf=False):
    return forecast_ends(items, printers, live or {}, sjf, NOW)


def test_chains_pinned_jobs_behind_the_running_print():
    a, b = job(printer_id=1), job(printer_id=1, print_time_seconds=1800)
    ends = run([a, b], [printer(1)], {1: PrinterLive(remaining_minutes=30, state="RUNNING")})
    assert ends[a.id] == NOW + 90 * MIN
    assert ends[b.id] == NOW + 120 * MIN


def test_spreads_model_based_jobs_by_earliest_free_time():
    jobs = [job(target_model="X1C") for _ in range(3)]
    live = {1: PrinterLive(remaining_minutes=120, state="RUNNING"), 2: PrinterLive(state="IDLE")}
    ends = run(jobs, [printer(1), printer(2), printer(3, "P1S")], live)
    assert [ends[j.id] for j in jobs] == [NOW + 60 * MIN, NOW + 120 * MIN, NOW + 180 * MIN]


def test_location_filter_and_cross_model_variants():
    in_cellar = job(target_model="X1C", target_location="Keller")
    cross = job(target_model="A1", variants=[SimpleNamespace(target_model="P1S")])
    printers = [printer(1, location="Werkstatt"), printer(2, location="Keller"), printer(3, "P1S")]
    ends = run([in_cellar, cross], printers)
    assert ends[in_cellar.id] == NOW + HOUR and ends[cross.id] == NOW + HOUR
    assert len(ends) == 2


def test_priority_sorts_before_position():
    normal, urgent = job(printer_id=1, position=0), job(printer_id=1, position=5, priority=2)
    ends = run([normal, urgent], [printer(1)])
    assert ends[urgent.id] == NOW + HOUR and ends[normal.id] == NOW + 2 * HOUR


def test_shortest_job_first_only_inside_a_priority():
    long_, short = (
        job(printer_id=1, print_time_seconds=9000, position=0),
        job(printer_id=1, print_time_seconds=60, position=1),
    )
    ends = run([long_, short], [printer(1)], sjf=True)
    assert ends[short.id] < ends[long_.id]
    urgent_long = job(printer_id=1, print_time_seconds=9000, priority=2)
    short2 = job(printer_id=1, print_time_seconds=60)
    ends = run([urgent_long, short2], [printer(1)], sjf=True)
    assert ends[urgent_long.id] < ends[short2.id]


def test_leaves_out_staged_blocked_unknown_and_unplaceable_jobs():
    staged = job(printer_id=1, manual_start=True)
    blocked = job(printer_id=1, waiting_reason="Waiting for filament: P1 (needs PETG)")
    busy = job(printer_id=1, waiting_reason="Busy: P1")
    unknown = job(printer_id=1, print_time_seconds=None)
    nowhere = job(target_model="H2D")
    loose = job()
    ends = run([staged, blocked, busy, unknown, nowhere, loose], [printer(1)])
    assert list(ends) == [busy.id]


def test_a_scheduled_job_starts_no_earlier_than_its_time():
    later = job(printer_id=1, scheduled_time=NOW + 5 * HOUR)
    assert run([later], [printer(1)])[later.id] == NOW + 6 * HOUR
    naive = job(printer_id=1, scheduled_time=(NOW + 2 * HOUR).replace(tzinfo=None))
    assert run([naive], [printer(1)])[naive.id] == NOW + 3 * HOUR


def test_progress_fallback_and_inactive_printers():
    running = job(status="printing", printer_id=1, print_time_seconds=7200)
    nxt = job(printer_id=1)
    ends = run(
        [running, nxt], [printer(1), printer(2, is_active=False)], {1: PrinterLive(progress=50, state="RUNNING")}
    )
    assert ends[nxt.id] == NOW + 2 * HOUR
    only_inactive = job(printer_id=2)
    assert run([only_inactive], [printer(2, is_active=False)]) == {}


def test_a_running_print_without_any_estimate_counts_one_hour_and_empty_input():
    running = job(status="printing", printer_id=1, print_time_seconds=None)
    nxt = job(printer_id=1)
    assert run([running, nxt], [printer(1)])[nxt.id] == NOW + 2 * HOUR
    assert run([], [printer(1)]) == {}


def test_model_names_ignore_case_and_punctuation():
    j = job(target_model="x1-c")
    assert j.id in run([j], [printer(1, "X1C")])
