from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from .config import Config
from .store import Store, utcnow


def show(tray: Any, message: str, title: str = "CAIO") -> None:
    from .i18n import tr
    from .ui import icon

    tray.showMessage(title, tr(message), icon(), 15000)


def enqueue(store: Store, config: Config, kind: str, job: str, run: str, message: str) -> bool:
    now = utcnow()
    cooldown = now - dt.timedelta(minutes=int(config.notifications["cooldown_minutes"]))
    hourly = now - dt.timedelta(hours=1)
    local = now.astimezone().strftime("%H:%M")
    start, end = (str(config.notifications.get(k, "")) for k in ("quiet_start", "quiet_end"))
    quiet = bool(
        start and end and (start <= local < end if start < end else local >= start or local < end)
    )
    allowed = bool(
        config.notifications.get("enabled", True)
        and config.job(job).notifications
        and config.notifications.get("kinds", {}).get(kind, True)
        and not quiet
    )
    with store.connect() as db:
        repeated = db.execute(
            "SELECT 1 FROM notifications WHERE kind=? AND job=? AND delivered IN (0,1) AND at>?",
            (kind, job, cooldown.isoformat()),
        ).fetchone()
        count = db.execute(
            "SELECT COUNT(*) FROM notifications WHERE delivered IN (0,1) AND at>?",
            (hourly.isoformat(),),
        ).fetchone()[0]
        allowed = allowed and not repeated and count < int(config.notifications["max_per_hour"])
        if allowed:
            previous = (
                db.execute(
                    "SELECT MAX(at) FROM notifications WHERE kind=? AND job=? AND delivered IN (0,1)",
                    (kind, job),
                ).fetchone()[0]
                or ""
            )
            grouped = db.execute(
                "SELECT COALESCE(SUM(repeat_count),0) FROM notifications WHERE kind=? AND job=? AND delivered=2 AND at>?",
                (kind, job, previous),
            ).fetchone()[0]
            if grouped:
                message += f" • {grouped} avisos anteriores agrupados; consulte a central."
        else:
            # Collapse repeated identical muted observations of the SAME run; different executions retain their links.
            previous = (
                db.execute(
                    "SELECT MAX(at) FROM notifications WHERE kind=? AND job=? AND delivered IN (0,1)",
                    (kind, job),
                ).fetchone()[0]
                or ""
            )
            muted = db.execute(
                "SELECT id FROM notifications WHERE kind=? AND job=? AND run=? AND message=? AND delivered=2 AND at>? ORDER BY at DESC LIMIT 1",
                (kind, job, run, message, previous),
            ).fetchone()
            if muted:
                db.execute(
                    "UPDATE notifications SET repeat_count=repeat_count+1,last_at=? WHERE id=?",
                    (now.isoformat(), muted["id"]),
                )
                return False
        db.execute(
            "INSERT INTO notifications(id,at,kind,job,run,message,delivered) VALUES(?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), now.isoformat(), kind, job, run, message, 0 if allowed else 2),
        )
    return bool(allowed)


def claim(store: Store, limit: int = 2) -> list[dict[str, Any]]:
    rows = []
    with store.connect() as db:
        for row in db.execute(
            "SELECT * FROM notifications WHERE delivered=0 ORDER BY at LIMIT ?", (limit,)
        ).fetchall():
            if db.execute(
                "UPDATE notifications SET delivered=1 WHERE id=? AND delivered=0", (row["id"],)
            ).rowcount:
                rows.append(dict(row))
    return rows
