from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".orquestrador-", suffix=".json.tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class BusyError(RuntimeError):
    pass


class Lock:
    """OS ownership, released on process death; never unlink another owner's lock file."""

    def __init__(self, path: Path):
        self.path = path
        self.stream: Any = None

    def __enter__(self) -> Lock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                self.stream.seek(0)
                if not self.stream.read(1):
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise BusyError("Recurso em uso por outra execução.") from exc
        return self

    def __exit__(self, *_: Any) -> None:
        if self.stream:
            if sys.platform == "win32":
                import msvcrt

                self.stream.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()
            self.stream = None


SECRET = re.compile(
    r"password|passwd|secret|token|cookie|authorization|credential|api.?key|access.?key|private.?key|connection.?string",
    re.I,
)
URL = re.compile(r"(?:https?|wss?)://[^\s\"'<>]+", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
WINPATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\r\n\"<>]+")
TOKEN = re.compile(r"(?i)(bearer\s+|(?:token|password|cookie|secret)\s*[=:]\s*)[^\s,;}]+")


def sanitize(value: Any, *, export: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            str(k): "[removido]" if SECRET.search(str(k)) else sanitize(v, export=export)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(v, export=export) for v in value]
    if isinstance(value, str):
        result = TOKEN.sub("[segredo removido]", value)
        if export:
            result = URL.sub("[destino removido]", result)
            result = EMAIL.sub("[email removido]", result)
            result = WINPATH.sub("[caminho removido]", result)
            result = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP removido]", result)
        return result
    return value
