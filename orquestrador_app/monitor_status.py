"""Owned monitor heartbeat, process identity and truthful scheduler observations."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psutil

from . import VERSION
from .config import Config
from .io import atomic_json, read_json
from .paths import Paths
from .schedule import next_execution, paused_until, period_for
from .store import Store


def write_heartbeat(paths: Paths, *, interval: int, state: str, error: str = "") -> None:
    process = psutil.Process()
    atomic_json(
        paths.root / "state/monitor-heartbeat.json",
        {
            "version": VERSION,
            "pid": process.pid,
            "created": process.create_time(),
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "interval": interval,
            "state": state,
            "error": error,
        },
    )


def monitor_state(
    paths: Paths,
    config: Config,
    *,
    installed: bool | None = None,
    task_error: str = "",
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    if config.execution_profile == "portable_gui":
        from .io import BusyError, Lock

        try:
            with Lock(paths.lock):
                active = False
        except BusyError:
            active = True
        check_file = paths.root / "state/scheduler-check.json"
        check = read_json(check_file) if check_file.is_file() else {}
        paused = config.scheduling_paused or paused_until(config.paused_until, now)
        return {
            "state": "active"
            if active
            else "paused"
            if paused
            else "installed"
            if installed
            else "configured",
            "configured": True,
            "installed": installed,
            "active": active,
            "paused": paused,
            "communicating": False,
            "last_seen": check.get("at", ""),
            "unexpected_stop": False,
            "error": task_error or check.get("error", ""),
            "task_status_known": installed is not None,
        }
    file = paths.root / "state/monitor-heartbeat.json"
    value: dict[str, Any] = {}
    try:
        if file.is_file():
            value = read_json(file)
        age = (
            now.timestamp() - dt.datetime.fromisoformat(value["at"]).timestamp() if value else None
        )
        process = psutil.Process(int(value["pid"])) if value else None
        active = bool(
            process
            and abs(process.create_time() - float(value["created"])) < 0.01
            and process.is_running()
            and value.get("state") != "stopped"
        )
    except (ValueError, KeyError, OSError, psutil.Error):
        age, active = None, False
    fresh = age is not None and 0 <= age <= max(15, int(value.get("interval", 30)) * 2 + 10)
    paused = config.scheduling_paused or paused_until(config.paused_until, now)
    state = (
        "stopped"
        if value.get("state") == "stopped"
        else "paused"
        if active and fresh and paused
        else "active"
        if active and fresh
        else "no_communication"
        if active or value
        else "installed"
        if installed
        else "configured"
        if config.install_schedules
        else "disabled"
    )
    return {
        "state": state,
        "configured": config.install_schedules,
        "installed": installed,
        "active": active,
        "paused": paused,
        "communicating": fresh and active,
        "last_seen": value.get("at", ""),
        "age_seconds": age,
        "pid": value.get("pid"),
        "unexpected_stop": bool(value and value.get("state") != "stopped" and not active),
        "error": task_error or value.get("error", ""),
        "task_status_known": installed is not None,
    }


def poll_seconds(config: Config, store: Store, now: dt.datetime, running: bool = False) -> int:
    if running:
        return 1
    if config.scheduling_paused or paused_until(config.paused_until, now):
        return 30
    nearest = 30.0
    for job in config.routines:
        state = store.decision_state(job.id, period_for(job, now))
        upcoming = next_execution(job, state, now, excluded_dates=config.calendar.get("dates", []))
        if upcoming:
            nearest = min(nearest, upcoming.timestamp() - now.timestamp())
    return max(1, min(30, int(nearest)))
