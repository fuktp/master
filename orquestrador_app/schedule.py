from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable

from .config import Config, Routine


@dataclass(frozen=True)
class Eligibility:
    due: bool
    reason: str
    occurrence: str | None = None
    period: str | None = None


def clocks_for(job: Routine, day: dt.date) -> list[str]:
    return sorted(job.schedule.day_times.get(str(day.weekday()), job.schedule.times))


def paused_until(value: str, now: dt.datetime) -> bool:
    return bool(value and dt.datetime.fromisoformat(value) > now)


def period_for(job: Routine, now: dt.datetime) -> str | None:
    day = now.date()
    if job.schedule.frequency in {"daily", "weekdays"}:
        return f"D:{day.isoformat()}"
    if job.schedule.frequency == "weekly":
        return f"W:{(day - dt.timedelta(days=day.weekday())).isoformat()}"
    return None


def satisfied(job: Routine, state: dict[str, Any], now: dt.datetime) -> bool:
    period = period_for(job, now)
    if not period:
        return False
    if period in state.get("periods", set()):
        return True
    success = state.get("last_success")
    if not success:
        return False
    previous = dt.datetime.fromisoformat(success["at"])
    previous = previous.astimezone(now.tzinfo)
    return period_for(job, previous) == period


def eligible(
    job: Routine,
    state: dict[str, Any],
    now: dt.datetime,
    *,
    manual: bool = False,
    force: bool = False,
    paused: bool = False,
    excluded_dates: Iterable[str] = (),
) -> Eligibility:
    if not job.enabled:
        return Eligibility(False, "desabilitada")
    if not manual and (
        paused or job.schedule.paused or paused_until(job.schedule.paused_until, now)
    ):
        return Eligibility(False, "agendamento pausado")
    if force:
        return Eligibility(True, "forçada", period=period_for(job, now))
    if satisfied(job, state, now):
        return Eligibility(False, "sucesso já concluído neste período")
    excluded = set(excluded_dates) | set(job.schedule.excluded_dates)
    if now.date().isoformat() in excluded:
        return Eligibility(False, "data excluída do calendário")
    if job.schedule.frequency == "weekdays" and now.weekday() >= 5:
        return Eligibility(False, "somente dias úteis")
    if now.weekday() not in job.schedule.days:
        return Eligibility(False, "dia não habilitado")
    schedule = job.schedule
    if schedule.frequency == "weekly":
        week_start = now.date() - dt.timedelta(days=now.weekday())
        start = dt.datetime.combine(
            week_start + dt.timedelta(days=schedule.weekday),
            dt.time.fromisoformat(
                min(clocks_for(job, week_start + dt.timedelta(days=schedule.weekday)))
            ),
            now.tzinfo,
        )
        if now < start:
            return Eligibility(False, "aguardando dia e horário semanais")
    if manual:
        # A manual batch respects enabled/days/frequency; a force request alone bypasses frequency.
        return Eligibility(True, "disparo manual elegível", period=period_for(job, now))
    candidates = []
    # Collapse missed occurrences to the newest eligible opportunity: never replay a backlog.
    for offset in range(min(schedule.catch_up_hours // 24 + 2, 9)):
        day = now.date() - dt.timedelta(days=offset)
        if day.weekday() not in schedule.days:
            continue
        if day.isoformat() in excluded:
            continue
        if schedule.frequency in {"daily", "weekdays"} and day != now.date():
            continue
        if schedule.frequency == "weekly" and day < start.date():
            continue
        for clock in clocks_for(job, day):
            candidate = dt.datetime.combine(day, dt.time.fromisoformat(clock), now.tzinfo)
            age = now.timestamp() - candidate.timestamp()
            if 0 <= age <= schedule.catch_up_hours * 3600:
                candidates.append(candidate)
    if not candidates:
        return Eligibility(False, "aguardando horário próprio")
    candidate = max(candidates)
    # Wall-clock identity avoids repeating the same slot after a backward clock/DST change.
    occurrence = f"{candidate.date().isoformat()}T{candidate:%H:%M}"
    attempted = state.get("occurrences", set())
    if any(slot >= occurrence for slot in attempted if not slot.startswith("manual:")):
        return Eligibility(False, "oportunidade já tentada; aguardando próximo horário")
    return Eligibility(True, "horário próprio ou recuperação", occurrence, period_for(job, now))


def next_execution(
    job: Routine,
    state: dict[str, Any],
    now: dt.datetime,
    paused: bool = False,
    excluded_dates: Iterable[str] = (),
) -> dt.datetime | None:
    if not job.enabled or job.schedule.paused or paused:
        return None
    if paused_until(job.schedule.paused_until, now):
        resume = dt.datetime.fromisoformat(job.schedule.paused_until).astimezone(now.tzinfo)
        return next_execution(job, state, resume, paused, excluded_dates)
    if eligible(job, state, now, excluded_dates=excluded_dates).due:
        return now
    for offset in range(15):
        day = now.date() + dt.timedelta(days=offset)
        for clock in clocks_for(job, day):
            candidate = dt.datetime.combine(day, dt.time.fromisoformat(clock), now.tzinfo)
            if (
                candidate > now
                and eligible(job, state, candidate, excluded_dates=excluded_dates).due
            ):
                return candidate
    return None


def opportunities(
    job: Routine, state: dict[str, Any], now: dt.datetime, config: Config, days: int = 7
) -> list[dict[str, Any]]:
    result = []
    current = eligible(
        job,
        state,
        now,
        paused=config.scheduling_paused or paused_until(config.paused_until, now),
        excluded_dates=config.calendar.get("dates", []),
    )
    if current.due:
        result.append(
            {
                "at": now.isoformat(),
                "eligible": True,
                "reason": current.reason,
                "period": current.period,
                "occurrence": current.occurrence,
                "catch_up_hours": job.schedule.catch_up_hours,
                "recovering": True,
            }
        )
    for offset in range(days):
        day = now.date() + dt.timedelta(days=offset)
        if day.weekday() not in job.schedule.days:
            continue
        for clock in clocks_for(job, day):
            candidate = dt.datetime.combine(day, dt.time.fromisoformat(clock), now.tzinfo)
            if candidate < now:
                continue
            decision = eligible(
                job,
                state,
                candidate,
                paused=config.scheduling_paused or paused_until(config.paused_until, candidate),
                excluded_dates=config.calendar.get("dates", []),
            )
            result.append(
                {
                    "at": candidate.isoformat(),
                    "eligible": decision.due,
                    "reason": decision.reason,
                    "period": decision.period,
                    "catch_up_hours": job.schedule.catch_up_hours,
                }
            )
    return result


def freshness(config: Config, job: Routine, state: dict[str, Any], now: dt.datetime) -> str:
    if not job.enabled:
        return "desabilitada"
    if (
        config.scheduling_paused
        or job.schedule.paused
        or paused_until(config.paused_until, now)
        or paused_until(job.schedule.paused_until, now)
    ):
        return "pausada"
    for dependency in job.dependencies:
        if not config.job(dependency.job).enabled:
            return "bloqueada por origem desabilitada"
    success = state.get("last_success")
    if not success:
        return "nunca atualizada"
    at = dt.datetime.fromisoformat(success["at"])
    # Count permitted weekdays, retaining the actual fractional local-day interval.
    cursor = at.astimezone(now.tzinfo)
    elapsed = 0.0
    while cursor < now:
        boundary = dt.datetime.combine(cursor.date() + dt.timedelta(days=1), dt.time(), now.tzinfo)
        end = min(boundary, now)
        if cursor.weekday() in job.schedule.days:
            elapsed += max(0, end.timestamp() - cursor.timestamp()) / 3600
        cursor = end
    deadline = job.expected_hours + job.grace_hours
    return "atrasada" if elapsed > deadline else "atualizada"
