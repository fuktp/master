from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from orquestrador_app.config import Config, Routine
from orquestrador_app.engine import Engine
from orquestrador_app.paths import Paths
from orquestrador_app.schedule import eligible, freshness, next_execution


def clock(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text)


def empty() -> dict:
    return {"periods": set(), "occurrences": set(), "last_success": None}


def test_own_time_outside_global_schedule() -> None:
    job = Routine("one", "one", "one.py")
    job.schedule.times = ["18:07"]
    assert not eligible(job, empty(), clock("2026-10-21T18:06:59-03:00")).due
    assert eligible(job, empty(), clock("2026-10-21T18:07:00-03:00")).due


def test_daily_multiple_opportunities_and_force_disabled() -> None:
    job = Routine("one", "one", "one.py")
    job.schedule.times = ["08:30", "12:21", "18:07"]
    state = empty()
    state["periods"].add("D:2026-10-21")
    now = clock("2026-10-21T18:07:00-03:00")
    assert not eligible(job, state, now).due
    assert eligible(job, state, now, force=True).due
    job.enabled = False
    assert not eligible(job, state, now, force=True).due


def test_every_run_catch_up_collapses_and_persists_occurrences() -> None:
    job = Routine("one", "one", "one.py")
    job.schedule.frequency = "every_run"
    job.schedule.times = ["08:30", "10:30", "12:30", "18:07"]
    state = empty()
    now = clock("2026-10-21T17:00:00-03:00")
    decision = eligible(job, state, now)
    assert decision.occurrence == "2026-10-21T12:30"
    state["occurrences"].add(decision.occurrence)
    assert not eligible(job, state, now).due
    assert eligible(job, state, clock("2026-10-21T18:07:00-03:00")).due


def test_weekly_initial_day_and_recovery() -> None:
    job = Routine("one", "one", "one.py")
    job.schedule.frequency = "weekly"
    job.schedule.weekday = 2
    now = clock("2026-10-20T18:07:00-03:00")
    assert not eligible(job, empty(), now).due
    assert eligible(job, empty(), clock("2026-10-22T10:00:00-03:00")).due
    state = empty()
    state["periods"].add("W:2026-10-19")
    assert not eligible(job, state, clock("2026-10-23T10:00:00-03:00")).due
    assert eligible(job, state, clock("2026-10-28T10:00:00-03:00")).due


def test_dst_fold_and_timezone_change_do_not_duplicate_slot_or_period() -> None:
    job = Routine("one", "one", "one.py")
    job.schedule.frequency = "every_run"
    job.schedule.times = ["01:30"]
    job.schedule.days = list(range(7))
    zone = ZoneInfo("America/New_York")
    first = dt.datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = first.replace(fold=1)
    state = empty()
    state["occurrences"].add(eligible(job, state, first).occurrence)
    assert not eligible(job, state, second).due
    job.schedule.frequency = "daily"
    state["periods"].add("D:2026-11-01")
    assert not eligible(job, state, second.astimezone(ZoneInfo("Europe/London"))).due


def test_next_execution_considers_success_pause_and_days() -> None:
    job = Routine("one", "one", "one.py")
    state = empty()
    state["periods"].add("D:2026-10-23")
    now = clock("2026-10-23T18:07:00-03:00")
    assert next_execution(job, state, now).isoformat() == "2026-10-26T08:30:00-03:00"
    assert next_execution(job, state, now, paused=True) is None


def test_freshness_counts_configured_calendar() -> None:
    job = Routine("one", "one", "one.py", expected_hours=24, grace_hours=0)
    config = Config(routines=[job])
    state = empty()
    assert freshness(config, job, state, clock("2026-10-23T18:07:00-03:00")) == "nunca atualizada"
    state["last_success"] = {"at": "2026-10-23T18:00:00-03:00"}
    assert freshness(config, job, state, clock("2026-10-26T08:00:00-03:00")) == "atualizada"
    assert freshness(config, job, state, clock("2026-10-27T08:00:00-03:00")) == "atrasada"


def test_engine_restarts_daily_success_and_login_does_not_consume(
    environment: tuple[Paths, Config],
) -> None:
    paths, config = environment
    calls = []

    def fake(*args: object) -> dict:
        calls.append(args)
        return {"code": 0}

    now = dt.datetime.now().astimezone().replace(hour=23, minute=59)
    for job in config.routines:
        job.schedule.days = list(range(7))
    engine = Engine(paths, config, runner=fake)
    engine.run([config.routines[0].id], login=True, now=now)
    assert engine.store.state(config.routines[0].id)["last_success"] is None
    engine.run([config.routines[0].id], now=now)
    restarted = Engine(paths, config, runner=fake)
    result = restarted.run([config.routines[0].id], now=now)
    assert result[0]["status"] == "not_eligible"
    assert len(calls) == 2
    assert restarted.run([config.routines[0].id], force=True, now=now)[0]["status"] == "success"


@pytest.mark.parametrize("code", [1, 20, 130])
def test_failure_does_not_consume_frequency(environment: tuple[Paths, Config], code: int) -> None:
    paths, config = environment
    job = config.routines[0]
    result = Engine(paths, config, runner=lambda *args: {"code": code, "category": "vpn"}).run(
        [job.id], force=True
    )
    assert result[0]["status"] != "success"
    assert Engine(paths, config).store.state(job.id)["last_success"] is None
