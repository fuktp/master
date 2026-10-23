from __future__ import annotations

import datetime as dt
import getpass
import platform
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import VERSION
from .clock import local_now
from .config import Config, Routine, load, ordered, to_dict
from .io import Lock, atomic_json, read_json, sanitize
from .notifications import enqueue
from .paths import Paths
from .processes import OwnedTree, command, spawn
from .schedule import (
    Eligibility,
    eligible,
    freshness,
    next_execution,
    opportunities,
    paused_until,
    period_for,
)
from .store import Store


class Engine:
    def __init__(
        self,
        paths: Paths,
        config: Config | None = None,
        runner: Callable[..., dict[str, Any]] | None = None,
        *,
        store: Store | None = None,
    ):
        self.paths = paths
        paths.ensure()
        self.config = config or load(paths)
        if self.config.test_mode:
            from .sandbox import validate_isolation

            validate_isolation(paths, self.config)
        self.store = store or Store(paths.database)
        self.runner = runner or self.run_worker
        self.batch = ""
        self.deadlines: dict[str, float] = {}

    def dependency_error(self, job: Routine, chain: dict[str, str], now: dt.datetime) -> str:
        for dependency in job.dependencies:
            origin = self.config.job(dependency.job)
            if not origin.enabled:
                return f"Origem desabilitada: {origin.label}"
            if dependency.mode == "same_chain":
                if chain.get(origin.id) != "success":
                    return f"Sucesso exigido nesta cadeia: {origin.label}"
            else:
                success = self.store.decision_state(origin.id, period_for(origin, now))[
                    "last_success"
                ]
                if not success:
                    return f"Origem sem sucesso: {origin.label}"
                age = now.timestamp() - dt.datetime.fromisoformat(success["at"]).timestamp()
                if not 0 <= age <= dependency.max_age_minutes * 60:
                    return f"Sucesso fora da validade: {origin.label}"
        return ""

    def run(
        self,
        names: list[str] | None = None,
        *,
        scheduled: bool = False,
        force: bool = False,
        simulate: bool = False,
        login: bool = False,
        source: Path | None = None,
        now: dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        now = now or local_now()
        if simulate:
            return self.preview(names, scheduled=scheduled, force=force, now=now)
        self.batch = str(uuid.uuid4())
        results: list[dict[str, Any]] = []
        if names and set(names) - {j.id for j in self.config.routines}:
            raise ValueError("Rotina não cadastrada.")
        with Lock(self.paths.lock):
            self.store.recover_interrupted()
            self.store.event(
                None,
                "batch",
                {
                    "batch": self.batch,
                    "version": VERSION,
                    "user": getpass.getuser(),
                    "computer": platform.node(),
                    "mode": "scheduled" if scheduled else "manual",
                    "configuration": sanitize(to_dict(self.config), export=True),
                },
            )
            chain: dict[str, str] = {}
            previous_finished: float | None = None
            for job in ordered(self.config):
                if names and job.id not in names:
                    continue
                if self.store.control("batch:" + self.batch) == "cancel":
                    decision = Eligibility(False, "lote cancelado")
                else:
                    decision = eligible(
                        job,
                        self.store.decision_state(job.id, period_for(job, now)),
                        now,
                        manual=not scheduled,
                        force=force,
                        paused=(
                            self.config.scheduling_paused
                            or paused_until(self.config.paused_until, now)
                        )
                        if scheduled
                        else False,
                        excluded_dates=self.config.calendar.get("dates", []),
                    )
                if (login or source) and job.enabled:
                    decision = Eligibility(True, "teste de login" if login else "publicação local")
                if not decision.due:
                    status = "ignored" if not job.enabled else "not_eligible"
                    run = None
                    if not simulate:
                        run = self.store.begin(self.batch, job.id, "eligibility", None)
                        self.store.finish(run, status, evidence=decision.reason)
                    results.append(
                        {"job": job.id, "run": run, "status": status, "reason": decision.reason}
                    )
                    chain[job.id] = status
                    continue
                occurrence = decision.occurrence if scheduled else None
                run = self.store.begin(
                    self.batch,
                    job.id,
                    "login" if login else ("local_publication" if source else "extraction"),
                    occurrence,
                )
                reason = "" if login or source else self.dependency_error(job, chain, now)
                if reason:
                    self.store.finish(run, "blocked_dependency", evidence=reason)
                    chain[job.id] = "blocked_dependency"
                    results.append(
                        {
                            "job": job.id,
                            "run": run,
                            "status": "blocked_dependency",
                            "reason": reason,
                        }
                    )
                    continue
                # The interval is measured after the previous routine ends; never overlaps profiles.
                if scheduled and previous_finished is not None:
                    deadline = previous_finished + (
                        job.queue_delay_seconds
                        if job.queue_delay_seconds is not None
                        else self.config.queue_delay_seconds
                    )
                    while time.monotonic() < deadline:
                        self.store.stage(
                            run,
                            f"fila: próxima rotina em {max(1, int(deadline - time.monotonic()))} s",
                        )
                        if (
                            self.store.control(run) == "cancel"
                            or self.store.control("batch:" + self.batch) == "cancel"
                        ):
                            break
                        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
                    if (
                        self.store.control(run) == "cancel"
                        or self.store.control("batch:" + self.batch) == "cancel"
                    ):
                        self.store.finish(run, "cancelled", 130)
                        chain[job.id] = "cancelled"
                        results.append(
                            {"job": job.id, "run": run, "status": "cancelled", "code": 130}
                        )
                        continue
                started = time.monotonic()
                self.deadlines[run] = started + job.timeout_seconds
                output: dict[str, Any] = {}
                attempt = 0
                retry_source = source
                action = (
                    "login"
                    if login
                    else (
                        "merge"
                        if job.id == "pipefy_eventos_tool_edge" and source
                        else "replace"
                        if source
                        else "run"
                    )
                )
                while True:
                    attempt += 1
                    self.store.stage(run, "iniciando tentativa", attempt)
                    self.store.event(run, "attempt", {"id": f"{run}:{attempt}", "attempt": attempt})
                    try:
                        output = self.runner(
                            job, run, "scheduled" if scheduled else "manual", action, retry_source
                        )
                    except Exception as exc:
                        output = {"code": 1, "category": "unknown", "error": str(exc)}
                    code = int(output.get("code", 1))
                    category = output.get("category", "unknown")
                    self.store.event(run, "attempt_result", {"attempt": attempt, **output})
                    if code in {0, 20, 130} or login:
                        break
                    retry = job.retries.get(category, job.retries["unknown"])
                    elapsed = time.monotonic() - started
                    if (
                        output.get("committed")
                        or attempt >= retry.attempts
                        or elapsed >= min(retry.total_timeout_seconds, job.timeout_seconds)
                    ):
                        break
                    delay = retry.delay_seconds * retry.backoff ** (attempt - 1)
                    if elapsed + delay >= min(retry.total_timeout_seconds, job.timeout_seconds):
                        break
                    if category == "locked_file":
                        if not output.get("retry_input"):
                            break
                        retry_source = Path(output["retry_input"])
                        action = "merge" if job.id == "pipefy_eventos_tool_edge" else "replace"
                    self.store.stage(
                        run, f"recuperação {category}; próxima tentativa em {delay:g} s", attempt
                    )
                    deadline = time.monotonic() + delay
                    while time.monotonic() < deadline and self.store.control(run) != "cancel":
                        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
                    if self.store.control(run) == "cancel":
                        code = 130
                        category = "cancelled"
                        break
                previous_finished = time.monotonic()
                status = {0: "success", 20: "skipped", 130: "cancelled"}.get(code, "failed")
                self.store.finish(run, status, code, category, output, time.monotonic() - started)
                if status == "success" and not login and source is None:
                    self.store.succeed(job.id, run, decision.period or period_for(job, now))
                chain[job.id] = status
                results.append(
                    {"job": job.id, "run": run, "status": status, "code": code, **output}
                )
                label = {
                    "success": "concluída",
                    "skipped": "pendente",
                    "cancelled": "cancelada",
                    "failed": "falhou",
                }[status]
                enqueue(
                    self.store,
                    self.config,
                    "complete" if status == "success" else "failure",
                    job.id,
                    run,
                    f"{job.label}: {label}. Abra o detalhe da execução.",
                )
                if status == "failed" and not self.config.continue_on_error:
                    self.store.event(run, "batch_stopped", {"reason": "continue_on_error=false"})
                    self.record_remainder(
                        names,
                        chain,
                        now,
                        results,
                        "Lote interrompido pela política de continuidade.",
                    )
                    break
                if status == "cancelled":
                    if (
                        not self.config.continue_on_error
                        or self.store.control("batch:" + self.batch) == "cancel"
                    ):
                        self.record_remainder(names, chain, now, results, "Lote cancelado.")
                        break
                # Code 20 always continues, has no external retries, and never consumes success.
        return results

    def preview(
        self,
        names: list[str] | None = None,
        *,
        scheduled: bool = False,
        force: bool = False,
        now: dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Read-only plan; potential source success is conditional, never an actual success."""
        now = now or local_now()
        if names and set(names) - {j.id for j in self.config.routines}:
            raise ValueError("Rotina não cadastrada.")
        chain: dict[str, str] = {}
        results: list[dict[str, Any]] = []
        for job in ordered(self.config):
            if names and job.id not in names:
                continue
            state = self.store.decision_state(job.id, period_for(job, now))
            decision = eligible(
                job,
                state,
                now,
                manual=not scheduled,
                force=force,
                paused=self.config.scheduling_paused or paused_until(self.config.paused_until, now),
                excluded_dates=self.config.calendar.get("dates", []),
            )
            blockers, requirements = [], []
            for dep in job.dependencies:
                origin = self.config.job(dep.job)
                if not origin.enabled:
                    blockers.append(f"Origem desabilitada: {origin.label}")
                elif dep.mode == "same_chain":
                    if chain.get(origin.id) in {"simulation", "conditional"}:
                        requirements.append(f"Sucesso nesta cadeia: {origin.label}")
                    else:
                        blockers.append(f"Inclua e conclua a origem nesta cadeia: {origin.label}")
                else:
                    last = self.store.decision_state(origin.id, None)["last_success"]
                    age = (
                        now.timestamp() - dt.datetime.fromisoformat(last["at"]).timestamp()
                        if last
                        else float("inf")
                    )
                    if not 0 <= age <= dep.max_age_minutes * 60:
                        if chain.get(origin.id) in {"simulation", "conditional"}:
                            requirements.append(f"Novo sucesso da origem: {origin.label}")
                        else:
                            blockers.append(
                                f"Sucesso anterior ausente ou fora da validade: {origin.label}"
                            )
            status = (
                "not_eligible"
                if not decision.due
                else "blocked_dependency"
                if blockers
                else "conditional"
                if requirements
                else "simulation"
            )
            chain[job.id] = status
            results.append(
                {
                    "job": job.id,
                    "label": job.label,
                    "position": len(results) + 1,
                    "status": status,
                    "reason": decision.reason,
                    "occurrence": decision.occurrence,
                    "blockers": blockers,
                    "requirements": requirements,
                    "dependencies": [d.job for d in job.dependencies],
                    "queue_delay_seconds": job.queue_delay_seconds
                    if job.queue_delay_seconds is not None
                    else self.config.queue_delay_seconds,
                    "execution_time": "depends on prior completion; not a guaranteed time",
                }
            )
        return results

    def record_remainder(
        self,
        names: list[str] | None,
        chain: dict[str, str],
        now: dt.datetime,
        results: list[dict[str, Any]],
        reason: str,
    ) -> None:
        for pending in ordered(self.config):
            if pending.id in chain or (names and pending.id not in names):
                continue
            dependency = self.dependency_error(pending, chain, now)
            status = "blocked_dependency" if dependency else "ignored"
            run = self.store.begin(self.batch, pending.id, "eligibility", None)
            self.store.finish(run, status, evidence=dependency or reason)
            chain[pending.id] = status
            results.append(
                {"job": pending.id, "run": run, "status": status, "reason": dependency or reason}
            )

    def run_worker(
        self, job: Routine, run: str, mode: str, action: str, source: Path | None
    ) -> dict[str, Any]:
        args = command(
            "--data-root",
            str(self.paths.root),
            "--worker",
            job.id,
            "--run-id",
            run,
            "--mode",
            mode,
            "--action",
            action,
        )
        if source:
            args += ["--input", str(source)]
        logfile = Path(self.config.logs) / f"{run}.process.log"
        logfile.parent.mkdir(parents=True, exist_ok=True)
        directory = Path(self.config.downloads) / f"run-{run}"
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = directory / "configuration.json"
        atomic_json(snapshot, to_dict(self.config))
        args += ["--snapshot", str(snapshot)]
        result_path = directory / "result.json"
        result_path.unlink(missing_ok=True)
        with logfile.open("ab") as log:
            process = spawn(args, stdout=log, stderr=log)
            tree = OwnedTree(process)
            self.store.event(
                run, "process", {"pid": process.pid, "created": tree.identities.get(process.pid)}
            )
            started = time.monotonic()
            cancel_at: float | None = None
            while process.poll() is None:
                tree.capture()
                control = self.store.control(run)
                if control == "cancel":
                    cancel_at = cancel_at or time.monotonic()
                if cancel_at and time.monotonic() - cancel_at > 8:
                    tree.stop()
                    return {"code": 130, "category": "cancelled", "forced_after_seconds": 8}
                if time.monotonic() >= self.deadlines.get(run, started + job.timeout_seconds):
                    self.store.control(run, "cancel")
                    tree.stop()
                    return {
                        "code": 1,
                        "category": "download",
                        "error": "Tempo total da rotina excedido.",
                    }
                time.sleep(0.1)
            # Browser subprocesses are owned and cleaned even if the worker exits unexpectedly.
            tree.stop()
        if result_path.is_file():
            return dict(read_json(result_path))
        return {
            "code": process.returncode or 1,
            "category": "unknown",
            "error": "Extrator terminou sem resultado estruturado; veja log local.",
        }

    def monitor(self) -> None:
        now = local_now()
        for job in self.config.routines:
            state = self.store.decision_state(job.id, period_for(job, now))
            status = freshness(self.config, job, state, now)
            if status in {"atrasada", "nunca atualizada"}:
                enqueue(
                    self.store, self.config, "stale", job.id, "", f"{job.label}: dados {status}."
                )
            last = self.store.latest(job.id)
            checkpoint = last.get("checkpoint_at") or last.get("started")
            if (
                last.get("status") == "running"
                and checkpoint
                and (now.timestamp() - dt.datetime.fromisoformat(checkpoint).timestamp())
                > job.stalled_minutes * 60
            ):
                enqueue(
                    self.store,
                    self.config,
                    "stalled",
                    job.id,
                    last["id"],
                    f"{job.label}: sem evolução recente. Confira etapa e processos; nenhum processo foi encerrado automaticamente.",
                )

    def panel(self) -> list[dict[str, Any]]:
        now = local_now()
        result = []
        for job in ordered(self.config):
            state = self.store.decision_state(job.id, period_for(job, now))
            last = self.store.latest(job.id)
            data_update = self.store.latest(job.id, published=True).get("finished", "")
            next_at = next_execution(
                job,
                state,
                now,
                self.config.scheduling_paused,
                self.config.calendar.get("dates", []),
            )
            if next_at and paused_until(self.config.paused_until, next_at):
                resume = dt.datetime.fromisoformat(self.config.paused_until).astimezone(now.tzinfo)
                next_at = next_execution(
                    job,
                    state,
                    resume,
                    self.config.scheduling_paused,
                    self.config.calendar.get("dates", []),
                )
            result.append(
                {
                    "id": job.id,
                    "label": job.label,
                    "enabled": job.enabled,
                    "last": last,
                    "last_success": state["last_success"],
                    "freshness": freshness(self.config, job, state, now),
                    "data_updated": data_update,
                    "next": next_at.isoformat() if next_at else "",
                    "timezone": str(now.tzinfo),
                    "weekly": opportunities(job, state, now, self.config),
                }
            )
        return result
