from __future__ import annotations

import contextlib
import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterator

from .io import sanitize


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Store:
    def __init__(self, path: Path, *, initialize: bool = True):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not initialize:
            return
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, batch TEXT NOT NULL, job TEXT NOT NULL, mode TEXT NOT NULL,
                started TEXT NOT NULL, finished TEXT, status TEXT NOT NULL, code INTEGER,
                category TEXT, evidence TEXT, attempt INTEGER NOT NULL DEFAULT 0,
                occurrence TEXT, duration REAL, stage TEXT NOT NULL DEFAULT 'fila');
            CREATE INDEX IF NOT EXISTS runs_job_time ON runs(job, started);
            CREATE TABLE IF NOT EXISTS success (
                job TEXT PRIMARY KEY, at TEXT NOT NULL, run TEXT NOT NULL, local_period TEXT);
            CREATE TABLE IF NOT EXISTS periods (
                job TEXT NOT NULL, period TEXT NOT NULL, PRIMARY KEY(job, period));
            CREATE TABLE IF NOT EXISTS occurrences (
                job TEXT NOT NULL, occurrence TEXT NOT NULL, run TEXT,
                PRIMARY KEY(job, occurrence));
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, run TEXT,
                kind TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, job TEXT,
                run TEXT, message TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS controls (
                key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS events_run ON events(run,seq);
            CREATE INDEX IF NOT EXISTS notifications_delivery ON notifications(delivered,at);
            CREATE INDEX IF NOT EXISTS notifications_kind_job_time ON notifications(kind,job,at);
            CREATE INDEX IF NOT EXISTS runs_status_time ON runs(status,started);
            """)
            for table, column, declaration in (
                ("runs", "checkpoint_at", "TEXT"),
                ("notifications", "repeat_count", "INTEGER NOT NULL DEFAULT 1"),
                ("notifications", "last_at", "TEXT"),
            ):
                if column not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
                    try:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
                    except sqlite3.OperationalError:
                        if column not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
                            raise
            db.execute(
                "CREATE INDEX IF NOT EXISTS notifications_recent ON notifications(COALESCE(last_at,at))"
            )

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def begin(self, batch: str, job: str, mode: str, occurrence: str | None) -> str:
        run = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(id,batch,job,mode,started,status,occurrence) VALUES(?,?,?,?,?,'running',?)",
                (run, batch, job, mode, utcnow().isoformat(), occurrence),
            )
            if occurrence:
                db.execute(
                    "INSERT INTO occurrences(job,occurrence,run) VALUES(?,?,?)",
                    (job, occurrence, run),
                )
        return run

    def finish(
        self,
        run: str,
        status: str,
        code: int | None = None,
        category: str = "",
        evidence: Any = None,
        duration: float = 0,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET finished=?,status=?,code=?,category=?,evidence=?,duration=?,stage=? WHERE id=?",
                (
                    utcnow().isoformat(),
                    status,
                    code,
                    category,
                    json.dumps(sanitize(evidence), ensure_ascii=False),
                    duration,
                    status,
                    run,
                ),
            )

    def stage(self, run: str, stage: str, attempt: int | None = None) -> None:
        with self.connect() as db:
            if attempt is None:
                db.execute(
                    "UPDATE runs SET stage=?,checkpoint_at=? WHERE id=?",
                    (stage, utcnow().isoformat(), run),
                )
            else:
                db.execute(
                    "UPDATE runs SET stage=?, attempt=?,checkpoint_at=? WHERE id=?",
                    (stage, attempt, utcnow().isoformat(), run),
                )

    def event(self, run: str | None, kind: str, detail: Any) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(at,run,kind,detail) VALUES(?,?,?,?)",
                (utcnow().isoformat(), run, kind, json.dumps(sanitize(detail), ensure_ascii=False)),
            )

    def succeed(self, job: str, run: str, period: str | None) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO success(job,at,run,local_period) VALUES(?,?,?,?) ON CONFLICT(job) DO UPDATE SET at=excluded.at,run=excluded.run,local_period=excluded.local_period",
                (job, utcnow().isoformat(), run, period),
            )
            if period:
                db.execute("INSERT OR IGNORE INTO periods(job,period) VALUES(?,?)", (job, period))

    def state(self, job: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM success WHERE job=?", (job,)).fetchone()
            periods = {r[0] for r in db.execute("SELECT period FROM periods WHERE job=?", (job,))}
            occurrences = {
                r[0] for r in db.execute("SELECT occurrence FROM occurrences WHERE job=?", (job,))
            }
        return {
            "last_success": dict(row) if row else None,
            "periods": periods,
            "occurrences": occurrences,
        }

    def decision_state(self, job: str, period: str | None) -> dict[str, Any]:
        """Bounded indexed reads; durable occurrence/period uniqueness remains unchanged."""
        with self.connect() as db:
            success = db.execute("SELECT * FROM success WHERE job=?", (job,)).fetchone()
            found = db.execute(
                "SELECT period FROM periods WHERE job=? AND period=?", (job, period)
            ).fetchone()
            occurrence = db.execute(
                "SELECT MAX(occurrence) FROM occurrences WHERE job=? AND occurrence NOT LIKE 'manual:%'",
                (job,),
            ).fetchone()[0]
        return {
            "last_success": dict(success) if success else None,
            "periods": {found[0]} if found else set(),
            "occurrences": {occurrence} if occurrence else set(),
        }

    def latest(self, job: str, *, published: bool = False) -> dict[str, Any]:
        condition = (
            "status='success' AND mode IN ('extraction','local_publication')"
            if published
            else "mode!='eligibility'"
        )
        with self.connect() as db:
            row = db.execute(
                f"SELECT * FROM runs WHERE job=? AND {condition} ORDER BY started DESC,rowid DESC LIMIT 1",
                (job,),
            ).fetchone()
        return dict(row) if row else {}

    def history_page(
        self,
        *,
        job: str = "",
        status: str = "",
        category: str = "",
        batch: str = "",
        text: str = "",
        start: str = "",
        end: str = "",
        page: int = 0,
        size: int = 50,
        sort: str = "started",
        descending: bool = True,
    ) -> dict[str, Any]:
        if not 1 <= size <= 200 or page < 0:
            raise ValueError("Página ou tamanho de histórico inválido.")
        if sort not in {"started", "job", "status", "mode", "category", "batch", "id", "stage"}:
            raise ValueError("Ordenação inválida.")
        fields, values = [], []
        for column, value in (
            ("job", job),
            ("status", status),
            ("category", category),
            ("batch", batch),
        ):
            if value:
                fields.append(column + "=?")
                values.append(value)
        if start:
            fields.append("started>=?")
            values.append(start)
        if end:
            fields.append("started<?")
            values.append(end)
        if text:
            fields.append(
                "(instr(lower(coalesce(stage,'')),lower(?))>0 OR instr(lower(coalesce(evidence,'')),lower(?))>0 OR instr(lower(id),lower(?))>0)"
            )
            values.extend([text] * 3)
        where = " AND ".join(fields) or "1"
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM runs WHERE " + where, values).fetchone()[0]
            page = min(page, max(0, (total - 1) // size))
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM runs WHERE "
                    + where
                    + " ORDER BY "
                    + sort
                    + (" DESC" if descending else " ASC")
                    + ",rowid DESC LIMIT ? OFFSET ?",
                    [*values, size, page * size],
                )
            ]
        return {"rows": rows, "total": total, "page": page, "size": size}

    def notification_history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM notifications ORDER BY COALESCE(last_at,at) DESC LIMIT ?",
                    (limit,),
                )
            ]

    def history(self, *, job: str = "", status: str = "", limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM runs WHERE (?='' OR job=?) AND (?='' OR status=?) ORDER BY started DESC LIMIT ?",
                    (job, job, status, status, limit),
                )
            ]

    def details(self, run: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [
                dict(r) for r in db.execute("SELECT * FROM events WHERE run=? ORDER BY seq", (run,))
            ]

    def control(self, key: str, value: str | None = None) -> str:
        with self.connect() as db:
            if value is not None:
                db.execute(
                    "INSERT INTO controls(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )
                return value
            row = db.execute("SELECT value FROM controls WHERE key=?", (key,)).fetchone()
            return row[0] if row else ""

    def recover_interrupted(self) -> None:
        # Caller holds the shared execution lock, so none of these runs can still own it.
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status='cancelled',finished=?,category='interrupted',stage='interrompido',evidence=? WHERE status='running'",
                (
                    utcnow().isoformat(),
                    json.dumps("Processo interrompido; sucesso não registrado."),
                ),
            )

    def snapshot(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, sqlite3.connect(target) as dest:
            source.backup(dest)

    def export(self, target: Path) -> None:
        with self.connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM runs ORDER BY started DESC")]
        result = []
        for row in rows:
            item = dict(row)
            item["events"] = self.details(row["id"])
            for event in item["events"]:
                event["detail"] = json.loads(event["detail"])
            if item["evidence"]:
                item["evidence"] = json.loads(item["evidence"])
            result.append(item)
        from .exporting import export_data

        if target.suffix.casefold() == ".xlsx":
            events = [{"run": item["id"], **event} for item in result for event in item["events"]]
            export_data(
                target,
                {
                    "Execuções": [
                        {k: v for k, v in item.items() if k != "events"} for item in result
                    ],
                    "Eventos": events,
                },
            )
        else:
            export_data(target, result)

    def migrate_state(self, path: Path, timezone: dt.tzinfo) -> None:
        if not path.is_file() or self.control("legacy_state_migrated"):
            return
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        with self.connect() as db:
            for job, state in raw.get("jobs", {}).items():
                value = state.get("last_success_at")
                if value:
                    at = dt.datetime.fromisoformat(value)
                    if at.tzinfo is None:
                        at = at.replace(tzinfo=timezone)
                    db.execute(
                        "INSERT OR IGNORE INTO success(job,at,run) VALUES(?,?,?)",
                        (job, at.isoformat(), "legacy"),
                    )
        self.control("legacy_state_migrated", "1")
