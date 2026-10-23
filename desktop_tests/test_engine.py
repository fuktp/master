from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from orquestrador_app.config import Config, Dependency, Retry, from_dict, to_dict
from orquestrador_app.engine import Engine
from orquestrador_app.io import BusyError, Lock
from orquestrador_app.notifications import enqueue
from orquestrador_app.paths import Paths, onedrives


def test_dependency_failure_disabled_and_independent_continues(
    environment: tuple[Paths, Config],
) -> None:
    paths, config = environment
    origin, dependent, independent = config.routines
    dependent.dependencies = [Dependency(origin.id)]
    config.continue_on_error = True
    calls = []

    def runner(job: object, *args: object) -> dict:
        calls.append(job.id)
        return {"code": 1 if job.id == origin.id else 0}

    result = Engine(paths, config, runner).run(force=True)
    assert [r["status"] for r in result] == ["failed", "blocked_dependency", "success"]
    assert dependent.id not in calls and independent.id in calls
    origin.enabled = False
    assert (
        Engine(paths, config, runner).run([dependent.id], force=True)[0]["status"]
        == "blocked_dependency"
    )


def test_previous_success_requires_explicit_window_and_same_chain_cannot_reuse_it(
    environment: tuple[Paths, Config],
) -> None:
    paths, config = environment
    origin, dependent, _ = config.routines
    engine = Engine(paths, config, lambda *args: {"code": 0})
    engine.run([origin.id], force=True)
    dependent.dependencies = [Dependency(origin.id)]
    assert engine.run([dependent.id], force=True)[0]["status"] == "blocked_dependency"
    dependent.dependencies = [Dependency(origin.id, "fresh_success", 60)]
    assert engine.run([dependent.id], force=True)[0]["status"] == "success"
    now = dt.datetime.now().astimezone() + dt.timedelta(hours=2)
    assert engine.run([dependent.id], force=True, now=now)[0]["status"] == "blocked_dependency"


def test_cycles_and_unspecified_validity_rejected(environment: tuple[Paths, Config]) -> None:
    _, config = environment
    config.routines[0].dependencies = [Dependency(config.routines[1].id)]
    config.routines[1].dependencies = [Dependency(config.routines[0].id)]
    with pytest.raises(ValueError, match="Ciclo"):
        from_dict(to_dict(config))
    config.routines[0].dependencies.clear()
    config.routines[1].dependencies = [Dependency(config.routines[0].id, "fresh_success")]
    with pytest.raises(ValueError, match="janela"):
        from_dict(to_dict(config))


def test_kwms_code20_no_external_retry_and_continues_even_fail_fast(
    environment: tuple[Paths, Config],
) -> None:
    paths, config = environment
    config.continue_on_error = False
    calls = []

    def runner(job: object, *args: object) -> dict:
        calls.append(job.id)
        return {"code": 20 if job.id == config.routines[0].id else 0, "category": "vpn"}

    result = Engine(paths, config, runner).run(force=True)
    assert [r["status"] for r in result] == ["skipped", "success", "success"]
    assert len(calls) == 3


def test_category_retry_limit_and_auth_no_loop(environment: tuple[Paths, Config]) -> None:
    paths, config = environment
    job = config.routines[0]
    job.retries["server"] = Retry(attempts=2, delay_seconds=0)
    calls = []

    def runner(*args: object) -> dict:
        calls.append(1)
        return {"code": 1, "category": "server"} if len(calls) == 1 else {"code": 0}

    assert Engine(paths, config, runner).run([job.id], force=True)[0]["status"] == "success"
    assert len(calls) == 2
    calls.clear()

    def auth(*args: object) -> dict:
        calls.append(1)
        return {"code": 1, "category": "authentication"}

    Engine(paths, config, auth).run([job.id], force=True)
    assert len(calls) == 1


def test_cancelled_origin_blocks_dependent_but_independent_can_continue(
    environment: tuple[Paths, Config],
) -> None:
    paths, config = environment
    config.continue_on_error = True
    origin, dependent, independent = config.routines
    dependent.dependencies = [Dependency(origin.id)]
    result = Engine(paths, config, lambda j, *args: {"code": 130 if j.id == origin.id else 0}).run(
        force=True
    )
    assert [r["status"] for r in result] == ["cancelled", "blocked_dependency", "success"]


def test_fail_fast_still_records_dependency_blocks(environment: tuple[Paths, Config]) -> None:
    paths, config = environment
    origin, dependent, independent = config.routines
    dependent.dependencies = [Dependency(origin.id)]
    result = Engine(paths, config, lambda *args: {"code": 1}).run(force=True)
    assert [r["status"] for r in result] == ["failed", "blocked_dependency", "ignored"]


def test_locked_file_retry_only_republishes_staged_file(
    environment: tuple[Paths, Config], tmp_path: Path
) -> None:
    paths, config = environment
    job = config.routines[0]
    job.retries["locked_file"] = Retry(attempts=2, delay_seconds=0)
    calls = []

    def runner(*args: object) -> dict:
        calls.append(args)
        return (
            {"code": 1, "category": "locked_file", "retry_input": str(tmp_path / "staged.xlsx")}
            if len(calls) == 1
            else {"code": 0}
        )

    Engine(paths, config, runner).run([job.id], force=True)
    assert len(calls) == 2
    assert calls[0][3] == "run" and calls[1][3] == "replace"
    assert calls[1][4] == tmp_path / "staged.xlsx"


def test_simulate_does_not_run_or_consume_frequency(environment: tuple[Paths, Config]) -> None:
    paths, config = environment

    def forbidden(*args: object) -> dict:
        raise AssertionError("simulação não pode executar")

    engine = Engine(paths, config, forbidden)
    assert all(r["status"] == "simulation" for r in engine.run(force=True, simulate=True))
    assert engine.store.history() == []


def test_os_lock_excludes_second_owner_and_releases_after_exit(tmp_path: Path) -> None:
    path = tmp_path / "shared.lock"
    with Lock(path):
        with pytest.raises(BusyError):
            with Lock(path):
                pass
    with Lock(path):
        pass


def test_notification_dedupe_and_headless_monitor(environment: tuple[Paths, Config]) -> None:
    paths, config = environment
    engine = Engine(paths, config, lambda *args: {"code": 0})
    engine.monitor()
    engine.monitor()
    with engine.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM notifications WHERE delivered=0").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM notifications WHERE delivered=2").fetchone()[0] == 3
    assert not enqueue(engine.store, config, "stale", config.routines[0].id, "", "again")


def test_onedrive_multiple_accounts_never_collapses_distinct_accounts() -> None:
    values = onedrives(
        {
            "OneDriveCommercial": "/profile/OneDrive - Empresa",
            "OneDriveConsumer": "/profile/OneDrive",
            "OneDrive": "/profile/OneDrive - Empresa",
        }
    )
    assert len(values) == 2
    assert {v["kind"] for v in values} == {"corporativa", "pessoal"}


def test_sanitized_diagnostic_omits_internal_urls_tokens_email_ip_and_paths(
    environment: tuple[Paths, Config], tmp_path: Path
) -> None:
    paths, config = environment
    engine = Engine(paths, config)
    run = engine.store.begin("batch", config.routines[0].id, "extraction", None)
    engine.store.event(
        run,
        "debug",
        {
            "url": "https://internal.invalid/path?token=secret",
            "Authorization": "Bearer secret",
            "detail": r"C:\Users\person\secret\file.xlsx",
            "user": "person@example.invalid",
            "address": "10.1.2.3",
        },
    )
    filename = tmp_path / "diagnostic.json"
    engine.store.export(filename)
    text = filename.read_text()
    assert (
        "internal.invalid" not in text and "person@example" not in text and "10.1.2.3" not in text
    )
    assert "Bearer secret" not in text
