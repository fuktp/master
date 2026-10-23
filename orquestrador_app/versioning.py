"""Internal, append-only release records backed by verified application snapshots."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Any

from . import VERSION
from .io import atomic_json, digest, read_json
from .paths import Paths


def history(paths: Paths) -> list[dict[str, Any]]:
    directory = paths.root / "versionamento"
    if not directory.is_dir():
        return []
    return [read_json(p) for p in sorted(directory.glob("versao-*.json"), reverse=True)]


def record(paths: Paths, executable: Path, backup: Path) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    value = {
        "id": str(uuid.uuid4()),
        "at": now.isoformat(),
        "version": VERSION,
        "method": "versionamento interno; manifesto e snapshot SHA-256",
        "executable": str(executable),
        "bytes": executable.stat().st_size,
        "sha256": digest(executable),
        "configuration_sha256": digest(paths.config),
        "previous_snapshot": str(backup),
        "previous_snapshot_manifest_sha256": digest(backup / "manifest.json"),
    }
    filename = now.strftime("versao-%Y%m%dT%H%M%S%fZ-") + str(value["id"]) + ".json"
    atomic_json(paths.root / "versionamento" / filename, value)
    return value
