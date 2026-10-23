from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    if sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import psutil
    from PySide6.QtCore import QEventLoop, QThread, QTimer
    from PySide6.QtWidgets import QApplication

    from orquestrador_app import VERSION
    from orquestrador_app.config import defaults, save
    from orquestrador_app.gui import MainWindow
    from orquestrador_app.paths import Paths
    from orquestrador_app.resources import source_root

    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="orquestrador-benchmark-") as temporary:
        paths = Paths.user(temporary)
        paths.ensure()
        save(paths, defaults(paths, source_root()))
        window = MainWindow(paths)
        window.show()
        app.processEvents()
        deadline = time.monotonic() + 15
        while window.read_task is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.001)
        if window.read_task is not None:
            raise RuntimeError("Initial observation timed out")
        ready = time.perf_counter() - started
        if sys.platform == "linux":
            match = re.search(r"^VmRSS:\s+(\d+) kB", Path("/proc/self/status").read_text(), re.M)
            if not match:
                raise RuntimeError("Medição de RSS indisponível; benchmark não inventa consumo.")
            memory = int(match.group(1)) * 1024
            memory_method = "/proc/self/status VmRSS (namespace-aware)"
        else:
            memory = psutil.Process().memory_info().rss
            memory_method = "psutil.Process().memory_info().rss"
        samples: list[float] = []
        previous = time.perf_counter()

        def sample() -> None:
            nonlocal previous
            current = time.perf_counter()
            samples.append(current - previous)
            previous = current

        timer = QTimer()
        timer.timeout.connect(sample)
        timer.start(10)
        cpu_started = time.process_time()
        idle_started = time.monotonic()
        loop = QEventLoop()
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        timer.stop()
        record = {
            "version": VERSION,
            "environment": platform.platform(),
            "idle_cpu_percent_one_core": 100
            * (time.process_time() - cpu_started)
            / (time.monotonic() - idle_started),
            "python": sys.version,
            "platform_plugin": app.platformName(),
            "mode": "source" if not getattr(sys, "frozen", False) else "packaged",
            "method": "one process; import + construct + show + processEvents; 10ms QTimer, 5s idle panel; OS page cache not reset",
            "opening_seconds": ready,
            "rss_bytes_ready": memory,
            "memory_method": memory_method,
            "timer_samples": len(samples),
            "median_timer_interval_seconds": statistics.median(samples),
            "max_timer_interval_seconds": max(samples),
            "windows_benchmark": "EXECUTED" if sys.platform == "win32" else "NOT_EXECUTED",
        }
        target = args.output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2))
        window.timer.stop()
        window.tray.hide()
        window.exit_requested = True
        window.close()
        deadline = time.monotonic() + 15
        while (
            any(thread.isRunning() for thread in window.findChildren(QThread))
            and time.monotonic() < deadline
        ):
            app.processEvents()
            time.sleep(0.002)


if __name__ == "__main__":
    main()
