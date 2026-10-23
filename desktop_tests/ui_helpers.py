"""Wait for real asynchronous observations; no nested GUI event loop in production."""

import time
from typing import Any

from PySide6.QtWidgets import QApplication


def settle(window: Any, timeout: float = 8) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if window.read_task is None and not window._refresh_pending:
            QApplication.processEvents()
            return
        time.sleep(0.002)
    raise AssertionError("Background observation did not complete")
