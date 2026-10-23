"""Comparable source benchmark; no Windows claims, no corporate access."""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path


def main() -> None:
    began = time.perf_counter()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from orquestrador_app.config import defaults, save
    from orquestrador_app.gui import MainWindow
    from orquestrador_app.paths import Paths
    from orquestrador_app.resources import source_root

    app = QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        paths = Paths.user(folder)
        paths.ensure()
        save(paths, defaults(paths, source_root()))
        window = MainWindow(paths)
        window.show()
        app.processEvents()
        startup = time.perf_counter() - began
        rss = (
            int(
                next(
                    line.split()[1]
                    for line in Path("/proc/self/status").read_text().splitlines()
                    if line.startswith("VmRSS:")
                )
            )
            * 1024
        )
        samples = []
        previous = time.perf_counter()

        def tick() -> None:
            nonlocal previous
            now = time.perf_counter()
            samples.append(now - previous)
            previous = now

        timer = QTimer()
        timer.timeout.connect(tick)
        timer.start(10)
        elapsed = time.monotonic() + 4
        while time.monotonic() < elapsed:
            app.processEvents()
            time.sleep(0.001)
        timer.stop()
        print(
            json.dumps(
                {
                    "platform": platform.platform(),
                    "python": sys.version,
                    "startup_seconds": startup,
                    "rss_ready_bytes": rss,
                    "timer_median_seconds": statistics.median(samples),
                    "timer_max_seconds": max(samples),
                    "samples": len(samples),
                    "method": "Linux source/offscreen; cold process, warm OS cache; 10ms timer during 4s panel; VmRSS from /proc; no Windows benchmark",
                }
            )
        )
        window.timer.stop()
        window.dev_panel.shutdown()
        window.tray.hide()
        window.exit_requested = True
        window.close()


if __name__ == "__main__":
    main()
