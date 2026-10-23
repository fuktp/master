"""Console suppression for every Python-created child, including preserved adapters."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
_installed = False
_streams: list[Any] = []


def hidden_options(options: dict[str, Any]) -> dict[str, Any]:
    result = dict(options)
    result["creationflags"] = (
        int(result.get("creationflags", 0)) | CREATE_NO_WINDOW
    ) & ~CREATE_NEW_CONSOLE
    # CREATE_NO_WINDOW affects console applications only. Browser GUI visibility is independent.
    return result


def install_console_policy() -> None:
    global _installed
    if _installed or sys.platform != "win32":
        return
    original = subprocess.Popen

    class HiddenPopen(original):  # type: ignore[valid-type, misc]
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **hidden_options(kwargs))

    setattr(subprocess, "Popen", HiddenPopen)
    _installed = True


def capture_windowed_streams(folder: Path) -> None:
    if not getattr(sys, "frozen", False) and sys.stdout is not None and sys.stderr is not None:
        return
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("stdout", "stderr"):
        current = getattr(sys, name)
        if current is None or current in _streams:
            if current is not None:
                _streams.remove(current)
                current.close()
            stream = (folder / f"runtime-{os.getpid()}.log").open(
                "a", encoding="utf-8", buffering=1, errors="replace"
            )
            _streams.append(stream)
            setattr(sys, name, stream)
    if sys.stdin is None:
        stream = open(os.devnull, encoding="utf-8")
        _streams.append(stream)
        sys.stdin = stream
    logging.getLogger(__name__).info("Runtime gráfico; subprocessos de console ocultos.")
