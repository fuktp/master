"""Give the private process hosts distinct filenames without altering upstream executable bytes."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_hosts(runtime: Path) -> None:
    from orquestrador_app.windows_hosts import HOST_DESCRIPTIONS

    original = runtime / "pythonw.exe"
    for name in HOST_DESCRIPTIONS:
        # Keep resources, publisher metadata and Authenticode signature exactly as supplied.
        shutil.copy2(original, runtime / name)
